import asyncio
from openai import AsyncOpenAI
from app.config import settings
import logging

class LLMUnavailable(Exception):
    pass

class LLMClient:
    def __init__(self):
        self.client = AsyncOpenAI(
            base_url=settings.LLM_BASE_URL if settings.LLM_BASE_URL else None,
            api_key=settings.LLM_API_KEY if settings.LLM_API_KEY else "dummy",
        )
        self.semaphore = asyncio.Semaphore(4)

    async def chat(self, messages, role="agent", tools=None, temperature=0, json_mode=False):
        model = settings.LLM_MODEL_AGENT
        if role == "fast":
            model = settings.LLM_MODEL_FAST
        elif role == "vision":
            model = settings.LLM_MODEL_VISION
            
        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        async with self.semaphore:
            try:
                # Add retry logic and fallback later. For phase 0, just pass.
                response = await self.client.chat.completions.create(**kwargs)
                return response
            except Exception as e:
                logging.error(f"LLM Error: {e}")
                raise LLMUnavailable("LLM failed")

    async def vision(self, image_bytes_list, prompt, schema=None):
        messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
        for b in image_bytes_list:
            pass # TODO: encode image base64
        async with self.semaphore:
            try:
                response = await self.client.chat.completions.create(
                    model=settings.LLM_MODEL_VISION,
                    messages=messages,
                )
                return response
            except Exception as e:
                raise LLMUnavailable("Vision LLM failed")

llm_client = LLMClient()
