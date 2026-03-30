"""Tiket Kereta Notifier - BookingKAI (Python)

Main entrypoint. Loads config, initializes providers, starts schedulers,
and runs the Telegram bot.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

from bookingkai import BookingKAIProvider, BrowserQueue
from bookingkai.scraper import close_nodriver_browser
from cloudflared import CloudflaredTunnel
from config import Config, load_config, parse_args
from provider import Provider
from telegram_bot.bot import TelegramBot
from utils import is_wildcard

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def init_all_providers(cfg: Config) -> tuple[list[Provider], BrowserQueue | None]:
    """Create providers for each flat train config.

    Returns (providers, browser_queue).
    """
    providers: list[Provider] = []

    # Find the first bookingkai proxy to initialize the shared queue
    proxy_url = ""
    for flat in cfg.flat_trains:
        if flat.provider_name == "bookingkai" and flat.proxy_url:
            proxy_url = flat.proxy_url
            break

    # Create shared BrowserQueue for all bookingkai providers
    bk_queue: BrowserQueue | None = None
    if cfg.flat_trains:
        bk_queue = BrowserQueue(proxy_url=proxy_url)

    for i, flat in enumerate(cfg.flat_trains):
        if flat.provider_name != "bookingkai":
            continue

        provider = BookingKAIProvider(
            origin=flat.origin,
            destination=flat.destination,
            date=flat.date,
            train_name=flat.name,
            interval=flat.interval_seconds,
            queue=bk_queue,
            index=i + 1,
            notes=flat.notes,
            max_price=flat.max_price,
            proxy_url=flat.proxy_url,
        )
        providers.append(provider)

        logger.info(
            "Initialized train monitor | train=%s | provider=%s | route=%s → %s | date=%s | interval=%ss",
            flat.name,
            flat.provider_name,
            flat.origin,
            flat.destination,
            flat.date,
            int(flat.interval_seconds),
        )

    return providers, bk_queue


async def validate_trains_exist(
    providers: list[Provider], cfg: Config
) -> None:
    """Validate that configured trains actually exist.

    Groups trains by (name, origin, destination, date) so each unique route
    is only validated once.
    """
    # Group key structure
    groups: dict[tuple[str, str, str, str], list[int]] = {}
    group_order: list[tuple[str, str, str, str]] = []

    for i, flat in enumerate(cfg.flat_trains):
        # Skip wildcard names
        if is_wildcard(flat.name):
            logger.info(
                "Wildcard train name, skipping validation | route=%s → %s",
                flat.origin,
                flat.destination,
            )
            continue
        if not flat.name:
            logger.info(
                "No train name filter, skipping validation | route=%s → %s",
                flat.origin,
                flat.destination,
            )
            continue

        key = (flat.name.lower(), flat.origin, flat.destination, flat.date)
        if key not in groups:
            groups[key] = []
            group_order.append(key)
        groups[key].append(i)

    # Validate each group
    for key in group_order:
        indices = groups[key]
        flat = cfg.flat_trains[indices[0]]

        validated = False
        last_err = None

        for idx in indices:
            provider = providers[idx]
            provider_name = cfg.flat_trains[idx].provider_name

            logger.info(
                "Validating train... | train=%s | provider=%s",
                flat.name,
                provider_name,
            )

            try:
                trains = await provider.search()
            except Exception as e:
                logger.warning(
                    "Validation failed, trying next provider | train=%s | provider=%s | error=%s",
                    flat.name,
                    provider_name,
                    e,
                )
                last_err = e
                continue

            # Check if any result matches
            target = flat.name.lower()
            for t in trains:
                if target in t.name.lower():
                    logger.info(
                        "✓ Train found | train=%s | matched=%s | availability=%s | via=%s",
                        flat.name,
                        t.name,
                        t.availability,
                        provider_name,
                    )
                    validated = True
                    break

            if validated:
                break

            # Train not found
            available_names = [t.name for t in trains]
            last_err = RuntimeError(
                f"train '{flat.name}' not found on route {flat.origin} → {flat.destination} "
                f"(date: {flat.date}). Available: {available_names}"
            )

        if not validated:
            raise RuntimeError(f"Failed to validate train {flat.name}: {last_err}")


async def main() -> None:
    """Main async entrypoint."""
    # Parse CLI args
    config_path = parse_args()

    # Load config
    cfg = load_config(config_path)

    # Validate config
    try:
        cfg.validate()
    except ValueError as e:
        logger.error("Config validation failed: %s", e)
        sys.exit(1)

    # Initialize providers
    providers, bk_queue = init_all_providers(cfg)

    if not providers:
        logger.error("No train monitors configured (bookingkai only)")
        sys.exit(1)

    # Start the browser queue worker
    if bk_queue:
        bk_queue.start()

    # Build Telegram bot
    tg_bot = TelegramBot(cfg)
    app = tg_bot.build(providers)

    # Create shutdown event
    shutdown_event = asyncio.Event()

    # Setup signal handlers
    loop = asyncio.get_running_loop()

    def signal_handler():
        logger.info("Received shutdown signal")
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler for SIGTERM
            pass

    # Start schedulers with staggered delays
    stagger_delay = 15  # seconds
    scheduler_tasks: list[asyncio.Task] = []

    async def run_scheduler(
        provider: Provider, delay: float, notify_func
    ) -> None:
        if delay > 0:
            logger.info(
                "Staggering scheduler start | provider=%s | delay=%ss",
                provider.name,
                delay,
            )
            await asyncio.sleep(delay)
        await provider.start_scheduler(notify_func)

    for i, provider in enumerate(providers):
        delay = i * stagger_delay

        async def make_notify(msg: str, _bot=tg_bot) -> None:
            await _bot.send_message(msg)

        task = asyncio.create_task(
            run_scheduler(provider, delay, make_notify)
        )
        scheduler_tasks.append(task)

    logger.info("Started train monitors: %d", len(providers))

    # Validate trains
    logger.info("Validating configured trains...")
    try:
        await validate_trains_exist(providers, cfg)
        logger.info("✅ All configured trains validated successfully")
    except RuntimeError as e:
        logger.warning(
            "⚠️ Train validation failed (will retry via scheduler): %s", e
        )

    # Start cloudflared tunnel to get public URL
    tunnel = CloudflaredTunnel(cfg.webhook.port)
    webhook_url = cfg.webhook.url
    if not webhook_url:
        webhook_url = await tunnel.start()
        logger.info("Cloudflared tunnel URL: %s", webhook_url)

    # Start bot (webhook mode)
    logger.info("Starting bot in webhook mode...")
    await tg_bot.start_webhook(cfg.webhook.port, webhook_url)

    startup_msg = f"🚀 Bot started!\nMonitoring {len(providers)} trains\nWebhook: {webhook_url}"
    await tg_bot.send_message(startup_msg)

    logger.info("Bot running. Press Ctrl+C to exit.")

    # Wait for shutdown
    try:
        await shutdown_event.wait()
    except asyncio.CancelledError:
        pass

    # Cleanup
    logger.info("Shutting down...")

    # Stop all schedulers
    for provider in providers:
        if isinstance(provider, BookingKAIProvider):
            provider.stop()

    for task in scheduler_tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # Stop bot
    await tg_bot.stop()

    # Close browser queue
    if bk_queue:
        await bk_queue.close()

    # Close nodriver browser if it was started
    await close_nodriver_browser()

    # Stop cloudflared tunnel
    await tunnel.stop()

    logger.info("Shutdown complete")


if __name__ == "__main__":
    # Handle Windows Ctrl+C properly
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
