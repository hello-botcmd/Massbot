import logging

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler, MessageHandler, filters,
    ConversationHandler, ContextTypes
)

from config import OWNER_ID, ADMIN_IDS
from utils.database import Database
from utils.account_ops import validate_session
from bot.keyboards import main_menu_kb, cancel_kb
from bot.states import *

logger = logging.getLogger(__name__)
db = Database()

AUTH = lambda uid: uid == OWNER_ID or uid in ADMIN_IDS


# ── Entry point ──

async def add_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point from add_type_kb — sub-routes to single or bulk."""
    query = update.callback_query
    await query.answer()
    if not AUTH(query.from_user.id):
        await query.edit_message_text("⛔ Unauthorized.")
        return ConversationHandler.END

    data = query.data
    if data == "add_acc:single":
        await query.edit_message_text(
            "📱 Send the **session string** for the account:",
            parse_mode="Markdown",
            reply_markup=cancel_kb(),
        )
        return WAIT_SINGLE_SESSION

    elif data == "add_acc:bulk":
        await query.edit_message_text(
            "🔢 Send the **number of accounts** you want to add:",
            parse_mode="Markdown",
            reply_markup=cancel_kb(),
        )
        return WAIT_BULK_COUNT

    return ConversationHandler.END


# ── Single add ──

async def single_handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    session_str = update.message.text.strip()

    if len(session_str) < 10:
        await update.message.reply_text(
            "❌ Invalid session string. Send a valid Telethon session string.",
            reply_markup=cancel_kb(),
        )
        return WAIT_SINGLE_SESSION

    status_msg = await update.message.reply_text("⏳ Validating session...")
    info = await validate_session(session_str)

    if not info:
        await status_msg.edit_text("❌ Invalid or expired session string.", reply_markup=main_menu_kb())
        return ConversationHandler.END

    phone = info.get("phone", info.get("id", "unknown"))
    try:
        await db.add_account(uid, str(phone), session_str)
        await status_msg.edit_text(
            f"✅ *Account Added!*\n\n"
            f"📱 Phone: `{phone}`\n"
            f"👤 Name: {info.get('first_name', '')} {info.get('last_name', '')}\n"
            f"🆔 ID: `{info.get('id')}`",
            parse_mode="Markdown",
            reply_markup=main_menu_kb(),
        )
    except Exception as e:
        await status_msg.edit_text(f"❌ Database error: {e}", reply_markup=main_menu_kb())

    return ConversationHandler.END


# ── Bulk add ──

async def bulk_count_handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit() or int(text) < 1:
        await update.message.reply_text("❌ Send a valid positive number.")
        return WAIT_BULK_COUNT

    count = int(text)
    context.user_data["add_total"] = count
    context.user_data["add_idx"] = 0
    context.user_data["add_ok"] = 0
    context.user_data["add_fail"] = 0
    context.user_data["add_log"] = []

    await update.message.reply_text(
        f"📱 Send session string **1 / {count}**:",
        parse_mode="Markdown",
        reply_markup=cancel_kb(),
    )
    return WAIT_BULK_SESSION


async def bulk_session_handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    session_str = update.message.text.strip()
    total = context.user_data.get("add_total", 1)
    idx = context.user_data.get("add_idx", 0) + 1

    if len(session_str) < 10:
        await update.message.reply_text(
            f"❌ Invalid session. Send session **{idx} / {total}** again:",
            parse_mode="Markdown",
        )
        return WAIT_BULK_SESSION

    status_msg = await update.message.reply_text(f"⏳ Validating session {idx}/{total}...")
    info = await validate_session(session_str)

    if not info:
        context.user_data["add_fail"] += 1
        context.user_data["add_log"].append(f"❌ #{idx} — invalid session")
        await status_msg.edit_text(f"❌ Session {idx} invalid. Moving to next...")
    else:
        phone = info.get("phone", info.get("id", "unknown"))
        try:
            await db.add_account(uid, str(phone), session_str)
            context.user_data["add_ok"] += 1
            context.user_data["add_log"].append(f"✅ #{idx} — {phone}")
            await status_msg.edit_text(f"✅ Session {idx} added: `{phone}`", parse_mode="Markdown")
        except Exception as e:
            context.user_data["add_fail"] += 1
            context.user_data["add_log"].append(f"❌ #{idx} — DB error: {e}")
            await status_msg.edit_text(f"❌ Session {idx} DB error: {e}")

    context.user_data["add_idx"] = idx

    if idx >= total:
        ok = context.user_data["add_ok"]
        fail = context.user_data["add_fail"]
        log = context.user_data["add_log"]
        summary = f"📦 *Bulk Add Complete!*\n\n✅ Success: `{ok}`\n❌ Failed: `{fail}`\n\n"
        detail = "\n".join(log[-15:])
        if len(log) > 15:
            detail = f"... and {len(log)-15} more\n" + detail

        await update.message.reply_text(
            summary + f"```\n{detail}\n```",
            parse_mode="Markdown",
            reply_markup=main_menu_kb(),
        )
        for k in ["add_total", "add_idx", "add_ok", "add_fail", "add_log"]:
            context.user_data.pop(k, None)
        return ConversationHandler.END

    await update.message.reply_text(
        f"📱 Send session string **{idx+1} / {total}**:",
        parse_mode="Markdown",
        reply_markup=cancel_kb(),
    )
    return WAIT_BULK_SESSION


# ── Cancel ──

async def cancel_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ Add account cancelled.", reply_markup=main_menu_kb())
    return ConversationHandler.END


# ── Handler definition ──

add_account_conv = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(add_entry, pattern="^add_acc:"),
    ],
    states={
        WAIT_SINGLE_SESSION: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, single_handle)
        ],
        WAIT_BULK_COUNT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, bulk_count_handle)
        ],
        WAIT_BULK_SESSION: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, bulk_session_handle)
        ],
    },
    fallbacks=[
        CallbackQueryHandler(cancel_add, pattern="^cancel_op$"),
    ],
    name="add_account",
    persistent=False,
    per_chat=False,
    per_user=True,
    allow_reentry=True,
)
