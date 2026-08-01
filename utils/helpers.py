import re

from telegram.helpers import escape_markdown

from config import OWNER_ID, ADMIN_IDS


def is_authorized(user_id: int) -> bool:
    """Owner + admins. Owner is always allowed even if not listed."""
    return user_id == OWNER_ID or user_id in ADMIN_IDS


def esc(text) -> str:
    """Escape user content for Telegram Markdown v1."""
    return escape_markdown(str(text), version=1)


TIMING_RE = re.compile(
    r"(?:min-)?(\d+(?:\.\d+)?)s?(?:\s+(?:max-)?(\d+(?:\.\d+)?)s?)?", re.I
)


def parse_timing(text):
    """'min-1s max-8s' or '2 6' → (min_s, max_s) or None."""
    m = TIMING_RE.search(text.strip())
    if not m:
        return None
    a = float(m.group(1))
    b = float(m.group(2)) if m.group(2) else a
    if a <= 0 or b < a:
        return None
    return (a, b)


EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]+")


def parse_reaction_emojis(text):
    """Extract unique emoji sequences from a string like '❤️🥰👍'."""
    out = []
    for chunk in EMOJI_RE.findall(text):
        e = chunk.rstrip("\uFE0F")
        if e and e not in out:
            out.append(e)
    return out
