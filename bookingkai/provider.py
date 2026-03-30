"""BookingKAI provider implementation."""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime

from bookingkai.queue import BrowserQueue
from bookingkai.scraper import build_search_url
from history import HistoryStore
from models import CheckResult, ProviderStatus, StatusTracker, Train
from provider import Provider
from utils import is_wildcard, parse_price

logger = logging.getLogger(__name__)


class BookingKAIProvider(Provider):
    """Provider for booking.kai.id train search."""

    def __init__(
        self,
        origin: str,
        destination: str,
        date: str,
        train_name: str,
        interval: float,
        queue: BrowserQueue,
        index: int,
        notes: str = "",
        max_price: int = 0,
        proxy_url: str = "",
    ) -> None:
        self._origin = origin
        self._destination = destination
        self._date = date
        self._train_name = train_name
        self._max_price = max_price
        self._interval = max(interval, 300.0)  # minimum 5 minutes
        self._index = index
        self._notes = notes
        self._proxy_url = proxy_url
        self._history = HistoryStore(100)
        self._status = StatusTracker()
        self._queue = queue
        self._cancel_event = asyncio.Event()

    @property
    def name(self) -> str:
        return f"bookingkai:{self._train_name}:{self._origin}→{self._destination}"

    async def search(self) -> list[Train]:
        """Search and return trains matching the configured train name."""
        all_trains = await self._fetch_trains()

        # Wildcard "any"/"*" or empty = return all trains
        if not self._train_name or is_wildcard(self._train_name):
            return all_trains

        # Filter by train name
        target = self._train_name.lower()
        return [t for t in all_trains if target in t.name.lower()]

    async def search_all(self) -> list[Train]:
        """Return all trains on the route without filtering."""
        return await self._fetch_trains()

    async def _fetch_trains(self) -> list[Train]:
        """Build search URL and enqueue to the shared BrowserQueue."""
        search_url = build_search_url(self._origin, self._destination, self._date)
        logger.debug("Enqueuing booking.kai.id request: %s", search_url)

        trains = await self._queue.enqueue(search_url, self._proxy_url)

        logger.info(
            "BookingKAI search complete | route=%s→%s | date=%s | total=%d",
            self._origin,
            self._destination,
            self._date,
            len(trains),
        )

        return trains

    async def start_scheduler(self, notify_func) -> None:
        """Start the polling loop.

        Args:
            notify_func: async or sync callable(message: str) to send notifications
        """
        interval = self._interval

        def jittered_interval() -> float:
            """Add ±10% random jitter to the interval."""
            jitter = interval * 0.1
            return interval + random.uniform(-jitter, jitter)

        logger.info(
            "BookingKAI scheduler started | interval=%ss | target=%s",
            interval,
            self._train_name,
        )

        while not self._cancel_event.is_set():
            wait_time = jittered_interval()
            try:
                await asyncio.wait_for(
                    self._cancel_event.wait(), timeout=wait_time
                )
                # If event is set, we should stop
                break
            except asyncio.TimeoutError:
                pass  # Timer expired, proceed with check

            if await self._status.is_paused():
                continue

            await self._status.record_check_start()

            logger.debug("Scheduler checking BookingKAI...")

            try:
                trains = await self.search()
            except Exception as e:
                logger.error(
                    "Poll failed | provider=BookingKAI | route=%s→%s | date=%s | train=%s | error=%s",
                    self._origin,
                    self._destination,
                    self._date,
                    self._train_name,
                    e,
                )
                await self._status.record_check_error(str(e))
                await self._history.add(
                    CheckResult(timestamp=datetime.now(), error=str(e))
                )
                continue

            # Filter for AVAILABLE trains only
            available_trains: list[Train] = []
            for t in trains:
                if t.seats_left not in ("0", ""):
                    # Apply max price filter if configured
                    if self._max_price > 0:
                        price = parse_price(t.price)
                        if price > 0 and price > self._max_price:
                            continue
                    available_trains.append(t)

            await self._status.record_check_success(len(available_trains) > 0)

            await self._history.add(
                CheckResult(
                    timestamp=datetime.now(),
                    trains_found=len(trains),
                    available_trains=available_trains,
                )
            )

            if available_trains:
                msg = (
                    f"🚂 #{self._index} {self._train_name}\n"
                    f"📍 {self._origin}→{self._destination} [{self._date}]\n"
                    f"✅ Tersedia! ({len(available_trains)} found) via bookingkai\n"
                )
                if self._notes:
                    msg += f"📝 {self._notes}\n"
                msg += "\n"
                for t in available_trains:
                    msg += f"• {t.name} [{t.class_}]\n  💺 {t.seats_left} seats @ {t.price}\n"

                # Support both sync and async notify_func
                if asyncio.iscoroutinefunction(notify_func):
                    await notify_func(msg)
                else:
                    notify_func(msg)

    async def get_history(self, n: int) -> list[CheckResult]:
        return await self._history.get_last(n)

    async def get_status(self) -> ProviderStatus:
        start_time, total, success, failed, last_time, last_found, last_err = (
            await self._status.get_stats()
        )
        return ProviderStatus(
            start_time=start_time,
            total_checks=total,
            successful_checks=success,
            failed_checks=failed,
            last_check_time=last_time,
            last_check_found=last_found,
            last_check_error=last_err,
            origin=self._origin,
            destination=self._destination,
            date=self._date,
            train_name=self._train_name,
            interval=self._interval,
        )

    async def set_paused(self, paused: bool) -> None:
        await self._status.set_paused(paused)

    async def is_paused(self) -> bool:
        return await self._status.is_paused()

    def stop(self) -> None:
        """Signal the scheduler to stop."""
        self._cancel_event.set()
