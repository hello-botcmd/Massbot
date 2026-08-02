import asyncio
import logging
import random

from utils.database import Database
from utils.account_ops import apply_mode_to_account
from utils.helpers import esc, MODE_COUNTS_RE
from bot.keyboards import main_menu_kb

logger = logging.getLogger(__name__)
db = Database()

LABELS = {1: "Always Online", 2: "Online 2 min", 3: "Hidden Last Seen"}


async def mode_count_handle(update, context):
    m = MODE_COUNTS_RE.match(update.message.text.strip())
    if not m:
        await update.message.reply_text(
            "❌ Invalid format. Send **three counts** like:\n`5,3,2`\n\n"
            "Mode 1 — Always Online\n"
            "Mode 2 — Online 2 min\n"
            "Mode 3 — Hide Last Seen",
            parse_mode="Markdown")
        return

    c1, c2, c3 = int(m.group(1)), int(m.group(2)), int(m.group(3))
    total = c1 + c2 + c3
    if total < 1:
        await update.message.reply_text("❌ Counts must be positive.")
        return

    accounts = await db.get_active_accounts()
    if len(accounts) < total:
        await update.message.reply_text(
            f"❌ Need `{total}` active accounts, only `{len(accounts)}` available.",
            parse_mode="Markdown", reply_markup=main_menu_kb())
        context.user_data["flow"] = None
        return

    random.shuffle(accounts)
    sel1 = accounts[:c1]
    sel2 = accounts[c1:c1 + c2]
    sel3 = accounts[c1 + c2:c1 + c2 + c3]

    assignments = [(1, a) for a in sel1] + \
                  [(2, a) for a in sel2] + \
                  [(3, a) for a in sel3]

    status = await update.message.reply_text("⏳ Applying mode distribution...")
    results = []
    for mode, acc in assignments:
        try:
            msg = await apply_mode_to_account(acc, mode, db)
            results.append(msg)
        except Exception as e:
            logger.exception("mode apply error")
            results.append(f"❌ {esc(acc.get('phone','?'))}: {esc(e)}")
        await asyncio.sleep(0.3)

    detail = "\n".join(results[-20:])
    if len(results) > 20:
        detail = f"... and {len(results)-20} more\n" + detail

    await status.edit_text(
        f"🎭 *Mode Distribution Complete*\n\n"
        f"Mode 1 (Always Online): `{c1}`\n"
        f"Mode 2 (Online 2 min): `{c2}`\n"
        f"Mode 3 (Hidden): `{c3}`\n\n"
        f"```\n{detail}\n```",
        parse_mode="Markdown", reply_markup=main_menu_kb())
    context.user_data["flow"] = None
