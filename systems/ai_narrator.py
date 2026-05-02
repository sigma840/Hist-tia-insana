import json
import random

from groq import Groq

from config import GROQ_API_KEY, RARITY_WEIGHTS, RARITY_COLORS
from models.schemas import Player, Session, Item
from database.db import new_id

client = Groq(api_key=GROQ_API_KEY)
MODEL  = "llama-3.3-70b-versatile"


def _chat(prompt: str, system: str = "", max_tokens: int = 1500) -> str:
    """Envia uma mensagem ao Groq e devolve o texto da resposta."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    resp = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        max_tokens=max_tokens,
        temperature=0.85,
    )
    return resp.choices[0].message.content.strip()


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

    return f"""PLAYERS:
{players_info}

LAST NARRATIVE:
{session.current_narrative or 'The adventure begins...'}

PLAYER ACTIONS THIS TURN:
{actions_info}
{sanity_note}

Session Turn: {session.turn}/{session.max_turns}
Time: {'DAY' if session.day_night == 'day' else 'NIGHT'} | Weather: {session.weather}
Prophecy: "{session.prophecy}"

RULES:
- Write EXACTLY 3 paragraphs of narrative (around 40-60 words each). Vivid, immersive, dramatic but concise.
- Show consequences of karma (villainous players cause fear; heroes inspire hope)
- NIGHT: undead, thieves, secret societies. DAY: merchants, guards, intrigue.
- Players may LOSE or FIND items naturally in the scene
- Reference past memories when dramatically relevant
- If sanity is low, distort that player's perception subtly
- End with exactly 4 numbered choices (max 10 words each): 1. [action] 2. [action] 3. [action] 4. [action]
- Combat should be rare — only trigger it if a choice clearly leads to a fight, or randomly 1 in 8 turns at most
- After the choices, output ONLY a JSON block (no markdown fences) with this exact structure:
{{"gold_earned":{{"player_id":0}},"xp_earned":{{"player_id":0}},"items_lost":[{{"player_id":0,"item_name":"","reason":""}}],"items_found":[{{"player_id":0,"name":"","type":"weapon","rarity":"Common","description":"","stat_bonus":{{}}}}],"sanity_changes":{{"player_id":0}},"karma_changes":{{"player_id":0}},"faction_changes":{{"player_id":{{}}}},"combat_triggered":false,"enemy_name":"","enemy_hp":0,"enemy_strength":0,"taming_opportunity":{{"creature_name":"","creature_species":"","player_id":0}},"dungeon_triggered":false,"image_prompt":""}}"""


async def narrate_turn(session: Session, players: list, actions: dict) -> dict:
    system = "You are the narrator of CHRONICLER, a dark medieval fantasy RPG. Be vivid, immersive, and dramatic."
    prompt = _build_context(session, players, actions)
    text   = _chat(prompt, system=system, max_tokens=1200)

    # Split narrative from JSON
    narrative, data = text, {}
    # Try to find JSON block at the end
    brace_idx = text.rfind("\n{")
    if brace_idx == -1:
        brace_idx = text.rfind("{")
    if brace_idx != -1:
        narrative = text[:brace_idx].strip()
        try:
            data = json.loads(text[brace_idx:].strip())
        except Exception:
            data = {}

    # Extract choices
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
        "narrative":    clean_narrative,
        "choices":      choices,
        "data":         data,
        "image_prompt": data.get("image_prompt", "medieval fantasy adventure scene"),
    }


# ── Prophecy ──────────────────────────────────────────────────

async def generate_prophecy(players: list) -> str:
    names = ", ".join(p.char_name for p in players)
    return _chat(
        f"Generate a cryptic 2-sentence prophecy for adventurers named {names} "
        f"in a dark medieval fantasy world. Make it ominous and poetic. No explanations.",
        max_tokens=120
    )


# ── Dream ─────────────────────────────────────────────────────

async def generate_dream(player: Player) -> str:
    memories = "; ".join([m["summary"] for m in player.memories[-5:]]) if player.memories else "no notable events yet"
    return _chat(
        f"Write a vivid, unsettling dream vision (3 sentences) for {player.char_name}, "
        f"a {player.char_class} with karma {player.karma} and sanity {player.sanity}. "
        f"Recent memories: {memories}. Hint at future events. Dark medieval fantasy.",
        max_tokens=200
    )


# ── Forge ─────────────────────────────────────────────────────

async def forge_item(item_a: Item, item_b: Item, player: Player) -> Item:
    prompt = (
        f"A {player.char_class} named {player.char_name} combines:\n"
        f"1. {item_a.name} ({item_a.rarity}) — {item_a.description}\n"
        f"2. {item_b.name} ({item_b.rarity}) — {item_b.description}\n"
        f"Create a NEW item. Respond ONLY with raw JSON (no markdown):\n"
        f'{{"name":"","description":"","item_type":"weapon","rarity":"Common",'
        f'"stat_bonus":{{"strength":0,"magic":0,"agility":0,"luck":0,"hp":0}},'
        f'"curse_effect":"","alive_personality":"","image_prompt":""}}'
    )
    raw = _chat(prompt, max_tokens=400)
    # Strip possible markdown fences
    raw = raw.replace("```json", "").replace("```", "").strip()
    d   = json.loads(raw)
    return Item(
        id=new_id(), name=d["name"], description=d["description"],
        rarity=d["rarity"], item_type=d["item_type"],
        stat_bonus=d.get("stat_bonus", {}),
        curse_effect=d.get("curse_effect", ""),
        alive_personality=d.get("alive_personality", ""),
        owner_id=player.telegram_id, acquired_session="forge"
    )


# ── Alive item message ────────────────────────────────────────

async def alive_item_message(item: Item, player: Player, context: str) -> str:
    return _chat(
        f"You are {item.name}, a sentient {item.item_type} with personality: {item.alive_personality}. "
        f"Your wielder {player.char_name} just experienced: {context}. "
        f"Speak ONE line (max 20 words) in character.",
        max_tokens=60
    )


# ── Combat narration ──────────────────────────────────────────

async def narrate_combat_round(
    session: Session, players: list,
    enemy_name: str, enemy_hp: int, enemy_max_hp: int,
    round_actions: dict, round_results: dict
) -> str:
    actions_str = "\n".join(f"- {k}: {v}" for k, v in round_actions.items())
    results_str = "\n".join(f"- {k}: {v}" for k, v in round_results.items())
    return _chat(
        f"Narrate this combat round in 2 sentences. Dark medieval fantasy.\n"
        f"Enemy: {enemy_name} ({enemy_hp}/{enemy_max_hp} HP)\n"
        f"Player actions:\n{actions_str}\nResults:\n{results_str}",
        max_tokens=150
    )


# ── Boss phase transition ─────────────────────────────────────

async def narrate_boss_phase(boss_name: str, phase: int, remaining_hp: int) -> tuple:
    text = _chat(
        f"The boss {boss_name} enters phase {phase} with {remaining_hp} HP. "
        f"Write 1 dramatic sentence, then output raw JSON (no markdown):\n"
        f'{{"new_ability":"","damage_multiplier":1.2,"special_effect":"","image_prompt":""}}',
        max_tokens=250
    )
    narration = text.split("{")[0].strip()
    data = {}
    idx  = text.find("{")
    if idx != -1:
        try:
            data = json.loads(text[idx:].strip())
        except Exception:
            pass
    return narration, data


# ── Taming attempt ────────────────────────────────────────────

async def attempt_taming(player: Player, creature_name: str, creature_species: str) -> tuple:
    chance  = min(90, 20 + player.agility + player.luck)
    success = random.randint(1, 100) <= chance
    text    = _chat(
        f"{player.char_name} ({'successfully tames' if success else 'fails to tame'}) "
        f"a {creature_name} ({creature_species}). Write 2 sentences of narration. "
        f"Then output raw JSON (no markdown):\n"
        f'{{"ability":"","combat_bonus":{{"strength":0}},"image_prompt":""}}',
        max_tokens=300
    )
    narration = text.split("{")[0].strip()
    data = {}
    idx  = text.find("{")
    if idx != -1:
        try:
            data = json.loads(text[idx:].strip())
        except Exception:
            pass
    return success, narration, data


# ── Dungeon generation ────────────────────────────────────────

async def generate_dungeon(party_level: int, session_context: str) -> list:
    raw = _chat(
        f"Generate a dungeon for party level {party_level}. Context: {session_context}. "
        f"Create 6-8 rooms. Respond ONLY with a raw JSON array (no markdown):\n"
        f'[{{"room_id":0,"description":"","room_type":"entry",'
        f'"exits":[1],"trap":null,"enemy":null,"loot_hint":""}}]',
        max_tokens=1200
    )
    raw = raw.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(raw)
    except Exception:
        return []


# ── World event ───────────────────────────────────────────────

async def generate_world_event(world_history: list) -> dict:
    hist = "; ".join(world_history[-5:]) if world_history else "world is at peace"
    raw  = _chat(
        f"Recent world events: {hist}\n"
        f"Generate a new world event for a dark medieval fantasy universe. "
        f"Respond ONLY with raw JSON (no markdown):\n"
        f'{{"title":"","message":"","affects_faction":"","karma_effect":0,"image_prompt":""}}',
        max_tokens=300
    )
    raw = raw.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(raw)
    except Exception:
        return {"title": "Strange winds blow", "message": "Something stirs in the dark.",
                "affects_faction": "", "karma_effect": 0, "image_prompt": "dark medieval castle at night"}


# ── NPC letter ────────────────────────────────────────────────

async def generate_npc_letter(player: Player) -> str:
    memories = "; ".join([m["summary"] for m in player.memories[-3:]]) if player.memories else "your travels"
    return _chat(
        f"Write a short in-world letter (3-4 sentences) from an NPC to {player.char_name} "
        f"referencing their deeds: {memories}. "
        f"Sign with a creative NPC name. Medieval fantasy tone.",
        max_tokens=200
    )


# ── Session summary ───────────────────────────────────────────

async def generate_session_summary(session: Session, players: list) -> dict:
    names         = ", ".join(p.char_name for p in players)
    history_brief = " → ".join([h["content"][:60] for h in session.history[-6:] if h["role"] == "assistant"])
    text = _chat(
        f"Summarize this RPG session in 3 sentences for players {names}. "
        f"Key events: {history_brief}. "
        f"Then output raw JSON (no markdown): "
        f'{{"title":"","image_prompt":"","highlight":""}}',
        max_tokens=400
    )
    summary = text.split("{")[0].strip()
    data    = {}
    idx     = text.find("{")
    if idx != -1:
        try:
            data = json.loads(text[idx:].strip())
        except Exception:
            pass
    return {"summary": summary, **data}
