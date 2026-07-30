from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu_kb():
    buttons = [
        [
            InlineKeyboardButton("➕ Add Account", callback_data="add_acc"),
            InlineKeyboardButton("🔗 Join", callback_data="join"),
        ],
        [
            InlineKeyboardButton("🎭 Mode", callback_data="mode"),
            InlineKeyboardButton("📊 Total Account", callback_data="total_acc"),
        ],
        [
            InlineKeyboardButton("❤️ Reaction", callback_data="react"),
            InlineKeyboardButton("👁️ Views", callback_data="views"),
        ],
        [
            InlineKeyboardButton("🌐 All Accounts Online", callback_data="all_online"),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


def add_type_kb():
    buttons = [
        [
            InlineKeyboardButton("1️⃣ Single Add", callback_data="add_acc:single"),
            InlineKeyboardButton("📦 Bulk Add", callback_data="add_acc:bulk"),
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(buttons)


def cancel_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_op")]
    ])
