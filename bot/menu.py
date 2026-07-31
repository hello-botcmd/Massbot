import asyncio
import logging

from telegram import Update
from telegram.ext import CommandHandler, CallbackQueryHandler, ContextTypes

from config import OWNER_ID, ADMIN_IDS
from utils.database import Database
from utils.account_ops import (
    apply_mode_to_account, cancel_user_operations, stop_account_mode
)
from bot.keyboards import main_menu_kb, add_type_kb, cancel_kb

logger = logging.getLogger(__name__)
db = Database()


def is_authorized(user_id: int) -> bool:
    return user_id == OWNER_ID or user_id in ADMIN_IDS


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_authorized(uid):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    await update.message.reply_text(
        "🤖 *Telegram Account Management Bot*\n\n"
        "Use the buttons below to control your Telegram accounts.",
        reply_markup=main_menu_kb(),
        parse_mode="Markdown",
    )


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_authorized(uid):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    await cancel_user_operations(uid)
    accounts = await db.get_active_accounts(uid)
    for acc in accounts:
        await stop_account_mode(acc, db)
    await update.message.reply_text(
        "✅ All operations and mode tasks stopped.",
        reply_markup=main_menu_kb(),
    )


async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    if not is_authorized(uid):
        await query.edit_message_text("⛔ Unauthorized.")
        return

    data = query.data

    if data == "main_menu":
        await query.edit_message_text(
            "🤖 *Main Menu*\nChoose an action below:",
            reply_markup=main_menu_kb(),
            parse_mode="Markdown",
        )

    elif data == "add_acc":
        await query.edit_message_text(
            "Select add method:",
            reply_markup=add_type_kb(),
        )

    elif data == "total_acc":
        counts = await db.get_global_counts()
        await query.edit_message_text(
            f"📊 *Account Statistics*\n\n"
            f"Total: `{counts['total']}`\n"
            f"Active: `{counts['active']}`",
            parse_mode="Markdown",
            reply_markup=main_menu_kb(),
        )

    elif data == "all_online":
        await query.edit_message_text(
            "⏳ Making all accounts online forever...",
            reply_markup=None,
        )
        await _make_all_online(query)

    elif data == "cancel_op":
        await cancel_user_operations(uid)
        accounts = await db.get_active_accounts(uid)
        for acc in accounts:
            await stop_account_mode(acc, db)
        await query.edit_message_text(
            "✅ All operations stopped.",
            reply_markup=main_menu_kb(),
        )


async def _make_all_online(query):
    accounts = await db.get_all_active_accounts()
    if not accounts:
        await query.edit_message_text("❌ No active accounts.", reply_markup=main_menu_kb())
        return

    success = errors = 0
    status_lines = []
    for acc in accounts:
        try:
            msg = await apply_mode_to_account(acc, 1, db)
            status_lines.append(msg)
            if "❌" not in msg:
                success += 1
            else:
                errors += 1
            await asyncio.sleep(0.5)
        except Exception as e:
            errors += 1
            status_lines.append(f"❌ {acc.get('phone','?')} — {e}")

    detail = "\n".join(status_lines[-10:])
    if len(status_lines) > 10:
        detail = f"... and {len(status_lines)-10} more\n" + detail

    await query.edit_message_text(
        f"🌐 *All Accounts Online*\n\n✅ Online: {success}\n❌ Failed: {errors}\n\n```\n{detail}\n```",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(),
      )
