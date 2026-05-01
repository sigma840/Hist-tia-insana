import asyncio
import random
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.constants import ParseMode
from config import WORLD_EVENT_INTERVAL_MINUTES
from database.db import all_players, get_world, set_world, save_player, load_player
from systems.ai_narrator import generate_world_event, generate_dream, generate_npc_letter
from systems.image_gen import generate_image

scheduler = AsyncIOScheduler()


def start_scheduler(bot):
    scheduler.add_job(
        lambda: asyncio.create_task(world_event_tick(bot)),
        "interval", minutes=WORLD_EVENT_INTERVAL_MINUTES
    )
    scheduler.add_job(
        lambda: asyncio.create_task(send_dreams(bot)),
        "cron", hour=3
    )
    scheduler.add_job(
        lambda: asyncio.create_task(send_npc_letters(bot)),
        "interval", hours=6
    )
    scheduler.start()


async def world_event_tick(bot):
    history = await get_world("event_history", [])
    event = await generate_world_event(history)
    img = await generate_image(event.get("image_prompt", "medieval castle"))
    history.append(event.get("title", ""))
    await set_world("event_history", history[-20:])

    players = await all_players()
    notified = set()
    for p in players:
        if p.telegram_id in notified:
            continue
        faction = event.get("affects_faction", "")
        if faction and p.faction_rep.get(faction, 0) >= 20:
            try:
                text = f"📰 *World Event: {event['title']}*\n\n{event['message']}"
                if img:
                    await bot.send_photo(p.telegram_id, img, caption=text, parse_mode=ParseMode.MARKDOWN)
                else:
                    await bot.send_message(p.telegram_id, text, parse_mode=ParseMode.MARKDOWN)
                notified.add(p.telegram_id)
            except Exception:
                pass


async def send_dreams(bot):
    players = await all_players()
    for p in players:
        if not p.memories:
            continue
        try:
            dream = await generate_dream(p)
            await bot.send_message(
                p.telegram_id,
                f"💤 *{p.char_name} dreams...*\n\n||{dream}||",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass
        await asyncio.sleep(1)


async def send_npc_letters(bot):
    players = await all_players()
    eligible = [p for p in players if p.memories and random.random() < 0.3]
    for p in eligible:
        try:
            letter = await generate_npc_letter(p)
            await bot.send_message(
                p.telegram_id,
                f"📜 *A letter arrives for {p.char_name}:*\n\n_{letter}_",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass
        await asyncio.sleep(2)
