import asyncio
import logging
import random

from telethon.errors import FloodWaitError

from config import REACTION_GAP
from utils.database import Database
from utils.telethon_client import TelethonManager
from utils.account_ops import (
    parse_post_link, get_peer, add_reaction, get_stop_event, clear_stop_event,
)
from utils.helpers import esc, parse_reaction_emojis
from bot.keyboards import main_menu_kb, cancel_kb

logger = logging.getLogger(__name__)
db = Database()
tm = TelethonManager()


async def react_link_handle(update, context):
    link = update.message.text.strip()
    try:
        peer, msg_id = parse_post_link(link)
    except ValueError as e:
        await update.message.reply_text(
            f"❌ {esc(e)}\nUse: `https://t.me/username/123`", parse_mode="Markdown")
        return
    context.user_data["react_peer"] = peer
    context.user_data["react_msg"] = msg_id
    context.user_data["flow"] = "react_count"
    await update.message.reply_text("🔢 How many reactions in total?", reply_markup=cancel_kb())


async def react_count_handle(update, context):
    text = update.message.text.strip()
    if not text.isdigit() or int(text) < 1:
        await update.message.reply_text("❌ Send a valid positive number.")
        return
    context.user_data["react_total"] = int(text)
    context.user_data["flow"] = "react_emoji"
    await update.message.reply_text("😊 Send emoji(s), e.g. `❤️🥰👍`",
                                    parse_mode="Markdown", reply_markup=cancel_kb())


async def react_emoji_handle(update, context):
    emojis = parse_reaction_emojis(update.message.text)
    if not emojis:
        await update.message.reply_text("❌ No emojis found. Send like `❤️🥰`")
        return

    peer = context.user_data["react_peer"]
    msg_id = context.user_data["react_msg"]
    total = context.user_data["react_total"]
    accounts = await db.get_active_accounts()

    if not accounts:
        await update.message.reply_text("❌ No active accounts.", reply_markup=main_menu_kb())
        context.user_data["flow"] = None
        return

    usable = random.sample(accounts, min(total, len(accounts)))
    if len(usable) < total:
        await update.message.reply_text(
            f"⚠️ Only {len(accounts)} active accounts; reactions capped at {len(usable)}.")

    status = await update.message.reply_text(f"⏳ Adding {len(usable)} reactions...")
    clear_stop_event()
    stop_ev = get_stop_event()
    success = failed = 0
    not_in_chat = []

    for acc in usable:
        if stop_ev.is_set():
            break
        client = await tm.get_fresh_client(acc["session_string"])
        if not client:
            failed += 1
            continue
        try:
            resolved = await get_peer(client, peer)
            await add_reaction(client, resolved, msg_id, random.choice(emojis))
            success += 1
        except FloodWaitError as e:
            failed += 1
            logger.warning("FloodWait %ss on %s", e.seconds, acc.get("phone"))
            await asyncio.sleep(min(e.seconds, 30))
        except Exception:
            failed += 1
            not_in_chat.append(acc.get("phone"))
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
        await asyncio.sleep(REACTION_GAP + random.uniform(0.5, 2))

    clear_stop_event()
    msg = (f"❤️ *Reactions Added*\n\n"
           f"Total attempted: `{success + failed}`\n"
           f"✅ Success: `{success}`\n"
           f"❌ Failed: `{failed}`")
    if not_in_chat:
        msg += f"\n⚠️ Not in chat: `{len(not_in_chat)}`"
    await status.edit_text(msg, parse_mode="Markdown", reply_markup=main_menu_kb())
    context.user_data["flow"] = None
