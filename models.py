"""Data models for the train ticket notifier."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional


@dataclass
class Train:
    """Standardized train data structure."""

    name: str = ""
    class_: str = ""
    price: str = ""
    departure_time: str = ""
    arrival_time: str = ""
    availability: str = ""  # "AVAILABLE" or "FULL"
    seats_left: str = ""  # e.g. "50", "0"


@dataclass
class CheckResult:
    """A single check result for history."""

    timestamp: datetime = field(default_factory=datetime.now)
    trains_found: int = 0
    available_trains: list[Train] = field(default_factory=list)
    error: str = ""


@dataclass
class ProviderStatus:
    """Status information for a provider."""

    start_time: datetime = field(default_factory=datetime.now)
    total_checks: int = 0
    successful_checks: int = 0
    failed_checks: int = 0
    last_check_time: Optional[datetime] = None
    last_check_found: bool = False
    last_check_error: str = ""
    origin: str = ""
    destination: str = ""
    date: str = ""
    train_name: str = ""
    interval: float = 300.0  # seconds


class StatusTracker:
    """Thread-safe status tracking for providers."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.start_time = datetime.now()
        self.total_checks = 0
        self.successful_checks = 0
        self.failed_checks = 0
        self.last_check_time: Optional[datetime] = None
        self.last_check_found = False
        self.last_check_error = ""
        self.paused = False

    async def record_check_start(self) -> None:
        async with self._lock:
            self.total_checks += 1
            self.last_check_time = datetime.now()

    async def record_check_success(self, found: bool) -> None:
        async with self._lock:
            self.successful_checks += 1
            self.last_check_found = found
            self.last_check_error = ""

    async def record_check_error(self, err: str) -> None:
        async with self._lock:
            self.failed_checks += 1
            self.last_check_found = False
            self.last_check_error = err

    async def get_stats(
        self,
    ) -> tuple[datetime, int, int, int, Optional[datetime], bool, str]:
        async with self._lock:
            return (
                self.start_time,
                self.total_checks,
                self.successful_checks,
                self.failed_checks,
                self.last_check_time,
                self.last_check_found,
                self.last_check_error,
            )

    async def set_paused(self, paused: bool) -> None:
        async with self._lock:
            self.paused = paused

    async def is_paused(self) -> bool:
        async with self._lock:
            return self.paused
