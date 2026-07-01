#!/usr/bin/env python3
"""
Voice-based Speaker Classifier for the Red Queen Companion.

Classifies speakers as adult or child using fundamental frequency (F0) analysis.
Adults typically speak at lower F0 than children:
  - Adult male:   85-180 Hz
  - Adult female: 165-255 Hz
  - Child:        250-500+ Hz

Uses parselmouth (Praat) for pitch extraction if available,
falls back to simple autocorrelation method.

Usage:
    from safety.voice_classifier import VoiceClassifier
    vc = VoiceClassifier()
    speaker_type = vc.classify(audio_bytes, sample_rate=16000)
    # Returns: 'adult' or 'child'
"""

import numpy as np
import logging
import os
import subprocess
import tempfile

logger = logging.getLogger(__name__)

# Try to import parselmouth for better pitch detection
try:
    import parselmouth
    from parselmouth.praat import call
    PARSLEMOUTH_AVAILABLE = True
except ImportError:
    PARSLEMOUTH_AVAILABLE = False
    logger.info("parselmouth not available — using autocorrelation pitch detection")


class VoiceClassifier:
    """Classify speaker as adult or child based on voice pitch (F0)."""

    # Pitch thresholds (Hz)
    ADULT_MAX_F0 = 220      # Above this, likely a child
    CHILD_MIN_F0 = 250      # Above this, definitely a child
    UNCERTAIN_RANGE = (200, 250)  # Ambiguous zone — default to child-safe

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.enrolled_voices = {}  # name -> mean_f0
        self._load_enrolled_voices()

    def _load_enrolled_voices(self):
        """Load any pre-enrolled voice profiles."""
        enroll_dir = os.path.expanduser("~/.red-queen/voices")
        if os.path.exists(enroll_dir):
            for fname in os.listdir(enroll_dir):
                if fname.endswith(".npy"):
                    name = fname.replace(".npy", "")
                    path = os.path.join(enroll_dir, fname)
                    try:
                        data = np.load(path, allow_pickle=True).item()
                        self.enrolled_voices[name] = data
                        logger.info(f"Loaded enrolled voice: {name} (F0={data['mean_f0']:.1f}Hz)")
                    except Exception as e:
                        logger.warning(f"Failed to load voice {name}: {e}")

    def classify(self, audio_np: np.ndarray, sample_rate: int = 16000) -> dict:
        """Classify audio as adult or child speaker.

        Args:
            audio_np: numpy array of audio samples (float32 or int16)
            sample_rate: sample rate in Hz

        Returns:
            dict with keys:
                - speaker_type: 'adult' | 'child' | 'unknown'
                - mean_f0: estimated fundamental frequency in Hz
                - confidence: 0.0-1.0
                - is_known_adult: bool (matches enrolled adult voice)
        """
        if audio_np is None or len(audio_np) == 0:
            return {"speaker_type": "unknown", "mean_f0": 0, "confidence": 0, "is_known_adult": False}

        # Normalize to float32 -1..1
        if audio_np.dtype == np.int16:
            audio_np = audio_np.astype(np.float32) / 32768.0

        # Extract pitch
        mean_f0, f0_confidence = self._extract_pitch(audio_np, sample_rate)

        if mean_f0 <= 0 or f0_confidence < 0.3:
            # Can't determine — default to child-safe
            return {"speaker_type": "unknown", "mean_f0": mean_f0, "confidence": f0_confidence, "is_known_adult": False}

        # Check against enrolled voices
        is_known_adult = self._match_enrolled(audio_np, sample_rate)

        # Classify based on pitch
        if mean_f0 < self.ADULT_MAX_F0:
            speaker_type = "adult"
            confidence = min(1.0, (self.ADULT_MAX_F0 - mean_f0) / 100 + f0_confidence * 0.5)
        elif mean_f0 > self.CHILD_MIN_F0:
            speaker_type = "child"
            confidence = min(1.0, (mean_f0 - self.CHILD_MIN_F0) / 150 + f0_confidence * 0.5)
        else:
            # Ambiguous zone — default to child-safe
            speaker_type = "child"
            confidence = 0.5

        return {
            "speaker_type": speaker_type,
            "mean_f0": round(mean_f0, 1),
            "confidence": round(confidence, 2),
            "is_known_adult": is_known_adult,
        }

    def _extract_pitch(self, audio: np.ndarray, sample_rate: int) -> tuple:
        """Extract mean fundamental frequency from audio.

        Returns (mean_f0_hz, confidence_0_to_1).
        """
        if PARSLEMOUTH_AVAILABLE:
            return self._extract_pitch_parselmouth(audio, sample_rate)
        else:
            return self._extract_pitch_autocorrelation(audio, sample_rate)

    def _extract_pitch_parselmouth(self, audio: np.ndarray, sample_rate: int) -> tuple:
        """Use parselmouth (Praat) for pitch extraction."""
        duration = len(audio) / sample_rate
        if duration < 0.1:
            return 0, 0

        snd = parselmouth.Sound(audio, sampling_frequency=sample_rate)
        pitch = call(snd, "To Pitch", 0.01, 75, 500)
        pitch_values = pitch.selected_array['frequency']

        # Filter out zeros (unvoiced segments)
        voiced = pitch_values[pitch_values > 0]
        if len(voiced) == 0:
            return 0, 0

        mean_f0 = float(np.mean(voiced))
        confidence = min(1.0, len(voiced) / (len(pitch_values) * 0.5))

        return mean_f0, confidence

    def _extract_pitch_autocorrelation(self, audio: np.ndarray, sample_rate: int) -> tuple:
        """Simple autocorrelation-based pitch detection (no dependencies)."""
        duration = len(audio) / sample_rate
        if duration < 0.1:
            return 0, 0

        # Window: focus on a short segment for stability
        window_size = int(sample_rate * 0.05)  # 50ms window
        step = window_size // 2
        f0_values = []

        for start in range(0, len(audio) - window_size, step):
            segment = audio[start:start + window_size]
            f0 = self._autocorrelation_f0(segment, sample_rate)
            if 75 < f0 < 500:  # Valid human speech range
                f0_values.append(f0)

        if len(f0_values) == 0:
            return 0, 0

        mean_f0 = float(np.median(f0_values))
        confidence = min(1.0, len(f0_values) / (len(audio) / (step * sample_rate) * 0.5))

        return mean_f0, confidence

    @staticmethod
    def _autocorrelation_f0(audio: np.ndarray, sample_rate: int) -> float:
        """Estimate F0 using autocorrelation on a single window."""
        # Trim silence
        energy = np.abs(audio)
        if np.mean(energy) < 0.01:
            return 0

        corr = np.correlate(audio, audio, mode='full')
        corr = corr[len(corr) // 2:]  # Take positive lags only

        # Search in F0 range 75-500 Hz
        min_lag = int(sample_rate / 500)
        max_lag = int(sample_rate / 75)

        if max_lag > len(corr):
            max_lag = len(corr) - 1

        corr_segment = corr[min_lag:max_lag]
        if len(corr_segment) == 0:
            return 0

        peak_lag = np.argmax(corr_segment) + min_lag
        if peak_lag == 0:
            return 0

        return sample_rate / peak_lag

    def _match_enrolled(self, audio: np.ndarray, sample_rate: int) -> bool:
        """Check if speaker matches an enrolled adult voice."""
        if not self.enrolled_voices:
            return False  # No enrollment yet — rely on pitch only

        mean_f0, _ = self._extract_pitch(audio, sample_rate)

        for name, profile in self.enrolled_voices.items():
            if profile.get("type") != "adult":
                continue
            enrolled_f0 = profile["mean_f0"]
            if abs(mean_f0 - enrolled_f0) < 40:  # Within 40 Hz
                logger.info(f"Voice matches enrolled adult: {name}")
                return True

        return False

    def enroll_voice(self, name: str, audio: np.ndarray, sample_rate: int, voice_type: str = "adult"):
        """Enroll a voice profile for later matching.

        Args:
            name: Speaker name (e.g., 'david')
            audio: Audio samples
            sample_rate: Sample rate
            voice_type: 'adult' or 'child'
        """
        mean_f0, confidence = self._extract_pitch(audio, sample_rate)

        if confidence < 0.3:
            logger.warning(f"Enrollment for {name}: low confidence ({confidence:.2f}), poor audio quality")

        profile = {
            "mean_f0": mean_f0,
            "type": voice_type,
            "confidence": confidence,
            "sample_count": len(audio),
        }

        self.enrolled_voices[name] = profile

        # Persist
        enroll_dir = os.path.expanduser("~/.red-queen/voices")
        os.makedirs(enroll_dir, exist_ok=True)
        np.save(os.path.join(enroll_dir, f"{name}.npy"), profile)

        logger.info(f"Enrolled voice: {name} (F0={mean_f0:.1f}Hz, type={voice_type})")
