#!/usr/bin/env python3
"""
Telegram Account Management Bot
Main entry point — wires up all handlers and starts polling.
"""

import asyncio
import logging
import sys

from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    PicklePersistence,
)

from config import BOT_TOKEN, OWNER_ID, ADMIN_IDS
from utils.database import Database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


async def post_init(application):
    """Run after the Application is initialised (called once on startup)."""
    logger.info("Connecting to MongoDB…")
    db = Database()
    await db.connect()
    logger.info("MongoDB connected.")

    # Restore mode 1 tasks for accounts that had online_task_running=True
    try:
        accounts = await db.get_all_active_accounts()
        restored = 0
        for acc in accounts:
            if acc.get("current_mode") == 1 and acc.get("online_task_running"):
                from utils.account_ops import apply_mode_to_account
                try:
                    asyncio.create_task(_restore_mode(acc, db))
                    restored += 1
                except Exception:
                    pass
        if restored:
            logger.info(f"Restored online-mode for {restored} account(s).")
    except Exception as e:
        logger.warning(f"Could not restore mode tasks: {e}")

    logger.info(f"Bot started. Owner={OWNER_ID} Admins={ADMIN_IDS}")


async def _restore_mode(account, db):
    """Background task to restore mode 1 for an account after restart."""
    from utils.account_ops import apply_mode_to_account
    try:
        await apply_mode_to_account(account, 1, db)
    except Exception as e:
        logger.error(f"Restore mode failed for {account.get('phone')}: {e}")


def main():
    """Non-async main — run_polling() manages its own event loop."""
    persistence = PicklePersistence(filepath="bot_data.pkl")

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .persistence(persistence)
        .build()
    )

    # ── Import handlers after app build to avoid circular imports ──
    from bot.handlers import (
        start, stop_command, main_menu_callback,
        add_account_conv, join_conv, mode_conv,
        reaction_conv, views_conv, remove_conv,
        error_handler,
    )

    # ── Register handlers ──

    # Simple command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop_command))

    # Main menu callback (catches non-conversation callbacks)
    app.add_handler(
        CallbackQueryHandler(
            main_menu_callback,
            pattern="^(main_menu|add_account|total_account|all_online)$"
        )
    )
    # Standalone cancel button handler (when no conversation is active)
    app.add_handler(
        CallbackQueryHandler(cancel_op_fallback, pattern="^cancel_op$")
    )
    # Conversation handlers
    app.add_handler(add_account_conv)
    app.add_handler(join_conv)
    app.add_handler(mode_conv)
    app.add_handler(reaction_conv)
    app.add_handler(views_conv)
    app.add_handler(remove_conv)

    # Error handler
    app.add_error_handler(error_handler)

    # ── Start polling (blocks until shutdown) ──
    logger.info("Starting bot polling…")
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
