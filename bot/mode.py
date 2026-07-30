import asyncio
import logging

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler, MessageHandler, filters,
    ConversationHandler, ContextTypes
)

from config import OWNER_ID, ADMIN_IDS
from utils.database import Database
from utils.account_ops import (
    apply_mode_to_account, stop_account_mode, cancel_user_operations
)
from utils.helpers import parse_mode_counts, distribute_accounts
from bot.keyboards import main_menu_kb, cancel_kb
from bot.states import *

logger = logging.getLogger(__name__)
db = Database()

AUTH = lambda uid: uid == OWNER_ID or uid in ADMIN_IDS


async def mode_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not AUTH(query.from_user.id):
        await query.edit_message_text("⛔ Unauthorized.")
        return ConversationHandler.END
    await query.edit_message_text(
        "🎭 Send counts as: `mode1, mode2, mode3`\n"
        "Example: `5,3,2`\n\n"
        "*Mode 1* — Always online\n"
        "*Mode 2* — Online 2 min, then offline\n"
        "*Mode 3* — Hidden last seen",
        parse_mode="Markdown",
        reply_markup=cancel_kb(),
    )
    return WAIT_MODE_COUNTS


async def mode_counts_handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    parsed = parse_mode_counts(update.message.text.strip())
    if not parsed:
        await update.message.reply_text("❌ Invalid. Use e.g.: `5,3,2`", parse_mode="Markdown")
        return WAIT_MODE_COUNTS

    c1, c2, c3 = parsed
    total = c1 + c2 + c3
    accounts = await db.get_active_accounts(uid)

    if len(accounts) < total:
        await update.message.reply_text(
            f"❌ Need {total} active accounts, but only {len(accounts)} available.",
            reply_markup=main_menu_kb(),
        )
        return ConversationHandler.END

    # Stop any previous mode tasks for these accounts first
    for acc in accounts:
        await stop_account_mode(acc, db)

    assignments = distribute_accounts(accounts, (c1, c2, c3))
    status_msg = await update.message.reply_text(f"⏳ Applying modes to {total} accounts...")

    results = []
    for acc, mode in assignments:
        msg = await apply_mode_to_account(acc, mode, db)
        results.append(msg)
        await asyncio.sleep(0.3)

    detail = "\n".join(results)
    if len(detail) > 3000:
        detail = detail[:3000] + "\n..."

    await status_msg.edit_text(
        f"🎭 *Mode Distribution Complete*\n\n"
        f"Mode 1 (always online): `{c1}`\n"
        f"Mode 2 (2 min online): `{c2}`\n"
        f"Mode 3 (hidden): `{c3}`\n\n"
        f"```\n{detail}\n```",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(),
    )
    return ConversationHandler.END


async def cancel_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ Mode distribution cancelled.", reply_markup=main_menu_kb())
    return ConversationHandler.END


mode_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(mode_entry, pattern="^mode$")],
    states={
        WAIT_MODE_COUNTS: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, mode_counts_handle)
        ],
    },
    fallbacks=[
        CallbackQueryHandler(cancel_mode, pattern="^cancel_op$"),
    ],
    name="mode",
    persistent=False,
    per_chat=False,
    per_user=True,
    allow_reentry=True,
)
