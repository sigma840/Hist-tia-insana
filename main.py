import asyncio
import logging

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)

from config import TELEGRAM_TOKEN
from database.db import init_db
from systems.world_events import start_scheduler

from handlers.session import (
    cmd_start, cb_pick_class, handle_name_input,
    cmd_new_session, cb_begin_adventure,
    cmd_join_session, cmd_end_session,
    cb_choice, cb_free_action, handle_free_action_input,
    cb_perk
)
from handlers.combat  import cb_combat
from handlers.dungeon import cb_dungeon
from handlers.social  import (
    cmd_guild, cb_guild, handle_guild_name,
    cmd_market, cmd_sell, cb_market, cb_sell_pick, cb_sell_type, handle_sell_input,
    cmd_ranking
)
from handlers.profile import (
    cmd_profile, cmd_inventory, cb_inventory,
    cmd_forge, cb_forge,
    cmd_companions, cb_tame
)
from handlers.extras import (
    cmd_prophecy, cmd_memories, cmd_factions,
    cmd_shop, cb_shop,
    cmd_build, cb_build
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


# ── Smart message router ──────────────────────────────────────

async def smart_message_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if ctx.user_data.get("awaiting_name"):
        await handle_name_input(update, ctx)
    elif ctx.user_data.get("awaiting_freeact"):
        await handle_free_action_input(update, ctx)
    elif ctx.user_data.get("awaiting_guild_name"):
        await handle_guild_name(update, ctx)
    elif ctx.user_data.get("awaiting_price") or ctx.user_data.get("awaiting_trade"):
        await handle_sell_input(update, ctx)


# ── Smart callback router ─────────────────────────────────────

async def smart_callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data
    if   data.startswith("pickclass:"):  await cb_pick_class(update, ctx)
    elif data.startswith("beginadv:"):   await cb_begin_adventure(update, ctx)
    elif data.startswith("choice:"):     await cb_choice(update, ctx)
    elif data.startswith("freeact:"):    await cb_free_action(update, ctx)
    elif data.startswith("perk:"):       await cb_perk(update, ctx)
    elif data.startswith("combat:"):     await cb_combat(update, ctx)
    elif data.startswith("dungeon:"):    await cb_dungeon(update, ctx)
    elif data.startswith("guild:"):      await cb_guild(update, ctx)
    elif data.startswith("market:"):     await cb_market(update, ctx)
    elif data.startswith("sell:pick:"):  await cb_sell_pick(update, ctx)
    elif data.startswith("selltype:"):   await cb_sell_type(update, ctx)
    elif data.startswith("inv:"):        await cb_inventory(update, ctx)
    elif data.startswith("forge:"):      await cb_forge(update, ctx)
    elif data.startswith("tame:"):       await cb_tame(update, ctx)
    elif data.startswith("shop:"):       await cb_shop(update, ctx)
    elif data.startswith("build:"):      await cb_build(update, ctx)
    elif data.startswith("ranking:"):    await cmd_ranking(update, ctx)


# ── Main ──────────────────────────────────────────────────────

async def main():
    await init_db()
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start",        cmd_start))
    app.add_handler(CommandHandler("newsession",   cmd_new_session))
    app.add_handler(CommandHandler("joinsession",  cmd_join_session))
    app.add_handler(CommandHandler("endsession",   cmd_end_session))
    app.add_handler(CommandHandler("profile",      cmd_profile))
    app.add_handler(CommandHandler("inventory",    cmd_inventory))
    app.add_handler(CommandHandler("forge",        cmd_forge))
    app.add_handler(CommandHandler("companions",   cmd_companions))
    app.add_handler(CommandHandler("guild",        cmd_guild))
    app.add_handler(CommandHandler("market",       cmd_market))
    app.add_handler(CommandHandler("sell",         cmd_sell))
    app.add_handler(CommandHandler("ranking",      cmd_ranking))
    app.add_handler(CommandHandler("prophecy",     cmd_prophecy))
    app.add_handler(CommandHandler("memories",     cmd_memories))
    app.add_handler(CommandHandler("factions",     cmd_factions))
    app.add_handler(CommandHandler("shop",         cmd_shop))
    app.add_handler(CommandHandler("build",        cmd_build))

    # Single callback router
    app.add_handler(CallbackQueryHandler(smart_callback_handler))

    # Single message router
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, smart_message_handler))

    # World event scheduler
    start_scheduler(app.bot)

    print("⚔️ Chronicler Bot is online!")
    await app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    asyncio.run(main())
