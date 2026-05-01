import aiosqlite
import json
import uuid
from typing import Optional
from models.schemas import Player, Session, Item, Creature, Guild, MarketListing, Memory

DB_PATH = "chronicler.db"


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS players (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            data TEXT
        );
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            data TEXT
        );
        CREATE TABLE IF NOT EXISTS items (
            item_id TEXT PRIMARY KEY,
            data TEXT
        );
        CREATE TABLE IF NOT EXISTS creatures (
            creature_id TEXT PRIMARY KEY,
            data TEXT
        );
        CREATE TABLE IF NOT EXISTS guilds (
            guild_id TEXT PRIMARY KEY,
            data TEXT
        );
        CREATE TABLE IF NOT EXISTS market (
            listing_id TEXT PRIMARY KEY,
            data TEXT
        );
        CREATE TABLE IF NOT EXISTS world_state (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """)
        await db.commit()


# ── Helpers ───────────────────────────────────────────────────

def _serial(obj):
    return json.dumps(obj.__dict__ if hasattr(obj, "__dict__") else obj)


def parse_obj(raw, cls):
    d = json.loads(raw)
    return cls(**d)


# ── Players ───────────────────────────────────────────────────

async def save_player(p: Player):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO players VALUES (?,?,?)",
            (p.telegram_id, p.username, _serial(p))
        )
        await db.commit()


async def load_player(tid: int) -> Optional[Player]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT data FROM players WHERE telegram_id=?", (tid,)) as c:
            row = await c.fetchone()
            return parse_obj(row[0], Player) if row else None


async def all_players() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT data FROM players") as c:
            rows = await c.fetchall()
            return [parse_obj(r[0], Player) for r in rows]


# ── Sessions ──────────────────────────────────────────────────

async def save_session(s: Session):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO sessions VALUES (?,?)",
            (s.session_id, _serial(s))
        )
        await db.commit()


async def load_session(sid: str) -> Optional[Session]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT data FROM sessions WHERE session_id=?", (sid,)) as c:
            row = await c.fetchone()
            return parse_obj(row[0], Session) if row else None


async def active_sessions() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT data FROM sessions") as c:
            rows = await c.fetchall()
            all_s = [parse_obj(r[0], Session) for r in rows]
            return [s for s in all_s if s.is_active]


# ── Items ─────────────────────────────────────────────────────

async def save_item(item: Item):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO items VALUES (?,?)",
            (item.id, _serial(item))
        )
        await db.commit()


async def load_item(item_id: str) -> Optional[Item]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT data FROM items WHERE item_id=?", (item_id,)) as c:
            row = await c.fetchone()
            return parse_obj(row[0], Item) if row else None


async def load_items(ids: list) -> list:
    result = []
    for x in ids:
        item = await load_item(x)
        if item:
            result.append(item)
    return result


# ── Creatures ─────────────────────────────────────────────────

async def save_creature(c: Creature):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO creatures VALUES (?,?)",
            (c.id, _serial(c))
        )
        await db.commit()


async def load_creature(cid: str) -> Optional[Creature]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT data FROM creatures WHERE creature_id=?", (cid,)) as c:
            row = await c.fetchone()
            return parse_obj(row[0], Creature) if row else None


# ── Guilds ────────────────────────────────────────────────────

async def save_guild(g: Guild):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO guilds VALUES (?,?)",
            (g.guild_id, _serial(g))
        )
        await db.commit()


async def load_guild(gid: str) -> Optional[Guild]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT data FROM guilds WHERE guild_id=?", (gid,)) as c:
            row = await c.fetchone()
            return parse_obj(row[0], Guild) if row else None


async def find_guild_by_member(tid: int) -> Optional[Guild]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT data FROM guilds") as c:
            rows = await c.fetchall()
            for r in rows:
                g = parse_obj(r[0], Guild)
                if tid in g.members:
                    return g
    return None


# ── Market ────────────────────────────────────────────────────

async def save_listing(lst: MarketListing):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO market VALUES (?,?)",
            (lst.listing_id, _serial(lst))
        )
        await db.commit()


async def load_listing(lid: str) -> Optional[MarketListing]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT data FROM market WHERE listing_id=?", (lid,)) as c:
            row = await c.fetchone()
            return parse_obj(row[0], MarketListing) if row else None


async def all_listings() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT data FROM market") as c:
            rows = await c.fetchall()
            return [parse_obj(r[0], MarketListing) for r in rows]


async def delete_listing(lid: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM market WHERE listing_id=?", (lid,))
        await db.commit()


# ── World State ───────────────────────────────────────────────

async def set_world(key: str, value):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO world_state VALUES (?,?)",
            (key, json.dumps(value))
        )
        await db.commit()


async def get_world(key: str, default=None):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM world_state WHERE key=?", (key,)) as c:
            row = await c.fetchone()
            return json.loads(row[0]) if row else default


def new_id():
    return str(uuid.uuid4())[:8]
