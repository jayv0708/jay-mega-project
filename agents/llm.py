from __future__ import annotations

import asyncio
import json
import os
from typing import Any, AsyncIterator

import httpx


ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_STREAM_URL = "https://api.anthropic.com/v1/messages"


class AnthropicClient:
    def __init__(self, model: str | None = None) -> None:
        self.api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.model = model or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

    async def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float,
        max_tokens: int,
        fallback: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.api_key:
            return fallback

        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(ANTHROPIC_API_URL, headers=headers, json=payload)
            response.raise_for_status()
        text = response.json()["content"][0]["text"]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                return json.loads(text[start : end + 1])
            return fallback

    async def stream_text(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        fallback_text: str = "",
    ) -> AsyncIterator[str]:
        """Stream text tokens from Anthropic API. Falls back to word-by-word simulation."""
        if not self.api_key:
            # Deterministic fallback: emit words one at a time with 30ms delay
            words = (fallback_text or "Processing complete.").split()
            for word in words:
                yield word + " "
                await asyncio.sleep(0.03)
            return

        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            "stream": True,
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream("POST", ANTHROPIC_STREAM_URL, headers=headers, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[len("data:"):].strip()
                    if raw == "[DONE]":
                        break
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    # Anthropic SSE: content_block_delta with delta.text
                    if event.get("type") == "content_block_delta":
                        delta = event.get("delta", {})
                        if delta.get("type") == "text_delta":
                            token = delta.get("text", "")
                            if token:
                                yield token
