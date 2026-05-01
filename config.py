import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GEMINI_API_KEY  = os.environ["GEMINI_API_KEY"]

POLLINATIONS_URL = "https://image.pollinations.ai/prompt/{prompt}?width=800&height=450&nologo=true"

# Session settings
MAX_TURNS_PER_SESSION   = 30
FREE_ACTIONS_PER_SESSION = 3
TURN_TIMEOUT_SECONDS    = 120

# Dungeon
DUNGEON_MIN_ROOMS = 5
DUNGEON_MAX_ROOMS = 12

# Economy
GOLD_PER_GOOD_ACTION   = (5, 20)
GOLD_PER_KILL          = (10, 50)
AUCTION_DURATION_SECONDS = 300

# Sanity
SANITY_MAX                     = 100
SANITY_HALLUCINATION_THRESHOLD = 30

# Karma thresholds
KARMA_HERO    =  100
KARMA_VILLAIN = -100

# Item rarity weights (higher = more common)
RARITY_WEIGHTS = {
    "Common":    50,
    "Uncommon":  25,
    "Rare":      12,
    "Epic":       7,
    "Legendary":  3,
    "Cursed":     2,
    "Alive":      1,
}

RARITY_COLORS = {
    "Common":    "⬜",
    "Uncommon":  "🟩",
    "Rare":      "🟦",
    "Epic":      "🟪",
    "Legendary": "🟨",
    "Cursed":    "🟥",
    "Alive":     "🌀",
}

# Classes with base stats: hp, strength, magic, agility, luck, sanity
CLASSES = {
    "Warrior":      {"hp": 120, "strength": 18, "magic":  2, "agility":  8, "luck":  5, "sanity":  90, "emoji": "⚔️",  "desc": "Unstoppable force on the battlefield."},
    "Mage":         {"hp":  70, "strength":  4, "magic": 20, "agility":  9, "luck":  7, "sanity":  85, "emoji": "🔮",  "desc": "Master of arcane forces."},
    "Archer":       {"hp":  90, "strength": 10, "magic":  4, "agility": 18, "luck": 10, "sanity":  88, "emoji": "🏹",  "desc": "Swift, precise, deadly from afar."},
    "Paladin":      {"hp": 110, "strength": 14, "magic": 10, "agility":  7, "luck":  8, "sanity": 100, "emoji": "🛡️",  "desc": "Holy warrior, protector of the innocent."},
    "Druid":        {"hp":  85, "strength":  8, "magic": 15, "agility": 11, "luck": 12, "sanity":  95, "emoji": "🌿",  "desc": "Shapeshifter bonded with nature."},
    "Rogue":        {"hp":  80, "strength": 12, "magic":  3, "agility": 20, "luck": 15, "sanity":  82, "emoji": "🗡️",  "desc": "Strikes from the shadows."},
    "Necromancer":  {"hp":  75, "strength":  5, "magic": 19, "agility":  7, "luck":  6, "sanity":  60, "emoji": "💀",  "desc": "Commands death itself."},
    "Bard":         {"hp":  82, "strength":  7, "magic": 12, "agility": 14, "luck": 18, "sanity":  92, "emoji": "🎶",  "desc": "Inspires allies, confounds enemies."},
    "Shaman":       {"hp":  88, "strength":  9, "magic": 16, "agility": 10, "luck":  9, "sanity":  78, "emoji": "🔱",  "desc": "Speaks with spirits of the world."},
    "Berserker":    {"hp": 130, "strength": 20, "magic":  1, "agility": 12, "luck":  4, "sanity":  55, "emoji": "🪓",  "desc": "Rage is the only god."},
    "Demon Hunter": {"hp":  95, "strength": 15, "magic":  8, "agility": 16, "luck":  7, "sanity":  70, "emoji": "😈",  "desc": "Fights darkness with darker arts."},
    "Oracle":       {"hp":  65, "strength":  3, "magic": 18, "agility":  8, "luck": 20, "sanity":  75, "emoji": "🔯",  "desc": "Sees threads of fate, bends probability."},
}

# Factions
FACTIONS = ["Crown", "Thieves Guild", "Mage Order", "Church of Light"]

# Day/Night cycle (real hours UTC)
DAYTIME_HOURS = range(6, 20)

# World events scheduler interval (minutes)
WORLD_EVENT_INTERVAL_MINUTES = 60
