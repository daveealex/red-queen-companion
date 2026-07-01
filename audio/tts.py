#!/usr/bin/env python3
"""
TTS (Text-to-Speech) wrapper for Piper TTS.
Converts text to speech audio and plays through the default output device.

Piper is installed on the Pi and runs as a standalone binary.
Download voices from: https://huggingface.co/rhasspy/piper-voices

Usage:
    from audio.tts import TTSEngine
    
    tts = TTSEngine(config)
    tts.speak("Hello, I am Atlas, your companion.")
    
    # Or with callback for progress
    tts.speak("Hello", on_start=lambda: face.set_state("speaking"),
                    on_complete=lambda: face.set_state("idle"))
"""

import subprocess
import os
import threading
import logging

logger = logging.getLogger(__name__)


class TTSEngine:
    """Text-to-Speech using Piper binary."""

    def __init__(self, config: dict):
        self.piper_path = config.get("piper_path", "/usr/local/bin/piper")
        self.voice = config.get("piper_voice", "en_US-amy-low")
        self.length_scale = config.get("piper_length_scale", 1.0)
        self.noise_scale = config.get("piper_noise_scale", 0.667)
        self.noise_w = config.get("piper_noise_w", 0.8)
        
        # Piper needs espeak-ng data directory (bundled in Piper tarball)
        self.espeak_data = config.get("piper_espeak_data", "/home/daveealex/piper/espeak-ng-data")
        # Full model path (onnx file)
        self.model_path = config.get("piper_model_path", 
            os.path.expanduser("~/.local/share/piper/voices/en_US-amy-low.onnx"))
        self.speaker_device = config.get("speaker_device", None)
        
        self._is_playing = False
        self._current_process = None

        # Verify Piper binary exists
        if not os.path.exists(self.piper_path):
            logger.warning(f"Piper not found at {self.piper_path}")
            logger.warning("Install Piper: https://github.com/rhasspy/piper")

    def _get_piper_args(self) -> list:
        """Build Piper command arguments."""
        args = [
            self.piper_path,
            "--model", self.model_path,
            "--espeak-data", self.espeak_data,
            "--length_scale", str(self.length_scale),
            "--noise_scale", str(self.noise_scale),
            "--noise_w", str(self.noise_w),
        ]
        return args

    def speak(self, text: str, on_start=None, on_complete=None):
        """Speak text. Blocks until speech is complete.
        
        Args:
            text: The text to speak
            on_start: Callback when speech starts
            on_complete: Callback when speech finishes
        """
        if not text or not text.strip():
            logger.debug("Empty text, skipping TTS.")
            return

        logger.info(f"Speaking: {text[:80]}{'...' if len(text) > 80 else ''}")

        if on_start:
            on_start()

        try:
            import tempfile
            
            # Piper reads from stdin, outputs WAV to a file
            # Write to temp file, then play with pw-play
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
                tmp_path = tmp.name
            
            piper_cmd = self._get_piper_args() + ["--output_file", tmp_path]
            
            piper = subprocess.Popen(
                piper_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            
            # Feed text to Piper
            piper.stdin.write(text.encode())
            piper.stdin.close()
            piper.wait()
            
            # Play the WAV file through the configured speaker or default
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
            
            # Clean up temp file
            os.unlink(tmp_path)
            
            self._is_playing = False
            
            if on_complete:
                on_complete()
                
            logger.debug("Speech complete.")
            
        except FileNotFoundError:
            logger.error(f"Piper not found: {self.piper_path}")
            if on_complete:
                on_complete()
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
        if self._current_process:
            try:
                self._current_process.terminate()
                self._current_process = None
                logger.info("TTS stopped.")
            except Exception as e:
                logger.error(f"Failed to stop TTS: {e}")

    def list_voices(self) -> list:
        """List available Piper voices (if installed as a package with manifest)."""
        # Piper doesn't have a built-in voice list, but we can check the data dir
        voice_dir = os.path.expanduser("~/.local/share/piper")
        if os.path.exists(voice_dir):
            return os.listdir(voice_dir)
        return [self.voice]  # Return configured voice
