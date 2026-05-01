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
