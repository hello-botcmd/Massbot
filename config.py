# ============================================================
#  Massbot configuration
#  EDIT ONLY: MONGO_URI (password + cluster host)
# ============================================================

# ── Bot Token (from @BotFather) ─────────────────────────────
BOT_TOKEN = "8881959713:AAFpjIXWuzEt3EwqDmn_bA0zHg6lMk7Au1o"

# ── MongoDB ─────────────────────────────────────────────────
# ⚠️  EDIT THIS: replace PASSWORD with your real Atlas password
#     (Settings → Database Access). Special chars (@ : / # ?)
#     must be percent-encoded. Also fix cluster0.mongodb.net
#     if your cluster host differs.
MONGO_URI = "mongodb+srv://quantumsoul120_db_user:Rv3nb9ChcyeDAxxr@cluster0.55zdpug.mongodb.net/?appName=Cluster0"
DB_NAME = "Mass"

# ── Telegram API credentials (my.telegram.org) ───────────────
API_ID = 22657083
API_HASH = "d6186691704bd901bdab275ceaab88f3"

# ── Owner & Admins ───────────────────────────────────────────
OWNER_ID = 8580367479
ADMIN_IDS = [8694029886,7684269512]

if OWNER_ID not in ADMIN_IDS:
    ADMIN_IDS.append(OWNER_ID)

# ── Operational constants ────────────────────────────────────
ONLINE_PING_INTERVAL = 30        # Mode 1 online ping (s)
MODE2_ONLINE_DURATION = 300     # Mode 2 online duration (s)
REACTION_GAP = 1
VIEW_GAP = 1
HEALTH_CHECK_INTERVAL = 60
