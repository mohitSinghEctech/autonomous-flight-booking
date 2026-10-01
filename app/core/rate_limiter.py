import asyncio
import time


class RateLimiter:
    def __init__(self, rate: int):
        self.interval = 1 / rate
        self.lock = asyncio.Lock()
        self.next_time = time.monotonic()

    async def acquire(self):
        async with self.lock:
            now = time.monotonic()

            scheduled_time = max(
                now,
                self.next_time
            )

            self.next_time = scheduled_time + self.interval

            delay = scheduled_time - now

        if delay > 0:
            await asyncio.sleep(delay)


llm_rate_limiter = RateLimiter(rate=5)