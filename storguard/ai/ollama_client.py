"""Ollama local LLM client — wraps the Ollama REST API via httpx.

Requires Ollama running locally:
    curl -fsSL https://ollama.com/install.sh | sh
    ollama pull llama3.2
    ollama serve                 # http://localhost:11434

All methods fail gracefully — callers should check is_available() first.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional

import httpx


@dataclass
class OllamaConfig:
    host: str = "http://localhost:11434"
    model: str = "gemma4:26b"
    timeout_seconds: int = 600
    temperature: float = 0.1  # low temp → deterministic, analytical output


@dataclass
class OllamaResponse:
    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    duration_ms: float = 0.0


class OllamaClient:
    def __init__(self, config: Optional[OllamaConfig] = None) -> None:
        self._cfg = config or OllamaConfig()
        self._http = httpx.Client(timeout=self._cfg.timeout_seconds)

    # ─── Health ───────────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        try:
            resp = self._http.get(f"{self._cfg.host}/api/tags", timeout=3)
            return resp.status_code == 200
        except Exception:
            return False

    def list_models(self) -> List[str]:
        resp = self._http.get(f"{self._cfg.host}/api/tags", timeout=5)
        resp.raise_for_status()
        return [m["name"] for m in resp.json().get("models", [])]

    # ─── Generation ───────────────────────────────────────────────────────────

    def generate(self, prompt: str, system: str = "") -> OllamaResponse:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self._cfg.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": self._cfg.temperature},
        }

        start = time.monotonic()
        resp = self._http.post(f"{self._cfg.host}/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()
        duration_ms = (time.monotonic() - start) * 1000

        return OllamaResponse(
            content=data["message"]["content"],
            model=data.get("model", self._cfg.model),
            prompt_tokens=data.get("prompt_eval_count", 0),
            completion_tokens=data.get("eval_count", 0),
            duration_ms=duration_ms,
        )

    # ─── Lifecycle ────────────────────────────────────────────────────────────

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "OllamaClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
