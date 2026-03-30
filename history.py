"""Thread-safe history storage for train check results."""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime

from models import CheckResult


class HistoryStore:
    """Async-safe history storage using a bounded deque."""

    def __init__(self, max_size: int = 100) -> None:
        self._lock = asyncio.Lock()
        self._max_size = max_size if max_size > 0 else 100
        self._results: deque[CheckResult] = deque(maxlen=self._max_size)

    async def add(self, result: CheckResult) -> None:
        """Add a new check result to history (newest first)."""
        async with self._lock:
            if result.timestamp is None:
                result.timestamp = datetime.now()
            self._results.appendleft(result)

    async def get_last(self, n: int) -> list[CheckResult]:
        """Return the last N check results (newest first)."""
        async with self._lock:
            if n <= 0 or n > len(self._results):
                n = len(self._results)
            return list(self._results)[:n]

    async def count(self) -> int:
        """Return the total number of stored results."""
        async with self._lock:
            return len(self._results)
