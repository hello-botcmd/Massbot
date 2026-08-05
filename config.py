import os

# ── Bot Token (from @BotFather) ──
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# ── MongoDB ──
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "mass_bot")

# ── Telegram API Credentials (from my.telegram.org) ──
API_ID = int(os.getenv("API_ID", "0"))          # ← put your API ID here, e.g. 123456
API_HASH = os.getenv("API_HASH", "YOUR_API_HASH_HERE")  # ← put your API hash here

# ── Owner & Admins: put your Telegram user IDs here directly ──
OWNER_ID = int(os.getenv("OWNER_ID", "0"))      # ← e.g. 123456789
ADMIN_IDS = [
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()
]                                               # ← e.g. [111111111, 222222222]

# Owner is always allowed even if not listed
if not ADMIN_IDS:
    ADMIN_IDS = [OWNER_ID]
if OWNER_ID not in ADMIN_IDS:
    ADMIN_IDS.append(OWNER_ID)

# ── Operational constants ──
ONLINE_PING_INTERVAL = 30        # Mode 1 online ping (s)
MODE2_ONLINE_DURATION = 120      # Mode 2 online duration (s) = 2 min
VIEW_GAP = 1                     # min gap between view boosts (s)
REACTION_GAP = 1                 # min gap between reactions (s)
HEALTH_CHECK_INTERVAL = 60       # account health check loop (s)
