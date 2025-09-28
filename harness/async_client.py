"""Async OpenRouter client with retries and timeout handling."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, Optional

import aiohttp
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from harness.config import get_settings
from harness.exceptions import HarnessError


def wrap_content(text: str) -> list[dict[str, str]]:
    return [{"type": "text", "text": text}]


class ResilientOpenRouterClient:
    def __init__(
        self,
        *,
        base_url: str = "https://openrouter.ai/api/v1",
        timeout_seconds: int = 120,
    ) -> None:
        self._settings = get_settings()
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._session: Optional[aiohttp.ClientSession] = None

    @asynccontextmanager
    async def session(self) -> AsyncIterator[aiohttp.ClientSession]:
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=self._timeout)
            connector = aiohttp.TCPConnector(limit=10)
            self._session = aiohttp.ClientSession(timeout=timeout, connector=connector)
        try:
            yield self._session
        finally:
            # caller is responsible for closing via close()
            ...

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def _call_with_retry(self, *, payload: Dict[str, Any]) -> Dict[str, Any]:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=2, max=10),
            retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)),
        ):
            with attempt:
                async with self.session() as session:
                    headers = {
                        "Authorization": f"Bearer {self._settings.openrouter_api_key}",
                        "HTTP-Referer": "benchmark-harness",
                        "Content-Type": "application/json",
                    }
                    async with session.post(
                        f"{self._base_url}/chat/completions",
                        json=payload,
                        headers=headers,
                    ) as response:
                        response.raise_for_status()
                        return await response.json()

    async def call_completion(
        self,
        *,
        prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> Dict[str, Any]:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": wrap_content("You produce clean, minimal patches.")},
                {"role": "user", "content": wrap_content(prompt)},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            return await self._call_with_retry(payload=payload)
        except Exception as exc:
            raise HarnessError(f"OpenRouter API call failed: {exc}") from exc
