from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu_kb():
    """Main menu keyboard."""
    buttons = [
        [
            InlineKeyboardButton("➕ Add Account", callback_data="add_account"),
            InlineKeyboardButton("🔗 Join", callback_data="join"),
        ],
        [
            InlineKeyboardButton("🎭 Mode", callback_data="mode"),
            InlineKeyboardButton("📊 Total Account", callback_data="total_account"),
        ],
        [
            InlineKeyboardButton("❤️ Reaction", callback_data="reaction"),
            InlineKeyboardButton("👁️ Views", callback_data="views"),
        ],
        [
            InlineKeyboardButton("🌐 All Accounts Online", callback_data="all_online"),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


def add_type_kb():
    """Single / Bulk add sub-menu."""
    buttons = [
        [
            InlineKeyboardButton("1️⃣ Single Add", callback_data="single_add"),
            InlineKeyboardButton("📦 Bulk Add", callback_data="bulk_add"),
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(buttons)


def cancel_kb():
    """Inline cancel button."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_op")]
    ])
