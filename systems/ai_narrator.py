import google.generativeai as genai
import json
import random
from config import GEMINI_API_KEY, RARITY_WEIGHTS, RARITY_COLORS
from models.schemas import Player, Session, Item
from database.db import new_id

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash")


# ── Core prompt builder ───────────────────────────────────────

def _build_context(session: Session, players: list, actions: dict) -> str:
    players_info = "\n".join([
        f"- {p.char_name} ({p.char_class}, Lvl {p.level}) | "
        f"HP:{p.hp}/{p.max_hp} STR:{p.strength} MAG:{p.magic} AGI:{p.agility} "
        f"LUCK:{p.luck} SAN:{p.sanity} KARMA:{p.karma} GOLD:{p.gold}g | "
        f"Weapon: {p.equipped_weapon or 'none'} | "
        f"Companions: {', '.join(p.companions) or 'none'} | "
        f"Memories: {'; '.join([m['summary'] for m in p.memories[-3:]]) if p.memories else 'none'}"
        for p in players
    ])
    actions_info = "\n".join([
        f"- {next((p.char_name for p in players if p.telegram_id == int(pid)), 'Unknown')}: {act}"
        for pid, act in actions.items()
    ])
    sanity_note = ""
    for p in players:
        if p.sanity < 30:
            sanity_note += f"\n⚠️ {p.char_name} is near madness (sanity {p.sanity}). Weave hallucinations into their perception."

    return f"""You are the narrator of CHRONICLER, a dark medieval fantasy RPG.
Universe: A persistent world where player choices permanently shape history, factions, and NPCs.
Time: {'DAY' if session.day_night == 'day' else 'NIGHT'} | Weather: {session.weather}
Session Turn: {session.turn}/{session.max_turns}
Prophecy this session: "{session.prophecy}"

PLAYERS:
{players_info}

LAST NARRATIVE:
{session.current_narrative or 'The adventure begins...'}

PLAYER ACTIONS THIS TURN:
{actions_info}
{sanity_note}

RULES:
- Write 2-4 paragraphs of vivid, immersive narrative responding to ALL player actions
- Show consequences of karma (villainous players cause fear; heroes inspire hope)
- Day/Night affects what is possible and what enemies appear
- NIGHT: darker threats, thieves, undead, secret societies active
- DAY: merchants, guards, travelers, political intrigue
- Players may LOSE items if contextually appropriate (stolen, broken, consumed, dropped in peril)
- Players may FIND items naturally in the scene
- Companions and tamed creatures should appear and act in narrative
- Reference past memories when dramatically relevant
- If sanity is low, distort that player's perception subtly
- End with exactly 4 numbered choices for what the group can do next
- Format choices as: 1. [action] | 2. [action] | 3. [action] | 4. [action]
- Also output a JSON block at the very end (inside ```json ```) with:
  {{
    "gold_earned": {{"player_telegram_id": amount}},
    "xp_earned": {{"player_telegram_id": amount}},
    "items_lost": [{{"player_id": id, "item_name": name, "reason": reason}}],
    "items_found": [{{"player_id": id, "name": name, "type": type, "rarity": rarity, "description": desc, "stat_bonus": {{}}}}],
    "sanity_changes": {{"player_id": delta}},
    "karma_changes": {{"player_id": delta}},
    "faction_changes": {{"player_id": {{"faction": delta}}}},
    "combat_triggered": false,
    "enemy_name": "",
    "enemy_hp": 0,
    "enemy_strength": 0,
    "taming_opportunity": {{"creature_name": "", "creature_species": "", "player_id": 0}},
    "dungeon_triggered": false,
    "image_prompt": "detailed fantasy scene description for image generation"
  }}"""


async def narrate_turn(session: Session, players: list, actions: dict) -> dict:
    ctx = _build_context(session, players, actions)
    resp = model.generate_content(ctx)
    text = resp.text

    narrative = text
    data = {}
    if "```json" in text:
        parts = text.split("```json")
        narrative = parts[0].strip()
        try:
            data = json.loads(parts[1].split("```")[0].strip())
        except Exception:
            data = {}

    choices = []
    for line in narrative.split("\n"):
        for i in range(1, 5):
            if line.strip().startswith(f"{i}."):
                choices.append(line.strip()[2:].strip())
    clean_narrative = "\n".join(
        l for l in narrative.split("\n")
        if not any(l.strip().startswith(f"{i}.") for i in range(1, 5))
    ).strip()

    return {
        "narrative": clean_narrative,
        "choices": choices,
        "data": data,
        "image_prompt": data.get("image_prompt", "medieval fantasy adventure scene")
    }


# ── Prophecy ──────────────────────────────────────────────────

async def generate_prophecy(players: list) -> str:
    names = ", ".join(p.char_name for p in players)
    resp = model.generate_content(
        f"Generate a cryptic 2-sentence prophecy for adventurers named {names} "
        f"in a dark medieval fantasy world. Make it ominous and poetic. No explanations."
    )
    return resp.text.strip()


# ── Dream between sessions ────────────────────────────────────

async def generate_dream(player: Player) -> str:
    memories = "; ".join([m["summary"] for m in player.memories[-5:]]) if player.memories else "no notable events yet"
    resp = model.generate_content(
        f"Write a vivid, unsettling dream vision (3 sentences) for {player.char_name} "
        f"a {player.char_class} with karma {player.karma} and sanity {player.sanity}. "
        f"Their recent memories: {memories}. "
        f"The dream should hint at future events. Dark medieval fantasy tone."
    )
    return resp.text.strip()


# ── Forge ─────────────────────────────────────────────────────

async def forge_item(item_a: Item, item_b: Item, player: Player) -> Item:
    prompt = (
        f"A {player.char_class} named {player.char_name} combines these two items in a forge:\n"
        f"1. {item_a.name} ({item_a.rarity}) — {item_a.description}\n"
        f"2. {item_b.name} ({item_b.rarity}) — {item_b.description}\n"
        f"Create a NEW item that makes narrative and mechanical sense. "
        f"Respond ONLY with JSON:\n"
        f'{{"name":"","description":"","item_type":"weapon/armor/artifact/consumable",'
        f'"rarity":"Common/Uncommon/Rare/Epic/Legendary/Cursed/Alive",'
        f'"stat_bonus":{{"strength":0,"magic":0,"agility":0,"luck":0,"hp":0}},'
        f'"curse_effect":"","alive_personality":"","image_prompt":""}}'
    )
    resp = model.generate_content(prompt)
    raw = resp.text.strip().replace("```json", "").replace("```", "").strip()
    d = json.loads(raw)
    return Item(
        id=new_id(),
        name=d["name"],
        description=d["description"],
        rarity=d["rarity"],
        item_type=d["item_type"],
        stat_bonus=d.get("stat_bonus", {}),
        curse_effect=d.get("curse_effect", ""),
        alive_personality=d.get("alive_personality", ""),
        owner_id=player.telegram_id,
        acquired_session="forge"
    )


# ── Alive item message ────────────────────────────────────────

async def alive_item_message(item: Item, player: Player, context: str) -> str:
    resp = model.generate_content(
        f"You are {item.name}, a sentient {item.item_type} with this personality: {item.alive_personality}. "
        f"Your wielder {player.char_name} just experienced: {context}. "
        f"Speak one short line (max 20 words) in character to them."
    )
    return resp.text.strip()


# ── Combat narration ──────────────────────────────────────────

async def narrate_combat_round(
    session: Session, players: list,
    enemy_name: str, enemy_hp: int, enemy_max_hp: int,
    round_actions: dict, round_results: dict
) -> str:
    actions_str = "\n".join(f"- {k}: {v}" for k, v in round_actions.items())
    results_str = "\n".join(f"- {k}: {v}" for k, v in round_results.items())
    resp = model.generate_content(
        f"Narrate this combat round in 2 sentences. Dark medieval fantasy.\n"
        f"Enemy: {enemy_name} ({enemy_hp}/{enemy_max_hp} HP)\n"
        f"Player actions:\n{actions_str}\nResults:\n{results_str}"
    )
    return resp.text.strip()


# ── Boss phase transition ─────────────────────────────────────

async def narrate_boss_phase(boss_name: str, phase: int, remaining_hp: int) -> tuple:
    resp = model.generate_content(
        f"The boss {boss_name} enters phase {phase} with {remaining_hp} HP remaining. "
        f"Write: 1 dramatic sentence of narration, then a JSON block with new mechanics:\n"
        f'{{"new_ability":"","damage_multiplier":1.0,"special_effect":"","image_prompt":""}}'
    )
    text = resp.text
    narration = text.split("```")[0].strip()
    data = {}
    if "```json" in text:
        try:
            data = json.loads(text.split("```json")[1].split("```")[0].strip())
        except Exception:
            pass
    return narration, data


# ── Taming attempt ────────────────────────────────────────────

async def attempt_taming(player: Player, creature_name: str, creature_species: str) -> tuple:
    chance = min(90, 20 + player.agility + player.luck)
    success = random.randint(1, 100) <= chance
    resp = model.generate_content(
        f"{player.char_name} ({'successfully tames' if success else 'fails to tame'}) "
        f"a {creature_name} ({creature_species}). Write 2 sentences of narration. "
        f"Then JSON: {{\"ability\":\"\",\"combat_bonus\":{{\"strength\":0}},\"image_prompt\":\"\"}}"
    )
    text = resp.text
    narration = text.split("```")[0].strip()
    data = {}
    if "```json" in text:
        try:
            data = json.loads(text.split("```json")[1].split("```")[0].strip())
        except Exception:
            pass
    return success, narration, data


# ── Dungeon room generation ───────────────────────────────────

async def generate_dungeon(party_level: int, session_context: str) -> list:
    resp = model.generate_content(
        f"Generate a procedural dungeon for party level {party_level} in this context: {session_context}. "
        f"Create 6-10 rooms. Respond ONLY with JSON array:\n"
        f'[{{"room_id":0,"description":"","room_type":"entry/corridor/treasure/trap/boss/exit/secret",'
        f'"exits":[1],"trap":null,"enemy":null,"loot_hint":""}}]'
    )
    raw = resp.text.strip().replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(raw)
    except Exception:
        return []


# ── World event ───────────────────────────────────────────────

async def generate_world_event(world_history: list) -> dict:
    hist = "; ".join(world_history[-5:]) if world_history else "world is at peace"
    resp = model.generate_content(
        f"Recent world events: {hist}\n"
        f"Generate a new world event in a persistent dark medieval fantasy universe. "
        f"Respond ONLY with JSON:\n"
        f'{{"title":"","message":"","affects_faction":"","karma_effect":0,"image_prompt":""}}'
    )
    raw = resp.text.strip().replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(raw)
    except Exception:
        return {"title": "Strange winds blow", "message": "Something stirs in the dark.", "affects_faction": "", "karma_effect": 0, "image_prompt": "dark medieval castle at night"}


# ── NPC letter ────────────────────────────────────────────────

async def generate_npc_letter(player: Player) -> str:
    memories = "; ".join([m["summary"] for m in player.memories[-3:]]) if player.memories else "your travels"
    resp = model.generate_content(
        f"Write a short in-world letter (3-4 sentences) from an NPC to {player.char_name} "
        f"referencing their recent deeds: {memories}. "
        f"The NPC could be an ally, rival, merchant, or mysterious figure. "
        f"Sign with a creative NPC name. Medieval fantasy tone."
    )
    return resp.text.strip()


# ── Session summary ───────────────────────────────────────────

async def generate_session_summary(session: Session, players: list) -> dict:
    names = ", ".join(p.char_name for p in players)
    history_brief = " → ".join([h["content"][:60] for h in session.history[-6:] if h["role"] == "assistant"])
    resp = model.generate_content(
        f"Summarize this RPG session in 3 sentences for players {names}. "
        f"Key events: {history_brief}. "
        f"Also return JSON: {{\"title\":\"\",\"image_prompt\":\"\",\"highlight\":\"\"}}"
    )
    text = resp.text
    summary = text.split("```")[0].strip()
    data = {}
    if "```json" in text:
        try:
            data = json.loads(text.split("```json")[1].split("```")[0].strip())
        except Exception:
            pass
    return {"summary": summary, **data}
