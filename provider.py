"""Abstract base class for train search providers."""

from __future__ import annotations

from abc import ABC, abstractmethod

from history import HistoryStore
from models import CheckResult, ProviderStatus, Train


class Provider(ABC):
    """Standard interface for train search providers."""

    @abstractmethod
    async def search(self) -> list[Train]:
        """Search and return trains matching the configured train name."""
        ...

    @abstractmethod
    async def search_all(self) -> list[Train]:
        """Return all trains on the route without name filtering."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the provider display name."""
        ...

    @abstractmethod
    async def start_scheduler(self, notify_func) -> None:
        """Start the polling loop. notify_func(message: str) sends notifications."""
        ...

    @abstractmethod
    async def get_history(self, n: int) -> list[CheckResult]:
        """Return the last N check results."""
        ...

    @abstractmethod
    async def get_status(self) -> ProviderStatus:
        """Return the current provider status."""
        ...

    @abstractmethod
    async def set_paused(self, paused: bool) -> None:
        """Set the paused state."""
        ...

    @abstractmethod
    async def is_paused(self) -> bool:
        """Return whether the provider is paused."""
        ...
