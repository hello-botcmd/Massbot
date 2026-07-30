from datetime import datetime
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URI, DB_NAME


class Database:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, '_initialised'):
            self.client = None
            self.db = None
            self._initialised = False

    async def connect(self):
        self.client = AsyncIOMotorClient(MONGO_URI)
        self.db = self.client[DB_NAME]
        # Ensure indexes
        await self.db.accounts.create_index("user_id")
        await self.db.accounts.create_index("phone")
        self._initialised = True

    async def close(self):
        if self.client:
            self.client.close()

    # ── Account CRUD ──

    async def add_account(self, user_id: int, phone: str, session_string: str) -> ObjectId:
        col = self.db.accounts
        existing = await col.find_one({"user_id": user_id, "phone": phone})
        if existing:
            await col.update_one(
                {"_id": existing["_id"]},
                {"$set": {
                    "session_string": session_string,
                    "status": "active",
                    "updated_at": datetime.utcnow()
                }}
            )
            return existing["_id"]
        result = await col.insert_one({
            "user_id": user_id,
            "phone": phone,
            "session_string": session_string,
            "added_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "status": "active",
            "current_mode": None,
            "is_online": False,
            "last_seen_hidden": False,
            "online_task_running": False,
            "in_use": False,
        })
        return result.inserted_id

    async def get_account(self, account_id: ObjectId) -> dict:
        return await self.db.accounts.find_one({"_id": account_id})

    async def get_user_accounts(self, user_id: int) -> list:
        cursor = self.db.accounts.find({"user_id": user_id})
        return await cursor.to_list(length=None)

    async def get_active_accounts(self, user_id: int) -> list:
        cursor = self.db.accounts.find({"user_id": user_id, "status": "active"})
        return await cursor.to_list(length=None)

    async def get_all_accounts(self) -> list:
        cursor = self.db.accounts.find({})
        return await cursor.to_list(length=None)

    async def get_all_active_accounts(self) -> list:
        cursor = self.db.accounts.find({"status": "active"})
        return await cursor.to_list(length=None)

    async def get_account_counts(self, user_id: int = None) -> dict:
        col = self.db.accounts
        if user_id:
            total = await col.count_documents({"user_id": user_id})
            active = await col.count_documents({"user_id": user_id, "status": "active"})
        else:
            total = await col.count_documents({})
            active = await col.count_documents({"status": "active"})
        return {"total": total, "active": active}

    async def get_global_counts(self) -> dict:
        """Counts across all users (for owner view)."""
        col = self.db.accounts
        total = await col.count_documents({})
        active = await col.count_documents({"status": "active"})
        return {"total": total, "active": active}

    async def update_account(self, account_id: ObjectId, **kwargs):
        kwargs["updated_at"] = datetime.utcnow()
        await self.db.accounts.update_one(
            {"_id": account_id},
            {"$set": kwargs}
        )

    async def delete_account(self, account_id: ObjectId):
        await self.db.accounts.delete_one({"_id": account_id})

    async def delete_user_accounts(self, user_id: int):
        await self.db.accounts.delete_many({"user_id": user_id})
