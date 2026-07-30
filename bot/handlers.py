import asyncio
import logging
import random
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CommandHandler, CallbackQueryHandler, MessageHandler,
    filters, ConversationHandler, ContextTypes
)

from config import OWNER_ID, ADMIN_IDS, VIEW_GAP, REACTION_GAP
from utils.database import Database
from utils.telethon_client import TelethonManager
from utils.account_ops import (
    validate_session, join_target, leave_target,
    apply_mode_to_account, stop_account_mode,
    parse_telegram_link, add_reaction, boost_view,
    resolve_entity, cancel_user_operations, cancel_all_account_modes,
    register_user_task, get_stop_event, clear_stop_event,
    _mode_tasks,
)
from utils.helpers import (
    parse_timing, parse_mode_counts, distribute_accounts,
    parse_reaction_emojis,
)
from bot.keyboards import main_menu_kb, add_type_kb, cancel_kb
from bot.states import *

logger = logging.getLogger(__name__)
db = Database()
tmanager = TelethonManager()

# ── Authorisation check ────────────────────────────────────

def is_authorized(user_id: int) -> bool:
    return user_id == OWNER_ID or user_id in ADMIN_IDS


# ── /start ─────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_authorized(uid):
        await update.message.reply_text("⛔ Unauthorized. You are not in the admin list.")
        return

    await update.message.reply_text(
        "🤖 *Telegram Account Management Bot*\n\n"
        "Use the buttons below to control your Telegram accounts.",
        reply_markup=main_menu_kb(),
        parse_mode="Markdown",
    )


# ── Main menu callback ────────────────────────────────────

async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    if not is_authorized(uid):
        await query.edit_message_text("⛔ Unauthorized.")
        return

    data = query.data
    text = "🤖 *Main Menu*\nChoose an action below:"

    if data == "main_menu":
        await query.edit_message_text(text, reply_markup=main_menu_kb(), parse_mode="Markdown")
        return

    elif data == "add_account":
        await query.edit_message_text(
            "Select add method:",
            reply_markup=add_type_kb(),
        )
        return

    elif data == "total_account":
        counts = await db.get_global_counts()
        await query.edit_message_text(
            f"📊 *Account Statistics*\n\n"
            f"Total: `{counts['total']}`\n"
            f"Active: `{counts['active']}`",
            parse_mode="Markdown",
            reply_markup=main_menu_kb(),
        )
        return

    elif data == "all_online":
        await query.edit_message_text(
            "⏳ Making all accounts online forever...\n"
            "This may take a moment.",
            reply_markup=None,
        )
        await _make_all_online(query, context)
        return

    elif data == "cancel_op":
        await cancel_user_operations(uid)
        await query.edit_message_text(
            "✅ Operation cancelled.",
            reply_markup=main_menu_kb(),
        )
        return

    # These start conversation handlers via entry points
    # but we handle inline button routing here
    await query.edit_message_text(text, reply_markup=main_menu_kb(), parse_mode="Markdown")


# ── Helper: make all accounts online ──────────────────────

async def _make_all_online(query, context):
    accounts = await db.get_all_active_accounts()
    if not accounts:
        await query.edit_message_text(
            "❌ No active accounts found.",
            reply_markup=main_menu_kb(),
        )
        return

    success = 0
    errors = 0
    status_lines = []
    for acc in accounts:
        try:
            msg = await apply_mode_to_account(acc, 1, db)
            status_lines.append(msg)
            if "❌" not in msg:
                success += 1
            else:
                errors += 1
            await asyncio.sleep(0.5)  # rate limit
        except Exception as e:
            errors += 1
            status_lines.append(f"❌ {acc.get('phone','?')} — {e}")

    summary = (
        f"🌐 *All Accounts Online*\n\n"
        f"✅ Online: {success}\n"
        f"❌ Failed: {errors}\n\n"
    )
    # Show last 10 status lines
    detail = "\n".join(status_lines[-10:])
    if len(status_lines) > 10:
        detail = f"... and {len(status_lines)-10} more\n" + detail

    await query.edit_message_text(
        summary + f"```\n{detail}\n```",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(),
    )


# ── /stop ─────────────────────────────────────────────────

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_authorized(uid):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    await cancel_user_operations(uid)
    await update.message.reply_text(
        "✅ All running operations stopped.",
        reply_markup=main_menu_kb(),
    )


# ════════════════════════════════════════════════════════════
#  1. ADD ACCOUNT conversation
# ════════════════════════════════════════════════════════════

async def single_add_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_authorized(query.from_user.id):
        await query.edit_message_text("⛔ Unauthorized.")
        return ConversationHandler.END
    await query.edit_message_text(
        "📱 Send the **session string** for the account:",
        parse_mode="Markdown",
        reply_markup=cancel_kb(),
    )
    return WAIT_SINGLE_SESSION


async def single_add_handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    session_str = update.message.text.strip()
    if len(session_str) < 10:
        await update.message.reply_text("❌ Invalid session string. Please send a valid Telethon session string.")
        return WAIT_SINGLE_SESSION

    status_msg = await update.message.reply_text("⏳ Validating session...")
    info = await validate_session(session_str)
    if not info:
        await status_msg.edit_text("❌ Invalid or expired session string. Please check and try again.")
        return WAIT_SINGLE_SESSION

    phone = info.get("phone", info.get("id", "unknown"))
    try:
        oid = await db.add_account(uid, str(phone), session_str)
        await status_msg.edit_text(
            f"✅ *Account Added!*\n\n"
            f"📱 Phone: `{phone}`\n"
            f"👤 Name: {info.get('first_name', '')} {info.get('last_name', '')}\n"
            f"🆔 ID: `{info.get('id')}`",
            parse_mode="Markdown",
            reply_markup=main_menu_kb(),
        )
    except Exception as e:
        await status_msg.edit_text(f"❌ Database error: {e}", reply_markup=main_menu_kb())

    return ConversationHandler.END


async def bulk_add_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_authorized(query.from_user.id):
        await query.edit_message_text("⛔ Unauthorized.")
        return ConversationHandler.END
    await query.edit_message_text(
        "🔢 Send the **number of accounts** you want to add:",
        parse_mode="Markdown",
        reply_markup=cancel_kb(),
    )
    return WAIT_BULK_COUNT


async def bulk_add_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit() or int(text) < 1:
        await update.message.reply_text("❌ Please send a valid positive number.")
        return WAIT_BULK_COUNT

    count = int(text)
    context.user_data["bulk_total"] = count
    context.user_data["bulk_index"] = 0
    context.user_data["bulk_success"] = 0
    context.user_data["bulk_fail"] = 0
    context.user_data["bulk_results"] = []

    await update.message.reply_text(
        f"📱 Send session string **1 / {count}**:",
        parse_mode="Markdown",
        reply_markup=cancel_kb(),
    )
    return WAIT_BULK_SESSION


async def bulk_add_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    session_str = update.message.text.strip()
    idx = context.user_data.get("bulk_index", 0) + 1
    total = context.user_data.get("bulk_total", 1)

    if len(session_str) < 10:
        await update.message.reply_text(
            f"❌ Invalid session. Send session **{idx} / {total}** again:",
            parse_mode="Markdown",
        )
        return WAIT_BULK_SESSION

    status_msg = await update.message.reply_text(f"⏳ Validating session {idx}/{total}...")
    info = await validate_session(session_str)

    if not info:
        context.user_data["bulk_fail"] = context.user_data.get("bulk_fail", 0) + 1
        context.user_data["bulk_results"].append(f"❌ #{idx} — invalid session")
        await status_msg.edit_text(f"❌ Session {idx} invalid. Moving to next...")
    else:
        phone = info.get("phone", info.get("id", "unknown"))
        try:
            await db.add_account(uid, str(phone), session_str)
            context.user_data["bulk_success"] = context.user_data.get("bulk_success", 0) + 1
            context.user_data["bulk_results"].append(
                f"✅ #{idx} — {phone} ({info.get('first_name', '')})"
            )
            await status_msg.edit_text(f"✅ Session {idx} added: `{phone}`", parse_mode="Markdown")
        except Exception as e:
            context.user_data["bulk_fail"] = context.user_data.get("bulk_fail", 0) + 1
            context.user_data["bulk_results"].append(f"❌ #{idx} — DB error: {e}")
            await status_msg.edit_text(f"❌ Session {idx} DB error: {e}")

    context.user_data["bulk_index"] = idx

    if idx >= total:
        # Done
        success = context.user_data["bulk_success"]
        fail = context.user_data["bulk_fail"]
        results = context.user_data["bulk_results"]
        summary = (
            f"📦 *Bulk Add Complete!*\n\n"
            f"✅ Success: `{success}`\n"
            f"❌ Failed: `{fail}`\n\n"
        )
        detail = "\n".join(results[-15:])
        if len(results) > 15:
            detail = f"... and {len(results)-15} more\n" + detail

        await update.message.reply_text(
            summary + f"```\n{detail}\n```",
            parse_mode="Markdown",
            reply_markup=main_menu_kb(),
        )

        # Cleanup user_data
        for key in ["bulk_total", "bulk_index", "bulk_success", "bulk_fail", "bulk_results"]:
            context.user_data.pop(key, None)

        return ConversationHandler.END

    # Ask for next
    await update.message.reply_text(
        f"📱 Send session string **{idx+1} / {total}**:",
        parse_mode="Markdown",
        reply_markup=cancel_kb(),
    )
    return WAIT_BULK_SESSION


# ── Cancel from conversation ──────────────────────────────

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text("❌ Cancelled.", reply_markup=main_menu_kb())
    else:
        await update.message.reply_text("❌ Cancelled.", reply_markup=main_menu_kb())
    return ConversationHandler.END


# ════════════════════════════════════════════════════════════
#  2. JOIN conversation
# ════════════════════════════════════════════════════════════

async def join_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_authorized(query.from_user.id):
        await query.edit_message_text("⛔ Unauthorized.")
        return ConversationHandler.END
    await query.edit_message_text(
        "🔗 Send the channel/group **username** or **invite link**:",
        parse_mode="Markdown",
        reply_markup=cancel_kb(),
    )
    return WAIT_JOIN_LINK


async def join_link_handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["join_target"] = update.message.text.strip()
    await update.message.reply_text(
        "🔢 How many accounts should join?",
        reply_markup=cancel_kb(),
    )
    return WAIT_JOIN_COUNT


async def join_count_handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit() or int(text) < 1:
        await update.message.reply_text("❌ Send a valid positive number.")
        return WAIT_JOIN_COUNT
    context.user_data["join_count"] = int(text)
    await update.message.reply_text(
        "⏱️ Send timing *(e.g., `min-1s max-8s` or `2 6` or `3`)*:",
        parse_mode="Markdown",
        reply_markup=cancel_kb(),
    )
    return WAIT_JOIN_TIMING


async def join_timing_handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    timing = parse_timing(update.message.text.strip())
    if not timing:
        await update.message.reply_text(
            "❌ Invalid timing format. Use e.g.: `min-1s max-8s`",
            parse_mode="Markdown",
        )
        return WAIT_JOIN_TIMING

    min_s, max_s = timing
    target = context.user_data["join_target"]
    count = context.user_data["join_count"]

    accounts = await db.get_active_accounts(uid)
    if len(accounts) < count:
        await update.message.reply_text(
            f"❌ Only {len(accounts)} active accounts available, but {count} requested.",
            reply_markup=main_menu_kb(),
        )
        # cleanup
        for k in ["join_target", "join_count"]:
            context.user_data.pop(k, None)
        return ConversationHandler.END

    selected = random.sample(accounts, count)
    status_msg = await update.message.reply_text(
        f"⏳ Joining {target} with {count} accounts...\n"
        f"Timing: `{min_s}s` – `{max_s}s` (alternating)",
        parse_mode="Markdown",
    )

    stop_ev = get_stop_event(uid)
    results = []
    for i, acc in enumerate(selected):
        if stop_ev.is_set():
            results.append(f"⏹️ #{i+1} — stopped by user")
            break

        client = await tmanager.get_client(acc)
        if not client:
            results.append(f"❌ #{i+1} — {acc.get('phone','?')} failed to connect")
            continue

        ok, chat_id, msg = await join_target(client, target)
        status = "✅" if ok else "❌"
        results.append(f"{status} #{i+1} — {acc.get('phone','?')} — {msg}")

        # Update status message every 5 accounts
        if (i + 1) % 5 == 0 or i == count - 1:
            try:
                partial = "\n".join(results[-10:])
                await status_msg.edit_text(
                    f"⏳ Joining... ({i+1}/{count})\n```\n{partial}\n```",
                    parse_mode="Markdown",
                )
            except Exception:
                pass

        # Alternating timing
        delay = min_s if i % 2 == 0 else max_s
        if i < count - 1 and not stop_ev.is_set():
            await asyncio.sleep(delay)

    clear_stop_event(uid)
    summary = "\n".join(results)
    await status_msg.edit_text(
        f"🔗 *Join Results*\n\n```\n{summary[:3000]}\n```" if len(summary) > 3000
        else f"🔗 *Join Results*\n\n```\n{summary}\n```",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(),
    )

    for k in ["join_target", "join_count"]:
        context.user_data.pop(k, None)
    return ConversationHandler.END


# ════════════════════════════════════════════════════════════
#  3. MODE conversation
# ════════════════════════════════════════════════════════════

async def mode_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_authorized(query.from_user.id):
        await query.edit_message_text("⛔ Unauthorized.")
        return ConversationHandler.END
    await query.edit_message_text(
        "🎭 Send counts as: `mode1, mode2, mode3`\n"
        "Example: `5,3,2`\n\n"
        "*Mode 1* — Always online\n"
        "*Mode 2* — Online 2 min, then offline\n"
        "*Mode 3* — Hidden last seen",
        parse_mode="Markdown",
        reply_markup=cancel_kb(),
    )
    return WAIT_MODE_COUNTS


async def mode_counts_handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    parsed = parse_mode_counts(update.message.text.strip())
    if not parsed:
        await update.message.reply_text(
            "❌ Invalid format. Use e.g.: `5,3,2`",
            parse_mode="Markdown",
        )
        return WAIT_MODE_COUNTS

    c1, c2, c3 = parsed
    total = c1 + c2 + c3
    accounts = await db.get_active_accounts(uid)

    if len(accounts) < total:
        await update.message.reply_text(
            f"❌ Need {total} active accounts, but only {len(accounts)} available.",
            reply_markup=main_menu_kb(),
        )
        return ConversationHandler.END

    # Distribute randomly
    assignments = distribute_accounts(accounts, (c1, c2, c3))
    status_msg = await update.message.reply_text(
        f"⏳ Applying modes to {total} accounts...",
    )

    results = []
    for acc, mode in assignments:
        msg = await apply_mode_to_account(acc, mode, db)
        results.append(msg)
        await asyncio.sleep(0.3)

    detail = "\n".join(results)
    if len(detail) > 3000:
        detail = detail[:3000] + "\n..."

    await status_msg.edit_text(
        f"🎭 *Mode Distribution Complete*\n\n"
        f"Mode 1 (always online): `{c1}`\n"
        f"Mode 2 (2 min online): `{c2}`\n"
        f"Mode 3 (hidden): `{c3}`\n\n"
        f"```\n{detail}\n```",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(),
    )
    return ConversationHandler.END


# ════════════════════════════════════════════════════════════
#  4. REACTION conversation
# ════════════════════════════════════════════════════════════

async def reaction_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_authorized(query.from_user.id):
        await query.edit_message_text("⛔ Unauthorized.")
        return ConversationHandler.END
    await query.edit_message_text(
        "❤️ Send the **post link** (e.g. `https://t.me/channel/123`):",
        parse_mode="Markdown",
        reply_markup=cancel_kb(),
    )
    return WAIT_REACTION_LINK


async def reaction_link_handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    chat_id, msg_id = parse_telegram_link(link)
    if not chat_id or not msg_id:
        await update.message.reply_text(
            "❌ Invalid link format. Use e.g.: `https://t.me/username/123`",
            parse_mode="Markdown",
        )
        return WAIT_REACTION_LINK

    context.user_data["reaction_chat"] = chat_id
    context.user_data["reaction_msg"] = msg_id
    await update.message.reply_text(
        "🔢 How many **reactions** in total?",
        reply_markup=cancel_kb(),
    )
    return WAIT_REACTION_COUNT


async def reaction_count_handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit() or int(text) < 1:
        await update.message.reply_text("❌ Send a valid positive number.")
        return WAIT_REACTION_COUNT
    context.user_data["reaction_total"] = int(text)
    await update.message.reply_text(
        "😊 Send **reaction emoji(s)** (e.g., `❤️🥰👍`):",
        reply_markup=cancel_kb(),
    )
    return WAIT_REACTION_EMOJI


async def reaction_emoji_handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    emoticons = parse_reaction_emojis(update.message.text.strip())
    if not emoticons:
        await update.message.reply_text("❌ No emojis found. Send emoji(s) like `❤️🥰`")
        return WAIT_REACTION_EMOJI

    chat_id = context.user_data["reaction_chat"]
    msg_id = context.user_data["reaction_msg"]
    total = context.user_data["reaction_total"]

    accounts = await db.get_active_accounts(uid)
    if not accounts:
        await update.message.reply_text("❌ No active accounts.", reply_markup=main_menu_kb())
        for k in ["reaction_chat", "reaction_msg", "reaction_total"]:
            context.user_data.pop(k, None)
        return ConversationHandler.END

    status_msg = await update.message.reply_text(f"⏳ Reacting {total} times...")

    stop_ev = get_stop_event(uid)
    success = 0
    errors = 0

    for i in range(total):
        if stop_ev.is_set():
            await status_msg.edit_text("⏹️ Reaction stopped by user.", reply_markup=main_menu_kb())
            break

        acc = accounts[i % len(accounts)]
        client = await tmanager.get_client(acc)
        if not client:
            errors += 1
            continue

        try:
            await add_reaction(client, chat_id, msg_id, emoticons)
            success += 1
        except Exception as e:
            errors += 1
            logger.error(f"Reaction error: {e}")

        if (i + 1) % 10 == 0 or i == total - 1:
            try:
                await status_msg.edit_text(
                    f"⏳ Reacting... {i+1}/{total}\n"
                    f"✅ {success}  ❌ {errors}"
                )
            except Exception:
                pass

        await asyncio.sleep(REACTION_GAP)

    clear_stop_event(uid)
    await status_msg.edit_text(
        f"❤️ *Reaction Complete*\n\n"
        f"Total: `{total}`\n"
        f"✅ Success: `{success}`\n"
        f"❌ Failed: `{errors}`\n"
        f"Emoji(s): `{''.join(emoticons)}`",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(),
    )

    for k in ["reaction_chat", "reaction_msg", "reaction_total"]:
        context.user_data.pop(k, None)
    return ConversationHandler.END


# ════════════════════════════════════════════════════════════
#  5. VIEWS conversation
# ════════════════════════════════════════════════════════════

async def views_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_authorized(query.from_user.id):
        await query.edit_message_text("⛔ Unauthorized.")
        return ConversationHandler.END
    await query.edit_message_text(
        "👁️ Send **post link(s)** (one per line for multiple):\n"
        "e.g. `https://t.me/channel/123`",
        reply_markup=cancel_kb(),
    )
    return WAIT_VIEWS_LINKS


async def views_links_handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    links = [ln.strip() for ln in text.split("\n") if ln.strip()]
    posts = []
    for ln in links:
        chat_id, msg_id = parse_telegram_link(ln)
        if chat_id and msg_id:
            posts.append((chat_id, msg_id))
    if not posts:
        await update.message.reply_text(
            "❌ No valid links found. Use format: `https://t.me/username/123`",
            parse_mode="Markdown",
        )
        return WAIT_VIEWS_LINKS

    context.user_data["views_posts"] = posts
    await update.message.reply_text(
        f"📊 Found `{len(posts)}` post(s).\n"
        "🔢 How many **views per post**?",
        parse_mode="Markdown",
        reply_markup=cancel_kb(),
    )
    return WAIT_VIEWS_COUNT


async def views_count_handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip()
    if not text.isdigit() or int(text) < 1:
        await update.message.reply_text("❌ Send a valid positive number.")
        return WAIT_VIEWS_COUNT

    views_per_post = int(text)
    posts = context.user_data["views_posts"]
    accounts = await db.get_active_accounts(uid)

    if not accounts:
        await update.message.reply_text("❌ No active accounts.", reply_markup=main_menu_kb())
        context.user_data.pop("views_posts", None)
        return ConversationHandler.END

    status_msg = await update.message.reply_text(
        f"⏳ Boosting `{views_per_post}` views on `{len(posts)}` post(s)...",
        parse_mode="Markdown",
    )

    stop_ev = get_stop_event(uid)
    total_ops = 0
    success_ops = 0
    fail_ops = 0

    for post_idx, (chat_id, msg_id) in enumerate(posts):
        if stop_ev.is_set():
            break

        for v in range(views_per_post):
            if stop_ev.is_set():
                break
            acc = accounts[(total_ops) % len(accounts)]
            client = await tmanager.get_client(acc)
            if not client:
                fail_ops += 1
                total_ops += 1
                continue

            ok = await boost_view(client, chat_id, msg_id)
            if ok:
                success_ops += 1
            else:
                fail_ops += 1
            total_ops += 1

            if total_ops % 10 == 0:
                try:
                    await status_msg.edit_text(
                        f"⏳ Views... Post {post_idx+1}/{len(posts)} | "
                        f"View {v+1}/{views_per_post}\n"
                        f"✅ {success_ops} ❌ {fail_ops}"
                    )
                except Exception:
                    pass

            await asyncio.sleep(VIEW_GAP)

    clear_stop_event(uid)
    await status_msg.edit_text(
        f"👁️ *Views Complete*\n\n"
        f"Posts: `{len(posts)}`\n"
        f"Views per post: `{views_per_post}`\n"
        f"✅ Success: `{success_ops}`\n"
        f"❌ Failed: `{fail_ops}`",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(),
    )

    context.user_data.pop("views_posts", None)
    return ConversationHandler.END


# ════════════════════════════════════════════════════════════
#  6. /remove command
# ════════════════════════════════════════════════════════════

async def remove_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_authorized(uid):
        await update.message.reply_text("⛔ Unauthorized.")
        return ConversationHandler.END
    await update.message.reply_text(
        "🗑️ Send the **chat ID or @username** to remove accounts from:",
        parse_mode="Markdown",
        reply_markup=cancel_kb(),
    )
    return WAIT_REMOVE_CHAT


async def remove_chat_handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    target = update.message.text.strip()

    accounts = await db.get_active_accounts(uid)
    if not accounts:
        await update.message.reply_text("❌ No active accounts.", reply_markup=main_menu_kb())
        return ConversationHandler.END

    status_msg = await update.message.reply_text(
        f"⏳ Removing {len(accounts)} accounts from {target}...",
    )

    success = 0
    errors = 0
    stop_ev = get_stop_event(uid)

    for i, acc in enumerate(accounts):
        if stop_ev.is_set():
            break
        client = await tmanager.get_client(acc)
        if not client:
            errors += 1
            continue
        ok, _ = await leave_target(client, target)
        if ok:
            success += 1
        else:
            errors += 1

        if (i + 1) % 5 == 0:
            try:
                await status_msg.edit_text(
                    f"⏳ Leaving... {i+1}/{len(accounts)} | ✅ {success} ❌ {errors}"
                )
            except Exception:
                pass
        await asyncio.sleep(1)

    clear_stop_event(uid)
    await status_msg.edit_text(
        f"🗑️ *Remove Complete*\n\n"
        f"Chat: `{target}`\n"
        f"✅ Left: `{success}`\n"
        f"❌ Failed: `{errors}`",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(),
    )
    return ConversationHandler.END


# ════════════════════════════════════════════════════════════
#  ConversationHandler definitions
# ════════════════════════════════════════════════════════════

# ── Add Account ──
add_account_conv = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(single_add_entry, pattern="^single_add$"),
        CallbackQueryHandler(bulk_add_entry, pattern="^bulk_add$"),
    ],
    states={
        WAIT_SINGLE_SESSION: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, single_add_handle)
        ],
        WAIT_BULK_COUNT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, bulk_add_count)
        ],
        WAIT_BULK_SESSION: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, bulk_add_session)
        ],
    },
    fallbacks=[
        CallbackQueryHandler(cancel_conversation, pattern="^cancel_op$"),
        CommandHandler("cancel", cancel_conversation),
    ],
    name="add_account",
    persistent=False,
    per_chat=False,
    per_user=True,
    per_message=True,          
)

# ── Join ──
join_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(join_entry, pattern="^join$")],
    states={
        WAIT_JOIN_LINK: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, join_link_handle)
        ],
        WAIT_JOIN_COUNT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, join_count_handle)
        ],
        WAIT_JOIN_TIMING: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, join_timing_handle)
        ],
    },
    fallbacks=[
        CallbackQueryHandler(cancel_conversation, pattern="^cancel_op$"),
        CommandHandler("cancel", cancel_conversation),
    ],
    name="join",
    persistent=False,
    per_chat=False,
    per_user=True,
    per_message=True,          
)

# ── Mode ──
mode_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(mode_entry, pattern="^mode$")],
    states={
        WAIT_MODE_COUNTS: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, mode_counts_handle)
        ],
    },
    fallbacks=[
        CallbackQueryHandler(cancel_conversation, pattern="^cancel_op$"),
        CommandHandler("cancel", cancel_conversation),
    ],
    name="mode",
    persistent=False,
    per_chat=False,
    per_user=True,
    per_message=True,          
)

# ── Reaction ──
reaction_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(reaction_entry, pattern="^reaction$")],
    states={
        WAIT_REACTION_LINK: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, reaction_link_handle)
        ],
        WAIT_REACTION_COUNT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, reaction_count_handle)
        ],
        WAIT_REACTION_EMOJI: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, reaction_emoji_handle)
        ],
    },
    fallbacks=[
        CallbackQueryHandler(cancel_conversation, pattern="^cancel_op$"),
        CommandHandler("cancel", cancel_conversation),
    ],
    name="reaction",
    persistent=False,
    per_chat=False,
    per_user=True,
    per_message=True,          
)

# ── Views ──
views_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(views_entry, pattern="^views$")],
    states={
        WAIT_VIEWS_LINKS: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, views_links_handle)
        ],
        WAIT_VIEWS_COUNT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, views_count_handle)
        ],
    },
    fallbacks=[
        CallbackQueryHandler(cancel_conversation, pattern="^cancel_op$"),
        CommandHandler("cancel", cancel_conversation),
    ],
    name="views",
    persistent=False,
    per_chat=False,
    per_user=True,
    per_message=True,          
)

# ── Remove ──
remove_conv = ConversationHandler(
    entry_points=[CommandHandler("remove", remove_start)],
    states={
        WAIT_REMOVE_CHAT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, remove_chat_handle)
        ],
    },
    fallbacks=[
        CallbackQueryHandler(cancel_conversation, pattern="^cancel_op$"),
        CommandHandler("cancel", cancel_conversation),
    ],
    name="remove",
    persistent=False,
    per_chat=False,
    per_user=True,
    per_message=True,          
)


# ── Error handler ─────────────────────────────────────────

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Bot error: %s", context.error)
    if update and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ An internal error occurred. Try again or use /start.",
                reply_markup=main_menu_kb(),
            )
        except Exception:
            pass
