from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Account", callback_data="add_acc"),
         InlineKeyboardButton("🔗 Join", callback_data="join")],
        [InlineKeyboardButton("🎭 Mode", callback_data="mode"),
         InlineKeyboardButton("📊 Total Account", callback_data="total_acc")],
        [InlineKeyboardButton("❤️ Reaction", callback_data="react"),
         InlineKeyboardButton("👁️ Views", callback_data="views")],
        [InlineKeyboardButton("🌐 All Accounts Online", callback_data="all_online")],
    ])


def add_type_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Single", callback_data="add_single"),
         InlineKeyboardButton("📦 Bulk", callback_data="add_bulk")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")],
    ])


def cancel_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_op")],
    ])


def mode_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1️⃣ Mode 1 — Always Online", callback_data="mode_sel:1"),
         InlineKeyboardButton("2️⃣ Mode 2 — Online 2 min", callback_data="mode_sel:2")],
        [InlineKeyboardButton("3️⃣ Mode 3 — Hide Last Seen", callback_data="mode_sel:3")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")],
    ])
