import asyncio
import logging

from utils.database import Database
from utils.helpers import esc, is_authorized
from utils.account_ops import (
    apply_mode_to_account, stop_account_mode,
    get_stop_event, clear_stop_event,
)
from bot.keyboards import main_menu_kb, add_type_kb, cancel_kb
from bot.add_account import single_handle, bulk_count_handle, bulk_session_handle
from bot.join import join_link_handle, join_count_handle, join_timing_handle
from bot.mode import mode_count_handle
from bot.reaction import react_link_handle, react_count_handle, react_emoji_handle
from bot.views import views_links_handle, views_count_handle
from bot.remove import remove_chat_handle

logger = logging.getLogger(__name__)
db = Database()


async def start(update, context):
    uid = update.effective_user.id
    if not is_authorized(uid):
        await update.message.reply_text("⛔ Unauthorized.")
        return
    await update.message.reply_text(
        "🤖 *Telegram Account Management Bot*\n\n"
        "Shared account pool — all admins use the same IDs.",
        parse_mode="Markdown", reply_markup=main_menu_kb())


async def _stop_everything():
    """Stop ALL running operations & mode tasks (shared pool)."""
    get_stop_event().set()                 # signal running loops
    accounts = await db.get_active_accounts()
    for acc in accounts:
        await stop_account_mode(acc, db)
    clear_stop_event()                     # fresh event for next op


async def stop_command(update, context):
    uid = update.effective_user.id
    if not is_authorized(uid):
        await update.message.reply_text("⛔ Unauthorized.")
        return
    await _stop_everything()
    context.user_data.clear()
    await update.message.reply_text(
        "⏹️ *All operations stopped.*\n"
        "• Running joins/reactions/views halted\n"
        "• Mode 1/2 online tasks cancelled\n"
        "• Accounts marked idle",
        parse_mode="Markdown", reply_markup=main_menu_kb())


async def callback_router(update, context):
    query = update.callback_query
    uid = query.from_user.id
    data = query.data

    if not is_authorized(uid):
        await query.answer("⛔ Unauthorized", show_alert=True)
        return
    await query.answer()

    if data == "cancel_op":
        await _stop_everything()
        context.user_data.clear()
        await query.edit_message_text("❌ Operation cancelled.", reply_markup=main_menu_kb())
        return

    if data == "main_menu":
        context.user_data["flow"] = None
        await query.edit_message_text("🤖 *Main Menu*\nChoose an action:",
                                      parse_mode="Markdown", reply_markup=main_menu_kb())
        return

    if data == "add_acc":
        await query.edit_message_text("Select add method:", reply_markup=add_type_kb())
        return

    if data == "add_single":
        context.user_data["flow"] = "add_single"
        await query.edit_message_text("📱 Send the **session string**:",
                                      parse_mode="Markdown", reply_markup=cancel_kb())
        return

    if data == "add_bulk":
        context.user_data["flow"] = "add_bulk_count"
        await query.edit_message_text("🔢 Send the **number of accounts**:",
                                      parse_mode="Markdown", reply_markup=cancel_kb())
        return

    if data == "join":
        context.user_data["flow"] = "join_link"
        await query.edit_message_text(
            "🔗 Send the channel/group link:\n"
            "• Public: `https://t.me/username`\n"
            "• Private invite: `https://t.me/+hash` or `joinchat/hash`\n"
            "• Approval-required links work too (auto join-request)",
            parse_mode="Markdown", reply_markup=cancel_kb())
        return

    if data == "mode":
        context.user_data["flow"] = "mode_counts"
        await query.edit_message_text(
            "🎭 Send counts as: `mode1, mode2, mode3`\n"
            "Example: `5,3,2`\n\n"
            "Mode 1 — Always Online\n"
            "Mode 2 — Online 2 min\n"
            "Mode 3 — Hide Last Seen",
            parse_mode="Markdown", reply_markup=cancel_kb())
        return

    if data == "react":
        context.user_data["flow"] = "react_link"
        await query.edit_message_text("❤️ Send the **post link**:\n`https://t.me/username/123`",
                                      parse_mode="Markdown", reply_markup=cancel_kb())
        return

    if data == "views":
        context.user_data["flow"] = "views_links"
        await query.edit_message_text("👁️ Send **post link(s)** (one per line):",
                                      reply_markup=cancel_kb())
        return

    if data == "total_acc":
        counts = await db.get_global_counts()
        await query.edit_message_text(
            "📊 *Account Statistics (shared pool)*\n\n"
            f"📚 Total added: `{counts['total']}`\n"
            f"🟢 Active: `{counts['active']}`\n"
            f"🔴 Disconnected: `{counts['disconnected']}`\n"
            f"⚙️ In use: `{counts['in_use']}`\n"
            f"💤 Idle: `{counts['idle']}`",
            parse_mode="Markdown", reply_markup=main_menu_kb())
        return

    if data == "all_online":
        await query.edit_message_text("🌐 Forcing all accounts online...",
                                      reply_markup=None)
        accounts = [a for a in await db.get_all_accounts() if a.get("status") == "active"]
        if not accounts:
            await query.edit_message_text("❌ No active accounts.", reply_markup=main_menu_kb())
            return
        success = failed = 0
        lines = []
        for acc in accounts:
            try:
                msg = await apply_mode_to_account(acc, 1, db)
                if "❌" in msg:
                    failed += 1
                else:
                    success += 1
                lines.append(msg)
            except Exception as e:
                failed += 1
                lines.append(f"❌ {esc(acc.get('phone','?'))}: {esc(e)}")
            await asyncio.sleep(0.3)
        detail = "\n".join(lines[-20:])
        if len(lines) > 20:
            detail = f"... and {len(lines)-20} more\n" + detail
        await query.edit_message_text(
            f"🌐 *All Accounts Online*\n✅ Online: `{success}`\n❌ Failed: `{failed}`\n\n```\n{detail}\n```",
            parse_mode="Markdown", reply_markup=main_menu_kb())
        return


async def text_router(update, context):
    flow = context.user_data.get("flow")
    if not flow:
        return

    dispatch = {
        "add_single": single_handle,
        "add_bulk_count": bulk_count_handle,
        "add_bulk_session": bulk_session_handle,
        "join_link": join_link_handle,
        "join_count": join_count_handle,
        "join_timing": join_timing_handle,
        "mode_counts": mode_count_handle,
        "react_link": react_link_handle,
        "react_count": react_count_handle,
        "react_emoji": react_emoji_handle,
        "views_links": views_links_handle,
        "views_count": views_count_handle,
        "remove_chat": remove_chat_handle,
    }
    handler = dispatch.get(flow)
    if handler:
        await handler(update, context)
