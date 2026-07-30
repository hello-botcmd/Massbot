import os

# ── Bot Token (from @BotFather) ──
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# ── MongoDB ──
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "telegram_account_bot")

# ── Telegram API Credentials (from my.telegram.org) ──
API_ID = int(os.getenv("API_ID", "0"))       # Replace with your API ID
API_HASH = os.getenv("API_HASH", "YOUR_API_HASH_HERE")

# ── Owner & Admins ──
OWNER_ID = int(os.getenv("OWNER_ID", "0"))           # Your Telegram user ID
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(","))) if os.getenv("ADMIN_IDS") else [OWNER_ID]

# ── Operational Constants ──
ONLINE_PING_INTERVAL = 30        # seconds between online status pings (Mode 1)
MODE2_ONLINE_DURATION = 120      # seconds to stay online in Mode 2 (2 minutes)
VIEW_GAP = 1                     # seconds between each view
REACTION_GAP = 1                 # seconds between each reaction
