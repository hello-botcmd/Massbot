import asyncio
import logging

from utils.database import Database
from utils.telethon_client import TelethonManager
from utils.account_ops import leave_target, get_stop_event, clear_stop_event
from utils.helpers import esc, is_authorized
from bot.keyboards import main_menu_kb, cancel_kb

logger = logging.getLogger(__name__)
db = Database()
tm = TelethonManager()


async def remove_start(update, context):
    uid = update.effective_user.id
    if not is_authorized(uid):
        await update.message.reply_text("⛔ Unauthorized.")
        return
    context.user_data["flow"] = "remove_chat"
    await update.message.reply_text("🗑️ Send the **chat ID or @username** to remove accounts from:",
                                    parse_mode="Markdown", reply_markup=cancel_kb())


async def remove_chat_handle(update, context):
    target = update.message.text.strip()
    accounts = await db.get_active_accounts()

    if not accounts:
        await update.message.reply_text("❌ No active accounts.", reply_markup=main_menu_kb())
        context.user_data["flow"] = None
        return

    status = await update.message.reply_text(
        f"⏳ Leaving {esc(target)} with {len(accounts)} accounts...")
    clear_stop_event()
    stop_ev = get_stop_event()
    success = failed = 0

    for i, acc in enumerate(accounts):
        if stop_ev.is_set():
            break
        client = await tm.get_fresh_client(acc["session_string"])
        if not client:
            failed += 1
            continue
        try:
            ok, _ = await leave_target(client, target)
            if ok:
                success += 1
            else:
                failed += 1
        except Exception:
            failed += 1
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
        if (i + 1) % 5 == 0:
            try:
                await status.edit_text(f"⏳ Leaving {i+1}/{len(accounts)} | ✅ {success} ❌ {failed}")
            except Exception:
                pass
        await asyncio.sleep(1)

    clear_stop_event()
    await status.edit_text(
        f"🗑️ *Remove Complete*\n\nChat: `{esc(target)}`\n"
        f"✅ Left: `{success}`\n❌ Failed: `{failed}`",
        parse_mode="Markdown", reply_markup=main_menu_kb())
    context.user_data["flow"] = None
