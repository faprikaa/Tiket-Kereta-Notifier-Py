"""Configuration loading, parsing, and validation."""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class TelegramConfig:
    """Telegram bot settings."""

    bot_token: str = ""
    chat_id: str = ""


@dataclass
class WebhookConfig:
    """Webhook settings."""

    enabled: bool = False
    port: int = 8080
    url: str = ""  # Public URL for webhook (user must provide if webhook enabled)


@dataclass
class ProviderEntry:
    """A provider in the providers array.
    Supports both simple string ('bookingkai') and object ({name: bookingkai, proxy_url: ...}).
    """

    name: str = ""
    proxy_url: str = ""


@dataclass
class TrainConfig:
    """Configuration for a single train to monitor."""

    name: str = ""
    origin: str = ""
    destination: str = ""
    date: str = ""  # YYYY-MM-DD
    interval: int = 300
    notes: str = ""
    max_price: int = 0  # Max price filter in IDR (0 = no filter)
    providers: list[ProviderEntry] = field(default_factory=list)

    # Backward compat: single provider field (deprecated)
    provider: str = ""
    proxy_url: str = ""

    def validate(self) -> None:
        """Validate train config, raises ValueError on error."""
        if not self.origin:
            raise ValueError(f"origin is required for train {self.name}")
        if not self.destination:
            raise ValueError(f"destination is required for train {self.name}")
        if not self.date:
            raise ValueError(f"date is required for train {self.name}")
        if not self.providers and not self.provider:
            raise ValueError(f"at least one provider is required for train {self.name}")


@dataclass
class FlatTrainConfig:
    """A single train × provider combination (internal use)."""

    name: str = ""
    origin: str = ""
    destination: str = ""
    date: str = ""  # YYYY-MM-DD
    interval: int = 300
    interval_seconds: float = 300.0
    notes: str = ""
    max_price: int = 0
    provider_name: str = ""
    proxy_url: str = ""

    def date_yyyymmdd(self) -> str:
        """Return date in YYYYMMDD format."""
        return self.date.replace("-", "")

    def date_parts(self) -> tuple[int, int, int]:
        """Return (day, month, year) from date string."""
        parsed = datetime.strptime(self.date, "%Y-%m-%d")
        return parsed.day, parsed.month, parsed.year


@dataclass
class Config:
    """Full application configuration."""

    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    webhook: WebhookConfig = field(default_factory=WebhookConfig)
    trains: list[TrainConfig] = field(default_factory=list)
    flat_trains: list[FlatTrainConfig] = field(default_factory=list)

    def validate(self) -> None:
        """Validate config, raises ValueError on error."""
        if not self.telegram.bot_token:
            raise ValueError("telegram.bot_token is required in config.yml")
        if not self.telegram.chat_id:
            raise ValueError("telegram.chat_id is required in config.yml")
        if not self.trains:
            raise ValueError("at least one train configuration is required")

        for i, train in enumerate(self.trains):
            try:
                train.validate()
            except ValueError as e:
                raise ValueError(f"train #{i + 1}: {e}") from e

        if not self.flat_trains:
            raise ValueError("no bookingkai provider configured for any train")


def _parse_provider_entry(raw) -> ProviderEntry:
    """Parse a provider entry from YAML (string or dict form)."""
    if isinstance(raw, str):
        return ProviderEntry(name=raw)
    elif isinstance(raw, dict):
        return ProviderEntry(
            name=raw.get("name", ""),
            proxy_url=raw.get("proxy_url", ""),
        )
    else:
        raise ValueError(f"invalid provider entry: {raw}")


def _parse_train_config(raw: dict) -> TrainConfig:
    """Parse a single train config from YAML dict."""
    providers_raw = raw.get("providers", [])
    providers = [_parse_provider_entry(p) for p in providers_raw]

    return TrainConfig(
        name=raw.get("name", ""),
        origin=raw.get("origin", ""),
        destination=raw.get("destination", ""),
        date=str(raw.get("date", "")),
        interval=raw.get("interval", 300),
        notes=raw.get("notes", ""),
        max_price=raw.get("max_price", 0),
        providers=providers,
        provider=raw.get("provider", ""),
        proxy_url=raw.get("proxy_url", ""),
    )


def _process_train_configs(cfg: Config) -> None:
    """Compute derived fields and flatten trains × providers.
    Only bookingkai providers are kept.
    """
    for train in cfg.trains:
        # Backward compat: single provider → providers array
        if train.provider and not train.providers:
            train.providers = [
                ProviderEntry(name=train.provider, proxy_url=train.proxy_url)
            ]

        if train.interval <= 0:
            train.interval = 300  # default 5 minutes

    # Flatten: one entry per train × bookingkai provider
    for train in cfg.trains:
        for prov in train.providers:
            prov_name = prov.name.lower()
            # Only include bookingkai providers
            if prov_name != "bookingkai":
                continue

            cfg.flat_trains.append(
                FlatTrainConfig(
                    name=train.name,
                    origin=train.origin,
                    destination=train.destination,
                    date=train.date,
                    interval=train.interval,
                    interval_seconds=float(train.interval),
                    notes=train.notes,
                    max_price=train.max_price,
                    provider_name=prov_name,
                    proxy_url=prov.proxy_url,
                )
            )

    # Default webhook port
    if cfg.webhook.port == 0:
        cfg.webhook.port = 8080


def load_config(config_path: str = "config.yml") -> Config:
    """Load configuration from a YAML file."""
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        logger.error("Config file not found: %s", config_path)
        sys.exit(1)
    except yaml.YAMLError as e:
        logger.error("Failed to parse YAML config: %s", e)
        sys.exit(1)

    if data is None:
        logger.error("Config file is empty: %s", config_path)
        sys.exit(1)

    # Parse telegram config
    tg_raw = data.get("telegram", {})
    telegram_cfg = TelegramConfig(
        bot_token=str(tg_raw.get("bot_token", "")),
        chat_id=str(tg_raw.get("chat_id", "")),
    )

    # Parse webhook config
    wh_raw = data.get("webhook", {})
    webhook_cfg = WebhookConfig(
        enabled=wh_raw.get("enabled", False),
        port=wh_raw.get("port", 8080),
        url=wh_raw.get("url", ""),
    )

    # Parse train configs
    trains_raw = data.get("trains", [])
    trains = [_parse_train_config(t) for t in trains_raw]

    cfg = Config(
        telegram=telegram_cfg,
        webhook=webhook_cfg,
        trains=trains,
    )

    _process_train_configs(cfg)

    return cfg


def parse_args() -> str:
    """Parse CLI arguments and return config file path."""
    parser = argparse.ArgumentParser(description="Tiket Kereta Notifier (BookingKAI)")
    parser.add_argument(
        "-c",
        "--config",
        default="config.yml",
        help="Path to YAML config file (default: config.yml)",
    )
    args = parser.parse_args()
    return args.config
