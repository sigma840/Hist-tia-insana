import random

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config import RARITY_COLORS, RARITY_WEIGHTS
from database.db import load_player, save_player, load_session, save_session, new_id, save_item
from models.schemas import Item
from systems.ai_narrator import generate_dungeon
from systems.image_gen import generate_image

ROOM_ICONS = {
    "entry":     "🚪",
    "corridor":  "🌑",
    "treasure":  "💰",
    "trap":      "⚠️",
    "boss":      "💀",
    "exit":      "🔆",
    "secret":    "🔍",
}


async def enter_dungeon(update, ctx, session, players):
    avg_level  = sum(p.level for p in players) // len(players)
    narrative  = session.current_narrative[:200]
    rooms_data = await generate_dungeon(avg_level, narrative)
    if not rooms_data:
        return

    session.dungeon      = rooms_data
    session.current_room = 0
    session.in_dungeon   = True
    await save_session(session)
    await show_dungeon_room(update, ctx, session, players, 0)


async def show_dungeon_room(update, ctx, session, players, room_idx: int):
    dungeon = session.dungeon
    if not dungeon or room_idx >= len(dungeon):
        session.in_dungeon = False
        await save_session(session)
        await update.effective_chat.send_message("🚪 You emerge from the dungeon!", parse_mode=ParseMode.MARKDOWN)
        return

    room      = dungeon[room_idx]
    room_type = room.get("room_type", "corridor")
    desc      = room.get("description", "A dark room.")
    exits     = room.get("exits", [])
    trap      = room.get("trap")
    loot_hint = room.get("loot_hint", "")
    icon      = ROOM_ICONS.get(room_type, "🏚️")

    img = await generate_image(f"dungeon {room_type} room, dark fantasy, {desc[:60]}")

    # Trap trigger (only on first visit)
    trap_text = ""
    if trap and not room.get("visited"):
        trap_text = f"\n\n⚠️ *TRAP:* ||{trap}||"
        for p in players:
            dmg    = random.randint(5, 15)
            p.hp  -= dmg
            await save_player(p)
        trap_text += "\nAll players take trap damage!"

    # Loot (treasure rooms, first visit only)
    loot_text = ""
    if room_type == "treasure" and loot_hint and not room.get("visited"):
        rarity    = random.choices(list(RARITY_WEIGHTS.keys()), weights=list(RARITY_WEIGHTS.values()), k=1)[0]
        loot_text = f"\n\n💎 *Loot found:* {RARITY_COLORS[rarity]} _{loot_hint}_ ({rarity})"

    dungeon[room_idx]["visited"] = True
    session.dungeon      = dungeon
    session.current_room = room_idx
    await save_session(session)

    text    = f"{icon} *Room {room_idx + 1}* — _{room_type.title()}_\n\n{desc}{trap_text}{loot_text}"
    buttons = []

    for exit_id in exits:
        if exit_id < len(dungeon):
            exit_room = dungeon[exit_id]
            exit_icon = ROOM_ICONS.get(exit_room.get("room_type", "corridor"), "🌑")
            buttons.append([InlineKeyboardButton(
                f"{exit_icon} Go to Room {exit_id + 1}",
                callback_data=f"dungeon:move:{session.session_id}:{exit_id}"
            )])

    if room.get("secret") and not room.get("secret_found"):
        buttons.append([InlineKeyboardButton(
            "🔍 Search for Secrets",
            callback_data=f"dungeon:secret:{session.session_id}:{room_idx}"
        )])

    buttons.append([InlineKeyboardButton(
        "🚪 Exit Dungeon",
        callback_data=f"dungeon:exit:{session.session_id}"
    )])

    kb = InlineKeyboardMarkup(buttons)
    if img:
        await update.effective_chat.send_photo(img, caption=text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.effective_chat.send_message(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)


async def cb_dungeon(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    parts   = query.data.split(":")
    action  = parts[1]
    sid     = parts[2]
    session = await load_session(sid)
    if not session:
        return
    players = [p for p in [await load_player(t) for t in session.players] if p]

    if action == "move":
        room_idx = int(parts[3])
        await show_dungeon_room(update, ctx, session, players, room_idx)

    elif action == "exit":
        session.in_dungeon = False
        await save_session(session)
        await query.edit_message_caption("🚪 You leave the dungeon behind...")
        from handlers.session import show_choices
        await show_choices(update, ctx, session, players, [
            "Continue the main quest",
            "Rest at a tavern",
            "Explore the area",
            "Head to the market"
        ])

    elif action == "secret":
        room_idx = int(parts[3])
        player   = await load_player(query.from_user.id)
        if not player:
            return
        chance = 30 + player.luck * 2
        if random.randint(1, 100) <= chance:
            session.dungeon[room_idx]["secret_found"] = True
            await save_session(session)
            await query.message.reply_text(
                "🔍 *Secret found!* ||A hidden passage reveals itself, along with something valuable...||",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await query.message.reply_text("🔍 You search carefully but find nothing hidden here.")
