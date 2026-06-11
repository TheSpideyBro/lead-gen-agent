import asyncio
import logging
import random
import time
from collections import defaultdict
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class RateLimiter:
    def __init__(self, requests_per_minute: int = 60, min_interval_seconds: float = 1.0):
        self.requests_per_minute = requests_per_minute
        self.min_interval_seconds = min_interval_seconds
        self._last_request_time: Dict[str, float] = defaultdict(float)
        self._request_counts: Dict[str, list] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def acquire(self, key: str = "default") -> bool:
        async with self._lock:
            now = time.time()
            
            self._request_counts[key] = [t for t in self._request_counts[key] if now - t < 60]
            
            if len(self._request_counts[key]) >= self.requests_per_minute:
                logger.warning(f"Rate limit exceeded for {key}")
                return False
            
            elapsed = now - self._last_request_time[key]
            if elapsed < self.min_interval_seconds:
                await asyncio.sleep(self.min_interval_seconds - elapsed)
            
            self._last_request_time[key] = time.time()
            self._request_counts[key].append(time.time())
            return True

    def reset(self, key: Optional[str] = None):
        if key:
            self._last_request_time.pop(key, None)
            self._request_counts.pop(key, None)
        else:
            self._last_request_time.clear()
            self._request_counts.clear()


class AsyncRetry:
    def __init__(self, max_attempts: int = 3, base_delay: float = 1.0, max_delay: float = 60.0):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay

    async def execute(self, func, *args, **kwargs):
        for attempt in range(self.max_attempts):
            try:
                return await func(*args, **kwargs)
            except Exception as exc:
                if attempt == self.max_attempts - 1:
                    raise
                delay = min(self.base_delay * (2 ** attempt), self.max_delay)
                logger.warning(f"Retry attempt {attempt + 1}/{self.max_attempts} after {delay}s: {exc}")
                await asyncio.sleep(delay + random.uniform(0, 1))