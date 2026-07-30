import asyncio
import logging
import re
from telethon import functions, types
from telethon.errors import (
    ChannelPrivateError, UsernameNotOccupiedError, InviteHashExpiredError,
    InviteHashInvalidError, UserAlreadyParticipantError, RPCError
)
from utils.telethon_client import TelethonManager

logger = logging.getLogger(__name__)
tmanager = TelethonManager()

# ── Running-tasks registry ──
# { str(account_id) : asyncio.Task }
_mode_tasks: dict[str, asyncio.Task] = {}
# { user_id : [asyncio.Task] }
_user_operations: dict[int, list[asyncio.Task]] = {}

# ── Cancellation event for bulk operations ──
_stop_events: dict[int, asyncio.Event] = {}

# ════════════════════════════════════════════════════════════
#  Session validation
# ════════════════════════════════════════════════════════════

async def validate_session(session_string: str) -> dict | None:
    """Validate a session string and return user info."""
    client = await tmanager.create_client(session_string)
    if not client:
        return None
    info = await tmanager.get_me(client)
    try:
        await client.disconnect()
    except Exception:
        pass
    return info


# ════════════════════════════════════════════════════════════
#  Resolve entities
# ════════════════════════════════════════════════════════════

async def resolve_entity(client, identifier):
    """Resolve a username / invite link / phone to an InputPeer."""
    try:
        entity = await client.get_entity(identifier)
        return entity, None
    except (UsernameNotOccupiedError, ValueError) as e:
        return None, f"Invalid username or link: {e}"
    except ChannelPrivateError:
        return None, "Channel is private or bot/account is not a member"
    except Exception as e:
        return None, f"Error: {e}"


# ════════════════════════════════════════════════════════════
#  Join Channel / Group
# ════════════════════════════════════════════════════════════

async def join_target(client, target: str):
    """Join a channel/group by username or invite link."""
    target = target.strip()
    try:
        # Invite link?
        invite_match = re.match(r'(?:https?://)?t\.me/(?:\+|joinchat/)([a-zA-Z0-9_\-]+)', target)
        if invite_match:
            hash_ = invite_match.group(1)
            result = await client(functions.messages.ImportChatInviteRequest(hash=hash_))
            if hasattr(result, 'chats') and result.chats:
                return True, result.chats[0].id, "Joined via invite link"
            return True, None, "Joined via invite link"

        # username or public link
        username_match = re.match(r'(?:https?://)?t\.me/([a-zA-Z0-9_]+)', target)
        if username_match:
            target = username_match.group(1)

        entity = await client.get_entity(target)
        if hasattr(entity, 'username') or hasattr(entity, 'title'):
            await client(functions.channels.JoinChannelRequest(channel=entity))
            return True, entity.id, f"Joined @{getattr(entity, 'username', entity.id)}"
        else:
            return False, None, "Not a valid channel or group"
    except UserAlreadyParticipantError:
        return True, None, "Already a member"
    except InviteHashExpiredError:
        return False, None, "Invite link expired"
    except InviteHashInvalidError:
        return False, None, "Invalid invite link"
    except RPCError as e:
        return False, None, f"RPC error: {e}"
    except Exception as e:
        return False, None, f"Error: {e}"


async def leave_target(client, target: str):
    """Leave a channel/group by username or chat ID."""
    try:
        entity = await client.get_entity(target)
        await client(functions.channels.LeaveChannelRequest(channel=entity))
        return True, f"Left successfully"
    except RPCError as e:
        return False, f"RPC error: {e}"
    except Exception as e:
        return False, f"Error: {e}"


# ════════════════════════════════════════════════════════════
#  Online / Offline / Privacy
# ════════════════════════════════════════════════════════════

async def set_online(client, online: bool = True):
    """Set the account online (offline=False) or offline (offline=True)."""
    await client(functions.account.UpdateStatusRequest(offline=not online))


async def set_privacy_last_seen(client, allow_all: bool = True):
    """Set last-seen privacy to everybody / nobody."""
    key = types.InputPrivacyKeyStatusTimestamp()
    if allow_all:
        rules = [types.InputPrivacyValueAllowAll()]
    else:
        rules = [types.InputPrivacyValueDisallowAll()]
    await client(functions.account.SetPrivacyRequest(key=key, rules=rules))


async def keep_online_loop(client, account_id: str, stop_event: asyncio.Event):
    """Background task: keep account online forever (Mode 1)."""
    from config import ONLINE_PING_INTERVAL
    try:
        while not stop_event.is_set():
            try:
                await set_online(client, online=True)
                logger.debug(f"[{account_id}] Online status ping")
            except Exception as e:
                logger.error(f"[{account_id}] keep_online error: {e}")
                break
            await asyncio.sleep(ONLINE_PING_INTERVAL)
    except asyncio.CancelledError:
        pass
    finally:
        logger.info(f"[{account_id}] keep_online_loop ended")


async def online_for_2min_task(client, account_id: str, stop_event: asyncio.Event):
    """Background task: stay online for 2 minutes then go offline (Mode 2)."""
    from config import MODE2_ONLINE_DURATION
    try:
        await set_online(client, online=True)
        logger.info(f"[{account_id}] Mode 2: online for {MODE2_ONLINE_DURATION}s")
        try:
            await asyncio.wait_for(
                asyncio.get_event_loop().create_future(),  # never completes
                timeout=MODE2_ONLINE_DURATION
            )
        except asyncio.TimeoutError:
            pass  # expected after 2 minutes
        except asyncio.CancelledError:
            raise

        if not stop_event.is_set():
            await set_online(client, online=False)
            logger.info(f"[{account_id}] Mode 2: now offline")
    except asyncio.CancelledError:
        # If cancelled during the 2 min, set offline on cancel
        try:
            await set_online(client, online=False)
        except Exception:
            pass
        raise


# ════════════════════════════════════════════════════════════
#  Apply mode to a single account
# ════════════════════════════════════════════════════════════

async def apply_mode_to_account(account: dict, new_mode: int, db) -> str:
    """Apply a mode (1, 2, or 3) to one account. Returns status string."""
    from utils.database import Database

    aid = str(account["_id"])
    client = await tmanager.get_client(account)
    if not client:
        return f"❌ {account.get('phone', '?')} — failed to connect"

    prev_mode = account.get("current_mode")

    # Cancel existing mode task
    if aid in _mode_tasks and not _mode_tasks[aid].done():
        _mode_tasks[aid].cancel()
        try:
            await _mode_tasks[aid]
        except (asyncio.CancelledError, Exception):
            pass

    # Create a stop_event for this account
    stop_event = asyncio.Event()

    try:
        # Handle transitions
        if prev_mode == 3 and new_mode in (1, 2):
            # Was hidden → show again
            await set_privacy_last_seen(client, allow_all=True)
            logger.info(f"[{aid}] Privacy: last_seen restored to everybody")

        if new_mode == 3 and prev_mode != 3:
            # Going into hidden mode
            await set_privacy_last_seen(client, allow_all=False)
            await set_online(client, online=False)
            logger.info(f"[{aid}] Privacy: last_seen hidden")
            await db.update_account(account["_id"],
                                    current_mode=3, is_online=False,
                                    last_seen_hidden=True, online_task_running=False)
            return f"🔵 {account.get('phone', '?')} → Mode 3 (hidden last seen)"

        if new_mode == 1:
            await set_online(client, online=True)
            await set_privacy_last_seen(client, allow_all=True)
            task = asyncio.create_task(keep_online_loop(client, aid, stop_event))
            _mode_tasks[aid] = task
            await db.update_account(account["_id"],
                                    current_mode=1, is_online=True,
                                    last_seen_hidden=False, online_task_running=True)
            return f"🟢 {account.get('phone', '?')} → Mode 1 (always online)"

        if new_mode == 2:
            await set_online(client, online=True)
            await set_privacy_last_seen(client, allow_all=True)
            task = asyncio.create_task(online_for_2min_task(client, aid, stop_event))
            _mode_tasks[aid] = task
            await db.update_account(account["_id"],
                                    current_mode=2, is_online=True,
                                    last_seen_hidden=False, online_task_running=True)
            return f"🟡 {account.get('phone', '?')} → Mode 2 (2 min online)"

    except Exception as e:
        logger.exception(f"[{aid}] apply_mode error: {e}")
        return f"❌ {account.get('phone', '?')} — error: {e}"

    return f"⚠️ {account.get('phone', '?')} — no change"


async def stop_account_mode(account: dict, db):
    """Stop any running mode for an account and set it back to normal (offline)."""
    aid = str(account["_id"])
    if aid in _mode_tasks and not _mode_tasks[aid].done():
        _mode_tasks[aid].cancel()
        try:
            await _mode_tasks[aid]
        except Exception:
            pass
    client = await tmanager.get_client(account)
    if client:
        try:
            await set_privacy_last_seen(client, allow_all=True)
            await set_online(client, online=False)
        except Exception:
            pass
    await db.update_account(account["_id"],
                            current_mode=None, is_online=False,
                            last_seen_hidden=False, online_task_running=False)
    return f"⏹️ {account.get('phone', '?')} — mode stopped"


# ════════════════════════════════════════════════════════════
#  Reaction
# ════════════════════════════════════════════════════════════

def parse_telegram_link(url: str):
    """Parse a Telegram message link → (chat_identifier, msg_id)."""
    url = url.strip()
    m = re.search(r't\.me/([a-zA-Z0-9_]+)/(\d+)', url)
    if m:
        return m.group(1), int(m.group(2))
    m = re.search(r't\.me/c/(\d+)/(\d+)', url)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


async def add_reaction(client, chat_id, msg_id, emoticons: list[str]):
    """React to a message with one or more emojis."""
    reactions = [types.ReactionEmoji(emoticon=e) for e in emoticons]
    await client(functions.messages.SendReactionRequest(
        peer=chat_id,
        msg_id=msg_id,
        reaction=reactions
    ))


# ════════════════════════════════════════════════════════════
#  Views
# ════════════════════════════════════════════════════════════

async def boost_view(client, chat_id, msg_id):
    """Try to increment the view count on a message."""
    try:
        await client(functions.messages.GetMessagesViewsRequest(
            peer=chat_id,
            id=[msg_id],
            increment=True
        ))
        return True
    except Exception as e:
        logger.warning(f"GetMessagesViewsRequest failed: {e}")
        # Fallback: send read acknowledge
        try:
            await client.send_read_acknowledge(chat_id, max_id=msg_id)
            return True
        except Exception:
            return False


# ════════════════════════════════════════════════════════════
#  Stop / Cancel helpers
# ════════════════════════════════════════════════════════════

def get_stop_event(user_id: int) -> asyncio.Event:
    if user_id not in _stop_events:
        _stop_events[user_id] = asyncio.Event()
    return _stop_events[user_id]


def clear_stop_event(user_id: int):
    _stop_events.pop(user_id, None)


def register_user_task(user_id: int, task: asyncio.Task):
    if user_id not in _user_operations:
        _user_operations[user_id] = []
    _user_operations[user_id].append(task)


async def cancel_user_operations(user_id: int):
    """Cancel all running operations for a user."""
    if user_id in _user_operations:
        for task in _user_operations[user_id]:
            if not task.done():
                task.cancel()
        _user_operations[user_id] = []
    get_stop_event(user_id).set()
    clear_stop_event(user_id)


async def cancel_all_account_modes():
    """Cancel all mode tasks globally (for all accounts)."""
    for aid, task in list(_mode_tasks.items()):
        if not task.done():
            task.cancel()
    _mode_tasks.clear()
