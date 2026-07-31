import re
import random
import math

from telegram.helpers import escape_markdown


def esc(text) -> str:
    """Escape user-provided text for Telegram Markdown (v1)."""
    return escape_markdown(str(text), version=1)
    
def parse_timing(timing_str: str) -> tuple[int, int] | None:
    """Parse timing string like 'min-1s max-8s' or '1s 8s' into (min_sec, max_sec)."""
    t = timing_str.strip().lower()
    nums = list(map(int, re.findall(r'(\d+)', t)))
    if len(nums) >= 2:
        return nums[0], nums[1]
    if len(nums) == 1:
        return nums[0], nums[0]
    return None


def parse_mode_counts(counts_str: str) -> tuple[int, int, int] | None:
    """Parse '5,3,2' or '5 3 2' into (mode1, mode2, mode3)."""
    parts = re.split(r'[,; ]+', counts_str.strip())
    nums = [int(p) for p in parts if p.isdigit()]
    if len(nums) == 3:
        return nums[0], nums[1], nums[2]
    if len(nums) == 2:
        return nums[0], nums[1], 0
    if len(nums) == 1:
        return nums[0], 0, 0
    return None


def distribute_accounts(accounts: list, counts: tuple[int, int, int]):
    """Randomly distribute accounts into three modes. Returns list of (account, mode)."""
    c1, c2, c3 = counts
    total = c1 + c2 + c3
    if total > len(accounts):
        raise ValueError(f"Need {total} accounts but only {len(accounts)} available")

    shuffled = random.sample(accounts, total)
    result = []
    idx = 0
    for mode, cnt in [(1, c1), (2, c2), (3, c3)]:
        for _ in range(cnt):
            result.append((shuffled[idx], mode))
            idx += 1
    random.shuffle(result)  # shuffle so order is random
    return result


def parse_reaction_emojis(text: str) -> list[str]:
    """Extract emoji characters from text."""
    # Basic emoji pattern covering most common ones
    emoji_pattern = re.compile(
        "[\U0001F600-\U0001F64F"   # emoticons
        "\U0001F300-\U0001F5FF"   # symbols & pictographs
        "\U0001F680-\U0001F6FF"   # transport & map
        "\U0001F1E0-\U0001F1FF"   # flags
        "\U00002702-\U000027B0"   # dingbats
        "\U000024C2-\U0001F251"   # misc
        "\U0001F900-\U0001F9FF"   # supplemental symbols
        "\U0001FA00-\U0001FA6F"   # chess symbols
        "\U0001FA70-\U0001FAFF"   # symbols extended-A
        "\u2764\uFE0F"            # ❤️
        "\u2764"                  # ❤
        "\U0001F90D-\U0001F90F"   # recent additions
        "\U0001F970"              # 🥰
        "\u2600-\u27BF"           # misc symbols
        "]+", re.UNICODE)

    emojis = emoji_pattern.findall(text)
    # If no emoji found, treat each character as possible emoji
    if not emojis:
        emojis = [c for c in text if ord(c) > 127]
    return emojis if emojis else ["❤️"]


def split_into_batches(items: list, batch_size: int):
    """Yield successive batches from items."""
    for i in range(0, len(items), batch_size):
        yield items[i:i + batch_size]
