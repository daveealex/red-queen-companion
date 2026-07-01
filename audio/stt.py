#!/usr/bin/env python3
"""
STT (Speech-to-Text) wrapper for whisper.cpp.
Records audio from microphone and transcribes using whisper.cpp binary.

Returns both transcribed text AND raw audio bytes (for safety gate speaker classification).

Usage:
    from audio.stt import STTEngine
    
    stt = STTEngine(config)
    result = stt.record_and_transcribe()
    text = result["text"]       # Transcribed text
    audio = result["audio_bytes"]  # Raw audio bytes (int16)
"""

import subprocess
import os
import tempfile
import wave
import numpy as np
import sounddevice as sd
import logging

logger = logging.getLogger(__name__)


class STTEngine:
    """Speech-to-Text using whisper.cpp binary."""

    def __init__(self, config: dict):
        self.whisper_path = config.get("whisper_path", "/usr/local/bin/whisper-cli")
        self.model = config.get("whisper_model", "tiny")
        self.threads = config.get("whisper_threads", 6)
        self.sample_rate = config.get("sample_rate", 16000)
        self.channels = config.get("channels", 1)
        
        # Recording settings
        self.speech_buffer_ms = config.get("vad_buffer_ms", 500)
        self.max_duration_ms = config.get("recording_duration", 5000)
        self.min_silence_ms = config.get("vad_min_silence_ms", 800)

        # Verify whisper.cpp binary exists
        if not os.path.exists(self.whisper_path):
            logger.warning(f"whisper.cpp not found at {self.whisper_path}")
            logger.warning("Build whisper.cpp first: see scripts/build_whisper.sh")

    def _record_audio(self, callback=None):
        """Record audio from microphone until silence detected.
        Returns (audio_array_float32, audio_array_int16, sample_rate).
        """
        duration_s = self.max_duration_ms / 1000.0
        audio_data = []
        
        def audio_callback(indata, frames, time_info, status):
            if status:
                logger.warning(f"Audio callback status: {status}")
            audio_data.append(indata.copy())
            if callback:
                callback(indata)
        
        try:
            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                callback=audio_callback,
                dtype='float32',
            ):
                sd.sleep(self.max_duration_ms)
        except Exception as e:
            logger.error(f"Recording failed: {e}")
            return None, None, self.sample_rate

        if not audio_data:
            return None, None, self.sample_rate

        audio_float = np.concatenate(audio_data, axis=0)
        if audio_float.ndim == 2:
            audio_float = audio_float.mean(axis=1)  # Mono
        
        # Convert to int16 for safety gate
        audio_int16 = (audio_float * 32767).astype(np.int16)
        
        return audio_float, audio_int16, self.sample_rate

    def _save_wav(self, audio: np.ndarray, sample_rate: int, path: str):
        """Save audio as WAV file for whisper.cpp."""
        # Convert float32 to int16
        audio_int16 = (audio * 32767).astype(np.int16)
        
        with wave.open(path, 'wb') as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(sample_rate)
            wf.writeframes(audio_int16.tobytes())

    def record_and_transcribe(self) -> dict:
        """Record audio and transcribe using whisper.cpp.
        
        Returns:
            dict with:
                - text: transcribed text string
                - audio_bytes: raw audio bytes (int16) for speaker classification
        """
        logger.info("Recording... speak now.")

        # Record
        audio_float, audio_int16, sr = self._record_audio()
        
        if audio_float is None or len(audio_float) == 0:
            logger.warning("No audio recorded.")
            return {"text": "", "audio_bytes": None}

        logger.info(f"Recording complete: {len(audio_float)/sr:.2f}s, {sr}Hz")

        # Save to temp WAV
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            wav_path = tmp.name

        try:
            self._save_wav(audio_float, sr, wav_path)

            # Run whisper.cpp
            logger.info("Transcribing...")
            result = self._transcribe_file(wav_path)
            logger.info(f"Transcribed: {result}")
            return {
                "text": result.strip(),
                "audio_bytes": audio_int16.tobytes() if audio_int16 is not None else None,
            }

        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            return {"text": "", "audio_bytes": audio_int16.tobytes() if audio_int16 is not None else None}
        finally:
            # Clean up temp file
            try:
                os.unlink(wav_path)
            except OSError:
                pass

    def _transcribe_file(self, wav_path: str) -> str:
        """Run whisper.cpp on a WAV file and return text."""
        cmd = [
            self.whisper_path,
            "-m", self.model,
            "-f", wav_path,
            "-t", str(self.threads),
            "--no-timestamps",
            "-l", "en",  # English language
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            
            output = result.stdout.strip()
            
            if result.returncode != 0:
                logger.error(f"whisper.cpp error: {result.stderr}")
                return ""
            
            return output or ""
        
        except subprocess.TimeoutExpired:
            logger.error("whisper.cpp timed out after 30s")
            return ""
        except FileNotFoundError:
            logger.error(f"whisper.cpp not found at {self.whisper_path}")
            return ""
        except Exception as e:
            logger.error(f"whisper.cpp error: {e}")
            return ""

    def transcribe_audio_bytes(self, audio_bytes: bytes, sample_rate: int = 16000) -> str:
        """Transcribe raw audio bytes directly (skip recording)."""
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            wav_path = tmp.name
        
        try:
            self._save_wav_from_bytes(audio_bytes, sample_rate, wav_path)
            return self._transcribe_file(wav_path)
        finally:
            try:
                os.unlink(wav_path)
            except OSError:
                pass

    def _save_wav_from_bytes(self, data: bytes, sample_rate: int, path: str):
        """Save raw audio bytes as WAV."""
        import struct
        with wave.open(path, 'wb') as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(data)
