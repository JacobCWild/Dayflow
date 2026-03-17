"""
OllamaProvider - talks to a locally-running Ollama instance via its HTTP API.

Default endpoint: http://localhost:11434
Default model:    llava  (a vision-capable model; must be pulled with `ollama pull llava`)

Ollama chat API reference:
  POST /api/chat
  Body: { "model": "...", "messages": [...], "stream": false }

For vision models the message includes images as a list of base64-encoded strings:
  { "role": "user", "content": "...", "images": ["<base64>", ...] }
"""

import base64
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "llava"


class OllamaProvider:
    """Sends screenshots and text to Ollama and returns AI-generated descriptions."""

    def __init__(
        self,
        base_url: str = DEFAULT_OLLAMA_URL,
        model: str = DEFAULT_MODEL,
        timeout: int = 120,
        max_retries: int = 3,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries

    # ------------------------------------------------------------------
    # Connectivity helpers
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Return True when Ollama is running and reachable."""
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    def get_available_models(self) -> List[str]:
        """Return the list of model names known to this Ollama instance."""
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=10)
            if resp.status_code == 200:
                return [m["name"] for m in resp.json().get("models", [])]
        except Exception as exc:
            logger.error("Failed to list Ollama models: %s", exc)
        return []

    # ------------------------------------------------------------------
    # Low-level API call
    # ------------------------------------------------------------------

    def _load_image_b64(self, image_path: Path) -> Optional[str]:
        """Read *image_path* and return its content as a base64 string."""
        try:
            return base64.b64encode(image_path.read_bytes()).decode("utf-8")
        except Exception as exc:
            logger.error("Cannot read image %s: %s", image_path, exc)
            return None

    def _call_ollama(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.7,
    ) -> Optional[str]:
        """POST a chat request to Ollama and return the assistant reply text."""
        url = f"{self.base_url}/api/chat"
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }

        for attempt in range(self.max_retries):
            try:
                resp = requests.post(url, json=payload, timeout=self.timeout)
                if resp.status_code == 200:
                    return resp.json().get("message", {}).get("content", "")
                logger.warning(
                    "Ollama HTTP %d (attempt %d/%d): %s",
                    resp.status_code,
                    attempt + 1,
                    self.max_retries,
                    resp.text[:200],
                )
            except requests.exceptions.Timeout:
                logger.warning(
                    "Ollama timeout (attempt %d/%d)", attempt + 1, self.max_retries
                )
            except Exception as exc:
                logger.error("Ollama request error: %s", exc)

            if attempt < self.max_retries - 1:
                time.sleep(2 ** attempt)  # exponential back-off: 1s, 2s, 4s

        return None

    # ------------------------------------------------------------------
    # High-level helpers
    # ------------------------------------------------------------------

    def describe_frame(self, image_path: Path) -> Optional[str]:
        """Return a 1-2 sentence description of the activity visible in *image_path*."""
        img_b64 = self._load_image_b64(image_path)
        if img_b64 is None:
            return None

        messages = [
            {
                "role": "user",
                "content": (
                    "Describe what the user is doing in this screenshot in 1-2 sentences. "
                    "Focus on the main application and activity "
                    "(e.g. 'Writing code in VS Code', 'Reading documentation in Chrome', "
                    "'In a video meeting'). Be concise and specific."
                ),
                "images": [img_b64],
            }
        ]
        return self._call_ollama(messages, temperature=0.3)

    def generate_activity_summary(
        self,
        observations: List[str],
        start_time: str,
        end_time: str,
    ) -> Dict[str, str]:
        """
        Given a list of per-frame descriptions, produce a structured activity summary.

        Returns a dict with keys: title, summary, category.
        """
        obs_text = "\n".join(f"- {o}" for o in observations if o)

        prompt = (
            f"Based on these screen-activity observations recorded from {start_time} to {end_time}:\n\n"
            f"{obs_text}\n\n"
            "Produce a brief activity summary with:\n"
            "1. A short title (5-8 words) describing the main activity.\n"
            "2. A 2-3 sentence summary of what was accomplished.\n"
            "3. A category chosen from: "
            "[work, communication, browsing, entertainment, development, writing, other]\n\n"
            'Respond with valid JSON only, in this exact shape:\n'
            '{"title": "...", "summary": "...", "category": "..."}'
        )

        messages = [{"role": "user", "content": prompt}]
        result = self._call_ollama(messages, temperature=0.5)

        if result:
            # Strip optional markdown fences that some models add.
            stripped = result.strip()
            if stripped.startswith("```"):
                lines = stripped.splitlines()
                stripped = "\n".join(
                    line for line in lines if not line.startswith("```")
                ).strip()
            try:
                data = json.loads(stripped)
                return {
                    "title": str(data.get("title", "Activity")),
                    "summary": str(data.get("summary", "")),
                    "category": str(data.get("category", "other")),
                }
            except json.JSONDecodeError:
                logger.warning("Could not parse activity summary JSON: %s", result[:200])
                return {"title": "Activity", "summary": result[:500], "category": "other"}

        return {"title": "Activity", "summary": "", "category": "other"}
