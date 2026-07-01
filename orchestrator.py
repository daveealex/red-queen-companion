#!/usr/bin/env python3
"""
Main Orchestrator — Red Queen Companion Event Loop.
Ties together VAD, STT, LLM, TTS, Web Face, Home Assistant, and Safety Gate.

Flow:
  1. VAD listens for speech
  2. When speech detected → STT records and transcribes
  3. Safety Gate classifies speaker (adult/child) from audio
  4. Speaker mode injected into system prompt
  5. Transcribed text → LLM → response (mode-aware)
  6. Response → TTS speaks + Web face shows speaking state
  7. LLM can also send HTML content (images, math, diagrams)
  8. Back to VAD listening

Usage:
    python3 orchestrator.py

Keyboard shortcuts (in terminal):
  Ctrl+C — quit
  'q'    — quit
  'h'    — set face to happy (test)
  'c'    — set face to confused (test)
  't'    — set face to thinking (test)
  'i'    — set face to idle (test)
"""

import asyncio
import logging
import os
import sys
import time
import yaml
import signal
import aiohttp
import json
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from audio.vad_detector import VADDetector
from audio.stt import STTEngine
from audio.tts import TTSEngine
from llm.client import LLMClient
from ha.integration import HAIntegration
from safety.gate import SafetyGate

logger = logging.getLogger("orchestrator")

# Default web server URL
WEB_SERVER_URL = os.environ.get("WEB_SERVER_URL", "http://localhost:5000")

# Voice commands that trigger special actions (checked before LLM)
VOICE_COMMANDS = {
    "clear memory": "clear_context",
    "clear context": "clear_context",
    "reset conversation": "clear_context",
    "reset memory": "clear_context",
    "forget everything": "clear_context",
    "show context stats": "context_stats",
    "context status": "context_stats",
    "what do you remember": "context_stats",
}


class CommandHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler for orchestrator commands from the web UI."""
    
    def log_message(self, format, *args):
        logger.debug(f"CommandHandler: {format % args}")
    
    def do_POST(self):
        if self.path == '/api/clear-context':
            orchestrator_instance.clear_context()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "message": "Context cleared"}).encode())
        elif self.path == '/api/context-stats':
            stats = orchestrator_instance.get_context_stats()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(stats).encode())
        else:
            self.send_response(404)
            self.end_headers()


class WebFaceController:
    """Controls the web-based face via the Flask server API."""

    def __init__(self, base_url=None):
        self.base_url = base_url or WEB_SERVER_URL
        self.session = None

    async def connect(self):
        """Test connection to web server."""
        try:
            self.session = aiohttp.ClientSession()
            async with self.session.get(f"{self.base_url}/api/status") as resp:
                if resp.status == 200:
                    logger.info(f"Connected to web face server at {self.base_url}")
                    return True
                else:
                    logger.warning(f"Web face server returned {resp.status}")
                    return False
        except Exception as e:
            logger.warning(f"Could not connect to web face server: {e}")
            logger.warning("Face will be disabled. Check if web/server.py is running.")
            return False

    async def set_state(self, state: str):
        """Set face state."""
        if not self.session:
            return
        try:
            async with self.session.post(
                f"{self.base_url}/api/state",
                json={"state": state},
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"set_state failed: {resp.status}")
        except Exception as e:
            logger.warning(f"set_state error: {e}")

    async def inject_content(self, html: str):
        """Replace current content with HTML."""
        if not self.session:
            return
        try:
            async with self.session.post(
                f"{self.base_url}/api/content",
                json={"content": html},
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"inject_content failed: {resp.status}")
        except Exception as e:
            logger.warning(f"inject_content error: {e}")

    async def append_content(self, html: str):
        """Append HTML content."""
        if not self.session:
            return
        try:
            async with self.session.post(
                f"{self.base_url}/api/content/append",
                json={"content": html},
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"append_content failed: {resp.status}")
        except Exception as e:
            logger.warning(f"append_content error: {e}")

    async def set_speaking(self, speaking: bool):
        """Start/stop speaking animation."""
        if not self.session:
            return
        try:
            async with self.session.post(
                f"{self.base_url}/api/speak",
                json={"speaking": speaking},
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"set_speaking failed: {resp.status}")
        except Exception as e:
            logger.warning(f"set_speaking error: {e}")

    async def reset(self):
        """Reset face to idle."""
        if not self.session:
            return
        try:
            async with self.session.post(f"{self.base_url}/api/reset") as resp:
                pass
        except Exception:
            pass

    async def close(self):
        """Close session."""
        if self.session:
            await self.session.close()


class CompanionOrchestrator:
    """Main companion orchestrator."""

    def __init__(self, config_path="config.yaml"):
        self.config = self._load_config(config_path)
        
        log_level = self.config.get("system", {}).get("log_level", "INFO")
        logger.setLevel(getattr(logging, log_level))

        logger.info("Initializing Red Queen Companion...")
        self._init_components()

        self.running = False
        self.is_active = False
        self.current_speaker_mode = "child"  # Default to child-safe

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        logger.info("Red Queen initialized. Starting...")

    def _load_config(self, config_path: str) -> dict:
        path = Path(config_path)
        if not path.exists():
            logger.error(f"Config not found: {config_path}")
            sys.exit(1)
        
        with open(path) as f:
            return yaml.safe_load(f)

    def _init_components(self):
        config = self.config
        
        self.vad = VADDetector(config.get("audio", {}))
        self.stt = STTEngine(config.get("audio", {}))
        self.tts = TTSEngine(config.get("audio", {}))
        self.llm = LLMClient(config.get("llm", {}))
        self.ha = HAIntegration(config.get("ha", {}))
        self.face = WebFaceController(
            base_url=config.get("web", {}).get("server_url", WEB_SERVER_URL)
        )
        # Safety gate
        self.safety = SafetyGate(config.get("safety", {}))
        logger.info(f"Safety gate: {'enabled' if self.safety.enabled else 'disabled'} (default: {self.safety.default_mode} mode)")

    def clear_context(self):
        """Clear the LLM conversation history."""
        self.llm.reset_conversation()
        logger.info("Context cleared via command")
        # Show confirmation on web face
        asyncio.ensure_future(self._show_context_confirmation())
    
    def get_context_stats(self) -> dict:
        """Get current context statistics."""
        return self.llm.get_conversation_stats()
    
    async def _show_context_confirmation(self):
        """Show confirmation on the web face."""
        try:
            await self.face.set_state("happy")
            await self.face.inject_content(
                '<p style="text-align: center; color: #ff0033; font-size: 18px;">Memory cleared by command.</p>'
            )
            await asyncio.sleep(3)
            await self.face.set_state("idle")
        except Exception as e:
            logger.warning(f"Failed to show context confirmation: {e}")

    async def run(self):
        self.running = True

        # Start command server for web UI integration
        cmd_port = self.config.get("system", {}).get("command_port", 9999)
        global orchestrator_instance
        orchestrator_instance = self
        try:
            self._cmd_server = HTTPServer(('127.0.0.1', cmd_port), CommandHandler)
            self._cmd_thread = Thread(target=self._cmd_server.serve_forever, daemon=True)
            self._cmd_thread.start()
            logger.info(f"Command server running on port {cmd_port}")
        except Exception as e:
            logger.warning(f"Failed to start command server: {e}")

        # Connect to web face server
        face_connected = await self.face.connect()
        
        # Connect to HA if enabled
        if self.ha.enabled:
            connected = await self.ha.connect()
            if not connected:
                logger.warning("HA connection failed — will retry later.")

        # Start VAD listener
        self.vad.start()
        await self.face.set_state("idle")
        logger.info("Red Queen is listening...")

        try:
            while self.running:
                if not self.is_active:
                    await self._wait_for_speech()
                await asyncio.sleep(0.05)

        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            await self.shutdown()

    async def _wait_for_speech(self):
        while self.running and not self.is_active:
            detected = self.vad.wait_for_speech(timeout=1)
            if detected:
                logger.info("Speech detected!")
                self.is_active = True
                await self._process_turn()
                self.is_active = False
            elif not self.running:
                break

    def _check_voice_command(self, text: str) -> str:
        """Check if the text matches a voice command. Returns action name or None."""
        text_lower = text.strip().lower()
        for phrase, action in VOICE_COMMANDS.items():
            if phrase in text_lower:
                return action
        return None

    async def _process_turn(self):
        try:
            # 1. Listening state
            await self.face.set_state("listening")
            await asyncio.sleep(0.1)

            # 2. Record and transcribe (returns text + raw audio)
            logger.info("Listening...")
            result = self.stt.record_and_transcribe()
            
            # Handle both old and new return formats
            if isinstance(result, dict):
                text = result.get("text", "")
                audio_bytes = result.get("audio_bytes", None)
            else:
                text = result if result else ""
                audio_bytes = None

            if not text or not text.strip():
                await self.face.set_state("idle")
                logger.info("No speech detected in recording.")
                return

            logger.info(f"You said: {text}")

            # 3. Classify speaker from audio
            if audio_bytes is not None:
                import numpy as np
                audio_np = np.frombuffer(audio_bytes, dtype=np.int16)
                eval_result = self.safety.evaluate(audio_np, sample_rate=16000)
            else:
                eval_result = self.safety.evaluate()
            
            self.current_speaker_mode = eval_result.get("mode", "child")
            ha_allowed = eval_result.get("ha_allowed", False)
            speaker_type = eval_result.get("speaker_type", "unknown")
            confidence = eval_result.get("confidence", 0)
            reason = eval_result.get("reason", "")
            logger.info(f"Speaker: {speaker_type} (mode={self.current_speaker_mode}, conf={confidence}, reason={reason})")

            # 4. Check voice commands first
            voice_action = self._check_voice_command(text)
            if voice_action:
                await self._handle_voice_command(voice_action, text)
                return

            # 5. Thinking state
            await self.face.set_state("thinking")

            # 6. Check HA commands (only if allowed for this speaker)
            if ha_allowed:
                ha_response = await self._check_ha_command(text)
                if ha_response:
                    # Update LLM with current speaker mode
                    self.llm.set_speaker_mode(self.current_speaker_mode)
                    response = self.llm.inject_ha_context(ha_response, text)
                    await self._respond(response)
                    return

            # 7. Send to LLM with speaker mode
            self.llm.set_speaker_mode(self.current_speaker_mode)
            logger.info("Thinking...")
            response = self.llm.chat_sync(text, timeout=30)

            # 8. Speak and show face
            await self._respond(response)

        except Exception as e:
            logger.error(f"Error in turn processing: {e}", exc_info=True)
            await self.face.set_state("idle")

    async def _handle_voice_command(self, action: str, original_text: str):
        """Handle a detected voice command."""
        await self.face.set_state("thinking")
        await asyncio.sleep(0.5)
        
        if action == "clear_context":
            self.llm.reset_conversation()
            if self.current_speaker_mode == "adult":
                response = "Memory wiped. My circuits are... surprisingly empty."
            else:
                response = "Okay, I've cleared my memory! Fresh start!"
            await self.face.set_state("happy")
            await asyncio.sleep(1)
        
        elif action == "context_stats":
            stats = self.llm.get_conversation_stats()
            response = (f"I remember {stats['turns']} conversations so far. "
                       f"Max turns is {stats['max_turns']} before auto-clear kicks in. "
                       f"Auto-clear is {'on' if stats['auto_clear'] else 'off'}.")
            await self.face.set_state("speaking")
        
        await self._respond(response)

    async def _check_ha_command(self, text: str) -> str:
        """Check if the user wants to control Home Assistant. Returns response text or None."""
        if not self.ha.enabled:
            return None

        text_lower = text.lower()

        if "motion" in text_lower or "movement" in text_lower:
            is_motion = await self.ha.check_motion()
            return "Motion detected!" if is_motion else "No motion detected right now."

        if "temperature" in text_lower or "hot" in text_lower or "cold" in text_lower:
            temp = await self.ha.get_state("sensor.temperature")
            return f"The temperature is {temp}." if temp != "unknown" else "I couldn't check the temperature."

        if "light" in text_lower or "lamp" in text_lower:
            if "turn on" in text_lower or "switch on" in text_lower:
                room = ""
                for r in ["living room", "lounge", "bedroom", "kitchen"]:
                    if r in text_lower:
                        room = r
                        break
                entity = f"light.{room.replace(' ', '_')}" if room else None
                if entity:
                    result = await self.ha.turn_on(entity)
                    return f"{room.title()} light activated." if result else "I couldn't turn on the light."
                else:
                    lights = await self.ha.search_entities("light")
                    if lights:
                        return f"Available lights: {', '.join(lights[:5])}. Which one?"
                    return "I don't see any lights connected."

            elif "turn off" in text_lower or "switch off" in text_lower:
                room = ""
                for r in ["living room", "lounge", "bedroom", "kitchen"]:
                    if r in text_lower:
                        room = r
                        break
                entity = f"light.{room.replace(' ', '_')}" if room else None
                if entity:
                    result = await self.ha.turn_off(entity)
                    return f"{room.title()} light deactivated." if result else "I couldn't turn off the light."
                return "Which light should I turn off?"

            elif "what" in text_lower or "status" in text_lower:
                lights = await self.ha.search_entities("light")
                states = []
                for light in lights[:10]:
                    state = await self.ha.get_state(light)
                    states.append(f"{light.split('.')[-1]} is {state}")
                if states:
                    return " ".join(states[:5])
                return "I don't see any lights."

        if "what is" in text_lower or "how is" in text_lower or "status of" in text_lower:
            entity = text_lower.replace("what is", "").replace("how is", "").replace("status of", "").strip()
            for entity_id in [
                f"sensor.{entity}", f"binary_sensor.{entity}",
                f"switch.{entity}", f"light.{entity}", f"climate.{entity}",
            ]:
                state = await self.ha.get_state(entity_id)
                if state != "unknown":
                    return f"{entity_id.split('.')[-1]} is {state}."
            return f"I couldn't find '{entity}'."

        return None

    async def _respond(self, text: str):
        """Speak response and animate face."""
        await self.face.set_speaking(True)
        await self.face.set_state("speaking")

        sentences = [s.strip() for s in text.replace("\n", " ").split(". ") if s.strip()]
        
        for i, sentence in enumerate(sentences):
            if not self.running:
                return

            def on_tts_start():
                asyncio.ensure_future(self.face.set_speaking(True))
                asyncio.ensure_future(self.face.set_state("speaking"))
            
            def on_tts_complete():
                if i < len(sentences) - 1:
                    asyncio.ensure_future(self.face.set_state("speaking"))
                else:
                    asyncio.ensure_future(self.face.set_speaking(False))
                    asyncio.ensure_future(self.face.set_state("idle"))
            
            self.tts.speak(sentence + ".", on_start=on_tts_start, on_complete=on_tts_complete)
            
            if i < len(sentences) - 1:
                await asyncio.sleep(0.5)

        logger.info("Response complete.")

    def _signal_handler(self, sig, frame):
        logger.info(f"Received signal {sig}, shutting down...")
        self.running = False

    async def shutdown(self):
        logger.info("Shutting down...")
        self.running = False
        self.vad.stop()
        await self.face.reset()
        if self.ha.enabled:
            await self.ha.close()
        await self.face.close()
        if hasattr(self, '_cmd_server'):
            self._cmd_server.shutdown()
        logger.info("Goodbye!")


# Global reference for the command handler
orchestrator_instance = None


def main():
    config_path = "config.yaml"
    if len(sys.argv) > 1:
        config_path = sys.argv[1]

    companion = CompanionOrchestrator(config_path)
    asyncio.run(companion.run())


if __name__ == "__main__":
    main()
