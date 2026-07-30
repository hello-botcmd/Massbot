import asyncio
import logging

from telegram import Update
from telegram.ext import (
    CommandHandler, MessageHandler, filters,
    ConversationHandler, ContextTypes
)

from config import OWNER_ID, ADMIN_IDS
from utils.database import Database
from utils.telethon_client import TelethonManager
from utils.account_ops import leave_target, get_stop_event, clear_stop_event
from bot.keyboards import main_menu_kb, cancel_kb
from bot.states import *

logger = logging.getLogger(__name__)
db = Database()
tmanager = TelethonManager()

AUTH = lambda uid: uid == OWNER_ID or uid in ADMIN_IDS


async def remove_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not AUTH(uid):
        await update.message.reply_text("⛔ Unauthorized.")
        return ConversationHandler.END
    await update.message.reply_text(
        "🗑️ Send the **chat ID or @username** to remove accounts from:",
        parse_mode="Markdown",
        reply_markup=cancel_kb(),
    )
    return WAIT_REMOVE_CHAT


async def remove_chat_handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    target = update.message.text.strip()
    accounts = await db.get_active_accounts(uid)

    if not accounts:
        await update.message.reply_text("❌ No active accounts.", reply_markup=main_menu_kb())
        return ConversationHandler.END

    status_msg = await update.message.reply_text(f"⏳ Removing {len(accounts)} accounts from {target}...")
    stop_ev = get_stop_event(uid)
    success = errors = 0

    for i, acc in enumerate(accounts):
        if stop_ev.is_set():
            break
        client = await tmanager.get_client(acc)
        if not client:
            errors += 1
            continue
        ok, _ = await leave_target(client, target)
        if ok:
            success += 1
        else:
            errors += 1
        if (i + 1) % 5 == 0:
            try:
                await status_msg.edit_text(f"⏳ Leaving... {i+1}/{len(accounts)} | ✅ {success} ❌ {errors}")
            except Exception:
                pass
        await asyncio.sleep(1)

    clear_stop_event(uid)
    await status_msg.edit_text(
        f"🗑️ *Remove Complete*\n\nChat: `{target}`\n✅ Left: `{success}`\n❌ Failed: `{errors}`",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(),
    )
    return ConversationHandler.END


async def cancel_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text("❌ Remove cancelled.", reply_markup=main_menu_kb())
    return ConversationHandler.END


remove_conv = ConversationHandler(
    entry_points=[CommandHandler("remove", remove_start)],
    states={
        WAIT_REMOVE_CHAT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, remove_chat_handle)
        ],
    },
    fallbacks=[
        CallbackQueryHandler(cancel_remove, pattern="^cancel_op$"),
        CommandHandler("cancel", cancel_remove),
    ],
    name="remove",
    persistent=False,
    per_chat=False,
    per_user=True,
    allow_reentry=True,
)
