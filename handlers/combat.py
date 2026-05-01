import asyncio
import random

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config import GOLD_PER_KILL, RARITY_COLORS
from database.db import load_player, save_player, load_session, save_session, load_item, load_items
from systems.ai_narrator import narrate_combat_round, narrate_boss_phase
from systems.image_gen import generate_image


def _hp_bar(hp: int, max_hp: int) -> str:
    pct    = hp / max_hp if max_hp > 0 else 0
    filled = int(pct * 10)
    bar    = "❤️" * filled + "🖤" * (10 - filled)
    return f"{bar} {hp}/{max_hp} HP"


def _combat_keyboard(sid: str, players: list) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚔️ Attack",          callback_data=f"combat:{sid}:attack"),
         InlineKeyboardButton("🔮 Ability",          callback_data=f"combat:{sid}:ability")],
        [InlineKeyboardButton("🎒 Use Item",         callback_data=f"combat:{sid}:item"),
         InlineKeyboardButton("🌑 Stealth Kill",     callback_data=f"combat:{sid}:stealth")],
        [InlineKeyboardButton("🏃 Cinematic Escape", callback_data=f"combat:{sid}:escape")]
    ])


async def start_combat(update, ctx, session, players, data):
    enemy = {
        "name":     data.get("enemy_name", "Unknown Beast"),
        "hp":       data.get("enemy_hp", 50),
        "max_hp":   data.get("enemy_hp", 50),
        "strength": data.get("enemy_strength", 10),
        "phase":    1,
    }
    session.in_combat = True
    ctx.bot_data[f"enemy_{session.session_id}"]        = enemy
    ctx.bot_data[f"combat_round_{session.session_id}"] = 0
    await save_session(session)

    img      = await generate_image(f"{enemy['name']} medieval fantasy monster dramatic")
    hp_bar   = _hp_bar(enemy["hp"], enemy["max_hp"])
    msg      = f"⚔️ *{enemy['name']}* appears!\n\n{hp_bar}\n\n_Choose your action:_"
    kb       = _combat_keyboard(session.session_id, players)

    if img:
        await update.effective_chat.send_photo(img, caption=msg, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.effective_chat.send_message(msg, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)


async def cb_combat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, sid, action = query.data.split(":")
    tid     = query.from_user.id
    session = await load_session(sid)
    player  = await load_player(tid)
    if not session or not player:
        return

    enemy = ctx.bot_data.get(f"enemy_{sid}", {})
    if not enemy:
        return

    if action == "escape":
        await cinematic_escape(update, ctx, session, player, enemy)
        return

    result_text = ""
    if action == "attack":
        weapon_bonus = 0
        if player.equipped_weapon:
            item = await load_item(player.equipped_weapon)
            if item:
                weapon_bonus = item.stat_bonus.get("strength", 0)
        dmg = max(1, player.strength + random.randint(-3, 5) + weapon_bonus)
        enemy["hp"] -= dmg
        result_text  = f"{player.char_name} deals *{dmg}* damage!"

    elif action == "stealth":
        if player.agility >= 14 or player.char_class in ["Rogue", "Archer"]:
            dmg = player.strength * 2 + random.randint(0, 10)
            enemy["hp"] -= dmg
            result_text  = f"🌑 {player.char_name} strikes from shadows for *{dmg}* damage!"
        else:
            result_text = f"❌ {player.char_name} lacks the agility for a stealth kill!"

    elif action == "ability":
        dmg = player.magic + random.randint(5, 15)
        enemy["hp"] -= dmg
        result_text  = f"✨ {player.char_name} uses a class ability for *{dmg}* damage!"

    elif action == "item":
        if player.inventory:
            items = await load_items(player.inventory[:5])
            kb    = InlineKeyboardMarkup([[
                InlineKeyboardButton(f"{i.name} ({i.rarity})", callback_data=f"useitem:{sid}:{i.id}")
            ] for i in items])
            await query.message.reply_text("🎒 Choose an item to use:", reply_markup=kb)
            return

    ctx.bot_data[f"enemy_{sid}"] = enemy

    # Enemy counter-attack
    enemy_dmg  = max(1, enemy["strength"] + random.randint(-2, 4))
    player.hp -= enemy_dmg
    await save_player(player)

    narration = await narrate_combat_round(
        session, [player], enemy["name"], enemy["hp"], enemy["max_hp"],
        {player.char_name: action},
        {player.char_name: result_text, enemy["name"]: f"deals {enemy_dmg} dmg"}
    )

    # Boss phase check
    for phase, threshold in {2: 0.5, 3: 0.25}.items():
        if enemy["hp"] / enemy["max_hp"] <= threshold and enemy.get("phase", 1) < phase:
            enemy["phase"] = phase
            ctx.bot_data[f"enemy_{sid}"] = enemy
            phase_narr, phase_data = await narrate_boss_phase(enemy["name"], phase, enemy["hp"])
            enemy["strength"] = int(enemy["strength"] * phase_data.get("damage_multiplier", 1.2))
            await update.effective_chat.send_message(
                f"💀 *PHASE {phase}!*\n\n{phase_narr}", parse_mode=ParseMode.MARKDOWN
            )

    # Player death
    if player.hp <= 0:
        player.hp             = 0
        player.deaths        += 1
        player.current_session = None
        await save_player(player)
        session.players.remove(tid)
        await update.effective_chat.send_message(
            f"💀 *{player.char_name}* has fallen in battle!\n_Your legend is remembered..._",
            parse_mode=ParseMode.MARKDOWN
        )
        if not session.players:
            from handlers.session import end_session
            await end_session(update, ctx, session, "death")
            return

    # Enemy death
    if enemy["hp"] <= 0:
        session.in_combat = False
        xp_reward   = random.randint(20, 60)
        gold_reward = random.randint(*GOLD_PER_KILL)
        player.xp   += xp_reward
        player.gold += gold_reward
        await save_player(player)
        await update.effective_chat.send_message(
            f"🏆 *{enemy['name']} defeated!*\n\n_{narration}_\n\n+{xp_reward} XP | +{gold_reward}g",
            parse_mode=ParseMode.MARKDOWN
        )
        await save_session(session)
        players = [p for p in [await load_player(t) for t in session.players] if p]
        from handlers.session import show_choices
        await show_choices(update, ctx, session, players, [
            "Continue exploring",
            "Search the area for loot",
            "Rest and tend to wounds",
            "Press deeper into danger"
        ])
        return

    hp_bar     = _hp_bar(enemy["hp"], enemy["max_hp"])
    player_bar = _hp_bar(player.hp, player.max_hp)
    await query.edit_message_caption(
        f"⚔️ *{enemy['name']}*\n{hp_bar}\n\n"
        f"*{player.char_name}*\n{player_bar}\n\n_{narration}_",
        reply_markup=_combat_keyboard(sid, [player]),
        parse_mode=ParseMode.MARKDOWN
    )


async def cinematic_escape(update, ctx, session, player, enemy):
    sid      = session.session_id
    sequence = ["🏃 Run!", "⬅️ Dodge Left!", "🪨 Jump!", "🔀 Weave!"]
    random.shuffle(sequence)
    success  = True

    for step in sequence[:3]:
        await update.effective_chat.send_message(
            f"🎬 *CINEMATIC ESCAPE!*\nPress *{step}* in 10 seconds!",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(step,    callback_data=f"escape_step:{sid}:success"),
                InlineKeyboardButton("❌ Wrong", callback_data=f"escape_step:{sid}:fail")
            ]]),
            parse_mode=ParseMode.MARKDOWN
        )
        await asyncio.sleep(10)
        if random.randint(1, 20) <= (10 - player.agility // 3):
            success = False
            break

    if success:
        session.in_combat = False
        await save_session(session)
        await update.effective_chat.send_message(
            f"💨 *{player.char_name}* escapes in a burst of adrenaline!",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        dmg        = enemy["strength"] * 2
        player.hp -= dmg
        await save_player(player)
        await update.effective_chat.send_message(
            f"💥 *Escape failed!* {player.char_name} takes *{dmg}* damage fleeing!",
            parse_mode=ParseMode.MARKDOWN
        )
