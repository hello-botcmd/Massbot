import asyncio
import logging

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler, MessageHandler, filters,
    ConversationHandler, ContextTypes
)

from config import OWNER_ID, ADMIN_IDS, VIEW_GAP
from utils.database import Database
from utils.telethon_client import TelethonManager
from utils.account_ops import (
    parse_telegram_link, boost_view,
    get_stop_event, clear_stop_event
)
from bot.keyboards import main_menu_kb, cancel_kb
from bot.states import *

logger = logging.getLogger(__name__)
db = Database()
tmanager = TelethonManager()

AUTH = lambda uid: uid == OWNER_ID or uid in ADMIN_IDS


async def views_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not AUTH(query.from_user.id):
        await query.edit_message_text("⛔ Unauthorized.")
        return ConversationHandler.END
    await query.edit_message_text(
        "👁️ Send **post link(s)** (one per line for multiple):\n"
        "e.g. `https://t.me/channel/123`",
        reply_markup=cancel_kb(),
    )
    return WAIT_VIEWS_LINKS


async def views_links_handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    links = [ln.strip() for ln in text.split("\n") if ln.strip()]
    posts = []
    for ln in links:
        cid, mid = parse_telegram_link(ln)
        if cid and mid:
            posts.append((cid, mid))
    if not posts:
        await update.message.reply_text(
            "❌ No valid links. Use: `https://t.me/username/123`",
            parse_mode="Markdown",
        )
        return WAIT_VIEWS_LINKS

    context.user_data["views_posts"] = posts
    await update.message.reply_text(
        f"📊 Found `{len(posts)}` post(s).\n"
        "🔢 How many **views per post**?",
        reply_markup=cancel_kb(),
    )
    return WAIT_VIEWS_COUNT


async def views_count_handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip()
    if not text.isdigit() or int(text) < 1:
        await update.message.reply_text("❌ Send a valid positive number.")
        return WAIT_VIEWS_COUNT

    views_pp = int(text)
    posts = context.user_data["views_posts"]
    accounts = await db.get_active_accounts(uid)

    if not accounts:
        await update.message.reply_text("❌ No active accounts.", reply_markup=main_menu_kb())
        context.user_data.pop("views_posts", None)
        return ConversationHandler.END

    status_msg = await update.message.reply_text(
        f"⏳ Boosting `{views_pp}` views on `{len(posts)}` post(s)...",
        parse_mode="Markdown",
    )

    stop_ev = get_stop_event(uid)
    total = success = failed = 0

    for pi, (cid, mid) in enumerate(posts):
        if stop_ev.is_set():
            break
        for v in range(views_pp):
            if stop_ev.is_set():
                break
            acc = accounts[total % len(accounts)]
            client = await tmanager.get_client(acc)
            if not client:
                failed += 1
                total += 1
                continue
            ok = await boost_view(client, cid, mid)
            if ok:
                success += 1
            else:
                failed += 1
            total += 1
            if total % 10 == 0:
                try:
                    await status_msg.edit_text(
                        f"⏳ Views... Post {pi+1}/{len(posts)} | "
                        f"View {v+1}/{views_pp}\n✅ {success} ❌ {failed}"
                    )
                except Exception:
                    pass
            await asyncio.sleep(VIEW_GAP)

    clear_stop_event(uid)
    await status_msg.edit_text(
        f"👁️ *Views Complete*\n\n"
        f"Posts: `{len(posts)}`\nViews per post: `{views_pp}`\n"
        f"✅ Success: `{success}`\n❌ Failed: `{failed}`",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(),
    )
    context.user_data.pop("views_posts", None)
    return ConversationHandler.END


async def cancel_views(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ Views cancelled.", reply_markup=main_menu_kb())
    return ConversationHandler.END


views_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(views_entry, pattern="^views$")],
    states={
        WAIT_VIEWS_LINKS: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, views_links_handle)
        ],
        WAIT_VIEWS_COUNT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, views_count_handle)
        ],
    },
    fallbacks=[
        CallbackQueryHandler(cancel_views, pattern="^cancel_op$"),
    ],
    name="views",
    persistent=False,
    per_chat=False,
    per_user=True,
    allow_reentry=True,
)
