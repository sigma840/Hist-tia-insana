from dataclasses import dataclass, field
from typing import Optional
import time


@dataclass
class Item:
    id: str
    name: str
    description: str
    rarity: str
    item_type: str
    stat_bonus: dict
    curse_effect: str = ""
    alive_personality: str = ""
    set_name: str = ""
    owner_id: Optional[int] = None
    equipped: bool = False
    market_price: Optional[int] = None
    auction_end: Optional[float] = None
    highest_bid: int = 0
    highest_bidder: Optional[int] = None
    acquired_session: Optional[str] = None


@dataclass
class Creature:
    id: str
    name: str
    description: str
    species: str
    combat_bonus: dict
    ability: str
    tamed_by: int
    loyalty: int = 50


@dataclass
class Memory:
    session_id: str
    summary: str
    turn: int
    timestamp: float = field(default_factory=time.time)


@dataclass
class Player:
    telegram_id: int
    username: str
    char_name: str
    char_class: str
    level: int = 1
    xp: int = 0
    xp_to_next: int = 100
    hp: int = 100
    max_hp: int = 100
    strength: int = 10
    magic: int = 10
    agility: int = 10
    luck: int = 10
    sanity: int = 100
    gold: int = 50
    karma: int = 0
    free_actions_left: int = 3
    perks: list = field(default_factory=list)
    inventory: list = field(default_factory=list)
    equipped_weapon: Optional[str] = None
    equipped_armor: Optional[str] = None
    companions: list = field(default_factory=list)
    memories: list = field(default_factory=list)
    faction_rep: dict = field(default_factory=lambda: {
        "Crown": 0, "Thieves Guild": 0, "Mage Order": 0, "Church of Light": 0
    })
    active_curses: list = field(default_factory=list)
    demon_contracts: list = field(default_factory=list)
    current_session: Optional[str] = None
    deaths: int = 0
    sessions_played: int = 0
    guild_id: Optional[str] = None


@dataclass
class DungeonRoom:
    room_id: int
    description: str
    room_type: str
    exits: list
    loot: list
    trap: Optional[str] = None
    enemy: Optional[str] = None
    visited: bool = False
    secret_found: bool = False


@dataclass
class Session:
    session_id: str
    host_id: int
    players: list
    turn: int = 0
    max_turns: int = 30
    is_active: bool = True
    current_narrative: str = ""
    current_image_url: str = ""
    history: list = field(default_factory=list)
    pending_actions: dict = field(default_factory=dict)
    in_combat: bool = False
    in_dungeon: bool = False
    dungeon: Optional[list] = None
    current_room: int = 0
    prophecy: str = ""
    day_night: str = "day"
    weather: str = "clear"
    started_at: float = field(default_factory=time.time)
    ended_at: Optional[float] = None
    end_reason: str = ""


@dataclass
class Guild:
    guild_id: str
    name: str
    members: list
    gold_vault: int = 0
    rank: int = 1
    missions_completed: int = 0
    active_mission: Optional[dict] = None


@dataclass
class MarketListing:
    listing_id: str
    seller_id: int
    item_id: str
    listing_type: str
    price: Optional[int] = None
    trade_for: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    auction_end: Optional[float] = None
    highest_bid: int = 0
    highest_bidder: Optional[int] = None
