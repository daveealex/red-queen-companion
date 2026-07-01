#!/usr/bin/env python3
"""
LLM Client for the AI Companion.
Supports multiple backends:
  - Hermes API (cloud, default) — best model quality
  - Local Llama.cpp server (fallback)

With Smart Harness integration:
  - H1: Prompt enrichment (rules, guidelines)
  - H3: Action realization (syntax validation)
  - H4: Trajectory regulation (loop detection)
  - H5: Self-review (loop before committing)
  - H6: Error retry
  - H8: Vector memory
  - H9: Feedback injection

Speaker Mode:
  - Adult mode: Full access, Red Queen personality
  - Child mode: Safe mode, no HA control

Usage:
    from llm.client import LLMClient
    
    client = LLMClient(config)
    client.set_speaker_mode("adult")  # or "child"
    response = await client.chat("Hello, I'm David.")
    print(response)
"""

import json
import os
import sys
import logging
import aiohttp
from pathlib import Path

# Add smart-harness-prod to path if present
harness_path = Path(__file__).parent.parent / "smart-harness-prod"
if harness_path.exists() and str(harness_path) not in sys.path:
    sys.path.insert(0, str(harness_path))

logger = logging.getLogger(__name__)

# Try to import the harness
try:
    from smart_harness_prod.harness import Harness
    HARNESS_AVAILABLE = True
except Exception:
    HARNESS_AVAILABLE = False
    logger.warning("Smart Harness not available — running without safety layers")


class LLMClient:
    """LLM client supporting Hermes API, local servers, and vision (VLM).
    With optional Smart Harness for safety and validation."""

    def __init__(self, config: dict):
        self.provider = config.get("provider", "hermes")
        self.max_tokens = config.get("max_tokens", 500)
        self.temperature = config.get("temperature", 0.7)
        self.top_p = config.get("top_p", 0.9)
        self.system_prompt_file = config.get("system_prompt_file", "assets/system_prompt.md")
        
        # Load base system prompt
        self._base_system_prompt = self._load_system_prompt()
        self._current_system_prompt = self._base_system_prompt
        
        # Speaker mode (default to child-safe)
        self._speaker_mode = "child"

        # Hermes API config (local Lemonade on Pi)
        if self.provider == "hermes":
            self.api_url = config.get("hermes_api_url", "http://localhost:13305/v1")
            self.api_key = config.get("hermes_api_key", "")
            self.model = config.get("hermes_model", "Holo-3.1-4B-Q6_K")
            self.base_url = f"{self.api_url}/chat/completions"

        # External inference server (Lemonade on another machine)
        elif self.provider == "external":
            self.api_url = config.get("external_url", "http://192.168.1.1:13305/v1")
            self.api_key = config.get("external_api_key", "")
            self.model = config.get("external_model", "Qwen3.6-27B-MTP-GGUF-Q4_K_M")
            self.base_url = f"{self.api_url}/chat/completions"

        # Local server config (fallback - llama.cpp)
        elif self.provider == "local":
            self.api_url = config.get("local_url", "http://192.168.1.137:13305/v1")
            self.api_key = config.get("local_api_key", "")
            self.model = config.get("local_model", "Qwen3.6-27B-MTP-GGUF-Q4_K_M")
            self.base_url = f"{self.api_url}/chat/completions"

        # Conversation history
        self.conversation = []

        # Context management
        self.max_turns = config.get("max_conversation_turns", 20)
        self.auto_clear = config.get("auto_clear", True)

        # Initialize Smart Harness if available
        self.harness = None
        if HARNESS_AVAILABLE and self.provider == "hermes":
            try:
                self.harness = Harness(
                    llama_cpp_url=self.api_url,
                    max_retries=3,
                    safety_password="atlas-companion",  # Optional safety password
                )
                logger.info("Smart Harness initialized — safety layers active")
            except Exception as e:
                logger.warning(f"Failed to initialize Smart Harness: {e}")
                self.harness = None

    def _load_system_prompt(self) -> str:
        """Load the system prompt from file."""
        prompt_path = Path(self.system_prompt_file)
        if prompt_path.exists():
            return prompt_path.read_text().strip()
        return "You are the Red Queen, an AI companion."

    def set_speaker_mode(self, mode: str):
        """Set the current speaker mode and update system prompt.
        
        Args:
            mode: 'adult' or 'child'
        """
        self._speaker_mode = mode
        self._current_system_prompt = self._resolve_system_prompt()
        logger.info(f"Speaker mode set to: {mode}")

    def _resolve_system_prompt(self) -> str:
        """Resolve system prompt based on current speaker mode.
        
        The system prompt may contain [SPEAKER_MODE: adult] and [SPEAKER_MODE: child]
        markers. The active mode's content is kept, the inactive one is removed.
        """
        prompt = self._base_system_prompt
        
        if self._speaker_mode == "adult":
            # Keep adult mode, remove child mode
            if "[SPEAKER_MODE: child]" in prompt:
                # Find and remove the child mode block
                child_start = prompt.find("### [SPEAKER_MODE: child]")
                if child_start >= 0:
                    # Find the end of the child block (next ### or ---)
                    child_end = self._find_block_end(prompt, child_start)
                    if child_end > child_start:
                        prompt = prompt[:child_start] + prompt[child_end:]
            # Clean up the adult marker
            prompt = prompt.replace("[SPEAKER_MODE: adult]", "")
        else:
            # Keep child mode, remove adult mode
            if "[SPEAKER_MODE: adult]" in prompt:
                adult_start = prompt.find("### [SPEAKER_MODE: adult]")
                if adult_start >= 0:
                    adult_end = self._find_block_end(prompt, adult_start)
                    if adult_end > adult_start:
                        prompt = prompt[:adult_start] + prompt[adult_end:]
            # Clean up the child marker
            prompt = prompt.replace("[SPEAKER_MODE: child]", "")
        
        # Clean up extra blank lines
        while "\n\n\n" in prompt:
            prompt = prompt.replace("\n\n\n", "\n\n")
        
        return prompt.strip()

    @staticmethod
    def _find_block_end(prompt: str, start: int) -> int:
        """Find the end of a markdown block (### header)."""
        # Look for next ### or --- after the start
        next_header = prompt.find("\n### ", start + 1)
        next_separator = prompt.find("\n---\n", start + 1)
        
        candidates = []
        if next_header >= 0:
            candidates.append(next_header)
        if next_separator >= 0:
            candidates.append(next_separator)
        
        if candidates:
            return min(candidates)
        return len(prompt)

    def inject_ha_context(self, ha_result: str, user_query: str) -> str:
        """Inject HA command result into LLM for Red Queen-style response.
        
        Args:
            ha_result: The raw HA response text
            user_query: The original user query
            
        Returns:
            A prompt for the LLM to style the HA response
        """
        if self._speaker_mode == "adult":
            return f"[HA_RESULT: {ha_result}] — Style this result in your Red Queen voice. The user asked: {user_query}"
        else:
            return f"[HA_RESULT: {ha_result}] — Share this info in a friendly, playful way. The user asked: {user_query}"

    def add_message(self, role: str, content: str, image_url: str = None):
        """Add a message to the conversation history.
        
        Args:
            role: 'user' or 'assistant'
            content: The text content
            image_url: Optional URL to an image (for VLM support)
        """
        if image_url:
            # Multimodal message (VLM format)
            self.conversation.append({
                "role": role,
                "content": [
                    {"type": "text", "text": content},
                    {"type": "image_url", "image_url": {"url": image_url}}
                ]
            })
        else:
            # Standard text-only message
            self.conversation.append({"role": role, "content": content})

    def reset_conversation(self):
        """Clear conversation history."""
        self.conversation = []

    def get_conversation_stats(self) -> dict:
        """Get conversation statistics."""
        turns = len(self.conversation) // 2
        return {
            "turns": turns,
            "max_turns": self.max_turns,
            "auto_clear": self.auto_clear,
            "speaker_mode": self._speaker_mode,
        }

    def _trim_conversation(self):
        """Auto-trim old messages if we exceed max turns."""
        if not self.auto_clear:
            return
        
        while len(self.conversation) > self.max_turns * 2:
            self.conversation.pop(0)

    def get_messages(self) -> list:
        """Get the full message list with system prompt."""
        self._trim_conversation()
        messages = [{"role": "system", "content": self._current_system_prompt}]
        messages.extend(self.conversation)
        return messages

    async def chat(self, user_message: str, image_url: str = None, timeout=30) -> str:
        """Send a message to the LLM and get a response.
        
        Args:
            user_message: The user's input text
            image_url: Optional image URL for vision models (VLM)
            timeout: Request timeout in seconds
            
        Returns:
            The LLM's response as a string
        """
        logger.info(f"Sending to LLM ({self.provider}): {user_message[:60]}...")
        
        self.add_message("user", user_message, image_url=image_url)
        messages = self.get_messages()

        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "stream": False,
        }

        headers = {
            "Content-Type": "application/json",
        }

        # Add API key if needed
        if self.provider == "hermes" and self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        elif self.provider == "local" and self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.base_url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"LLM API error ({response.status}): {error_text[:200]}")
                        return f"Sorry, I had trouble thinking about that."

                    data = await response.json()
                    response_text = data["choices"][0]["message"].get("content", "")
                    reasoning = data["choices"][0]["message"].get("reasoning_content", "")
                    
                    # For reasoning models (Qwen3.6), content may be empty
                    # Extract final answer from reasoning_content
                    if not response_text and reasoning:
                        # Look for final answer patterns
                        if "Final answer:" in reasoning:
                            response_text = reasoning.split("Final answer:")[-1].strip()
                        elif "</think>" in reasoning:
                            # Strip thinking tags and use what's after
                            response_text = reasoning.split("</think>")[-1].strip()
                        else:
                            # Use the last part of reasoning (after the thinking process)
                            for separator in ["Drafting:", "Here's the response:", "Response:"]:
                                if separator in reasoning:
                                    response_text = reasoning.split(separator)[-1].strip()
                                    break
                            else:
                                response_text = reasoning[-200:].strip()
                    elif not response_text:
                        response_text = "Hmm, let me try again."
                    
                    self.add_message("assistant", response_text)
                    logger.info(f"LLM response: {response_text[:80]}{'...' if len(response_text) > 80 else ''}")
                    
                    # Log to harness memory if available
                    if self.harness:
                        try:
                            self.harness.memory.store_turn(
                                role="assistant",
                                content=response_text,
                            )
                        except Exception as e:
                            logger.warning(f"Failed to store in harness memory: {e}")
                    
                    return response_text

        except asyncio.TimeoutError:
            logger.error("LLM request timed out")
            return "I'm thinking... that took a while."
        except aiohttp.ClientError as e:
            logger.error(f"LLM connection error: {e}")
            return "I'm having trouble connecting right now."
        except Exception as e:
            logger.error(f"LLM error: {e}")
            return "Hmm, something went wrong. Try again?"

    def chat_sync(self, user_message: str, image_url: str = None, timeout=30) -> str:
        """Synchronous wrapper for chat()."""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                pass
            else:
                return asyncio.run(self.chat(user_message, image_url, timeout))
        except RuntimeError:
            return asyncio.run(self.chat(user_message, image_url, timeout))
