import asyncio
import logging
from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError, PhoneCodeInvalidError,
    AuthKeyUnregisteredError, RPCError
)
from telethon.sessions import StringSession
from config import API_ID, API_HASH

logger = logging.getLogger(__name__)


class TelethonManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._clients = {}       # account_id -> TelegramClient
            cls._instance._locks = {}          # account_id -> asyncio.Lock
        return cls._instance

    def _lock(self, account_id: str) -> asyncio.Lock:
        if account_id not in self._locks:
            self._locks[account_id] = asyncio.Lock()
        return self._locks[account_id]

    async def create_client(self, session_string: str) -> TelegramClient | None:
        """Create a fresh Telethon client from a session string and connect."""
        client = TelegramClient(StringSession(session_string), API_ID, API_HASH,
                                connection_retries=3)
        try:
            await client.connect()
            if await client.is_user_authorized():
                return client
            logger.warning("Session string not authorized")
            await client.disconnect()
            return None
        except Exception as e:
            logger.error(f"Failed to create client: {e}")
            return None

    async def get_client(self, account: dict) -> TelegramClient | None:
        """Return a connected, authorised client for the given account dict."""
        aid = str(account["_id"])
        async with self._lock(aid):
            if aid in self._clients:
                c = self._clients[aid]
                if c.is_connected():
                    try:
                        if await c.is_user_authorized():
                            return c
                    except AuthKeyUnregisteredError:
                        logger.warning(f"Auth key for {aid} unregistered, removing client")
                        del self._clients[aid]
                    except Exception:
                        pass
                # disconnected or stale — reconnect
                try:
                    await c.connect()
                    if await c.is_user_authorized():
                        return c
                except Exception:
                    pass
                # can't recover, remove and create fresh
                try:
                    await c.disconnect()
                except Exception:
                    pass
                if aid in self._clients:
                    del self._clients[aid]

            # Create fresh client
            client = await self.create_client(account["session_string"])
            if client:
                self._clients[aid] = client
            return client

    async def remove_client(self, account_id: str):
        """Disconnect and remove a client."""
        if account_id in self._clients:
            try:
                await self._clients[account_id].disconnect()
            except Exception:
                pass
            del self._clients[account_id]

    async def disconnect_all(self):
        for cid, client in list(self._clients.items()):
            try:
                await client.disconnect()
            except Exception:
                pass
        self._clients.clear()

    async def get_me(self, client: TelegramClient) -> dict | None:
        """Get user info from a connected client."""
        try:
            me = await client.get_me()
            if me:
                return {
                    "id": me.id,
                    "phone": getattr(me, "phone", "N/A"),
                    "username": me.username,
                    "first_name": me.first_name or "",
                    "last_name": me.last_name or "",
                }
        except Exception as e:
            logger.error(f"get_me error: {e}")
        return None
