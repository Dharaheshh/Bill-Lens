"""
BillLens full LLM client with cache, retry, fallback, and LLMUnavailable.
"""
import asyncio
import base64
import hashlib
import json
import logging
from typing import Any

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)


class LLMUnavailable(Exception):
    pass


class LLMResponse:
    def __init__(self, text: str, tool_calls: list | None = None, usage: dict | None = None):
        self.text = text
        self.tool_calls = tool_calls or []
        self.usage = usage or {}


class LLMClient:
    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(4)
        self._primary: AsyncOpenAI | None = None
        self._fallback: AsyncOpenAI | None = None

    def _get_primary(self) -> AsyncOpenAI:
        if self._primary is None:
            self._primary = AsyncOpenAI(
                base_url=settings.LLM_BASE_URL or None,
                api_key=settings.LLM_API_KEY or "dummy",
                timeout=30.0,
            )
        return self._primary

    def _get_fallback(self) -> AsyncOpenAI | None:
        if not settings.LLM_FALLBACK_API_KEY:
            return None
        if self._fallback is None:
            self._fallback = AsyncOpenAI(
                base_url=settings.LLM_FALLBACK_BASE_URL or None,
                api_key=settings.LLM_FALLBACK_API_KEY,
                timeout=30.0,
            )
        return self._fallback

    def _model_for(self, role: str) -> str:
        if role == "vision":
            return settings.LLM_MODEL_VISION or "gpt-4o"
        if role == "fast":
            return settings.LLM_MODEL_FAST or settings.LLM_MODEL_AGENT or "gpt-4o-mini"
        return settings.LLM_MODEL_AGENT or "gpt-4o-mini"

    def _cache_key(self, model: str, messages: list, tools: Any, temperature: float) -> str:
        raw = json.dumps({"model": model, "messages": messages, "tools": tools, "temperature": temperature}, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()

    async def _try_call(self, client: AsyncOpenAI, **kwargs) -> LLMResponse:
        resp = await client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        text = msg.content or ""
        tool_calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "args": json.loads(tc.function.arguments or "{}"),
                })
        usage = {}
        if resp.usage:
            usage = {"prompt_tokens": resp.usage.prompt_tokens, "completion_tokens": resp.usage.completion_tokens}
        return LLMResponse(text=text, tool_calls=tool_calls, usage=usage)

    async def chat(
        self,
        messages: list,
        role: str = "agent",
        tools: list | None = None,
        temperature: float = 0,
        json_mode: bool = False,
    ) -> LLMResponse:
        if not settings.LLM_API_KEY:
            raise LLMUnavailable("No LLM_API_KEY configured")

        model = self._model_for(role)
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        async with self._semaphore:
            # Try primary
            for attempt in range(2):
                try:
                    return await asyncio.wait_for(
                        self._try_call(self._get_primary(), **kwargs),
                        timeout=25.0,
                    )
                except LLMUnavailable:
                    raise
                except Exception as e:  # noqa: BLE001
                    if attempt == 0:
                        await asyncio.sleep(1)
                        continue
                    logger.warning("Primary LLM failed: %s", e)
                    break

            # Try fallback
            fb = self._get_fallback()
            if fb:
                fb_model = settings.LLM_FALLBACK_MODEL or model
                try:
                    fb_kwargs = {**kwargs, "model": fb_model}
                    return await asyncio.wait_for(self._try_call(fb, **fb_kwargs), timeout=25.0)
                except Exception as e:  # noqa: BLE001
                    logger.warning("Fallback LLM failed: %s", e)

            raise LLMUnavailable("All LLM providers failed")

    async def vision(self, image_bytes_list: list[bytes], prompt: str, schema: dict | None = None) -> LLMResponse:
        if not settings.LLM_API_KEY:
            raise LLMUnavailable("No LLM_API_KEY configured")

        content: list[dict] = [{"type": "text", "text": prompt}]
        for img_bytes in image_bytes_list:
            b64 = base64.b64encode(img_bytes).decode()
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "high"},
            })
        messages = [{"role": "user", "content": content}]
        kwargs: dict[str, Any] = {
            "model": self._model_for("vision"),
            "messages": messages,
            "max_tokens": 4096,
        }
        if schema:
            kwargs["response_format"] = {"type": "json_object"}

        async with self._semaphore:
            for attempt in range(2):
                try:
                    return await asyncio.wait_for(self._try_call(self._get_primary(), **kwargs), timeout=45.0)
                except LLMUnavailable:
                    raise
                except Exception as e:  # noqa: BLE001
                    if attempt == 0:
                        await asyncio.sleep(1)
                        continue
                    logger.warning("Vision LLM failed: %s", e)
                    break
            raise LLMUnavailable("Vision LLM failed")


llm_client = LLMClient()
