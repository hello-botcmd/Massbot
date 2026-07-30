import asyncio
import logging
import random

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler, MessageHandler, filters,
    ConversationHandler, ContextTypes
)

from config import OWNER_ID, ADMIN_IDS
from utils.database import Database
from utils.telethon_client import TelethonManager
from utils.account_ops import join_target, get_stop_event, clear_stop_event
from utils.helpers import parse_timing
from bot.keyboards import main_menu_kb, cancel_kb
from bot.states import *

logger = logging.getLogger(__name__)
db = Database()
tmanager = TelethonManager()

AUTH = lambda uid: uid == OWNER_ID or uid in ADMIN_IDS


async def join_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not AUTH(query.from_user.id):
        await query.edit_message_text("⛔ Unauthorized.")
        return ConversationHandler.END
    await query.edit_message_text(
        "🔗 Send the channel/group **username** or **invite link**:",
        parse_mode="Markdown",
        reply_markup=cancel_kb(),
    )
    return WAIT_JOIN_LINK


async def join_link_handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["join_target"] = update.message.text.strip()
    await update.message.reply_text(
        "🔢 How many accounts should join?",
        reply_markup=cancel_kb(),
    )
    return WAIT_JOIN_COUNT


async def join_count_handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit() or int(text) < 1:
        await update.message.reply_text("❌ Send a valid positive number.")
        return WAIT_JOIN_COUNT
    context.user_data["join_count"] = int(text)
    await update.message.reply_text(
        "⏱️ Send timing *(e.g., `min-1s max-8s` or `2 6`)*:",
        parse_mode="Markdown",
        reply_markup=cancel_kb(),
    )
    return WAIT_JOIN_TIMING


async def join_timing_handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    timing = parse_timing(update.message.text.strip())
    if not timing:
        await update.message.reply_text(
            "❌ Invalid timing. Use e.g.: `min-1s max-8s`",
            parse_mode="Markdown",
        )
        return WAIT_JOIN_TIMING

    min_s, max_s = timing
    target = context.user_data["join_target"]
    count = context.user_data["join_count"]
    accounts = await db.get_active_accounts(uid)

    if len(accounts) < count:
        await update.message.reply_text(
            f"❌ Only {len(accounts)} active, but {count} requested.",
            reply_markup=main_menu_kb(),
        )
        for k in ["join_target", "join_count"]:
            context.user_data.pop(k, None)
        return ConversationHandler.END

    selected = random.sample(accounts, count)
    status_msg = await update.message.reply_text(
        f"⏳ Joining {target} with {count} accounts...\n"
        f"Timing: `{min_s}s` – `{max_s}s` (alternating)",
        parse_mode="Markdown",
    )

    stop_ev = get_stop_event(uid)
    results = []
    for i, acc in enumerate(selected):
        if stop_ev.is_set():
            results.append(f"⏹️ #{i+1} — stopped by user")
            break

        client = await tmanager.get_client(acc)
        if not client:
            results.append(f"❌ #{i+1} — {acc.get('phone','?')} failed to connect")
            continue

        ok, _, msg = await join_target(client, target)
        status = "✅" if ok else "❌"
        results.append(f"{status} #{i+1} — {acc.get('phone','?')} — {msg}")

        if (i + 1) % 5 == 0 or i == count - 1:
            try:
                await status_msg.edit_text(
                    f"⏳ Joining... ({i+1}/{count})\n```\n" + "\n".join(results[-10:]) + "\n```",
                    parse_mode="Markdown",
                )
            except Exception:
                pass

        delay = min_s if i % 2 == 0 else max_s
        if i < count - 1 and not stop_ev.is_set():
            await asyncio.sleep(delay)

    clear_stop_event(uid)
    summary = "\n".join(results)
    await status_msg.edit_text(
        f"🔗 *Join Results*\n\n```\n{summary[:3000]}\n```",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(),
    )

    for k in ["join_target", "join_count"]:
        context.user_data.pop(k, None)
    return ConversationHandler.END


async def cancel_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ Join cancelled.", reply_markup=main_menu_kb())
    return ConversationHandler.END


join_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(join_entry, pattern="^join$")],
    states={
        WAIT_JOIN_LINK: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, join_link_handle)
        ],
        WAIT_JOIN_COUNT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, join_count_handle)
        ],
        WAIT_JOIN_TIMING: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, join_timing_handle)
        ],
    },
    fallbacks=[
        CallbackQueryHandler(cancel_join, pattern="^cancel_op$"),
    ],
    name="join",
    persistent=False,
    per_chat=False,
    per_user=True,
    allow_reentry=True,
)
