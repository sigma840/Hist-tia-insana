import time
import uuid
import aiosqlite

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config import RARITY_COLORS, AUCTION_DURATION_SECONDS
from database.db import (
    DB_PATH, parse_obj,
    load_player, save_player,
    load_guild, save_guild, find_guild_by_member,
    load_item, save_item, load_items,
    load_listing, save_listing, all_listings, delete_listing,
    all_players
)
from models.schemas import Guild, MarketListing, Item


# ── /guild ────────────────────────────────────────────────────

async def cmd_guild(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tid    = update.effective_user.id
    player = await load_player(tid)
    if not player:
        return
    guild = await find_guild_by_member(tid)
    if not guild:
        await update.message.reply_text(
            "🏰 You're not in a guild.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⚔️ Create Guild", callback_data="guild:create"),
                InlineKeyboardButton("🔍 Browse Guilds", callback_data="guild:browse")
            ]])
        )
        return

    members      = [await load_player(m) for m in guild.members]
    member_list  = "\n".join([f"• {p.char_name} ({p.char_class}) Lvl {p.level}" for p in members if p])
    mission      = guild.active_mission
    mission_text = f"\n\n📋 *Active Mission:* {mission['title']}" if mission else ""

    await update.message.reply_text(
        f"🏰 *{guild.name}*\nRank {guild.rank} | Vault: {guild.gold_vault}g | Missions: {guild.missions_completed}\n\n"
        f"*Members:*\n{member_list}{mission_text}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Missions",    callback_data=f"guild:missions:{guild.guild_id}"),
             InlineKeyboardButton("🏆 Ranking",     callback_data="ranking:global")],
            [InlineKeyboardButton("💰 Deposit Gold", callback_data=f"guild:deposit:{guild.guild_id}")]
        ])
    )


async def cb_guild(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    parts  = query.data.split(":")
    action = parts[1]
    tid    = query.from_user.id

    if action == "create":
        ctx.user_data["awaiting_guild_name"] = True
        await query.message.reply_text("🏰 Enter your guild name:")

    elif action == "browse":
        all_guilds = []
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT data FROM guilds") as c:
                rows = await c.fetchall()
                all_guilds = [parse_obj(r[0], Guild) for r in rows]
        if not all_guilds:
            await query.edit_message_text("No guilds exist yet. Create one!")
            return
        buttons = [
            [InlineKeyboardButton(f"🏰 {g.name} ({len(g.members)} members)", callback_data=f"guild:join:{g.guild_id}")]
            for g in all_guilds[:5]
        ]
        await query.edit_message_text("Choose a guild to join:", reply_markup=InlineKeyboardMarkup(buttons))

    elif action == "join" and len(parts) > 2:
        gid    = parts[2]
        guild  = await load_guild(gid)
        if not guild:
            return
        player = await load_player(tid)
        guild.members.append(tid)
        player.guild_id = gid
        await save_guild(guild)
        await save_player(player)
        await query.edit_message_text(f"✅ Joined *{guild.name}*!", parse_mode=ParseMode.MARKDOWN)


async def handle_guild_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.user_data.get("awaiting_guild_name"):
        return
    ctx.user_data.pop("awaiting_guild_name")
    tid    = update.effective_user.id
    name   = update.message.text.strip()[:32]
    gid    = str(uuid.uuid4())[:8]
    player = await load_player(tid)
    guild  = Guild(guild_id=gid, name=name, members=[tid])
    player.guild_id = gid
    await save_guild(guild)
    await save_player(player)
    await update.message.reply_text(f"🏰 Guild *{name}* created!", parse_mode=ParseMode.MARKDOWN)


# ── /market ───────────────────────────────────────────────────

async def cmd_market(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    listings = await all_listings()
    if not listings:
        await update.message.reply_text(
            "🛒 *Player Market* — No listings yet.\nSell your items with /sell",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    buttons = []
    for lst in listings[:8]:
        item = await load_item(lst.item_id)
        if not item:
            continue
        emoji = RARITY_COLORS.get(item.rarity, "⬜")
        if lst.listing_type == "fixed":
            label = f"{emoji} {item.name} — {lst.price}g"
        elif lst.listing_type == "auction":
            remaining = max(0, int((lst.auction_end or 0) - time.time()) // 60)
            label = f"{emoji} {item.name} — Bid: {lst.highest_bid}g ({remaining}m left)"
        else:
            label = f"{emoji} {item.name} — Trade for: {lst.trade_for}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"market:view:{lst.listing_id}")])

    await update.message.reply_text(
        "🛒 *Player Market*",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.MARKDOWN
    )


async def cmd_sell(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tid    = update.effective_user.id
    player = await load_player(tid)
    if not player or not player.inventory:
        await update.message.reply_text("Your inventory is empty.")
        return
    items   = await load_items(player.inventory)
    buttons = [[InlineKeyboardButton(
        f"{RARITY_COLORS.get(i.rarity,'⬜')} {i.name} ({i.rarity})",
        callback_data=f"sell:pick:{i.id}"
    )] for i in items]
    await update.message.reply_text("🛒 Which item to sell?", reply_markup=InlineKeyboardMarkup(buttons))


async def cb_market(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    parts  = query.data.split(":")
    action = parts[1]
    tid    = query.from_user.id

    if action == "view" and len(parts) > 2:
        lst    = await load_listing(parts[2])
        if not lst:
            return
        item   = await load_item(lst.item_id)
        seller = await load_player(lst.seller_id)
        emoji  = RARITY_COLORS.get(item.rarity, "⬜")
        text   = f"{emoji} *{item.name}* ({item.rarity})\n_{item.description}_\n\nSeller: {seller.char_name if seller else '?'}"
        kb_rows = []
        if lst.listing_type == "fixed":
            kb_rows.append([InlineKeyboardButton(f"💰 Buy for {lst.price}g", callback_data=f"market:buy:{lst.listing_id}")])
        elif lst.listing_type == "auction":
            kb_rows.append([InlineKeyboardButton(f"📈 Bid (current: {lst.highest_bid}g)", callback_data=f"market:bid:{lst.listing_id}")])
        elif lst.listing_type == "trade":
            kb_rows.append([InlineKeyboardButton("🔄 Propose Trade", callback_data=f"market:trade:{lst.listing_id}")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb_rows), parse_mode=ParseMode.MARKDOWN)

    elif action == "buy" and len(parts) > 2:
        lst    = await load_listing(parts[2])
        if not lst:
            return
        buyer  = await load_player(tid)
        seller = await load_player(lst.seller_id)
        if not buyer or not seller:
            return
        if buyer.gold < lst.price:
            await query.answer("❌ Not enough gold!", show_alert=True)
            return
        buyer.gold  -= lst.price
        seller.gold += lst.price
        buyer.inventory.append(lst.item_id)
        if lst.item_id in seller.inventory:
            seller.inventory.remove(lst.item_id)
        item          = await load_item(lst.item_id)
        item.owner_id = tid
        await save_item(item)
        await save_player(buyer)
        await save_player(seller)
        await delete_listing(lst.listing_id)
        await query.edit_message_text(f"✅ Purchased *{item.name}* for *{lst.price}g*!", parse_mode=ParseMode.MARKDOWN)


async def cb_sell_pick(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    item_id = query.data.split(":")[2]
    ctx.user_data["selling_item"] = item_id
    await query.edit_message_text(
        "How do you want to sell it?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 Fixed Price", callback_data=f"selltype:fixed:{item_id}"),
             InlineKeyboardButton("📈 Auction",     callback_data=f"selltype:auction:{item_id}")],
            [InlineKeyboardButton("🔄 Trade",       callback_data=f"selltype:trade:{item_id}")]
        ])
    )


async def cb_sell_type(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query     = update.callback_query
    await query.answer()
    _, sell_type, item_id = query.data.split(":")
    ctx.user_data["sell_type"]    = sell_type
    ctx.user_data["sell_item_id"] = item_id
    if sell_type == "fixed":
        ctx.user_data["awaiting_price"] = True
        await query.message.reply_text("💰 Enter your price in gold:")
    elif sell_type == "auction":
        ctx.user_data["awaiting_price"] = "auction"
        await query.message.reply_text("📈 Enter starting bid in gold:")
    elif sell_type == "trade":
        ctx.user_data["awaiting_trade"] = True
        await query.message.reply_text("🔄 What item do you want in return?")


async def handle_sell_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tid       = update.effective_user.id
    item_id   = ctx.user_data.get("sell_item_id")
    sell_type = ctx.user_data.get("sell_type")
    if not item_id:
        return

    listing_id = str(uuid.uuid4())[:8]
    lst        = MarketListing(listing_id=listing_id, seller_id=tid, item_id=item_id, listing_type=sell_type)

    if ctx.user_data.pop("awaiting_price", None):
        try:
            price = int(update.message.text.strip())
        except ValueError:
            await update.message.reply_text("❌ Invalid price.")
            return
        if sell_type == "auction":
            lst.highest_bid = price
            lst.auction_end = time.time() + AUCTION_DURATION_SECONDS
        else:
            lst.price = price
    elif ctx.user_data.pop("awaiting_trade", None):
        lst.trade_for = update.message.text.strip()

    ctx.user_data.pop("sell_item_id", None)
    ctx.user_data.pop("sell_type", None)
    item = await load_item(item_id)
    await save_listing(lst)
    await update.message.reply_text(
        f"✅ *{item.name}* listed on the market!",
        parse_mode=ParseMode.MARKDOWN
    )


# ── /ranking ──────────────────────────────────────────────────

async def cmd_ranking(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    players = await all_players()
    players.sort(key=lambda p: (p.level, p.xp), reverse=True)
    top     = players[:10]
    medals  = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
    lines   = [
        f"{medals[i]} *{p.char_name}* ({p.char_class}) — Lvl {p.level} | {p.sessions_played} sessions | {p.gold}g"
        for i, p in enumerate(top)
    ]
    await update.message.reply_text(
        "🏆 *Global Rankings*\n\n" + "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN
    )
