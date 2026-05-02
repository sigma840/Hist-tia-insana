import asyncio
import time
import random
import uuid

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config import (
    CLASSES, MAX_TURNS_PER_SESSION, FREE_ACTIONS_PER_SESSION,
    DAYTIME_HOURS, RARITY_WEIGHTS, RARITY_COLORS
)
from models.schemas import Player, Session, Item
from database.db import (
    load_player, save_player, load_session, save_session,
    load_item, save_item, load_items, new_id
)
from systems.ai_narrator import (
    narrate_turn, generate_prophecy,
    alive_item_message, generate_session_summary
)
from systems.image_gen import generate_image
from systems.karma import apply_karma_effects
from systems.sanity import apply_sanity_effects

# Per-session lock to prevent race conditions
_session_locks: dict = {}

CAPTION_LIMIT   = 950   # Telegram max is 1024, leave buffer
NARRATIVE_LIMIT = 3500  # Max chars for text-only messages


def _get_lock(sid: str) -> asyncio.Lock:
    if sid not in _session_locks:
        _session_locks[sid] = asyncio.Lock()
    return _session_locks[sid]


def _roll_rarity() -> str:
    return random.choices(list(RARITY_WEIGHTS.keys()), weights=list(RARITY_WEIGHTS.values()), k=1)[0]


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit - 3] + "..."


# ── /start ────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tid      = update.effective_user.id
    existing = await load_player(tid)
    if existing:
        await update.message.reply_text(
            f"⚔️ Welcome back, *{existing.char_name}* the {existing.char_class}!\n"
            f"Level {existing.level} | {existing.gold}g | Karma: {existing.karma}\n\n"
            f"Use /help to see all commands.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    buttons, row = [], []
    for i, (cls_name, stats) in enumerate(CLASSES.items()):
        row.append(InlineKeyboardButton(
            f"{stats['emoji']} {cls_name}",
            callback_data=f"pickclass:{cls_name}"
        ))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    await update.message.reply_text(
        "⚔️ *Welcome to CHRONICLER*\n\n"
        "_A dark realm awaits. Choose your class, adventurer:_",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.MARKDOWN
    )


# ── /help ─────────────────────────────────────────────────────

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚔️ *CHRONICLER — Commands*\n\n"
        "*Adventure*\n"
        "/newsession — Start a new adventure\n"
        "/joinsession \\[ID\\] — Join a friend's session\n"
        "/endsession — End the current session\n"
        "/prophecy — See the session prophecy\n\n"
        "*Character*\n"
        "/profile — View your stats\n"
        "/inventory — View your items\n"
        "/forge — Combine two items\n"
        "/companions — View tamed creatures\n"
        "/memories — View past memories\n"
        "/factions — View faction reputation\n\n"
        "*Economy*\n"
        "/shop — Buy items from NPC shop\n"
        "/market — Player marketplace\n"
        "/sell — List an item for sale\n"
        "/build — Construct buildings\n\n"
        "*Social*\n"
        "/guild — Guild management\n"
        "/ranking — Global leaderboard\n\n"
        "_During a session, use the buttons to act or type a Free Action\\._",
        parse_mode=ParseMode.MARKDOWN
    )


# ── /newsession ───────────────────────────────────────────────

async def cmd_new_session(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tid    = update.effective_user.id
    player = await load_player(tid)
    if not player:
        await update.message.reply_text("⚠️ Create a character first with /start")
        return
    if player.current_session:
        await update.message.reply_text("⚠️ You're already in a session. Use /endsession first.")
        return

    sid       = str(uuid.uuid4())[:8].upper()
    now       = time.time()
    hour      = int(time.strftime("%H", time.gmtime(now)))
    day_night = "day" if hour in DAYTIME_HOURS else "night"
    weathers  = (["clear", "stormy", "foggy", "blizzard", "scorching"]
                 if day_night == "day" else ["clear", "moonlit", "stormy", "eerie fog"])
    prophecy  = await generate_prophecy([player])

    session = Session(
        session_id=sid, host_id=tid, players=[tid],
        max_turns=MAX_TURNS_PER_SESSION,
        day_night=day_night, weather=random.choice(weathers),
        prophecy=prophecy
    )
    player.current_session  = sid
    player.free_actions_left = FREE_ACTIONS_PER_SESSION
    await save_session(session)
    await save_player(player)

    await update.message.reply_text(
        f"🏰 *Session {sid} created!*\n\n"
        f"{'☀️ Day' if day_night == 'day' else '🌙 Night'} | 🌤 *Weather:* {session.weather.title()}\n"
        f"🔮 *Prophecy:* ||{prophecy}||\n\n"
        f"Others can join with: `/joinsession {sid}`\n\n"
        f"_Press Begin when ready\\._",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⚔️ Begin Adventure", callback_data=f"beginadv:{sid}")
        ]])
    )


async def cb_begin_adventure(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    sid     = query.data.split(":")[1]
    session = await load_session(sid)
    if not session:
        return
    players = [p for p in [await load_player(tid) for tid in session.players] if p]
    await query.edit_message_text("⏳ *The narrator stirs...*", parse_mode=ParseMode.MARKDOWN)
    await run_turn(update, ctx, session, players, {str(p.telegram_id): "start adventure" for p in players})


# ── /joinsession ──────────────────────────────────────────────

async def cmd_join_session(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tid  = update.effective_user.id
    args = ctx.args
    if not args:
        await update.message.reply_text("Usage: /joinsession SESSION_ID")
        return
    sid     = args[0].upper()
    session = await load_session(sid)
    if not session or not session.is_active:
        await update.message.reply_text("❌ Session not found or already ended.")
        return
    player = await load_player(tid)
    if not player:
        await update.message.reply_text("❌ Create a character first with /start")
        return
    if tid in session.players:
        await update.message.reply_text("You're already in this session!")
        return
    session.players.append(tid)
    player.current_session = sid
    await save_session(session)
    await save_player(player)
    await update.message.reply_text(
        f"⚔️ *{player.char_name}* joined session *{sid}*!\n\n"
        f"_{_truncate(session.current_narrative, 300)}_",
        parse_mode=ParseMode.MARKDOWN
    )


# ── /endsession ───────────────────────────────────────────────

async def cmd_end_session(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tid    = update.effective_user.id
    player = await load_player(tid)
    if not player or not player.current_session:
        await update.message.reply_text("You're not in a session.")
        return
    session = await load_session(player.current_session)
    if session and session.host_id != tid:
        await update.message.reply_text("Only the session host can end it.")
        return
    await end_session(update, ctx, session, "command")


async def end_session(update, ctx, session: Session, reason: str):
    session.is_active  = False
    session.ended_at   = time.time()
    session.end_reason = reason

    players = [p for p in [await load_player(tid) for tid in session.players] if p]
    for p in players:
        p.current_session = None
        p.sessions_played += 1
        await save_player(p)

    summary = await generate_session_summary(session, players)
    img     = await generate_image(summary.get("image_prompt", "medieval fantasy farewell scene"))
    await save_session(session)

    text = (
        f"📜 *Session {session.session_id} Ended* — _{reason}_\n\n"
        f"*{summary.get('title', 'The adventure concludes')}*\n\n"
        f"{_truncate(summary.get('summary', ''), 400)}\n\n"
        f"✨ *Highlight:* {summary.get('highlight', '')}"
    )
    if img:
        await update.effective_chat.send_photo(
            img, caption=_truncate(text, CAPTION_LIMIT), parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.effective_chat.send_message(text, parse_mode=ParseMode.MARKDOWN)

    _session_locks.pop(session.session_id, None)


# ── Core turn engine ──────────────────────────────────────────

async def run_turn(update, ctx, session: Session, players: list, actions: dict):
    from handlers.combat  import start_combat
    from handlers.dungeon import enter_dungeon

    async with _get_lock(session.session_id):
        # Reset pending actions at start of new turn
        session.pending_actions = {}

        result    = await narrate_turn(session, players, actions)
        narrative = result["narrative"]
        choices   = result["choices"]
        data      = result["data"]

        for p in players:
            pid = str(p.telegram_id)
            p.gold += data.get("gold_earned", {}).get(pid, 0)

            xp_gain = data.get("xp_earned", {}).get(pid, 0)
            if xp_gain:
                await apply_xp(p, xp_gain, update)

            san_delta = data.get("sanity_changes", {}).get(pid, 0)
            if san_delta:
                await apply_sanity_effects(p, san_delta, update)

            karma_delta = data.get("karma_changes", {}).get(pid, 0)
            if karma_delta:
                await apply_karma_effects(p, karma_delta)

            for fc in data.get("faction_changes", {}).get(pid, {}).items():
                p.faction_rep[fc[0]] = p.faction_rep.get(fc[0], 0) + fc[1]

            for lost in data.get("items_lost", []):
                if str(lost.get("player_id")) == pid:
                    for iid in p.inventory[:]:
                        item = await load_item(iid)
                        if item and item.name == lost["item_name"]:
                            p.inventory.remove(iid)
                            if p.equipped_weapon == iid:
                                p.equipped_weapon = None
                            break

            for found in data.get("items_found", []):
                if str(found.get("player_id")) == pid:
                    rarity = found.get("rarity", _roll_rarity())
                    item   = Item(
                        id=new_id(), name=found["name"],
                        description=found.get("description", ""),
                        rarity=rarity, item_type=found.get("type", "weapon"),
                        stat_bonus=found.get("stat_bonus", {}),
                        owner_id=p.telegram_id,
                        acquired_session=session.session_id
                    )
                    await save_item(item)
                    p.inventory.append(item.id)
                    emoji = RARITY_COLORS.get(rarity, "⬜")
                    await update.effective_chat.send_message(
                        f"🎁 *{p.char_name}* found: {emoji} *{item.name}* ({rarity})\n_{item.description}_",
                        parse_mode=ParseMode.MARKDOWN
                    )

            await save_player(p)

        session.history.append({"role": "assistant", "content": narrative[:500]})
        session.current_narrative = narrative
        session.turn += 1

        img_url = await generate_image(data.get("image_prompt", "medieval fantasy scene"))
        session.current_image_url = img_url or ""

        if session.turn >= session.max_turns:
            await update.effective_chat.send_message(
                "⏳ *The sands of time run out...*", parse_mode=ParseMode.MARKDOWN
            )
            await end_session(update, ctx, session, "timeout")
            return

        await save_session(session)

        # Send narrative — split into image + text to avoid caption limit
        short_caption = f"📜 *Turn {session.turn}*"
        if img_url:
            await update.effective_chat.send_photo(img_url, caption=short_caption, parse_mode=ParseMode.MARKDOWN)
            await update.effective_chat.send_message(
                _truncate(narrative, NARRATIVE_LIMIT), parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.effective_chat.send_message(
                f"📜 *Turn {session.turn}*\n\n{_truncate(narrative, NARRATIVE_LIMIT)}",
                parse_mode=ParseMode.MARKDOWN
            )

        # Alive item messages
        for p in players:
            if p.equipped_weapon:
                item = await load_item(p.equipped_weapon)
                if item and item.rarity == "Alive" and item.alive_personality and random.random() < 0.4:
                    msg = await alive_item_message(item, p, narrative[:200])
                    await update.effective_chat.send_message(
                        f"🌀 *{item.name}* whispers to {p.char_name}: _{msg}_",
                        parse_mode=ParseMode.MARKDOWN
                    )

        if data.get("combat_triggered"):
            await start_combat(update, ctx, session, players, data)
            return

        if data.get("dungeon_triggered") and not session.in_dungeon:
            await enter_dungeon(update, ctx, session, players)
            return

        tame = data.get("taming_opportunity", {})
        if tame.get("creature_name") and tame.get("player_id"):
            tame_player = next((p for p in players if p.telegram_id == tame["player_id"]), None)
            if tame_player:
                await update.effective_chat.send_message(
                    f"🐉 A wild *{tame['creature_name']}* appears! {tame_player.char_name}, attempt to tame it?",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🐾 Attempt Taming", callback_data=f"tame:{tame['creature_name']}:{tame['creature_species']}:{tame_player.telegram_id}:{session.session_id}"),
                        InlineKeyboardButton("⚔️ Ignore", callback_data="tame:ignore")
                    ]]),
                    parse_mode=ParseMode.MARKDOWN
                )

        if choices:
            await show_choices(update, ctx, session, players, choices)


async def show_choices(update, ctx, session: Session, players: list, choices: list):
    # Ensure fresh pending_actions
    session.pending_actions = {}
    await save_session(session)

    ctx.bot_data[f"choices_{session.session_id}"] = choices

    buttons = [
        [InlineKeyboardButton(f"{i+1}. {_truncate(c, 50)}", callback_data=f"choice:{session.session_id}:{i}")]
        for i, c in enumerate(choices)
    ]
    buttons.append([InlineKeyboardButton("✍️ Free Action", callback_data=f"freeact:{session.session_id}")])

    total   = len(session.players)
    waiting = total - len(session.pending_actions)
    await update.effective_chat.send_message(
        f"⚔️ *What do you do?* (Waiting for {waiting}/{total} player(s))",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.MARKDOWN
    )


async def cb_choice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("✅ Action registered!")
    _, sid, idx = query.data.split(":")
    tid = query.from_user.id
    idx = int(idx)

    session = await load_session(sid)
    player  = await load_player(tid)
    if not session or not player or tid not in session.players:
        return

    # Ignore if this player already acted this turn
    if str(tid) in session.pending_actions:
        await query.answer("You already chose an action this turn!", show_alert=True)
        return

    choices = ctx.bot_data.get(f"choices_{sid}", [])
    if idx < len(choices):
        chosen = choices[idx]
        session.pending_actions[str(tid)] = chosen
        session.history.append({"role": "user", "content": f"{player.char_name}: {chosen}"})

    await save_session(session)

    waiting = len(session.players) - len(session.pending_actions)
    if waiting > 0:
        await query.edit_message_text(
            f"✅ *{player.char_name}* chose: _{_truncate(choices[idx], 80)}_\n\n"
            f"⏳ Waiting for {waiting} more player(s)...",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await query.edit_message_text(
            f"✅ All players have acted! Starting next turn...",
            parse_mode=ParseMode.MARKDOWN
        )
        players = [p for p in [await load_player(t) for t in session.players] if p]
        await run_turn(update, ctx, session, players, session.pending_actions)


async def cb_free_action(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    sid    = query.data.split(":")[1]
    tid    = query.from_user.id
    player = await load_player(tid)
    if not player:
        return
    if player.free_actions_left <= 0:
        await query.answer("❌ No free actions left this session!", show_alert=True)
        return

    # Ignore if already acted
    session = await load_session(sid)
    if session and str(tid) in session.pending_actions:
        await query.answer("You already chose an action this turn!", show_alert=True)
        return

    ctx.user_data["freeact_session"]  = sid
    ctx.user_data["awaiting_freeact"] = True
    await query.message.reply_text(
        f"✍️ *Free Action* ({player.free_actions_left} remaining)\nDescribe your action:",
        parse_mode=ParseMode.MARKDOWN
    )


async def handle_free_action_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.user_data.get("awaiting_freeact"):
        return
    tid    = update.effective_user.id
    sid    = ctx.user_data.pop("freeact_session")
    ctx.user_data.pop("awaiting_freeact")
    action  = update.message.text.strip()
    player  = await load_player(tid)
    session = await load_session(sid)
    if not player or not session:
        return
    player.free_actions_left -= 1
    session.pending_actions[str(tid)] = action
    session.history.append({"role": "user", "content": f"{player.char_name}: {action}"})
    await save_player(player)
    await save_session(session)
    await update.message.reply_text(
        f"✅ Action recorded: _{_truncate(action, 100)}_\n({player.free_actions_left} free actions left)",
        parse_mode=ParseMode.MARKDOWN
    )
    if len(session.pending_actions) >= len(session.players):
        players = [p for p in [await load_player(t) for t in session.players] if p]
        await run_turn(update, ctx, session, players, session.pending_actions)


# ── XP & Level Up ─────────────────────────────────────────────

PERKS = {
    "Warrior":      ["Iron Skin (+15 HP)", "Berserker Strike (+5 STR)", "Battle Cry (allies +3 STR/turn)"],
    "Mage":         ["Arcane Surge (+5 MAG)", "Mana Shield (absorb 20 dmg)", "Spell Echo (repeat last spell)"],
    "Archer":       ["Eagle Eye (+5 AGI)", "Volley (hit all enemies)", "Shadow Step (free stealth)"],
    "Paladin":      ["Holy Aura (heal 10 HP/turn)", "Divine Shield (+10 HP)", "Smite (+8 STR vs undead)"],
    "Druid":        ["Wild Shape (transform 1/session)", "Nature's Grasp (root enemy)", "Regrowth (+5 HP/turn)"],
    "Rogue":        ["Backstab (+10 STR from stealth)", "Pickpocket (steal gold)", "Vanish (escape combat)"],
    "Necromancer":  ["Soul Harvest (gain HP on kill)", "Raise Dead (summon ally)", "Curse (reduce enemy stats)"],
    "Bard":         ["Inspire (+5 all ally stats)", "Lullaby (put enemy to sleep)", "Discord (confuse enemy)"],
    "Shaman":       ["Spirit Walk (become ethereal)", "Totem (summon protective spirit)", "Storm Call (AoE damage)"],
    "Berserker":    ["Blood Rage (+10 STR when low HP)", "Reckless Charge (stun enemy)", "Primal Roar (fear all)"],
    "Demon Hunter": ["Demon Mark (track any enemy)", "Soul Rend (+8 magic damage)", "Warglaives (+6 AGI+STR)"],
    "Oracle":       ["Foresight (preview next turn)", "Fate Twist (reroll any die)", "Prophecy (hint at danger)"],
}


async def apply_xp(player: Player, amount: int, update):
    player.xp += amount
    if player.xp >= player.xp_to_next:
        player.xp       -= player.xp_to_next
        player.level    += 1
        player.xp_to_next = int(player.xp_to_next * 1.5)
        player.max_hp   += 10
        player.hp        = min(player.hp + 10, player.max_hp)
        player.strength += 1
        player.magic    += 1
        player.agility  += 1
        available = PERKS.get(player.char_class, [])
        new_perks = [p for p in available if p not in player.perks][:3]
        if new_perks:
            buttons = [
                [InlineKeyboardButton(perk, callback_data=f"perk:{player.telegram_id}:{perk}")]
                for perk in new_perks
            ]
            await update.effective_chat.send_message(
                f"🎉 *{player.char_name}* reached *Level {player.level}*!\n\nChoose a perk:",
                reply_markup=InlineKeyboardMarkup(buttons),
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.effective_chat.send_message(
                f"🎉 *{player.char_name}* reached *Level {player.level}*! All class perks mastered.",
                parse_mode=ParseMode.MARKDOWN
            )


async def cb_perk(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, tid, perk = query.data.split(":", 2)
    player = await load_player(int(tid))
    if not player:
        return
    player.perks.append(perk)
    await save_player(player)
    await query.edit_message_text(
        f"✨ *{player.char_name}* learned: *{perk}*!", parse_mode=ParseMode.MARKDOWN
    )
