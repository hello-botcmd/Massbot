import asyncio
import logging
import re

from telethon import functions, types
from telethon.errors import (
    UserAlreadyParticipantError, InviteRequestSentError,
)
from telethon.tl.functions.account import (
    UpdateStatusRequest, SetPrivacyRequest, GetPrivacyRequest,
)
from telethon.tl.functions.messages import (
    SendReactionRequest, GetMessagesViewsRequest, ImportChatInviteRequest,
)
from telethon.tl.types import (
    InputPrivacyKeyStatusTimestamp,
    InputPrivacyValueAllowAll,
    InputPrivacyValueAllowContacts,
    UpdatePendingJoinRequests,
)

from config import ONLINE_PING_INTERVAL, MODE2_ONLINE_DURATION
from utils.helpers import esc
from utils.telethon_client import TelethonManager

logger = logging.getLogger(__name__)

LINK_PATTERN = re.compile(r"https?://t\.me/(?:c/(\d+)|([^/]+))/(\d+)")

# ── stop machinery — ONE GLOBAL EVENT (shared pool: any admin stops all) ──
_stop_event = None
_online_tasks = {}   # account_id -> asyncio.Task


def get_stop_event() -> asyncio.Event:
    global _stop_event
    if _stop_event is None:
        _stop_event = asyncio.Event()
    return _stop_event


def clear_stop_event():
    global _stop_event
    _stop_event = None


async def cancel_user_operations(uid=None):
    get_stop_event().set()


def is_mode_task_running(account_id: str) -> bool:
    task = _online_tasks.get(account_id)
    return task is not None and not task.done()


# ── link parsing ─────────────────────────────────────────────
def parse_post_link(link: str):
    m = LINK_PATTERN.match(link.strip())
    if not m:
        raise ValueError(f"Invalid Telegram post link: {link}")
    cid, uname, mid = m.groups()
    if cid:
        return int(cid), int(mid)
    return uname, int(mid)


async def get_peer(client, peer_id):
    if isinstance(peer_id, int):
        return await client.get_entity(types.PeerChannel(peer_id))
    return await client.get_entity(peer_id)


# ── privacy helpers (verified unhide) ────────────────────────
def _rule_is_allow_all(r) -> bool:
    return isinstance(r, (types.PrivacyValueAllowAll,
                          types.InputPrivacyValueAllowAll))


def _rule_is_restrictive(r) -> bool:
    return isinstance(r, (
        types.PrivacyValueAllowContacts, types.InputPrivacyValueAllowContacts,
        types.PrivacyValueDisallowAll, types.InputPrivacyValueDisallowAll,
        types.PrivacyValueDisallowContacts, types.InputPrivacyValueDisallowContacts,
        types.PrivacyValueAllowUsers, types.InputPrivacyValueAllowUsers,
        types.PrivacyValueDisallowUsers, types.InputPrivacyValueDisallowUsers,
    ))


async def _is_last_seen_visible(client) -> bool:
    """True if Telegram ACTUALLY shows this account's last seen to everyone."""
    try:
        res = await client(GetPrivacyRequest(key=InputPrivacyKeyStatusTimestamp()))
        rules = res.rules
        if not rules:
            return True                       # empty == default (everyone)
        has_allow_all = any(_rule_is_allow_all(r) for r in rules)
        has_restrict = any(_rule_is_restrictive(r) for r in rules)
        return has_allow_all and not has_restrict
    except Exception as e:
        logger.warning("GetPrivacy failed: %s", e)
        return False


async def _ensure_last_seen_visible(client) -> tuple:
    """Enforce visible last seen. Returns (was_hidden, is_visible_now)."""
    if await _is_last_seen_visible(client):
        return False, True
    # 1) explicit Everybody
    await client(SetPrivacyRequest(
        key=InputPrivacyKeyStatusTimestamp(),
        rules=[InputPrivacyValueAllowAll()],
    ))
    await asyncio.sleep(1.5)
    if await _is_last_seen_visible(client):
        return True, True
    # 2) fallback: reset to default (empty rules == everybody)
    await client(SetPrivacyRequest(
        key=InputPrivacyKeyStatusTimestamp(),
        rules=[],
    ))
    await asyncio.sleep(1.5)
    return True, await _is_last_seen_visible(client)


async def _set_last_seen_hidden(client):
    """Hide last seen from non-contacts (Mode 3)."""
    await client(SetPrivacyRequest(
        key=InputPrivacyKeyStatusTimestamp(),
        rules=[InputPrivacyValueAllowContacts()],
    ))
    await asyncio.sleep(1.0)


# ── online loops (mode 1 & 2) with auto-reconnect ────────────
async def _online_loop(acc, mode, db):
    account_id = str(acc["_id"])
    tm = TelethonManager()
    stop_ev = get_stop_event()     # capture once — survives clear_stop_event()
    client = None
    try:
        while True:
            if stop_ev.is_set():
                break
            # (re)connect if needed
            if client is None or not client.is_connected():
                await tm.drop_persistent(account_id)
                client = await tm.get_persistent_client(account_id, acc["session_string"])
                if client is None:
                    await db.update_account(account_id, {"status": "disconnected"})
                    return
            try:
                await client(UpdateStatusRequest(offline=False))
                if mode == 2:
                    await asyncio.sleep(MODE2_ONLINE_DURATION)
                    if stop_ev.is_set():
                        break
                    await client(UpdateStatusRequest(offline=True))
                    break
            except Exception as e:
                logger.warning("online ping error %s: %s", acc.get("phone"), e)
                await asyncio.sleep(5)
                try:
                    await tm.drop_persistent(account_id)
                except Exception:
                    pass
                client = None          # force reconnect next iteration
                continue
            await asyncio.sleep(ONLINE_PING_INTERVAL)
    finally:
        await tm.drop_persistent(account_id)
        await db.update_account(account_id, {
            "current_mode": 0, "online_task_running": False, "in_use": False,
        })


async def stop_account_mode(acc, db):
    account_id = str(acc["_id"])
    task = _online_tasks.pop(account_id, None)
    if task:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    try:
        client = await TelethonManager().get_fresh_client(acc["session_string"], timeout=10)
        if client:
            await client(UpdateStatusRequest(offline=True))
            await client.disconnect()
    except Exception:
        pass
    await db.update_account(account_id, {
        "current_mode": 0, "online_task_running": False, "in_use": False,
    })


async def apply_mode_to_account(acc, mode, db):
    """Apply a mode to ONE account.

    Mode 1/2: ALWAYS enforce visible last seen (check real Telegram state,
              unhide + verify if needed), THEN go online.
    Mode 3  : hide last seen from non-contacts.
    """
    account_id = str(acc["_id"])
    tm = TelethonManager()
    await stop_account_mode(acc, db)   # kill old online task BEFORE switching

    if mode in (1, 2):
        client = await tm.get_persistent_client(account_id, acc["session_string"])
        if not client:
            await db.update_account(account_id, {"status": "disconnected"})
            return f"❌ {esc(acc.get('phone','?'))}: session invalid"
        try:
            was_hidden, now_visible = await _ensure_last_seen_visible(client)
            await client(UpdateStatusRequest(offline=False))   # then online
        except Exception as e:
            return f"❌ {esc(acc.get('phone','?'))}: {esc(e)}"

        await db.update_account(account_id, {
            "status": "active", "current_mode": mode,
            "last_seen_hidden": False,
            "online_task_running": True, "in_use": True,
        })
        task = asyncio.create_task(_online_loop(acc, mode, db))
        _online_tasks[account_id] = task
        label = "Always Online" if mode == 1 else "Online 2 min"
        if was_hidden:
            tag = " 🔓 unhidden ✓" if now_visible else " ⚠️ unhide FAILED"
        else:
            tag = ""
        return f"✅ {esc(acc.get('phone','?'))}: Mode {mode} ({label}){tag}"

    if mode == 3:
        client = await tm.get_fresh_client(acc["session_string"])
        if not client:
            await db.update_account(account_id, {"status": "disconnected"})
            return f"❌ {esc(acc.get('phone','?'))}: session invalid"
        try:
            await _set_last_seen_hidden(client)
            await client.disconnect()
        except Exception as e:
            return f"❌ {esc(acc.get('phone','?'))}: {esc(e)}"
        await db.update_account(account_id, {
            "status": "active", "current_mode": 3,
            "last_seen_hidden": True,
            "online_task_running": False, "in_use": False,
        })
        return f"✅ {esc(acc.get('phone','?'))}: Mode 3 (last seen hidden)"

    return f"❌ {esc(acc.get('phone','?'))}: unknown mode"


# ── JOIN — direct join AND join-request (approval) flows ─────
def _has_pending(updates) -> bool:
    if isinstance(updates, types.Updates):
        return any(isinstance(u, UpdatePendingJoinRequests) for u in updates.updates)
    return False


def _parse_join_target(target: str):
    """Returns ('username', name) or ('invite', hash)."""
    t = target.strip()
    if t.startswith("https://t.me/"):
        t = t[len("https://t.me/"):]
    elif t.startswith("t.me/"):
        t = t[len("t.me/"):]
    elif t.startswith("@"):
        t = t[1:]
    t = t.rstrip("/")
    if t.startswith("joinchat/"):
        return ("invite", t[len("joinchat/"):])
    if t.startswith("+"):
        return ("invite", t[1:])
    return ("username", t)


async def join_target(client, target: str):
    """Join a channel/group.
    Public/private links → direct join.
    Approval-required links → sends join request automatically.
    """
    kind, val = _parse_join_target(target)
    if not val:
        return False, "invalid target"
    try:
        if kind == "invite":
            updates = await client(ImportChatInviteRequest(hash=val))
            if _has_pending(updates):
                return True, "join request sent (awaiting approval)"
            return True, "joined via invite"
        # username / public
        entity = await client.get_entity(val)
        updates = await client(functions.channels.JoinChannelRequest(entity))
        if _has_pending(updates):
            return True, "join request sent (awaiting approval)"
        return True, "joined"
    except UserAlreadyParticipantError:
        return True, "already joined"
    except InviteRequestSentError:
        return True, "join request already sent"
    except Exception as e:
        msg = str(e)
        if "already" in msg.lower() or "participant" in msg.lower():
            return True, "already joined"
        return False, msg


async def leave_target(client, target: str):
    try:
        entity = await client.get_entity(target)
        await client(functions.channels.LeaveChannelRequest(entity))
        return True, "left"
    except Exception as e:
        return False, str(e)


# ── reaction / views ─────────────────────────────────────────
async def add_reaction(client, peer, msg_id: int, emoji: str):
    await client(SendReactionRequest(
        peer=peer, msg_id=msg_id,
        reaction=[types.ReactionEmoji(emoticon=emoji)],
    ))


async def boost_views(client, peer, msg_id: int):
    await client(GetMessagesViewsRequest(peer=peer, id=[msg_id], increment=True))
