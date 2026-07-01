#!/usr/bin/env python3
"""
TTS (Text-to-Speech) wrapper for Piper TTS Python package.
Converts text to speech audio and plays through the default output device.

Usage:
    from audio.tts import TTSEngine
    
    tts = TTSEngine(config)
    tts.speak("Hello, I am Red Queen, your companion.")
    
    # Or with callback for progress
    tts.speak("Hello", on_start=lambda: face.set_state("speaking"),
                    on_complete=lambda: face.set_state("idle"))
"""

import os
import subprocess
import tempfile
import threading
import logging

logger = logging.getLogger(__name__)


class TTSEngine:
    """Text-to-Speech using Piper TTS Python package."""

    def __init__(self, config: dict):
        self.model_path = config.get("piper_model_path",
            os.path.expanduser("~/.local/share/piper/voices/en_US-amy-low.onnx"))
        self.length_scale = config.get("piper_length_scale", 1.0)
        self.noise_scale = config.get("piper_noise_scale", 0.667)
        self.noise_w = config.get("piper_noise_w", 0.8)
        self.speaker_device = config.get("speaker_device", None)

        self._is_playing = False
        self._piper_voice = None

        try:
            from piper import PiperVoice
            # Load config alongside the model
            config_path = self.model_path.replace(".onnx", ".onnx.json")
            if not os.path.exists(config_path):
                config_path = None
            self._piper_voice = PiperVoice.load(self.model_path, config_path=config_path)
            logger.info(f"Piper TTS loaded: {self.model_path}")
        except Exception as e:
            logger.warning(f"Piper TTS not available: {e}")
            logger.warning("Install: pip install piper-tts")

    def speak(self, text: str, on_start=None, on_complete=None):
        """Speak text. Blocks until speech is complete."""
        if not text or not text.strip():
            logger.debug("Empty text, skipping TTS.")
            return

        if not self._piper_voice:
            logger.warning("Piper not loaded, skipping speech.")
            if on_complete:
                on_complete()
            return

        logger.info(f"Speaking: {text[:80]}{'...' if len(text) > 80 else ''}")

        if on_start:
            on_start()

        try:
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
                tmp_path = tmp.name

            # Use Piper Python API
            self._piper_voice.synthesize(
                text,
                output=tmp_path,
                output_format="wav",
                length_scale=self.length_scale,
                noise_scale=self.noise_scale,
                noise_w=self.noise_w,
            )

            # Play the WAV file
            if self.speaker_device:
                player = subprocess.Popen(
                    ["aplay", "-D", self.speaker_device, tmp_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                player = subprocess.Popen(
                    ["pw-play", tmp_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            player.wait()

            os.unlink(tmp_path)
            self._is_playing = False

            if on_complete:
                on_complete()

            logger.debug("Speech complete.")

        except Exception as e:
            logger.error(f"TTS error: {e}")
            if on_complete:
                on_complete()

    def speak_async(self, text: str, on_start=None, on_complete=None):
        """Speak text in a background thread (non-blocking)."""
        thread = threading.Thread(
            target=self.speak,
            args=(text, on_start, on_complete),
            daemon=True,
        )
        thread.start()
        return thread

    def is_playing(self) -> bool:
        """Check if TTS is currently speaking."""
        return self._is_playing

    def stop(self):
        """Stop current speech."""
        self._is_playing = False
        logger.info("TTS stopped.")
