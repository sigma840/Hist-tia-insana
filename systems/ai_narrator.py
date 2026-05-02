import google.generativeai as genai
import json
import random
from config import GEMINI_API_KEY, RARITY_WEIGHTS, RARITY_COLORS
from models.schemas import Player, Session, Item
from database.db import new_id

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

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
            sanity_note += f"\n⚠️ {p.char_name} has very low sanity ({p.sanity}). Subtly distort their perception of events — they may misread faces, hear things, or misunderstand what's happening. Keep it grounded, not poetic."

    return f"""You are the narrator of CHRONICLER, a dark medieval fantasy RPG told like a novel.

WORLD STATE:
Time: {'DAY' if session.day_night == 'day' else 'NIGHT'} | Weather: {session.weather}
Turn: {session.turn}/{session.max_turns} | Prophecy: "{session.prophecy}"

PLAYERS:
{players_info}

PREVIOUS SCENE:
{session.current_narrative or 'The adventure begins.'}

PLAYER ACTIONS THIS TURN:
{actions_info}
{sanity_note}

NARRATION RULES — READ CAREFULLY:
1. Write like a novelist, NOT a poet. No metaphors every sentence. No purple prose. Be clear and direct.
   GOOD: "The guard grabbed Aldric by the collar and slammed him against the wall."
   BAD: "Shadow tendrils of fate entwined with the moonlit whispers of destiny..."
2. Write 3-4 paragraphs. Every paragraph must move the story forward. Describe what actually happens as a result of player actions.
3. Characters must react realistically. NPCs have motives. Enemies have reasons. The world feels lived-in.
4. Vary the situations wildly. Don't always go to combat. Think: political intrigue, moral dilemmas, unexpected allies, betrayals, mysteries, disasters, comedy, tragedy, exploration, puzzles, negotiations, chases, heists, curses, festivals, bar fights, corruption, lost children, plague, romance, revenge.
5. Reference player karma visibly — villainous players cause NPCs to flinch, lock doors, call guards. Heroes get respect, help, information.
6. Day/Night matters: night = danger, crime, secrets; day = commerce, politics, travel.
7. Players can LOSE items (stolen, broken, confiscated, lost in a fall). Make it feel earned, not random.
8. Players can FIND items naturally woven into the scene — don't announce it, let it happen in the narrative.
9. Companions and tamed creatures act on their own in the scene.
10. If sanity is low for a player, distort their experience subtly within the prose itself.

CHOICES — CRITICAL:
After the narrative, write exactly 4 choices. These must be SPECIFIC to this exact scene, not generic.
- They should feel like real decisions with consequences, not just actions.
- Mix types: one might be risky, one cautious, one creative, one that uses a specific class skill or item.
- NEVER write: "Approach cautiously", "Use magic", "Attack", "Explore the area" — these are banned.
- DO write things like: "Bribe the gate captain with your last 20 gold", "Slip the antidote into the merchant's wine", "Challenge the warlord to single combat in front of his men", "Follow the child — she clearly knows something"
- Format: 1. [choice] | 2. [choice] | 3. [choice] | 4. [choice] on separate lines.

End with a JSON block inside ```json ```:
{{
  "gold_earned": {{"player_telegram_id_as_string": amount}},
  "xp_earned": {{"player_telegram_id_as_string": amount}},
  "items_lost": [{{"player_id": id, "item_name": name, "reason": reason}}],
  "items_found": [{{"player_id": id, "name": name, "type": "weapon/armor/consumable/artifact", "rarity": "Common/Uncommon/Rare/Epic/Legendary/Cursed/Alive", "description": desc, "stat_bonus": {{}}}}],
  "sanity_changes": {{"player_id_as_string": delta}},
  "karma_changes": {{"player_id_as_string": delta}},
  "faction_changes": {{"player_id_as_string": {{"faction_name": delta}}}},
  "combat_triggered": false,
  "enemy_name": "",
  "enemy_hp": 0,
  "enemy_strength": 0,
  "taming_opportunity": {{"creature_name": "", "creature_species": "", "player_id": 0}},
  "dungeon_triggered": false,
  "image_prompt": "specific scene description for image generation, no abstract concepts"
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

    # Extract choices
    choices = []
    for line in narrative.split("\n"):
        stripped = line.strip()
        for i in range(1, 5):
            if stripped.startswith(f"{i}."):
                choices.append(stripped[2:].strip())

    # Remove choices from narrative text
    clean_narrative = "\n".join(
        l for l in narrative.split("\n")
        if not any(l.strip().startswith(f"{i}.") for i in range(1, 5))
    ).strip()

    return {
        "narrative": clean_narrative,
        "choices": choices,
        "data": data,
        "image_prompt": data.get("image_prompt", "medieval fantasy tavern scene")
    }


# ── Prophecy ──────────────────────────────────────────────────

async def generate_prophecy(players: list) -> str:
    names = ", ".join(p.char_name for p in players)
    resp = model.generate_content(
        f"Generate a cryptic 2-sentence prophecy for adventurers named {names} "
        f"in a dark medieval fantasy world. Write it like something carved on a tombstone — "
        f"ominous but readable. No flowery language. No explanations."
    )
    return resp.text.strip()


# ── Dream between sessions ────────────────────────────────────

async def generate_dream(player: Player) -> str:
    memories = "; ".join([m["summary"] for m in player.memories[-5:]]) if player.memories else "no notable events yet"
    resp = model.generate_content(
        f"Write a short dream (3 sentences, plain prose like a novel) for {player.char_name}, "
        f"a {player.char_class} with karma {player.karma} and sanity {player.sanity}. "
        f"Their recent memories: {memories}. "
        f"The dream hints at something to come. Dark, clear, unsettling. No poetry."
    )
    return resp.text.strip()


# ── Forge ─────────────────────────────────────────────────────

async def forge_item(item_a: Item, item_b: Item, player: Player) -> Item:
    prompt = (
        f"A {player.char_class} named {player.char_name} combines these two items in a forge:\n"
        f"1. {item_a.name} ({item_a.rarity}) — {item_a.description}\n"
        f"2. {item_b.name} ({item_b.rarity}) — {item_b.description}\n"
        f"Create a new item that makes logical and narrative sense. "
        f"Name it something a blacksmith would actually call it, not something poetic. "
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
        f"Say one short line (max 15 words) in character. Speak plainly, like a person talking, not a prophecy."
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
        f"Write 2 sentences describing this combat exchange. Write like a novel — clear, visceral, grounded. No poetry.\n"
        f"Enemy: {enemy_name} ({enemy_hp}/{enemy_max_hp} HP remaining)\n"
        f"Actions:\n{actions_str}\nResults:\n{results_str}"
    )
    return resp.text.strip()


# ── Boss phase transition ─────────────────────────────────────

async def narrate_boss_phase(boss_name: str, phase: int, remaining_hp: int) -> tuple:
    resp = model.generate_content(
        f"The boss {boss_name} enters phase {phase} with {remaining_hp} HP remaining. "
        f"Write 1 dramatic sentence describing what changes (no poetry, just what happens physically). "
        f"Then a JSON block: "
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
        f"{player.char_name} {'successfully tames' if success else 'fails to tame'} "
        f"a {creature_name} ({creature_species}). "
        f"Write 2 plain sentences describing what happens. Then JSON: "
        f'{{\"ability\":\"\",\"combat_bonus\":{{\"strength\":0}},\"image_prompt\":\"\"}}'
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
        f"Generate a procedural dungeon for a party of level {party_level}. "
        f"Context: {session_context}. "
        f"Create 6-10 rooms with clear, practical descriptions (what you see, smell, hear — no poetry). "
        f"Respond ONLY with a JSON array:\n"
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
    hist = "; ".join(world_history[-5:]) if world_history else "the realm is quiet"
    resp = model.generate_content(
        f"Recent world events: {hist}\n"
        f"Generate a new world event in a dark medieval fantasy setting. "
        f"Write it like a town crier announcement or a rumor heard at a tavern — plain, specific, interesting. "
        f"Respond ONLY with JSON:\n"
        f'{{"title":"","message":"","affects_faction":"","karma_effect":0,"image_prompt":""}}'
    )
    raw = resp.text.strip().replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(raw)
    except Exception:
        return {
            "title": "Trouble on the King's Road",
            "message": "Merchants report a new toll being collected by armed men near the eastern pass. Nobody knows who they answer to.",
            "affects_faction": "Crown",
            "karma_effect": 0,
            "image_prompt": "medieval road ambush bandits"
        }


# ── NPC letter ───────────────────────────────────────────────

async def generate_npc_letter(player: Player) -> str:
    memories = "; ".join([m["summary"] for m in player.memories[-3:]]) if player.memories else "your travels"
    resp = model.generate_content(
        f"Write a short letter (3-4 sentences) from an NPC to {player.char_name}, "
        f"referencing their recent deeds: {memories}. "
        f"Write it like a real person wrote it — informal, specific, with an agenda. "
        f"The NPC has a name and wants something. Medieval setting, plain language."
    )
    return resp.text.strip()


# ── Session summary ───────────────────────────────────────────

async def generate_session_summary(session: Session, players: list) -> dict:
    names = ", ".join(p.char_name for p in players)
    history_brief = " → ".join([h["content"][:80] for h in session.history[-6:] if h["role"] == "assistant"])
    resp = model.generate_content(
        f"Summarize this RPG session in 3 plain sentences for players {names}. "
        f"Write it like the closing paragraph of a chapter — what happened, what changed, what was lost or gained. "
        f"Key events: {history_brief}. "
        f'Also return JSON: {{"title":"","image_prompt":"","highlight":""}}'
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
