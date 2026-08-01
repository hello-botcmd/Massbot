import logging
from datetime import datetime

from bson.objectid import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

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
        await self.db.accounts.create_index("phone")
        logger.info("MongoDB connected: %s", DB_NAME)

    async def add_account(self, owner_uid, phone, session_string, name=""):
        doc = {
            "owner_uid": owner_uid,
            "phone": phone,
            "name": name,
            "session_string": session_string,
            "status": "active",          # active | disconnected
            "current_mode": 0,
            "in_use": False,
            "added_at": datetime.utcnow(),
        }
        await self.db.accounts.update_one(
            {"owner_uid": owner_uid, "phone": phone},
            {"$set": doc},
            upsert=True,
        )

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
