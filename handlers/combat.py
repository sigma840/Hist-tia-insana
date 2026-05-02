import asyncio
import random

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config import GOLD_PER_KILL, RARITY_COLORS, RARITY_WEIGHTS
from database.db import (
    load_player, save_player, load_session, save_session,
    load_item, load_items, save_item, new_id
)
from models.schemas import Item
from systems.ai_narrator import narrate_combat_round, narrate_boss_phase
from systems.image_gen import generate_image


# ── Enemy tiers ───────────────────────────────────────────────

ENEMY_TIERS = [
    # (name_pool, hp_range, str_range, gold_range, xp_range, is_boss)
    (["Goblin Scout", "Bandit", "Wolf", "Skeleton", "Rat Swarm"],
     (20, 45), (6, 10), (8, 20), (15, 30), False),
    (["Orc Warrior", "Dark Knight", "Ghoul", "Troll", "Cultist"],
     (50, 90), (11, 16), (20, 45), (30, 55), False),
    (["Vampire", "Golem", "Wyvern", "Necromancer", "Shadow Demon"],
     (95, 160), (17, 24), (45, 90), (55, 100), False),
    (["Ancient Dragon", "Lich King", "Demon Lord", "Abyssal Titan", "Death Knight"],
     (180, 320), (25, 35), (90, 200), (100, 200), True),
]


def _pick_enemy(party_level: int) -> dict:
    """Pick an enemy appropriate for the party level, with a small chance of a boss."""
    boss_chance = min(0.08, 0.01 * party_level)  # max 8% boss chance
    if random.random() < boss_chance:
        tier = ENEMY_TIERS[3]
    else:
        # Weight lower tiers for low level, higher tiers for high level
        tier_idx = min(2, max(0, (party_level - 1) // 4))
        # Small chance to go one tier up
        if random.random() < 0.25 and tier_idx < 2:
            tier_idx += 1
        tier = ENEMY_TIERS[tier_idx]

    names, hp_r, str_r, gold_r, xp_r, is_boss = tier
    name = random.choice(names)
    hp   = random.randint(*hp_r)
    return {
        "name":     name,
        "hp":       hp,
        "max_hp":   hp,
        "strength": random.randint(*str_r),
        "gold":     random.randint(*gold_r),
        "xp":       random.randint(*xp_r),
        "phase":    1,
        "is_boss":  is_boss,
    }


def _hp_bar(hp: int, max_hp: int) -> str:
    pct    = max(0, hp / max_hp) if max_hp > 0 else 0
    filled = int(pct * 10)
    return "❤️" * filled + "🖤" * (10 - filled) + f" {hp}/{max_hp}"


def _combat_kb(sid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚔️ Attack",      callback_data=f"combat:{sid}:attack"),
         InlineKeyboardButton("🔮 Use Ability", callback_data=f"combat:{sid}:ability")],
        [InlineKeyboardButton("🎒 Use Item",    callback_data=f"combat:{sid}:item"),
         InlineKeyboardButton("🌑 Stealth",     callback_data=f"combat:{sid}:stealth")],
        [InlineKeyboardButton("🏃 Flee",        callback_data=f"combat:{sid}:flee")],
    ])


async def start_combat(update, ctx, session, players, data):
    """Initialise a combat encounter from narration data or generate a fitting enemy."""
    avg_level = sum(p.level for p in players) // max(len(players), 1)

    # Use AI-provided enemy if valid, otherwise generate one
    ai_name = data.get("enemy_name", "").strip()
    ai_hp   = int(data.get("enemy_hp", 0))
    ai_str  = int(data.get("enemy_strength", 0))

    if ai_name and ai_hp > 0 and ai_str > 0:
        enemy = {
            "name":     ai_name,
            "hp":       ai_hp,
            "max_hp":   ai_hp,
            "strength": ai_str,
            "gold":     random.randint(*GOLD_PER_KILL),
            "xp":       random.randint(20, 80),
            "phase":    1,
            "is_boss":  ai_hp >= 150,
        }
    else:
        enemy = _pick_enemy(avg_level)

    session.in_combat = True
    ctx.bot_data[f"enemy_{session.session_id}"] = enemy
    await save_session(session)

    img = await generate_image(f"{enemy['name']} fantasy monster dramatic battle scene")
    boss_tag = " 👑 *BOSS*" if enemy["is_boss"] else ""
    text = (
        f"⚔️ *{enemy['name']}*{boss_tag} appears!\n\n"
        f"{_hp_bar(enemy['hp'], enemy['max_hp'])}\n\n"
        f"_Prepare for battle!_"
    )
    kb = _combat_kb(session.session_id)
    if img:
        await update.effective_chat.send_photo(img, caption=text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.effective_chat.send_message(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)


async def cb_combat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts  = query.data.split(":")
    sid    = parts[1]
    action = parts[2]
    tid    = query.from_user.id

    session = await load_session(sid)
    player  = await load_player(tid)
    enemy   = ctx.bot_data.get(f"enemy_{sid}")

    if not session or not player or not enemy:
        return
    if tid not in session.players:
        return

    result_text = ""

    # ── Player action ─────────────────────────────────────────
    if action == "attack":
        weapon_bonus = 0
        if player.equipped_weapon:
            item = await load_item(player.equipped_weapon)
            if item:
                weapon_bonus = item.stat_bonus.get("strength", 0)
        dmg = max(1, player.strength + random.randint(-2, 4) + weapon_bonus)
        enemy["hp"] -= dmg
        result_text  = f"*{player.char_name}* deals *{dmg}* damage!"

    elif action == "stealth":
        if player.agility >= 14 or player.char_class in ["Rogue", "Archer", "Demon Hunter"]:
            dmg = player.strength * 2 + random.randint(0, 8)
            enemy["hp"] -= dmg
            result_text  = f"🌑 *{player.char_name}* strikes from shadows for *{dmg}* damage!"
        else:
            result_text = f"❌ *{player.char_name}* lacks the agility for a stealth strike!"

    elif action == "ability":
        dmg = player.magic + random.randint(4, 12)
        enemy["hp"] -= dmg
        result_text  = f"✨ *{player.char_name}* uses a class ability for *{dmg}* magic damage!"

    elif action == "item":
        if player.inventory:
            items = await load_items(player.inventory[:5])
            if items:
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton(f"{i.name} ({i.rarity})", callback_data=f"combatitem:{sid}:{i.id}")
                ] for i in items])
                await query.message.reply_text("🎒 Choose an item:", reply_markup=kb)
                return
        result_text = "🎒 No usable items!"

    elif action == "flee":
        chance = 30 + player.agility * 2
        if random.randint(1, 100) <= chance:
            session.in_combat = False
            await save_session(session)
            await query.edit_message_caption(
                caption=f"💨 *{player.char_name}* flees the battle!",
                parse_mode=ParseMode.MARKDOWN
            )
            # Return to turn loop
            await _resume_after_combat(update, ctx, session, players_fled=True)
            return
        else:
            dmg        = max(1, enemy["strength"])
            player.hp -= dmg
            await save_player(player)
            result_text = f"❌ Flee failed! *{player.char_name}* takes *{dmg}* damage!"

    ctx.bot_data[f"enemy_{sid}"] = enemy

    # ── Enemy counter-attack ──────────────────────────────────
    enemy_dmg  = max(1, enemy["strength"] + random.randint(-2, 3))
    player.hp -= enemy_dmg
    if player.hp < 0:
        player.hp = 0
    await save_player(player)

    # ── Boss phase check ──────────────────────────────────────
    if enemy["is_boss"]:
        for phase, threshold in {2: 0.5, 3: 0.25}.items():
            if (enemy["hp"] / enemy["max_hp"]) <= threshold and enemy.get("phase", 1) < phase:
                enemy["phase"] = phase
                ctx.bot_data[f"enemy_{sid}"] = enemy
                phase_narr, phase_data = await narrate_boss_phase(enemy["name"], phase, enemy["hp"])
                mult = phase_data.get("damage_multiplier", 1.2)
                enemy["strength"] = int(enemy["strength"] * mult)
                await update.effective_chat.send_message(
                    f"💀 *PHASE {phase}!*\n\n_{phase_narr}_",
                    parse_mode=ParseMode.MARKDOWN
                )

    # ── Narrate round ─────────────────────────────────────────
    narration = await narrate_combat_round(
        session, [player], enemy["name"], enemy["hp"], enemy["max_hp"],
        {player.char_name: action},
        {player.char_name: result_text, enemy["name"]: f"deals {enemy_dmg} dmg"}
    )

    # ── Check: player dead ────────────────────────────────────
    if player.hp <= 0:
        player.deaths         += 1
        player.current_session = None
        await save_player(player)
        if tid in session.players:
            session.players.remove(tid)
        await update.effective_chat.send_message(
            f"💀 *{player.char_name}* has fallen!\n\n_{narration}_",
            parse_mode=ParseMode.MARKDOWN
        )
        if not session.players:
            from handlers.session import end_session
            await end_session(update, ctx, session, "death")
        return

    # ── Check: enemy dead ─────────────────────────────────────
    if enemy["hp"] <= 0:
        session.in_combat = False
        player.xp   += enemy["xp"]
        player.gold += enemy["gold"]
        player.hp    = min(player.hp + 10, player.max_hp)  # small heal after fight
        await save_player(player)
        await save_session(session)

        loot_text = ""
        # Small chance to drop an item
        if random.random() < 0.35:
            rarity = random.choices(
                list(RARITY_WEIGHTS.keys()),
                weights=list(RARITY_WEIGHTS.values()), k=1
            )[0]
            loot_names = ["Worn Blade", "Shadow Cloak Fragment", "Cursed Coin", "Bone Charm",
                          "Vial of Blood", "Ancient Rune", "Enchanted Shard"]
            loot_item = Item(
                id=new_id(),
                name=random.choice(loot_names),
                description="Dropped by a defeated enemy.",
                rarity=rarity, item_type="artifact",
                stat_bonus={"strength": random.randint(0, 3), "luck": random.randint(0, 2)},
                owner_id=player.telegram_id,
                acquired_session=session.session_id
            )
            await save_item(loot_item)
            player.inventory.append(loot_item.id)
            await save_player(player)
            loot_text = f"\n🎁 Dropped: {RARITY_COLORS.get(rarity,'⬜')} *{loot_item.name}* ({rarity})"

        await update.effective_chat.send_message(
            f"🏆 *{enemy['name']} defeated!*\n\n_{narration}_\n\n"
            f"+{enemy['xp']} XP | +{enemy['gold']}g | ❤️ +10 HP{loot_text}",
            parse_mode=ParseMode.MARKDOWN
        )
        await _resume_after_combat(update, ctx, session)
        return

    # ── Update combat message ─────────────────────────────────
    enemy_bar  = _hp_bar(enemy["hp"], enemy["max_hp"])
    player_bar = _hp_bar(player.hp, player.max_hp)
    new_caption = (
        f"⚔️ *{enemy['name']}*\n{enemy_bar}\n\n"
        f"*{player.char_name}*\n{player_bar}\n\n"
        f"_{narration}_"
    )
    try:
        await query.edit_message_caption(
            caption=new_caption[:1020],
            reply_markup=_combat_kb(sid),
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception:
        await update.effective_chat.send_message(
            new_caption[:1020],
            reply_markup=_combat_kb(sid),
            parse_mode=ParseMode.MARKDOWN
        )


async def _resume_after_combat(update, ctx, session, players_fled: bool = False):
    """Return to the normal turn loop after combat ends."""
    from handlers.session import show_choices
    players = [p for p in [await load_player(t) for t in session.players] if p]
    if not players:
        return
    choices = (
        ["Catch your breath and look around", "Search the area for loot",
         "Press on before more enemies arrive", "Return to the road"]
        if not players_fled else
        ["Find a safe place to hide", "Keep running", "Circle back carefully", "Look for help"]
    )
    await show_choices(update, ctx, session, players, choices)
