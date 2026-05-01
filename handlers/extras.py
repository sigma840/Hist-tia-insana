import random
import uuid

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config import FACTIONS, RARITY_COLORS
from database.db import (
    load_player, save_player,
    load_session,
    load_item, save_item,
    get_world, set_world,
    new_id
)
from models.schemas import Item
from systems.image_gen import generate_image


# ── /prophecy ─────────────────────────────────────────────────

async def cmd_prophecy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    p   = await load_player(tid)
    if not p or not p.current_session:
        await update.message.reply_text("Join an active session to receive a prophecy.")
        return
    session = await load_session(p.current_session)
    if session and session.prophecy:
        await update.message.reply_text(
            f"🔮 *Session Prophecy:*\n\n||{session.prophecy}||",
            parse_mode=ParseMode.MARKDOWN
        )


# ── /memories ─────────────────────────────────────────────────

async def cmd_memories(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    p   = await load_player(tid)
    if not p or not p.memories:
        await update.message.reply_text("📜 No memories recorded yet.")
        return
    text = "📜 *Your Memories:*\n\n"
    for m in p.memories[-10:]:
        text += f"• _{m['summary']}_\n"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ── /factions ─────────────────────────────────────────────────

async def cmd_factions(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    p   = await load_player(tid)
    if not p:
        return
    lines = []
    for f in FACTIONS:
        rep = p.faction_rep.get(f, 0)
        if   rep >= 80:  status = "🌟 Champion"
        elif rep >= 40:  status = "😇 Ally"
        elif rep >= 0:   status = "⚖️ Neutral"
        elif rep >= -40: status = "😠 Distrusted"
        else:            status = "💀 Enemy"
        lines.append(f"*{f}*: {status} ({rep:+d})")
    await update.message.reply_text(
        "⚜️ *Faction Reputation:*\n\n" + "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN
    )


# ── /shop (NPC) ───────────────────────────────────────────────

NPC_SHOP_ITEMS = [
    {"name": "Health Potion",  "type": "consumable", "rarity": "Common",   "price": 30,  "stat_bonus": {"hp": 30},    "desc": "Restores 30 HP."},
    {"name": "Mana Crystal",   "type": "consumable", "rarity": "Uncommon", "price": 50,  "stat_bonus": {"magic": 5},  "desc": "Boosts magic temporarily."},
    {"name": "Lucky Charm",    "type": "artifact",   "rarity": "Rare",     "price": 120, "stat_bonus": {"luck": 8},   "desc": "Fortune favors the bold."},
    {"name": "Shadow Cloak",   "type": "armor",      "rarity": "Rare",     "price": 200, "stat_bonus": {"agility": 6},"desc": "Woven from night itself."},
    {"name": "Iron Ration",    "type": "consumable", "rarity": "Common",   "price": 15,  "stat_bonus": {"hp": 10},    "desc": "Restores a little HP."},
    {"name": "Runic Scroll",   "type": "consumable", "rarity": "Epic",     "price": 300, "stat_bonus": {"magic": 12}, "desc": "Ancient power, one use."},
]


async def cmd_shop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    p = await load_player(update.effective_user.id)
    if not p:
        return
    buttons = [[InlineKeyboardButton(
        f"{RARITY_COLORS.get(i['rarity'],'⬜')} {i['name']} — {i['price']}g",
        callback_data=f"shop:buy:{idx}"
    )] for idx, i in enumerate(NPC_SHOP_ITEMS)]
    await update.message.reply_text(
        f"🛖 *NPC Shop* | Your gold: *{p.gold}g*",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.MARKDOWN
    )


async def cb_shop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query     = update.callback_query
    await query.answer()
    idx       = int(query.data.split(":")[2])
    shop_item = NPC_SHOP_ITEMS[idx]
    p         = await load_player(query.from_user.id)
    if not p:
        return
    if p.gold < shop_item["price"]:
        await query.answer("❌ Not enough gold!", show_alert=True)
        return
    p.gold -= shop_item["price"]
    item = Item(
        id=new_id(), name=shop_item["name"], description=shop_item["desc"],
        rarity=shop_item["rarity"], item_type=shop_item["type"],
        stat_bonus=shop_item["stat_bonus"], owner_id=p.telegram_id
    )
    await save_item(item)
    p.inventory.append(item.id)
    await save_player(p)
    await query.edit_message_text(
        f"✅ Purchased *{item.name}* for *{shop_item['price']}g*!\nGold remaining: {p.gold}g",
        parse_mode=ParseMode.MARKDOWN
    )


# ── /build ────────────────────────────────────────────────────

async def cmd_build(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tid    = update.effective_user.id
    p      = await load_player(tid)
    if not p:
        return
    builds     = await get_world(f"builds:{tid}", {})
    structures = builds.get("structures", [])
    struct_list = "\n".join([f"• {s}" for s in structures]) or "_None yet_"
    await update.message.reply_text(
        f"🏗️ *Your Holdings*\n\n{struct_list}\n\nGold: {p.gold}g",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏚️ Build Hut (50g)",        callback_data="build:hut:50"),
             InlineKeyboardButton("🏰 Build Fort (300g)",      callback_data="build:fort:300")],
            [InlineKeyboardButton("⚗️ Build Alchemist (150g)", callback_data="build:alchemist:150"),
             InlineKeyboardButton("🔨 Build Smithy (200g)",    callback_data="build:smithy:200")]
        ]),
        parse_mode=ParseMode.MARKDOWN
    )


async def cb_build(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query     = update.callback_query
    await query.answer()
    _, structure, cost_str = query.data.split(":")
    cost = int(cost_str)
    tid  = query.from_user.id
    p    = await load_player(tid)
    if not p:
        return
    if p.gold < cost:
        await query.answer("❌ Not enough gold!", show_alert=True)
        return
    p.gold -= cost
    await save_player(p)
    builds = await get_world(f"builds:{tid}", {"structures": []})
    builds["structures"].append(structure.title())
    await set_world(f"builds:{tid}", builds)
    await query.edit_message_text(
        f"🏗️ *{structure.title()}* constructed! Gold remaining: {p.gold}g",
        parse_mode=ParseMode.MARKDOWN
    )
