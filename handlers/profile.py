from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config import RARITY_COLORS, CLASSES
from database.db import (
    load_player, save_player,
    load_item, save_item, load_items,
    load_creature, save_creature,
    new_id
)
from models.schemas import Creature
from systems.ai_narrator import forge_item, attempt_taming
from systems.image_gen import generate_image


async def cmd_profile(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    p   = await load_player(tid)
    if not p:
        await update.message.reply_text("No character found. Use /start")
        return
    from systems.karma import get_karma_label
    karma_label, karma_desc = get_karma_label(p.karma)
    faction_str = "\n".join([f"  {f}: {v:+d}" for f, v in p.faction_rep.items() if v != 0]) or "  None yet"
    perks_str   = "\n".join([f"  ✨ {pk}" for pk in p.perks]) or "  None yet"
    await update.message.reply_text(
        f"⚔️ *{p.char_name}* — {CLASSES[p.char_class]['emoji']} {p.char_class}\n"
        f"Level {p.level} | XP: {p.xp}/{p.xp_to_next}\n\n"
        f"❤️ HP: {p.hp}/{p.max_hp} | 🧠 Sanity: {p.sanity}/100\n"
        f"⚔️ STR: {p.strength} | 🔮 MAG: {p.magic} | 🏃 AGI: {p.agility} | 🍀 LCK: {p.luck}\n\n"
        f"💰 Gold: {p.gold}g | ☠️ Deaths: {p.deaths}\n"
        f"{karma_label} | Karma: {p.karma}\n_{karma_desc}_\n\n"
        f"*Factions:*\n{faction_str}\n\n"
        f"*Perks:*\n{perks_str}",
        parse_mode=ParseMode.MARKDOWN
    )


async def cmd_inventory(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    p   = await load_player(tid)
    if not p or not p.inventory:
        await update.message.reply_text("🎒 Your inventory is empty.")
        return
    items   = await load_items(p.inventory)
    buttons = []
    for item in items:
        emoji    = RARITY_COLORS.get(item.rarity, "⬜")
        equipped = " ✅" if item.id in [p.equipped_weapon, p.equipped_armor] else ""
        buttons.append([InlineKeyboardButton(
            f"{emoji} {item.name} ({item.rarity}){equipped}",
            callback_data=f"inv:view:{item.id}"
        )])
    await update.message.reply_text(
        f"🎒 *Inventory* ({len(items)} items)",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.MARKDOWN
    )


async def cb_inventory(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    parts  = query.data.split(":")
    action = parts[1]
    tid    = query.from_user.id
    p      = await load_player(tid)

    if action == "view":
        item = await load_item(parts[2])
        if not item:
            return
        emoji      = RARITY_COLORS.get(item.rarity, "⬜")
        bonuses    = " | ".join([f"{k.upper()}+{v}" for k, v in item.stat_bonus.items() if v])
        curse_text = f"\n☠️ *Curse:* {item.curse_effect}"       if item.curse_effect    else ""
        alive_text = f"\n🌀 *Personality:* {item.alive_personality}" if item.alive_personality else ""
        await query.edit_message_text(
            f"{emoji} *{item.name}* ({item.rarity})\n_{item.description}_\n\n"
            f"Type: {item.item_type} | Bonuses: {bonuses or 'none'}{curse_text}{alive_text}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚔️ Equip",         callback_data=f"inv:equip:{item.id}"),
                 InlineKeyboardButton("🔨 Use in Forge",  callback_data=f"forge:pick1:{item.id}")],
                [InlineKeyboardButton("🛒 Sell",          callback_data=f"sell:pick:{item.id}"),
                 InlineKeyboardButton("↩️ Back",          callback_data="inv:back")]
            ]),
            parse_mode=ParseMode.MARKDOWN
        )

    elif action == "equip":
        item = await load_item(parts[2])
        if not item or not p:
            return
        if item.item_type == "weapon":
            p.equipped_weapon = item.id
        else:
            p.equipped_armor = item.id
        await save_player(p)
        await query.answer(f"✅ {item.name} equipped!", show_alert=True)

    elif action == "back":
        await cmd_inventory(update, ctx)


async def cmd_forge(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    p   = await load_player(tid)
    if not p or len(p.inventory) < 2:
        await update.message.reply_text("🔨 You need at least 2 items to forge.")
        return
    items   = await load_items(p.inventory)
    buttons = [[InlineKeyboardButton(
        f"{RARITY_COLORS.get(i.rarity,'⬜')} {i.name}",
        callback_data=f"forge:pick1:{i.id}"
    )] for i in items]
    await update.message.reply_text(
        "🔨 *The Forge* — Select first item:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.MARKDOWN
    )


async def cb_forge(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    parts  = query.data.split(":")
    action = parts[1]
    tid    = query.from_user.id
    p      = await load_player(tid)

    if action == "pick1":
        ctx.user_data["forge_item1"] = parts[2]
        items   = await load_items([i for i in p.inventory if i != parts[2]])
        buttons = [[InlineKeyboardButton(
            f"{RARITY_COLORS.get(i.rarity,'⬜')} {i.name}",
            callback_data=f"forge:pick2:{i.id}"
        )] for i in items]
        await query.edit_message_text(
            "🔨 Select second item:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    elif action == "pick2":
        item1_id = ctx.user_data.pop("forge_item1", None)
        item2_id = parts[2]
        if not item1_id:
            return
        item1 = await load_item(item1_id)
        item2 = await load_item(item2_id)
        await query.edit_message_text("🔥 *The forge roars...*", parse_mode=ParseMode.MARKDOWN)
        new_item = await forge_item(item1, item2, p)
        await save_item(new_item)
        p.inventory.remove(item1_id)
        p.inventory.remove(item2_id)
        p.inventory.append(new_item.id)
        await save_player(p)
        emoji = RARITY_COLORS.get(new_item.rarity, "⬜")
        img   = await generate_image(f"{new_item.name} medieval fantasy weapon artifact glowing")
        text  = (
            f"⚒️ *Forged:* {emoji} *{new_item.name}* ({new_item.rarity})\n"
            f"_{new_item.description}_\n\n"
            f"Bonuses: {' | '.join([f'{k.upper()}+{v}' for k, v in new_item.stat_bonus.items() if v]) or 'none'}"
        )
        if img:
            await update.effective_chat.send_photo(img, caption=text, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.effective_chat.send_message(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_companions(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    p   = await load_player(tid)
    if not p or not p.companions:
        await update.message.reply_text("🐉 You have no tamed companions.")
        return
    text = "🐉 *Your Companions:*\n\n"
    for cid in p.companions:
        c = await load_creature(cid)
        if c:
            text += f"• *{c.name}* ({c.species}) — Loyalty: {c.loyalty}/100\n_{c.ability}_\n\n"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cb_tame(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    if parts[1] == "ignore":
        await query.edit_message_text("You let the creature go.")
        return
    # tame:{creature_name}:{species}:{player_tid}:{sid}
    _, creature_name, species, player_tid, sid = parts
    player = await load_player(int(player_tid))
    if not player:
        return
    success, narration, data = await attempt_taming(player, creature_name, species)
    if success:
        c = Creature(
            id=new_id(), name=creature_name,
            description=narration[:100], species=species,
            combat_bonus=data.get("combat_bonus", {}),
            ability=data.get("ability", ""),
            tamed_by=int(player_tid), loyalty=60
        )
        await save_creature(c)
        player.companions.append(c.id)
        await save_player(player)
    await query.edit_message_text(
        f"{'✅' if success else '❌'} {narration}",
        parse_mode=ParseMode.MARKDOWN
    )
