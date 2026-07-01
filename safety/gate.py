#!/usr/bin/env python3
"""
Safety Gate — Speaker identification and access control for the Red Queen.

Sits between the user's speech and the LLM. Determines:
  1. Who is speaking (voice classification)
  2. What mode to use (adult vs child-safe)
  3. Whether HA control is permitted
  4. Which system prompt variant to inject

Flow:
    Audio recorded -> Safety Gate -> {mode: adult|child, ha_allowed: bool}
    -> System prompt modified -> LLM call

The gate uses voice-based classification (F0 analysis) by default.
Face recognition can be added later via camera module.

Usage:
    from safety.gate import SafetyGate

    gate = SafetyGate(config)
    result = gate.evaluate(audio_np, sample_rate=16000)
    # result = {'mode': 'adult', 'ha_allowed': True, 'speaker_type': 'adult', ...}

    # Get system prompt for this speaker
    prompt = gate.get_system_prompt(base_prompt)
"""

import logging
import time
from pathlib import Path
import numpy as np

from safety.voice_classifier import VoiceClassifier

logger = logging.getLogger(__name__)


class SafetyGate:
    """Evaluates speaker and determines access level."""

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.enabled = self.config.get("enabled", True)
        self.default_mode = self.config.get("default_mode", "child")  # child-safe by default
        self.require_enrollment = self.config.get("require_enrollment", False)
        self.voice_classifier = VoiceClassifier(self.config.get("voice", {}))

        # Speaker history (recent classifications)
        self.recent_speakers = []  # (timestamp, result)
        self.history_window = self.config.get("history_window_seconds", 60)
        self.history_min_samples = self.config.get("history_min_samples", 3)

        # HA access rules
        self.ha_rules = self.config.get("ha_rules", {
            "adult": {"allowed": True, "restricted_entities": []},
            "child": {"allowed": False, "restricted_entities": []},
        })

        if not self.enabled:
            logger.info("Safety gate disabled — all requests pass through in adult mode")

    def evaluate(self, audio_np=None, sample_rate=16000) -> dict:
        """Evaluate audio and determine speaker mode.

        Args:
            audio_np: Audio samples (numpy array). If None, uses recent history or default.
            sample_rate: Sample rate in Hz.

        Returns:
            dict with:
                - mode: 'adult' | 'child'
                - ha_allowed: bool
                - speaker_type: 'adult' | 'child' | 'unknown'
                - confidence: float 0-1
                - reason: str explanation
        """
        if not self.enabled:
            return {
                "mode": "adult",
                "ha_allowed": True,
                "speaker_type": "adult",
                "confidence": 1.0,
                "reason": "safety_gate_disabled",
            }

        if audio_np is not None and len(audio_np) > 0:
            # Classify the speaker
            classification = self.voice_classifier.classify(audio_np, sample_rate)

            # Store in history
            self.recent_speakers.append((time.time(), classification))
            self._cleanup_history()

            result = self._determine_mode(classification)
            result["reason"] = f"voice_f0={classification['mean_f0']}Hz"
            return result

        # No audio — use history or default
        if self.recent_speakers:
            recent = self._get_recent_classifications()
            if recent:
                # Majority vote from recent samples
                adult_count = sum(1 for r in recent if r["speaker_type"] == "adult")
                child_count = sum(1 for r in recent if r["speaker_type"] == "child")

                if adult_count > child_count and adult_count >= self.history_min_samples:
                    if self.require_enrollment:
                        has_known = any(r.get("is_known_adult") for r in recent)
                        if has_known:
                            return {"mode": "adult", "ha_allowed": True, "speaker_type": "adult", "confidence": 0.7, "reason": "history_adult_enrolled"}
                    return {"mode": "adult", "ha_allowed": True, "speaker_type": "adult", "confidence": 0.7, "reason": "history_majority_adult"}
                else:
                    return {"mode": "child", "ha_allowed": False, "speaker_type": "child", "confidence": 0.7, "reason": "history_majority_child"}

        # Default to child-safe
        return {
            "mode": self.default_mode,
            "ha_allowed": self.default_mode == "adult",
            "speaker_type": "unknown",
            "confidence": 0.0,
            "reason": f"default_{self.default_mode}_no_audio",
        }

    def get_system_prompt(self, base_prompt: str, mode: str = None) -> str:
        """Get the system prompt with speaker mode injected.

        Args:
            base_prompt: The base system prompt template
            mode: Override mode ('adult' or 'child'). If None, uses recent evaluation.

        Returns:
            System prompt with [SPEAKER_MODE] replaced.
        """
        if mode is None:
            eval_result = self.evaluate()
            mode = eval_result["mode"]

        prompt = base_prompt.replace("[SPEAKER_MODE: adult]", mode == "adult" and "ACTIVE" or "")
        prompt = prompt.replace("[SPEAKER_MODE: child]", mode == "child" and "ACTIVE" or "")

        # If both are blank (no placeholders in prompt), inject at top
        if "[SPEAKER_MODE:" not in base_prompt:
            mode_instruction = ""
            if mode == "adult":
                mode_instruction = "\n[SPEAKER MODE: ADULT] — Full access. Menacing, authoritative Red Queen personality."
            else:
                mode_instruction = "\n[SPEAKER MODE: CHILD] — Child-safe. No HA control. Playful, warm, educational."
            prompt = prompt + mode_instruction

        # Clean up blank lines from inactive mode blocks
        prompt = self._clean_prompt(prompt)

        return prompt

    def is_ha_allowed(self, mode: str = None) -> bool:
        """Check if Home Assistant control is allowed for current speaker."""
        if mode is None:
            eval_result = self.evaluate()
            mode = eval_result["mode"]

        rule = self.ha_rules.get(mode, {})
        return rule.get("allowed", False)

    def enroll_voice(self, name: str, audio_np: np.ndarray, sample_rate: int, voice_type: str = "adult"):
        """Enroll a speaker voice profile."""
        import numpy as np
        self.voice_classifier.enroll_voice(name, audio_np, sample_rate, voice_type)

    def _determine_mode(self, classification: dict) -> dict:
        """Determine adult/child mode from voice classification."""
        speaker_type = classification["speaker_type"]
        confidence = classification["confidence"]
        is_known = classification.get("is_known_adult", False)

        if speaker_type == "adult" and confidence > 0.5:
            if self.require_enrollment and not is_known:
                # Require known adult enrollment
                return {
                    "mode": self.default_mode,
                    "ha_allowed": False,
                    "speaker_type": speaker_type,
                    "confidence": confidence,
                    "reason": "adult_pitch_but_not_enrolled",
                }
            return {
                "mode": "adult",
                "ha_allowed": True,
                "speaker_type": speaker_type,
                "confidence": confidence,
                "reason": "voice_classification_adult",
            }
        else:
            return {
                "mode": "child",
                "ha_allowed": False,
                "speaker_type": speaker_type,
                "confidence": confidence,
                "reason": "voice_classification_child_or_unknown",
            }

    def _cleanup_history(self):
        """Remove old entries from speaker history."""
        cutoff = time.time() - self.history_window
        self.recent_speakers = [(t, r) for t, r in self.recent_speakers if t > cutoff]

    def _get_recent_classifications(self) -> list:
        """Get recent classification results."""
        return [r for _, r in self.recent_speakers]

    @staticmethod
    def _clean_prompt(prompt: str) -> str:
        """Clean up inactive mode blocks from prompt."""
        lines = prompt.split("\n")
        cleaned = []
        for line in lines:
            # Remove lines that are clearly inactive mode blocks
            stripped = line.strip()
            if stripped in ("[SPEAKER_MODE: adult]", "[SPEAKER_MODE: child]"):
                continue
            cleaned.append(line)
        return "\n".join(cleaned)
