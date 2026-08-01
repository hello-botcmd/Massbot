import asyncio
import logging
import re

from telethon import functions, types
from telethon.errors import UserAlreadyParticipantError
from telethon.tl.functions.account import UpdateStatusRequest, SetPrivacyRequest
from telethon.tl.functions.messages import SendReactionRequest, GetMessagesViewsRequest
from telethon.tl.types import (
    InputPrivacyKeyStatusTimestamp,
    InputPrivacyValueAllowContacts,   # hides last seen from non-contacts (Mode 3)
    InputPrivacyValueAllowAll,        # shows last seen to everyone (Mode 1/2)
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
    account_id = str(acc["_id"])
    tm = TelethonManager()
    # Always stop any running online task BEFORE switching (kills the 3→1/2 race)
    await stop_account_mode(acc, db)

    if mode in (1, 2):
        client = await tm.get_persistent_client(account_id, acc["session_string"])
        if not client:
            await db.update_account(account_id, {"status": "disconnected"})
            return f"❌ {esc(acc.get('phone','?'))}: session invalid"
        try:
            # ⭐ Mode 3 → 1/2 transition: UNHIDE last seen FIRST, then go online
            if acc.get("current_mode") == 3:
                await client(SetPrivacyRequest(
                    key=InputPrivacyKeyStatusTimestamp(),
                    rules=[InputPrivacyValueAllowAll()],
                ))
            await client(UpdateStatusRequest(offline=False))
        except Exception as e:
            return f"❌ {esc(acc.get('phone','?'))}: {esc(e)}"
        await db.update_account(account_id, {
            "status": "active", "current_mode": mode,
            "online_task_running": True, "in_use": True,
        })
        task = asyncio.create_task(_online_loop(acc, mode, db))
        _online_tasks[account_id] = task
        label = "Always Online" if mode == 1 else "Online 2 min"
        return f"✅ {esc(acc.get('phone','?'))}: Mode {mode} ({label})"

    if mode == 3:
        client = await tm.get_fresh_client(acc["session_string"])
        if not client:
            await db.update_account(account_id, {"status": "disconnected"})
            return f"❌ {esc(acc.get('phone','?'))}: session invalid"
        try:
            await client(SetPrivacyRequest(
                key=InputPrivacyKeyStatusTimestamp(),
                rules=[InputPrivacyValueAllowContacts()],
            ))
            await client.disconnect()
        except Exception as e:
            return f"❌ {esc(acc.get('phone','?'))}: {esc(e)}"
        await db.update_account(account_id, {
            "status": "active", "current_mode": 3,
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
