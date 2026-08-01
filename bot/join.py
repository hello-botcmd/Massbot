        import asyncio
import logging
import random

from utils.database import Database
from utils.telethon_client import TelethonManager
from utils.account_ops import join_target, get_stop_event, clear_stop_event
from utils.helpers import esc, parse_timing
from bot.keyboards import main_menu_kb, cancel_kb

logger = logging.getLogger(__name__)
db = Database()
tm = TelethonManager()


async def join_link_handle(update, context):
    context.user_data["join_target"] = update.message.text.strip()
    context.user_data["flow"] = "join_count"
    await update.message.reply_text("🔢 How many accounts should join?", reply_markup=cancel_kb())


async def join_count_handle(update, context):
    text = update.message.text.strip()
    if not text.isdigit() or int(text) < 1:
        await update.message.reply_text("❌ Send a valid positive number.")
        return
    context.user_data["join_count"] = int(text)
    context.user_data["flow"] = "join_timing"
    await update.message.reply_text("⏱️ Timing? e.g. `min-1s max-8s` or `2 6`",
                                    parse_mode="Markdown", reply_markup=cancel_kb())


async def join_timing_handle(update, context):
    uid = update.effective_user.id
    timing = parse_timing(update.message.text.strip())
    if not timing:
        await update.message.reply_text("❌ Invalid timing. e.g. `min-1s max-8s`")
        return

    min_s, max_s = timing
    target = context.user_data.get("join_target")
    count = context.user_data.get("join_count", 1)
    accounts = await db.get_active_accounts(uid)

    if len(accounts) < count:
        await update.message.reply_text(
            f"❌ Need {count} accounts, only {len(accounts)} available.",
            reply_markup=main_menu_kb())
        context.user_data["flow"] = None
        return

    selected = random.sample(accounts, count)
    status = await update.message.reply_text(
        f"⏳ Joining {count} accounts to {esc(target)}...")
    stop_ev = get_stop_event(uid)
    results = []

    for i, acc in enumerate(selected):
        if stop_ev.is_set():
            results.append(f"⏹️ #{i+1} stopped by user")
            break
        client = await tm.get_fresh_client(acc["session_string"])
        if not client:
            results.append(f"❌ #{i+1} {esc(acc.get('phone', '?'))} connect failed")
            continue
        try:
            ok, msg = await join_target(client, target)
            results.append(f"{'✅' if ok else '❌'} #{i+1} {esc(acc.get('phone', '?'))} — {esc(msg)}")
        except Exception as e:
            results.append(f"❌ #{i+1} {esc(e)}")
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
        if (i + 1) % 5 == 0:
            try:
                await status.edit_text(f"⏳ Joining {i+1}/{count}...")
            except Exception:
                pass
        if i < count - 1 and not stop_ev.is_set():
            await asyncio.sleep(min_s if i % 2 == 0 else max_s)

    clear_stop_event(uid)
    detail = "\n".join(results[-15:])
    await status.edit_text(
        f"🔗 *Join Results*\n\n```\n{detail}\n```",
        parse_mode="Markdown", reply_markup=main_menu_kb())
    context.user_data["flow"] = None
