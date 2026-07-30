import asyncio
import logging

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler, MessageHandler, filters,
    ConversationHandler, ContextTypes
)

from config import OWNER_ID, ADMIN_IDS, REACTION_GAP
from utils.database import Database
from utils.telethon_client import TelethonManager
from utils.account_ops import (
    parse_telegram_link, add_reaction,
    get_stop_event, clear_stop_event
)
from utils.helpers import parse_reaction_emojis
from bot.keyboards import main_menu_kb, cancel_kb
from bot.states import *

logger = logging.getLogger(__name__)
db = Database()
tmanager = TelethonManager()

AUTH = lambda uid: uid == OWNER_ID or uid in ADMIN_IDS


async def react_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not AUTH(query.from_user.id):
        await query.edit_message_text("⛔ Unauthorized.")
        return ConversationHandler.END
    await query.edit_message_text(
        "❤️ Send the **post link** (e.g. `https://t.me/channel/123`):",
        parse_mode="Markdown",
        reply_markup=cancel_kb(),
    )
    return WAIT_REACTION_LINK


async def react_link_handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    chat_id, msg_id = parse_telegram_link(link)
    if not chat_id or not msg_id:
        await update.message.reply_text(
            "❌ Invalid link. Use: `https://t.me/username/123`",
            parse_mode="Markdown",
        )
        return WAIT_REACTION_LINK

    context.user_data["react_chat"] = chat_id
    context.user_data["react_msg"] = msg_id
    await update.message.reply_text(
        "🔢 How many **reactions** in total?",
        reply_markup=cancel_kb(),
    )
    return WAIT_REACTION_COUNT


async def react_count_handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit() or int(text) < 1:
        await update.message.reply_text("❌ Send a valid positive number.")
        return WAIT_REACTION_COUNT
    context.user_data["react_total"] = int(text)
    await update.message.reply_text(
        "😊 Send **reaction emoji(s)** (e.g., `❤️🥰👍`):",
        reply_markup=cancel_kb(),
    )
    return WAIT_REACTION_EMOJI


async def react_emoji_handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    emoticons = parse_reaction_emojis(update.message.text.strip())
    if not emoticons:
        await update.message.reply_text("❌ No emojis found. Send like `❤️🥰`")
        return WAIT_REACTION_EMOJI

    chat_id = context.user_data["react_chat"]
    msg_id = context.user_data["react_msg"]
    total = context.user_data["react_total"]
    accounts = await db.get_active_accounts(uid)

    if not accounts:
        await update.message.reply_text("❌ No active accounts.", reply_markup=main_menu_kb())
        for k in ["react_chat", "react_msg", "react_total"]:
            context.user_data.pop(k, None)
        return ConversationHandler.END

    status_msg = await update.message.reply_text(f"⏳ Reacting {total} times...")
    stop_ev = get_stop_event(uid)
    success = errors = 0

    for i in range(total):
        if stop_ev.is_set():
            break
        acc = accounts[i % len(accounts)]
        client = await tmanager.get_client(acc)
        if not client:
            errors += 1
            continue
        try:
            await add_reaction(client, chat_id, msg_id, emoticons)
            success += 1
        except Exception as e:
            errors += 1
            logger.error(f"React error: {e}")
        if (i + 1) % 10 == 0 or i == total - 1:
            try:
                await status_msg.edit_text(f"⏳ Reacting... {i+1}/{total} | ✅ {success} ❌ {errors}")
            except Exception:
                pass
        await asyncio.sleep(REACTION_GAP)

    clear_stop_event(uid)
    await status_msg.edit_text(
        f"❤️ *Reaction Complete*\n\n"
        f"Total: `{total}`\n✅ Success: `{success}`\n❌ Failed: `{errors}`\n"
        f"Emoji: `{''.join(emoticons)}`",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(),
    )
    for k in ["react_chat", "react_msg", "react_total"]:
        context.user_data.pop(k, None)
    return ConversationHandler.END


async def cancel_react(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ Reaction cancelled.", reply_markup=main_menu_kb())
    return ConversationHandler.END


reaction_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(react_entry, pattern="^react$")],
    states={
        WAIT_REACTION_LINK: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, react_link_handle)
        ],
        WAIT_REACTION_COUNT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, react_count_handle)
        ],
        WAIT_REACTION_EMOJI: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, react_emoji_handle)
        ],
    },
    fallbacks=[
        CallbackQueryHandler(cancel_react, pattern="^cancel_op$"),
    ],
    name="reaction",
    persistent=False,
    per_chat=False,
    per_user=True,
    allow_reentry=True,
)
