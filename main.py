#!/usr/bin/env python3
import asyncio
import logging
import sys
import warnings

from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    PicklePersistence,
)
from telegram.warnings import PTBUserWarning

from config import BOT_TOKEN, OWNER_ID, ADMIN_IDS
from utils.database import Database

# Suppress harmless PTB per_message warnings
warnings.filterwarnings("ignore", category=PTBUserWarning,
                        message=".*per_message=False.*CallbackQueryHandler.*")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


async def post_init(application):
    logger.info("Connecting to MongoDB…")
    db = Database()
    await db.connect()
    logger.info("MongoDB connected.")

    # Restore mode 1 tasks after restart
    try:
        accounts = await db.get_all_active_accounts()
        restored = 0
        for acc in accounts:
            if acc.get("current_mode") == 1 and acc.get("online_task_running"):
                from utils.account_ops import apply_mode_to_account
                asyncio.create_task(_restore_mode(acc, db))
                restored += 1
        if restored:
            logger.info(f"Restored online-mode for {restored} account(s).")
    except Exception as e:
        logger.warning(f"Restore modes skipped: {e}")

    logger.info(f"Bot started. Owner={OWNER_ID} Admins={ADMIN_IDS}")


async def _restore_mode(account, db):
    from utils.account_ops import apply_mode_to_account
    try:
        await apply_mode_to_account(account, 1, db)
    except Exception as e:
        logger.error(f"Restore failed for {account.get('phone')}: {e}")


async def error_handler(update, context):
    logger.exception("Bot error: %s", context.error)
    if update and update.effective_message:
        try:
            from bot.keyboards import main_menu_kb
            await update.effective_message.reply_text(
                "⚠️ Internal error occurred. Use /start to restart.",
                reply_markup=main_menu_kb(),
            )
        except Exception:
            pass


def main():
    persistence = PicklePersistence(filepath="bot_data.pkl")
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .persistence(persistence)
        .build()
    )

    # ── Imports (each feature is its own file) ──
    from bot.menu import start, stop_command, main_menu_callback
    from bot.add_account import add_account_conv
    from bot.join import join_conv
    from bot.mode import mode_conv
    from bot.reaction import reaction_conv
    from bot.views import views_conv
    from bot.remove import remove_conv

    # 1) Simple commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop_command))

    # 2) Main menu navigation — only catches its own exact patterns
    app.add_handler(
        CallbackQueryHandler(
            main_menu_callback,
            pattern="^(main_menu|add_acc|total_acc|all_online|cancel_op)$"
        )
    )

    # 3) Conversation handlers (each with totally unique entry patterns)
    app.add_handler(add_account_conv)   # entry: ^add_acc:(single|bulk)
    app.add_handler(join_conv)          # entry: ^join$
    app.add_handler(mode_conv)          # entry: ^mode$
    app.add_handler(reaction_conv)      # entry: ^react$
    app.add_handler(views_conv)         # entry: ^views$
    app.add_handler(remove_conv)        # entry: /remove command

    # 4) Error handler
    app.add_error_handler(error_handler)

    logger.info("Starting bot polling…")
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
