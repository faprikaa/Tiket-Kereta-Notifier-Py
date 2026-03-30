"""Telegram bot command handlers.

All 7 commands from the Go version, ported to python-telegram-bot handlers.
"""

from __future__ import annotations

import logging
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from config import Config, FlatTrainConfig
from models import Train
from provider import Provider
from utils import format_duration, format_rupiah, parse_price

logger = logging.getLogger(__name__)


def _timestamp_prefix() -> str:
    """Return a timestamp prefix for messages."""
    return datetime.now().strftime("[%Y-%m-%d %H:%M:%S WIB]")


def _truncate(msg: str, max_len: int = 4096) -> str:
    """Truncate message to Telegram's max length."""
    if len(msg) > max_len:
        return msg[: max_len - 25] + "\n\n[Message truncated]"
    return msg


async def _check_train_result(
    provider: Provider, flat: FlatTrainConfig
) -> str:
    """Check availability and return a formatted result string."""
    try:
        trains = await provider.search()
    except Exception as e:
        return f"❌ {flat.name} [{flat.date}] via {flat.provider_name}\n   Error: {e}"

    if not trains:
        return f"❌ {flat.name} [{flat.date}] via {flat.provider_name}\n   No trains found"

    # Filter for available trains
    available: list[Train] = []
    for t in trains:
        if t.availability == "AVAILABLE" or (t.seats_left not in ("0", "")):
            if flat.max_price > 0:
                price = parse_price(t.price)
                if price > 0 and price > flat.max_price:
                    continue
            available.append(t)

    if available:
        lines = [
            f"✅ {flat.name} [{flat.date}] via {flat.provider_name}: {len(available)} tersedia!"
        ]
        for t in available:
            lines.append(
                f"   🚂 {t.name}\n   ⏰ {t.departure_time} → {t.arrival_time}\n   💺 {t.seats_left} seats @ {t.price}"
            )
        return "\n".join(lines)

    return f"⛔ {flat.name} [{flat.date}] via {flat.provider_name}: Habis ({len(trains)} kereta full)"


def register_commands(
    app,
    providers: list[Provider],
    cfg: Config,
) -> None:
    """Register all command handlers on the PTB Application.

    Commands: /check, /all, /list, /status, /history, /toggle, /help
    """
    from telegram.ext import CommandHandler

    # --- /check [index] ---
    async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        args = " ".join(context.args) if context.args else ""
        args = args.strip()

        # Single train check
        if args:
            try:
                idx = int(args)
                if 1 <= idx <= len(providers):
                    result = await _check_train_result(
                        providers[idx - 1], cfg.flat_trains[idx - 1]
                    )
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=_truncate(f"{_timestamp_prefix()} {result}"),
                    )
                    return
            except ValueError:
                pass

        # Check all trains
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"{_timestamp_prefix()} 🔍 Checking {len(providers)} trains...",
        )

        lines: list[str] = []
        available_count = 0

        for i, provider in enumerate(providers):
            flat = cfg.flat_trains[i]
            try:
                trains = await provider.search()
            except Exception:
                lines.append(
                    f"❌ #{i + 1} {flat.name} [{flat.date}] via {flat.provider_name}: Error"
                )
                continue

            # Filter for available
            available: list[Train] = []
            for t in trains:
                if t.availability == "AVAILABLE" or (
                    t.seats_left not in ("0", "")
                ):
                    if flat.max_price > 0:
                        price = parse_price(t.price)
                        if price > 0 and price > flat.max_price:
                            continue
                    available.append(t)

            if available:
                available_count += 1
                lines.append(
                    f"✅ #{i + 1} {flat.name} [{flat.date}] via {flat.provider_name}: {len(available)} tersedia!"
                )
                for t in available:
                    lines.append(f"   💺 {t.seats_left} seats @ {t.price}")
            else:
                lines.append(
                    f"⛔ #{i + 1} {flat.name} [{flat.date}] via {flat.provider_name}: Habis"
                )

        header = f"📊 Hasil Check ({available_count}/{len(providers)} tersedia):\n\n"
        text = header + "\n".join(lines)
        await context.bot.send_message(
            chat_id=chat_id,
            text=_truncate(f"{_timestamp_prefix()} {text}"),
        )

    # --- /all <index> ---
    async def cmd_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        args = " ".join(context.args) if context.args else ""
        args = args.strip()

        if not args:
            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ Usage: /all <index>\nExample: /all 1",
            )
            return

        try:
            idx = int(args)
        except ValueError:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ Invalid index. Use 1-{len(providers)}",
            )
            return

        if idx < 1 or idx > len(providers):
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ Invalid index. Use 1-{len(providers)}",
            )
            return

        flat = cfg.flat_trains[idx - 1]
        provider = providers[idx - 1]

        await context.bot.send_message(
            chat_id=chat_id,
            text=f"📋 Fetching all trains for #{idx} [{flat.date}] {flat.provider_name}...",
        )

        try:
            trains = await provider.search_all()
        except Exception as e:
            await context.bot.send_message(
                chat_id=chat_id, text=f"❌ Error: {e}"
            )
            return

        if not trains:
            await context.bot.send_message(
                chat_id=chat_id, text="❌ No trains found on this route"
            )
            return

        lines: list[str] = [
            f"🚂 All Trains: {flat.origin} → {flat.destination} [{flat.date}]\n"
        ]

        for i, t in enumerate(trains):
            status = "⛔"
            if t.availability == "AVAILABLE" or (
                t.seats_left not in ("0", "")
            ):
                status = "✅"
            lines.append(f"{i + 1}. {status} {t.name}")
            lines.append(f"   ⏰ {t.departure_time} → {t.arrival_time}")
            if t.seats_left not in ("0", ""):
                lines.append(f"   💺 {t.seats_left} seats @ {t.price}")
            lines.append("")

            # Break message if too long
            text_so_far = "\n".join(lines)
            if len(text_so_far) > 3500:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=_truncate(f"{_timestamp_prefix()} {text_so_far}"),
                )
                lines = []

        if lines:
            lines.append(f"Total: {len(trains)} trains")
            await context.bot.send_message(
                chat_id=chat_id,
                text=_truncate(
                    f"{_timestamp_prefix()} {chr(10).join(lines)}"
                ),
            )

    # --- /list [index] ---
    async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        args = " ".join(context.args) if context.args else ""
        args = args.strip()

        # Single train details
        if args:
            try:
                idx = int(args)
                if 1 <= idx <= len(providers):
                    flat = cfg.flat_trains[idx - 1]
                    status = await providers[idx - 1].get_status()
                    last_check = "Never"
                    if status.last_check_time:
                        elapsed = (
                            datetime.now() - status.last_check_time
                        ).total_seconds()
                        last_check = format_duration(elapsed) + " ago"

                    paused_str = ""
                    if await providers[idx - 1].is_paused():
                        paused_str = " ⏸️ PAUSED"

                    proxy_str = "Yes" if flat.proxy_url else "No"

                    msg = f"🚂 Train #{idx}: {flat.name}{paused_str}\n\n"
                    msg += f"📍 Route: {flat.origin} → {flat.destination}\n"
                    msg += f"📅 Date: {flat.date}\n"
                    msg += f"🔌 Provider: {flat.provider_name}\n"
                    msg += f"⏱️ Interval: {int(flat.interval_seconds)}s\n"
                    msg += f"🌐 Proxy: {proxy_str}\n"
                    if flat.max_price > 0:
                        msg += f"💰 Max Price: Rp {format_rupiah(flat.max_price)}\n"
                    if flat.notes:
                        msg += f"📝 Notes: {flat.notes}\n"
                    msg += f"\n📊 Last check: {last_check}"

                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=_truncate(f"{_timestamp_prefix()} {msg}"),
                    )
                    return
            except ValueError:
                pass

        # List all trains, grouped by train identity
        provider_emoji = {
            "traveloka": "✈️",
            "tiketkai": "🚉",
            "tiketcom": "🎫",
            "bookingkai": "🏛️",
        }

        lines = ["🚂 *Configured Trains*"]
        flat_idx = 0

        for train_cfg in cfg.trains:
            # Count bookingkai providers for this train
            bk_count = sum(
                1
                for p in train_cfg.providers
                if p.name.lower() == "bookingkai"
            )
            if bk_count == 0:
                continue

            lines.append(
                f"\n🚂 *{train_cfg.name}* | {train_cfg.origin} → {train_cfg.destination}"
            )
            date_line = f"📅 {train_cfg.date}"
            if train_cfg.notes:
                date_line += f" | 📝 {train_cfg.notes}"
            lines.append(date_line)

            for prov in train_cfg.providers:
                if prov.name.lower() != "bookingkai":
                    continue
                if flat_idx >= len(providers):
                    break

                provider = providers[flat_idx]
                flat = cfg.flat_trains[flat_idx]
                status = await provider.get_status()

                # Status icon from last check
                status_icon = "⬜"
                if status.last_check_time:
                    if status.last_check_error:
                        status_icon = "❌"
                    elif status.last_check_found:
                        status_icon = "✅"
                    else:
                        status_icon = "⛔"

                if await provider.is_paused():
                    status_icon = "⏸️"

                last_check = "never"
                if status.last_check_time:
                    elapsed = (
                        datetime.now() - status.last_check_time
                    ).total_seconds()
                    last_check = format_duration(elapsed) + " ago"

                emoji = provider_emoji.get(flat.provider_name, "🔌")
                provider_label = flat.provider_name.upper()
                if flat.proxy_url:
                    provider_label += " (proxy)"

                lines.append(
                    f" {status_icon} {emoji} {provider_label} | #{flat_idx + 1} | {last_check}"
                )
                flat_idx += 1

        lines.append("\n/list <n> · /check <n> · /toggle <n>")

        await context.bot.send_message(
            chat_id=chat_id,
            text=_truncate(f"{_timestamp_prefix()} {chr(10).join(lines)}"),
        )

    # --- /status [index] ---
    async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        args = " ".join(context.args) if context.args else ""
        args = args.strip()

        # Single train status
        if args:
            try:
                idx = int(args)
                if 1 <= idx <= len(providers):
                    await _show_train_status(
                        context, chat_id, providers[idx - 1], cfg.flat_trains[idx - 1], idx
                    )
                    return
            except ValueError:
                pass

        # Summary of all trains
        lines = ["🤖 Bot Status Summary\n"]

        total_checks = 0
        total_success = 0
        total_failed = 0

        for i, provider in enumerate(providers):
            status = await provider.get_status()
            flat = cfg.flat_trains[i]

            total_checks += status.total_checks
            total_success += status.successful_checks
            total_failed += status.failed_checks

            icon = "⛔"
            if status.last_check_found:
                icon = "✅"
            if status.last_check_error:
                icon = "❌"

            lines.append(
                f"{i + 1}. {icon} {flat.name} [{flat.date}] via {flat.provider_name}"
            )

        lines.append(
            f"\n📊 Total: {total_checks} checks | ✅ {total_success} | ❌ {total_failed}"
        )
        lines.append("\nUse /status [n] for detailed status")

        await context.bot.send_message(
            chat_id=chat_id,
            text=_truncate(f"{_timestamp_prefix()} {chr(10).join(lines)}"),
        )

    # --- /history [index] [count] ---
    async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        parts = context.args if context.args else []

        # Defaults
        train_idx = 0
        count = 3

        if len(parts) >= 1:
            try:
                idx = int(parts[0])
                if 1 <= idx <= len(providers):
                    train_idx = idx - 1
            except ValueError:
                pass

        if len(parts) >= 2:
            try:
                n = int(parts[1])
                if n > 0:
                    count = n
            except ValueError:
                pass

        results = await providers[train_idx].get_history(count)
        flat = cfg.flat_trains[train_idx]

        if not results:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"📭 No history for {flat.name} yet.",
            )
            return

        lines = [f"📜 History: {flat.name} (last {len(results)})\n"]

        for i, r in enumerate(results):
            timestamp = r.timestamp.strftime("%d %b %H:%M")
            if r.error:
                lines.append(f"{i + 1}. ❌ [{timestamp}] Error")
            elif r.available_trains:
                lines.append(
                    f"{i + 1}. ✅ [{timestamp}] {len(r.available_trains)} available"
                )
            else:
                lines.append(f"{i + 1}. ⛔ [{timestamp}] No seats")

        await context.bot.send_message(
            chat_id=chat_id,
            text=_truncate(f"{_timestamp_prefix()} {chr(10).join(lines)}"),
        )

    # --- /toggle <index> ---
    async def cmd_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        args = " ".join(context.args) if context.args else ""
        args = args.strip()

        if not args:
            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ Usage: /toggle <index>\nExample: /toggle 1",
            )
            return

        try:
            idx = int(args)
        except ValueError:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ Invalid index. Use 1-{len(providers)}",
            )
            return

        if idx < 1 or idx > len(providers):
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ Invalid index. Use 1-{len(providers)}",
            )
            return

        provider = providers[idx - 1]
        flat = cfg.flat_trains[idx - 1]
        new_state = not await provider.is_paused()
        await provider.set_paused(new_state)

        if new_state:
            text = f"⏸️ Train #{idx} ({flat.name}) paused"
        else:
            text = f"▶️ Train #{idx} ({flat.name}) resumed"

        await context.bot.send_message(chat_id=chat_id, text=text)

    # --- /help ---
    async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        help_text = f"""🚂 Train Notifier (Monitoring {len(providers)} trains)

/list - List all configured trains
/list [n] - Show train #n details
/check [n] - Check train #n (or all)
/all [n] - Show all trains on route #n
/status [n] - Status of train #n (or summary)
/history [n] [count] - History of train #n
/toggle [n] - Pause/resume train #n

Examples:
/check 1 - Check first train only
/check - Check all trains
/all 3 - All trains on route #3
/toggle 5 - Pause/resume train #5"""

        await context.bot.send_message(chat_id=chat_id, text=help_text)

    # Register all handlers
    app.add_handler(CommandHandler("check", cmd_check))
    app.add_handler(CommandHandler("all", cmd_all))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("toggle", cmd_toggle))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("start", cmd_help))  # /start also shows help


async def _show_train_status(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    provider: Provider,
    flat: FlatTrainConfig,
    index: int,
) -> None:
    """Show detailed status for a single train."""
    status = await provider.get_status()

    uptime = format_duration(
        (datetime.now() - status.start_time).total_seconds()
    )

    last_check = "Never"
    last_result = "N/A"
    if status.last_check_time:
        elapsed = (datetime.now() - status.last_check_time).total_seconds()
        last_check = format_duration(elapsed) + " ago"
        if status.last_check_error:
            last_result = "❌ Error"
        elif status.last_check_found:
            last_result = "✅ Found seats!"
        else:
            last_result = "⛔ No seats"

    msg = f"""🚂 Train #{index}: {flat.name}

📍 Route: {flat.origin} → {flat.destination}
📅 Date: {flat.date}
🔌 Provider: {flat.provider_name}
⏱️ Interval: {int(flat.interval_seconds)}s

📊 Statistics:
• Uptime: {uptime}
• Checks: {status.total_checks} (✅ {status.successful_checks} | ❌ {status.failed_checks})
• Last: {last_check} - {last_result}"""

    await context.bot.send_message(
        chat_id=chat_id,
        text=_truncate(f"{_timestamp_prefix()} {msg}"),
    )
