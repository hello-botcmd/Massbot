import logging

from utils.database import Database
from utils.telethon_client import TelethonManager
from utils.helpers import esc
from bot.keyboards import main_menu_kb, cancel_kb

logger = logging.getLogger(__name__)
db = Database()
tm = TelethonManager()


async def single_handle(update, context):
    session_str = update.message.text.strip()
    if len(session_str) < 10:
        await update.message.reply_text("❌ Invalid session string.", reply_markup=cancel_kb())
        return

    status = await update.message.reply_text("⏳ Validating session...")
    client = await tm.create_client(session_str)
    if not client:
        await status.edit_text("❌ Invalid or expired session string.", reply_markup=main_menu_kb())
        context.user_data["flow"] = None
        return

    me = await client.get_me()
    phone = getattr(me, "phone", None) or str(me.id)
    name = f"{me.first_name or ''} {me.last_name or ''}".strip()
    await client.disconnect()

    try:
        res = await db.add_account(update.effective_user.id, phone, session_str, name)
    except Exception as e:
        logger.exception("add_account DB error")
        await status.edit_text(f"❌ DB error: {esc(e)}", reply_markup=main_menu_kb())
        context.user_data["flow"] = None
        return

    if not res["ok"]:
        await status.edit_text(
            "⚠️ This session is **already added** to the server by another admin.\n"
            "Each Telegram session can be used once.",
            parse_mode="Markdown", reply_markup=main_menu_kb())
        context.user_data["flow"] = None
        return

    if res.get("refreshed"):
        await status.edit_text(
            f"🔄 Account already existed — *refreshed & reactivated*.\n"
            f"📱 Phone: `{esc(phone)}`\n👤 Name: {esc(name)}",
            parse_mode="Markdown", reply_markup=main_menu_kb())
    else:
        await status.edit_text(
            f"✅ *Account Added!*\n\n📱 Phone: `{esc(phone)}`\n"
            f"👤 Name: {esc(name)}\n🆔 ID: `{me.id}`",
            parse_mode="Markdown", reply_markup=main_menu_kb())
    context.user_data["flow"] = None


async def bulk_count_handle(update, context):
    text = update.message.text.strip()
    if not text.isdigit() or int(text) < 1:
        await update.message.reply_text("❌ Send a valid positive number.")
        return

    context.user_data["add_total"] = int(text)
    context.user_data["add_idx"] = 0
    context.user_data["add_ok"] = 0
    context.user_data["add_fail"] = 0
    context.user_data["add_log"] = []
    context.user_data["flow"] = "add_bulk_session"
    await update.message.reply_text(f"📱 Send session string 1 / {text}:", reply_markup=cancel_kb())


async def bulk_session_handle(update, context):
    uid = update.effective_user.id
    session_str = update.message.text.strip()
    total = context.user_data.get("add_total", 1)
    idx = context.user_data.get("add_idx", 0) + 1

    if len(session_str) < 10:
        await update.message.reply_text(f"❌ Invalid session. Send {idx}/{total} again:")
        return

    status = await update.message.reply_text(f"⏳ Validating {idx}/{total}...")
    client = await tm.create_client(session_str)

    if not client:
        context.user_data["add_fail"] = context.user_data.get("add_fail", 0) + 1
        context.user_data["add_log"].append(f"❌ #{idx} invalid session")
        await status.edit_text(f"❌ Session {idx} invalid. Next...")
    else:
        me = await client.get_me()
        phone = getattr(me, "phone", None) or str(me.id)
        name = f"{me.first_name or ''} {me.last_name or ''}".strip()
        await client.disconnect()
        try:
            res = await db.add_account(uid, phone, session_str, name)
            if not res["ok"]:
                context.user_data["add_fail"] = context.user_data.get("add_fail", 0) + 1
                context.user_data["add_log"].append(f"⚠️ #{idx} already exists")
                await status.edit_text(f"⚠️ #{idx} already added — skipped.")
            else:
                context.user_data["add_ok"] = context.user_data.get("add_ok", 0) + 1
                context.user_data["add_log"].append(f"✅ #{idx} {phone}")
                await status.edit_text(f"✅ #{idx} added: {esc(phone)}")
        except Exception as e:
            logger.exception("bulk add DB error")
            context.user_data["add_fail"] = context.user_data.get("add_fail", 0) + 1
            context.user_data["add_log"].append(f"❌ #{idx} DB error: {esc(e)}")
            await status.edit_text("❌ #{idx} DB error")

    context.user_data["add_idx"] = idx

    if idx >= total:
        ok = context.user_data.get("add_ok", 0)
        fail = context.user_data.get("add_fail", 0)
        log = context.user_data.get("add_log", [])
        detail = "\n".join(log[-15:])
        if len(log) > 15:
            detail = f"... and {len(log)-15} more\n" + detail
        await update.message.reply_text(
            f"📦 *Bulk Add Complete*\n✅ Success: `{ok}`\n❌ Failed: `{fail}`\n\n```\n{detail}\n```",
            parse_mode="Markdown", reply_markup=main_menu_kb())
        for k in ("add_total", "add_idx", "add_ok", "add_fail", "add_log", "flow"):
            context.user_data.pop(k, None)
        return

    await update.message.reply_text(f"📱 Send session string {idx+1} / {total}:", reply_markup=cancel_kb())
