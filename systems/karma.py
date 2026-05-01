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
