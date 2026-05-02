# ============================================================
# systems/image_gen.py
# ============================================================
# Cria o ficheiro: systems/image_gen.py

import asyncio
import aiohttp
from urllib.parse import quote
from config import POLLINATIONS_URL

_MAX_RETRIES = 5
_RETRY_DELAY = 4  # seconds between retries


async def generate_image(prompt: str):
    """Fetch image from Pollinations, retrying up to 5 times if not ready yet."""
    encoded = quote(f"medieval fantasy {prompt}, dark atmospheric, oil painting, highly detailed")
    url     = POLLINATIONS_URL.format(prompt=encoded)

    for attempt in range(_MAX_RETRIES):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
                    if r.status == 200:
                        return url
                    # 503 / 429 = server busy, wait and retry
                    if r.status in (429, 503) and attempt < _MAX_RETRIES - 1:
                        await asyncio.sleep(_RETRY_DELAY * (attempt + 1))
                        continue
        except asyncio.TimeoutError:
            if attempt < _MAX_RETRIES - 1:
                await asyncio.sleep(_RETRY_DELAY)
                continue
        except Exception:
            pass
        break

    # Last resort: return the URL anyway — Telegram will try to load it
    return url


# ============================================================
# systems/karma.py
# ============================================================
# Cria o ficheiro: systems/karma.py

from config import KARMA_HERO, KARMA_VILLAIN
from models.schemas import Player

KARMA_LABELS = {
    range(80, 200):    ("🌟 Legendary Hero",  "NPCs bow, guards protect you, merchants offer discounts."),
    range(40, 80):     ("😇 Hero",             "NPCs are friendly and trusting."),
    range(-40, 40):    ("⚖️ Neutral",          "The world regards you with indifference."),
    range(-80, -40):   ("😈 Villain",          "NPCs fear you, guards are hostile."),
    range(-200, -80):  ("💀 Notorious Evil",   "Wanted on sight. Bounty on your head."),
}


def get_karma_label(karma: int) -> tuple:
    for r, (label, desc) in KARMA_LABELS.items():
        if karma in r:
            return label, desc
    return "⚖️ Neutral", ""


async def apply_karma_effects(player: Player, delta: int):
    player.karma = max(-200, min(200, player.karma + delta))
    if delta > 0:
        player.faction_rep["Church of Light"] = player.faction_rep.get("Church of Light", 0) + max(0, delta // 3)
    elif delta < 0:
        player.faction_rep["Thieves Guild"] = player.faction_rep.get("Thieves Guild", 0) + abs(delta) // 3


# ============================================================
# systems/sanity.py
# ============================================================
# Cria o ficheiro: systems/sanity.py

from config import SANITY_MAX, SANITY_HALLUCINATION_THRESHOLD
from models.schemas import Player
import random

HALLUCINATIONS = [
    "The walls breathe. Something watches from the shadows.",
    "Your companions' faces blur — are they who they claim to be?",
    "A voice whispers your deepest fear. You cannot tell if it is real.",
    "The torchlight dims and a child's laughter echoes from nowhere.",
    "For a moment, the enemy's face is someone you loved.",
]


async def apply_sanity_effects(player: Player, delta: int, update):
    from telegram.constants import ParseMode
    player.sanity = max(0, min(SANITY_MAX, player.sanity + delta))
    if delta < 0 and player.sanity < SANITY_HALLUCINATION_THRESHOLD:
        hallucination = random.choice(HALLUCINATIONS)
        await update.effective_chat.send_message(
            f"🌀 *{player.char_name}'s mind fractures:* ||{hallucination}||",
            parse_mode=ParseMode.MARKDOWN
        )
        if player.sanity < 10:
            player.agility = max(1, player.agility - 1)
            player.luck    = max(1, player.luck - 1)
    return None

