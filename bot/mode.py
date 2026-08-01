import asyncio
import logging
import random

from utils.database import Database
from utils.account_ops import apply_mode_to_account
from bot.keyboards import main_menu_kb

logger = logging.getLogger(__name__)
db = Database()

LABELS = {"1": "Always Online", "2": "Online 2 min", "3": "Hidden Last Seen"}


async def mode_count_handle(update, context):
    uid = update.effective_user.id
    flow = context.user_data.get("flow", "")
    mode = flow.split("_")[-1]  # "mode_count_1" → "1"
    if mode not in LABELS:
        return

    text = update.message.text.strip()
    if not text.isdigit() or int(text) < 1:
        await update.message.reply_text("❌ Send a valid positive number.")
        return
    count = int(text)

    accounts = await db.get_active_accounts(uid)
    if len(accounts) < count:
        await update.message.reply_text(
            f"❌ Only {len(accounts)} active accounts available.",
            reply_markup=main_menu_kb())
        context.user_data["flow"] = None
        return

    selected = random.sample(accounts, count)
    status = await update.message.reply_text(
        f"⏳ Applying Mode {mode} to {count} accounts...")

    results = []
    for acc in selected:
        msg = await apply_mode_to_account(acc, int(mode), db)
        results.append(msg)
        await asyncio.sleep(0.3)

    detail = "\n".join(results[-15:])
    await status.edit_text(
        f"🎭 *Mode {mode} Applied — {LABELS[mode]}*\nAccounts: `{count}`\n\n```\n{detail}\n```",
        parse_mode="Markdown", reply_markup=main_menu_kb())
    context.user_data["flow"] = None
