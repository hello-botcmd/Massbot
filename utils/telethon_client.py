import asyncio
import logging

from telethon import TelegramClient
from telethon.sessions import StringSession

from config import API_ID, API_HASH

logger = logging.getLogger(__name__)


class TelethonManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._clients = {}   # account_id -> persistent TelegramClient
            cls._instance._locks = {}     # account_id -> asyncio.Lock
        return cls._instance

    def _lock(self, account_id):
        if account_id not in self._locks:
            self._locks[account_id] = asyncio.Lock()
        return self._locks[account_id]

    async def create_client(self, session_string: str, timeout: float = 25.0):
        """Validate a session. Returns connected+authorized client or None."""
        client = TelegramClient(
            StringSession(session_string), API_ID, API_HASH,
            connection_retries=2, device_model="Massbot",
        )
        try:
            await asyncio.wait_for(client.connect(), timeout=timeout)
            if await client.is_user_authorized():
                return client
        except Exception as e:
            logger.warning("create_client error: %s", e)
        try:
            await client.disconnect()
        except Exception:
            pass
        return None

    async def get_fresh_client(self, session_string: str, timeout: float = 25.0):
        """One-shot client for single API calls. Caller MUST disconnect."""
        return await self.create_client(session_string, timeout)

    async def get_persistent_client(self, account_id: str, session_string: str):
        """Cached client kept connected — used by online-mode loops."""
        async with self._lock(account_id):
            client = self._clients.get(account_id)
            if client and client.is_connected():
                return client
            client = TelegramClient(
                StringSession(session_string), API_ID, API_HASH,
                connection_retries=5, device_model="Massbot",
            )
            try:
                await asyncio.wait_for(client.connect(), timeout=30)
                if await client.is_user_authorized():
                    self._clients[account_id] = client
                    return client
            except Exception as e:
                logger.warning("persistent connect failed %s: %s", account_id, e)
            try:
                await client.disconnect()
            except Exception:
                pass
            return None

    async def drop_persistent(self, account_id: str):
        async with self._lock(account_id):
            client = self._clients.pop(account_id, None)
            if client:
                try:
                    await client.disconnect()
                except Exception:
                    pass

    async def disconnect_all(self):
        for aid in list(self._clients):
            await self.drop_persistent(aid)
