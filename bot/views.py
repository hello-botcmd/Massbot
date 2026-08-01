import asyncio
import logging
import random

from telethon.errors import FloodWaitError

from config import VIEW_GAP
from utils.database import Database
from utils.telethon_client import TelethonManager
from utils.account_ops import (
    parse_post_link, get_peer, boost_views, get_stop_event, clear_stop_event,
)
from bot.keyboards import main_menu_kb, cancel_kb

logger = logging.getLogger(__name__)
db = Database()
tm = TelethonManager()


async def views_links_handle(update, context):
    text = update.message.text.strip()
    links = [ln.strip() for ln in text.splitlines() if ln.strip()]
    posts = []
    for ln in links:
        try:
            peer, mid = parse_post_link(ln)
            posts.append((peer, mid))
        except ValueError:
            continue
    if not posts:
        await update.message.reply_text(
            "❌ No valid links. Use `https://t.me/username/123`", parse_mode="Markdown")
        return

    context.user_data["views_posts"] = posts
    context.user_data["flow"] = "views_count"
    await update.message.reply_text(
        f"📊 Found `{len(posts)}` post(s).\n🔢 Views per post?",
        parse_mode="Markdown", reply_markup=cancel_kb())


async def views_count_handle(update, context):
    uid = update.effective_user.id
    text = update.message.text.strip()
    if not text.isdigit() or int(text) < 1:
        await update.message.reply_text("❌ Send a valid positive number.")
        return

    views_pp = int(text)
    posts = context.user_data["views_posts"]
    accounts = await db.get_active_accounts(uid)

    if not accounts:
        await update.message.reply_text("❌ No active accounts.", reply_markup=main_menu_kb())
        context.user_data["flow"] = None
        return

    status = await update.message.reply_text(
        f"⏳ Boosting {views_pp} views on {len(posts)} post(s)...")
    stop_ev = get_stop_event(uid)
    total = success = failed = 0

    for pi, (peer, mid) in enumerate(posts):
        for v in range(views_pp):
            if stop_ev.is_set():
                break
            acc = accounts[total % len(accounts)]
            client = await tm.get_fresh_client(acc["session_string"])
            if not client:
                failed += 1
                total += 1
                continue
            try:
                resolved = await get_peer(client, peer)
                await boost_views(client, resolved, mid)
                success += 1
            except FloodWaitError as e:
                failed += 1
                await asyncio.sleep(min(e.seconds, 30))
            except Exception:
                failed += 1
            finally:
                try:
                    await client.disconnect()
                except Exception:
                    pass
            total += 1
            if total % 10 == 0:
                try:
                    await status.edit_text(
                        f"⏳ Post {pi+1}/{len(posts)} | view {v+1}/{views_pp}\n✅ {success} ❌ {failed}")
                except Exception:
                    pass
            await asyncio.sleep(VIEW_GAP + random.uniform(0.5, 2))

    clear_stop_event(uid)
    await status.edit_text(
        f"👁️ *Views Complete*\n\n"
        f"Posts: `{len(posts)}`\nViews/post: `{views_pp}`\n"
        f"✅ Success: `{success}`\n❌ Failed: `{failed}`\n\n"
        f"_Note: Telegram caps ~1–2 increments/account/day._",
        parse_mode="Markdown", reply_markup=main_menu_kb())
    context.user_data["flow"] = None
