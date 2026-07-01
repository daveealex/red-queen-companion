#!/usr/bin/env python3
"""
Voice Activity Detection (VAD) using Silero VAD ONNX model.
Continuously monitors microphone input and signals when speech is detected.

Usage:
    from audio.vad_detector import VADDetector
    
    vad = VADDetector()
    vad.start()
    
    # Wait for speech
    vad.wait_for_speech(timeout=10)
    
    # Get audio chunks during speech
    for chunk in vad.get_speech_chunks():
        process_audio(chunk)
    
    vad.stop()
"""

import json
import numpy as np
import os
import sounddevice as sd
import onnxruntime as ort
import threading
import queue
import time
import logging

logger = logging.getLogger(__name__)


class VADDetector:
    """Silero VAD-based voice activity detector."""

    def __init__(self, config: dict):
        self.sample_rate = config.get("sample_rate", 16000)
        self.channels = config.get("channels", 1)
        self.mic_device = config.get("mic_device", None)
        self.threshold = config.get("vad_threshold", 0.35)
        self.speech_threshold = config.get("vad_speech_threshold", 0.3)
        self.min_speech_ms = config.get("vad_min_speech_ms", 300)
        self.min_silence_ms = config.get("vad_min_silence_ms", 800)
        self.buffer_ms = config.get("vad_buffer_ms", 500)

        # State
        self._running = False
        self._listener_thread = None
        self._speech_detected = threading.Event()
        self._audio_queue = queue.Queue(maxsize=100)
        self._speech_chunks = []
        self._is_speaking = False

        # Initialize VAD model
        self._session = self._init_vad()

        # Chunk size (256 samples = 16ms at 16kHz)
        self.chunk_size = 512  # 32ms at 16kHz

    def _init_vad(self):
        """Load the Silero VAD ONNX model (bundled with project)."""
        try:
            # Use bundled model from assets directory
            model_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "assets",
                "silero_vad.onnx"
            )

            if not os.path.exists(model_path):
                raise FileNotFoundError(f"VAD model not found at {model_path}")

            session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
            logger.info("Silero VAD model loaded.")
            return session
        except Exception as e:
            logger.error(f"Failed to load VAD model: {e}")
            raise

    def _get_model_input(self, audio: np.ndarray) -> dict:
        """Prepare input for VAD model."""
        return {
            self._session.get_inputs()[0].name: audio.astype(np.float32),
            self._session.get_inputs()[1].name: np.array([self.sample_rate], dtype=np.int64),
            self._session.get_inputs()[2].name: np.array([0], dtype=np.int64),
        }

    def _vad_callback(self, audio: np.ndarray, frames, time_info, status):
        """Audio callback from sounddevice stream."""
        if not self._running:
            return

        # Flatten and convert to float32
        audio_flat = audio.flatten().astype(np.float32)

        # Run VAD inference
        try:
            input_dict = self._get_model_input(audio_flat)
            output = self._session.run(None, input_dict)[0][0][0]
        except Exception:
            return

        # Check speech probability
        is_speech = output > self.threshold

        if is_speech and not self._is_speaking:
            # Speech just started
            self._is_speaking = True
            self._speech_chunks = []
            self._speech_detected.set()
            logger.info("Speech detected!")
        elif not is_speech and self._is_speaking:
            # Speech just ended
            if len(self._speech_chunks) > 0:
                self._is_speaking = False
                self._speech_detected.clear()
                logger.debug("Speech ended.")

    def start(self):
        """Start listening for voice activity."""
        if self._running:
            return

        self._running = True
        self._speech_detected.clear()
        
        try:
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                callback=self._vad_callback,
                device=self.mic_device,
                blocksize=self.chunk_size,
            )
            self._stream.start()
            logger.info(f"VAD listener started (sample rate: {self.sample_rate}Hz)")
        except Exception as e:
            logger.error(f"Failed to start audio stream: {e}")
            raise

    def stop(self):
        """Stop listening."""
        self._running = False
        if hasattr(self, "_stream") and self._stream is not None:
            self._stream.stop()
            self._stream.close()
            logger.info("VAD listener stopped.")

    def wait_for_speech(self, timeout=10):
        """Wait for speech to be detected. Returns True if speech detected."""
        detected = self._speech_detected.wait(timeout=timeout)
        if detected:
            return True
        return False

    def get_speech_buffer(self):
        """Get the audio buffer containing the speech.
        Returns numpy array of int16 samples.
        """
        # This is a simplified version — in production you'd accumulate
        # audio chunks during the speech detection phase.
        # For now, the caller should use a recording approach.
        return None

    def is_listening(self):
        """Check if VAD is currently active."""
        return self._running
