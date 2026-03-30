"""Telegram bot setup using python-telegram-bot v21+.

Supports both webhook and polling modes.
"""

from __future__ import annotations

import logging
from datetime import datetime

from telegram.ext import Application

from config import Config
from provider import Provider
from telegram_bot.commands import register_commands

logger = logging.getLogger(__name__)


class TelegramBot:
    """Wrapper around python-telegram-bot Application."""

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._app: Application | None = None

    def build(self, providers: list[Provider]) -> Application:
        """Build the PTB Application with all command handlers registered."""
        builder = Application.builder().token(self._cfg.telegram.bot_token)

        # Rate limiting is built into PTB
        self._app = builder.build()

        # Register commands
        register_commands(self._app, providers, self._cfg)

        logger.info("Telegram bot built with %d command handlers", len(self._app.handlers[0]))
        return self._app

    async def send_message(self, text: str, chat_id: str | None = None) -> bool:
        """Send a message to the configured chat or specified chat ID.

        Adds timestamp prefix and handles truncation.
        """
        target = chat_id or self._cfg.telegram.chat_id
        if not target or not self._app:
            return False

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S WIB")
        full_message = f"[{current_time}] {text}"

        max_length = 4096
        if len(full_message) > max_length:
            full_message = full_message[: max_length - 25] + "\n\n[Message truncated]"

        try:
            await self._app.bot.send_message(chat_id=target, text=full_message)
            logger.debug("Telegram message sent to %s", target)
            return True
        except Exception as e:
            logger.error("Failed to send telegram message: %s", e)
            return False

    async def start_polling(self) -> None:
        """Start the bot in long-polling mode."""
        if not self._app:
            raise RuntimeError("Bot not built. Call build() first.")

        logger.info("Starting bot in polling mode...")
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(
            allowed_updates=["message"],
            drop_pending_updates=True,
        )

    async def start_webhook(self, port: int, webhook_url: str) -> None:
        """Start the bot in webhook mode.

        Args:
            port: Local port to listen on
            webhook_url: Public URL that Telegram will call
        """
        if not self._app:
            raise RuntimeError("Bot not built. Call build() first.")

        logger.info("Starting bot in webhook mode on port %d...", port)
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_webhook(
            listen="0.0.0.0",
            port=port,
            url_path="/webhook",
            webhook_url=f"{webhook_url}/webhook",
            allowed_updates=["message"],
            drop_pending_updates=True,
        )

    async def stop(self) -> None:
        """Stop the bot gracefully."""
        if self._app:
            logger.info("Stopping Telegram bot...")
            if self._app.updater and self._app.updater.running:
                await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            logger.info("Telegram bot stopped")
