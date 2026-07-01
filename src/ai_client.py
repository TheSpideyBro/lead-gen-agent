import asyncio
import logging
import os
import random
import time
from typing import Optional

logger = logging.getLogger(__name__)


class AIClient:
    # Minimum seconds between AI calls from a single client instance.
    _MIN_CALL_INTERVAL: float = 1.0

    def __init__(self):
        self.provider = self._detect_provider()
        self._client = None
        self._init_client()
        self._last_call_time: float = 0.0
        self._rate_limit_lock: asyncio.Lock = asyncio.Lock()

    def _detect_provider(self) -> str:
        if os.getenv("GROQ_API_KEY"):
            return "groq"
        if os.getenv("GOOGLE_AI_API_KEY"):
            return "google"
        logger.warning("No AI API key found! Set GROQ_API_KEY or GOOGLE_AI_API_KEY")
        return "none"

    def _init_client(self):
        if self.provider == "groq":
            try:
                from openai import OpenAI
                self._client = OpenAI(
                    api_key=os.getenv("GROQ_API_KEY"),
                    base_url="https://api.groq.com/openai/v1",
                )
                self._model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
            except ImportError:
                logger.error("Install: pip install openai")

        elif self.provider == "google":
            try:
                import google.generativeai as genai
                genai.configure(api_key=os.getenv("GOOGLE_AI_API_KEY"))
                self._model = os.getenv("GOOGLE_AI_MODEL", "gemini-2.0-flash")
                self._client = genai.GenerativeModel(self._model)
            except ImportError:
                logger.error("Install: pip install google-generativeai")

    async def generate(self, prompt: str, system_prompt: str = "You are a helpful assistant.") -> str:
        if self.provider == "none":
            return "[AI disabled — set API key in .env]"

        async with self._rate_limit_lock:
            elapsed = time.time() - self._last_call_time
            if elapsed < self._MIN_CALL_INTERVAL:
                await asyncio.sleep(self._MIN_CALL_INTERVAL - elapsed)
            self._last_call_time = time.time()

        max_attempts = int(os.getenv("AI_MAX_RETRIES", "3"))
        for attempt in range(max_attempts):
            try:
                if self.provider == "groq":
                    return await self._groq_generate(system_prompt, prompt)
                elif self.provider == "google":
                    return await self._google_generate(system_prompt, prompt)
            except Exception as exc:
                if attempt < max_attempts - 1:
                    wait = (2 ** (attempt + 1)) + random.uniform(0, 1)
                    logger.warning(f"AI retry {attempt+1}/{max_attempts} in {wait:.1f}s: {exc}")
                    await asyncio.sleep(wait)
                else:
                    return f"[AI Error: {exc}]"

        return "[AI Error: exhausted retries]"

    async def _groq_generate(self, system_prompt: str, user_prompt: str) -> str:
        response = await asyncio.to_thread(
            self._client.chat.completions.create,
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=1500,
            temperature=0.7,
        )
        return response.choices[0].message.content

    async def _google_generate(self, system_prompt: str, user_prompt: str) -> str:
        full_prompt = f"{system_prompt}\n\n{user_prompt}"
        response = await asyncio.to_thread(
            self._client.generate_content,
            full_prompt,
        )
        return response.text