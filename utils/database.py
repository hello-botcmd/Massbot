import logging
from datetime import datetime

from bson.objectid import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import DuplicateKeyError

from config import MONGO_URI, DB_NAME

logger = logging.getLogger(__name__)


class Database:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.client = None
            cls._instance.db = None
        return cls._instance

    async def connect(self):
        if self.db is not None:
            return
        self.client = AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        self.db = self.client[DB_NAME]
        await self.db.accounts.create_index("owner_uid")
        await self.db.accounts.create_index("tg_id")
        await self.db.accounts.create_index("phone")
        # Drop the legacy unique index that caused E11000 on re-adds
        try:
            await self.db.accounts.drop_index("session_string_1")
        except Exception:
            pass
        logger.info("MongoDB connected: %s", DB_NAME)

    async def add_account(self, owner_uid, tg_id, phone, session_string, name=""):
        """Dedupe by Telegram account ID.
        Returns {"ok": bool, "refreshed": bool, "exists": bool}"""
        # Same Telegram account already stored?
        existing = await self.db.accounts.find_one({"tg_id": tg_id})
        if existing is None:
            # Legacy docs (pre-tg_id) — fall back to phone
            existing = await self.db.accounts.find_one(
                {"owner_uid": owner_uid, "phone": phone})

        if existing:
            if existing.get("owner_uid") != owner_uid:
                return {"ok": False, "exists": True}   # used by another admin
            # Same owner re-adds → refresh session + reactivate
            await self.db.accounts.update_one(
                {"_id": existing["_id"]},
                {"$set": {
                    "tg_id": tg_id,
                    "phone": phone,
                    "name": name,
                    "session_string": session_string,
                    "status": "active",
                    "current_mode": 0,
                    "last_seen_hidden": existing.get("last_seen_hidden", False),
                    "in_use": False,
                    "added_at": datetime.utcnow(),
                }}
            )
            return {"ok": True, "refreshed": True}

        doc = {
            "owner_uid": owner_uid,
            "tg_id": tg_id,
            "phone": phone,
            "name": name,
            "session_string": session_string,
            "status": "active",
            "current_mode": 0,
            "last_seen_hidden": False,
            "in_use": False,
            "added_at": datetime.utcnow(),
        }
        try:
            await self.db.accounts.insert_one(doc)
            return {"ok": True}
        except DuplicateKeyError:
            return {"ok": False, "exists": True}

    async def get_accounts(self, owner_uid):
        return [a async for a in self.db.accounts.find({"owner_uid": owner_uid})]

    async def get_active_accounts(self, owner_uid):
        return [a async for a in self.db.accounts.find({"owner_uid": owner_uid, "status": "active"})]

    async def get_all_accounts(self):
        return [a async for a in self.db.accounts.find({})]

    async def update_account(self, account_id, fields):
        oid = account_id if isinstance(account_id, ObjectId) else ObjectId(account_id)
        await self.db.accounts.update_one({"_id": oid}, {"$set": fields})

    async def get_global_counts(self, owner_uid):
        accounts = await self.get_accounts(owner_uid)
        total = len(accounts)
        active = sum(1 for a in accounts if a.get("status") == "active")
        disconnected = sum(1 for a in accounts if a.get("status") == "disconnected")
        in_use = sum(1 for a in accounts if a.get("in_use"))
        idle = sum(1 for a in accounts if a.get("status") == "active" and not a.get("in_use"))
        return {
            "total": total, "active": active, "disconnected": disconnected,
            "in_use": in_use, "idle": idle,
        }
