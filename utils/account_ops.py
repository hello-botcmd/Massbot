        import asyncio
import logging
import re

from telethon import functions, types
from telethon.errors import UserAlreadyParticipantError
from telethon.tl.functions.account import (
    UpdateStatusRequest, SetPrivacyRequest, GetPrivacyRequest,
)
from telethon.tl.functions.messages import SendReactionRequest, GetMessagesViewsRequest
from telethon.tl.types import (
    InputPrivacyKeyStatusTimestamp,
    InputPrivacyValueAllowAll,
    InputPrivacyValueAllowContacts,
    InputPrivacyValueDisallowAll,
)

from config import ONLINE_PING_INTERVAL, MODE2_ONLINE_DURATION
from utils.helpers import esc
from utils.telethon_client import TelethonManager

logger = logging.getLogger(__name__)

LINK_PATTERN = re.compile(r"https?://t\.me/(?:c/(\d+)|([^/]+))/(\d+)")

_stop_events = {}    # owner_uid -> asyncio.Event
_online_tasks = {}   # account_id -> asyncio.Task


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


# ── stop machinery ───────────────────────────────────────────
def get_stop_event(uid: int) -> asyncio.Event:
    if uid not in _stop_events:
        _stop_events[uid] = asyncio.Event()
    return _stop_events[uid]


def clear_stop_event(uid: int):
    ev = _stop_events.pop(uid, None)
    if ev:
        ev.set()


async def cancel_user_operations(uid: int):
    ev = _stop_events.get(uid)
    if ev:
        ev.set()


# ── privacy helpers ──────────────────────────────────────────
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


async def _set_last_seen_visible(client) -> bool:
    """Unhide → 'Everybody', then VERIFY it stuck. Returns True if confirmed."""
    if await _is_last_seen_visible(client):
        return True
    # 1) explicit Everybody
    await client(SetPrivacyRequest(
        key=InputPrivacyKeyStatusTimestamp(),
        rules=[InputPrivacyValueAllowAll()],
    ))
    await asyncio.sleep(1.5)
    if await _is_last_seen_visible(client):
        return True
    # 2) fallback: reset to default (empty rules == everybody)
    await client(SetPrivacyRequest(
        key=InputPrivacyKeyStatusTimestamp(),
        rules=[],
    ))
    await asyncio.sleep(1.5)
    return await _is_last_seen_visible(client)


async def _set_last_seen_hidden(client):
    """Hide last seen from non-contacts (Mode 3)."""
    await client(SetPrivacyRequest(
        key=InputPrivacyKeyStatusTimestamp(),
        rules=[InputPrivacyValueAllowContacts()],
    ))
    await asyncio.sleep(1.0)


# ── online loops (mode 1 & 2) ────────────────────────────────
async def _online_loop(acc, mode, db):
    account_id = str(acc["_id"])
    tm = TelethonManager()
    try:
        client = await tm.get_persistent_client(account_id, acc["session_string"])
        if not client:
            await db.update_account(account_id, {"status": "disconnected"})
            return
        while True:
            ev = _stop_events.get(acc["owner_uid"])
            if ev and ev.is_set():
                break
            try:
                await client(UpdateStatusRequest(offline=False))
                if mode == 2:
                    await asyncio.sleep(MODE2_ONLINE_DURATION)
                    await client(UpdateStatusRequest(offline=True))
                    break
            except Exception as e:
                logger.warning("online ping error %s: %s", acc.get("phone"), e)
                await asyncio.sleep(5)
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

    Mode 1/2: ALWAYS enforce visible last seen on Telegram (unhide if hidden,
              verify) THEN go online. Never skips the check based on DB flags.
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
            # ⭐ ALWAYS check Telegram's real privacy, not the DB flag
            was_actually_hidden = not await _is_last_seen_visible(client)
            unhidden_ok = await _set_last_seen_visible(client)  # enforce visible
            await client(UpdateStatusRequest(offline=False))    # then online
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
        if was_actually_hidden:
            tag = " 🔓 unhidden ✓" if unhidden_ok else " ⚠️ unhide FAILED"
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


# ── join / leave ─────────────────────────────────────────────
async def join_target(client, target: str):
    target = target.strip()
    try:
        if target.startswith("https://t.me/") or target.startswith("t.me/"):
            entity = await client.get_entity(target)
            await client(functions.channels.JoinChannelRequest(entity))
            return True, "joined via link"
        if target.startswith("@"):
            entity = await client.get_entity(target)
            await client(functions.channels.JoinChannelRequest(entity))
            return True, "joined"
        await client(functions.messages.ImportChatInviteRequest(hash=target.split("/")[-1]))
        return True, "joined via invite"
    except UserAlreadyParticipantError:
        return True, "already joined"
    except Exception as e:
        return False, str(e)


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
