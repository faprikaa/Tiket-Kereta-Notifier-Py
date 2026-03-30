"""Serialized request queue for BookingKAI.

All BookingKAI providers share one queue so that requests to booking.kai.id
are serialized (one at a time), avoiding rate-limit issues.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from models import Train
from bookingkai.scraper import fetch_trains

logger = logging.getLogger(__name__)


@dataclass
class Job:
    """A single search request to be processed by the queue."""

    search_url: str
    proxy_url: str = ""
    result_future: asyncio.Future = field(default_factory=lambda: asyncio.get_event_loop().create_future())


class BrowserQueue:
    """Serializes all requests to booking.kai.id through a single async worker.

    Uses curl_cffi with browser impersonation (no actual browser needed).
    All bookingkai providers should share the same queue.
    """

    def __init__(self, proxy_url: str = "") -> None:
        self._proxy_url = proxy_url
        self._queue: asyncio.Queue[Job] = asyncio.Queue(maxsize=64)
        self._worker_task: asyncio.Task | None = None
        self._closed = False

        logger.info(
            "BookingKAI queue initialized (proxy=%s)",
            proxy_url or "none",
        )

    def start(self) -> None:
        """Start the background worker task."""
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._worker())
            logger.info("BookingKAI queue worker started")

    async def _worker(self) -> None:
        """Process jobs one at a time from the queue."""
        while not self._closed:
            try:
                job = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            try:
                trains = await fetch_trains(
                    search_url=job.search_url,
                    proxy_url=job.proxy_url or self._proxy_url,
                )
                if not job.result_future.done():
                    job.result_future.set_result(trains)
            except Exception as e:
                if not job.result_future.done():
                    job.result_future.set_exception(e)
            finally:
                self._queue.task_done()

    async def enqueue(self, search_url: str, proxy_url: str = "") -> list[Train]:
        """Submit a search URL to the queue and wait for the result.

        This is the main entry point for providers.
        """
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        job = Job(
            search_url=search_url,
            proxy_url=proxy_url,
            result_future=future,
        )

        await self._queue.put(job)
        return await future

    async def close(self) -> None:
        """Shut down the queue worker gracefully."""
        self._closed = True
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info("BookingKAI queue stopped")
