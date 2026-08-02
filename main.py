#!/usr/bin/env python3
import asyncio
import logging
import sys

from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters,
)

from config import BOT_TOKEN, OWNER_ID, ADMIN_IDS, HEALTH_CHECK_INTERVAL
from utils.database import Database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


async def health_check_loop():
    from utils.telethon_client import TelethonManager
    from utils.account_ops import apply_mode_to_account, is_mode_task_running
    db = Database()
    tm = TelethonManager()
    while True:
        try:
            accounts = await db.get_all_accounts()
            for acc in accounts:
                if acc.get("status") != "active":
                    continue
                aid = str(acc["_id"])
                mode = acc.get("current_mode")
                # 1) Restore crashed mode-1/2 tasks (not just VPS restarts)
                if mode in (1, 2) and acc.get("online_task_running") and not is_mode_task_running(aid):
                    logger.warning("Restoring dead mode-%s task for %s", mode, acc.get("phone"))
                    try:
                        await apply_mode_to_account(acc, mode, db)
                    except Exception as e:
                        logger.warning("restore failed %s: %s", acc.get("phone"), e)
                # 2) Reconnect dead clients instead of marking disconnected
                client = tm._clients.get(aid)
                if client and not client.is_connected():
                    try:
                        await client.connect()
                    except Exception:
                        pass
                    if not client.is_connected():
                        try:
                            ok = await client.is_user_authorized()
                        except Exception:
                            ok = False
                        if not ok:
                            logger.warning("Session dead for %s → disconnected", acc.get("phone"))
                            await db.update_account(aid, {"status": "disconnected", "in_use": False})
        except Exception as e:
            logger.warning("Health check error: %s", e)
        await asyncio.sleep(HEALTH_CHECK_INTERVAL)


async def post_init(app):
    db = Database()
    await db.connect()
    app.create_task(health_check_loop())

    # ── Resume all modes automatically after VPS restart / bot restart ──
    from utils.account_ops import apply_mode_to_account
    accounts = await db.get_all_accounts()
    to_restore = [a for a in accounts
                  if a.get("status") == "active" and a.get("current_mode") in (1, 2, 3)]
    if to_restore:
        logger.info("Restoring mode for %d account(s) after restart...", len(to_restore))
        sem = asyncio.Semaphore(8)

        async def _restore(acc):
            async with sem:
                try:
                    await apply_mode_to_account(acc, acc["current_mode"], db)
                except Exception as e:
                    logger.warning("restore %s: %s", acc.get("phone"), e)

        await asyncio.gather(*[_restore(a) for a in to_restore])
        logger.info("Mode restore finished.")

    logger.info("Bot started. Owner=%s Admins=%s", OWNER_ID, ADMIN_IDS)


async def error_handler(update, context):
    logger.exception("Bot error: %s", context.error)
    if update and update.effective_message:
        try:
            from bot.keyboards import main_menu_kb
            await update.effective_message.reply_text(
                "⚠️ Internal error. Use /start to restart.",
                reply_markup=main_menu_kb())
        except Exception:
            pass


def main():
    if "PASSWORD@" in MONGO_URI or "YOUR_" in str(BOT_TOKEN):
        print("❌ config.py: fill MONGO_URI (password + cluster) before running.")
        sys.exit(1)

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    from bot.menu import start, stop_command, callback_router, text_router
    from bot.remove import remove_start

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop_command))
    app.add_handler(CommandHandler("remove", remove_start))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    app.add_error_handler(error_handler)

    logger.info("Starting bot polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
