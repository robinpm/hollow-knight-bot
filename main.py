"""
Entry point for the Hollow Knight Progress Tracker Discord bot.

sThis module initializes the Discord client, defines command handlers, and runs
two background tasks: a keep-alive HTTP server (for Render free tier) and a
summary loop that triggers daily recaps using the Gemini integration.
"""

import os
import re
import asyncio
import logging
from datetime import datetime, time, timedelta, timezone

import discord
from aiohttp import web

from database import Database
from gemini_integration import generate_daily_summary

from typing import Optional, Dict, List, Tuple
# Configure logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("hollowbot")

# Retrieve essential environment variables
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN environment variable")

# Database URL can point to Postgres or default to local SQLite
DB_URL = os.getenv("DATABASE_URL", "sqlite:///data.sqlite")
# Port for the keep-alive HTTP server. Render injects PORT for web services.
PORT = int(os.getenv("PORT", "10000"))

# Instantiate the database
db = Database(DB_URL)

# Configure Discord intents: minimal by default but enable message content and members
intents = discord.Intents.default()
intents.message_content = True  # required to read messages for mention-commands
intents.members = True  # needed to fetch display names for recaps
client = discord.Client(intents=intents)

# Regular expression to parse commands addressing the bot
MENTION_RE = re.compile(r"^<@!?(\d+)>")

HELP_TEXT = (
    "Commands (mention me first):\n"
    "• progress <text> — save your progress.\n"
    "• get_progress [@user] — show last update (yours by default).\n"
    "• set_reminder_channel — set this channel for daily recap (admin).\n"
    "• schedule_daily_reminder <HH:MM> — UTC time for daily recap (admin).\n"
    "Example: @HollowBot schedule_daily_reminder 18:00"
)


def is_admin(member: discord.Member) -> bool:
    """Determine if a guild member has administrative permissions."""
    permissions = member.guild_permissions
    return (
        permissions.administrator
        or permissions.manage_guild
        or permissions.manage_channels
    )


async def keepalive_server() -> None:
    """Run a tiny HTTP server to keep the Render web service awake."""

    async def handle(_request):
        return web.Response(text="ok")

    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    log.info("Keepalive HTTP server listening on port %d", PORT)


async def summary_loop() -> None:
    """Periodically check schedules and send daily recaps."""
    await client.wait_until_ready()
    log.info("Summary loop started")
    while not client.is_closed():
        try:
            now = datetime.now(timezone.utc)
            current_hhmm = now.strftime("%H:%M")
            for settings in db.all_schedules():
                # If no channel or time is set, skip
                if not settings.reminder_channel_id or not settings.reminder_utc_time:
                    continue
                # Avoid sending multiple times per day
                already_today = (
                    settings.last_summary_at
                    and settings.last_summary_at.astimezone(timezone.utc).date()
                    == now.date()
                )
                if settings.reminder_utc_time == current_hhmm and not already_today:
                    # Determine time window for updates: since last summary or since midnight UTC
                    since = settings.last_summary_at or datetime.combine(
                        now.date(), time(0, 0), tzinfo=timezone.utc
                    )
                    updates = db.get_updates_since(settings.guild_id, since)
                    # Map user IDs to display names, falling back to ID string
                    guild = client.get_guild(settings.guild_id)
                    pretty_updates: Dict[str, List[str]] = {}
                    if guild:
                        for uid, items in updates.items():
                            member = guild.get_member(uid) or await guild.fetch_member(uid)
                            name = member.display_name if member else f"User {uid}"
                            pretty_updates[name] = items
                    else:
                        pretty_updates = {str(uid): items for uid, items in updates.items()}
                    # Generate recap text via Gemini
                    recap = generate_daily_summary(
                        guild.name if guild else f"Guild {settings.guild_id}",
                        pretty_updates,
                    )
                    # Send to configured channel
                    channel = client.get_channel(
                        settings.reminder_channel_id
                    ) or await client.fetch_channel(settings.reminder_channel_id)
                    await channel.send(recap)
                    db.mark_summary_sent(settings.guild_id)
        except Exception as exc:
            log.exception("Error in summary loop: %s", exc)
        # Check schedules once per minute
        await asyncio.sleep(60)


@client.event
async def on_ready() -> None:
    """Triggered when the bot logs in."""
    log.info("Logged in as %s", client.user)
    # Start HTTP server and summary loop tasks
    asyncio.create_task(keepalive_server())
    asyncio.create_task(summary_loop())


def parse_command(message: discord.Message) -> tuple[Optional[str], Optional[str]]:
    """Parse a message to extract the command and its arguments."""
    match = MENTION_RE.match(message.content.strip())
    if not match:
        return None, None
    # Ensure the bot is being mentioned
    if int(match.group(1)) != client.user.id:
        return None, None
    rest = message.content[match.end() :].strip()
    if not rest:
        return "help", ""
    parts = rest.split(None, 1)
    cmd = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""
    return cmd, args


# Time format validator: ensures "HH:MM" with 24-hour clock
TIME_RE = re.compile(r"^(?:[01]?\d|2[0-3]):[0-5]\d$")


@client.event
async def on_message(message: discord.Message) -> None:
    """Handle incoming messages for commands after mention."""
    # Ignore messages from bots or direct messages
    if message.author.bot or not message.guild:
        return
    cmd, args = parse_command(message)
    if not cmd:
        return
    # Help command
    if cmd in ("help", "commands"):
        await message.reply(HELP_TEXT)
        return
    # Save progress
    if cmd == "progress":
        content = args.strip()
        if not content:
            await message.reply("Usage: @HollowBot progress <what you did>")
            return
        db.add_progress(message.guild.id, message.author.id, content)
        await message.add_reaction("✅")
        return
    # Get last progress
    if cmd == "get_progress":
        # Find mentioned user other than the bot; default to author
        target = message.author
        for user in message.mentions:
            if user.id != client.user.id:
                target = user
                break
        result = db.get_last_progress(message.guild.id, target.id)
        if not result:
            await message.reply(f"No progress saved for {target.display_name} yet.")
        else:
            content, timestamp = result
            ts_str = timestamp.astimezone(timezone.utc).strftime(
                "%Y-%m-%d %H:%M UTC"
            )
            await message.reply(
                f"Last for **{target.display_name}**: “{content}”  (`{ts_str}`)"
            )
        return
    # Set reminder channel (admin only)
    if cmd == "set_reminder_channel":
        if not is_admin(message.author):
            await message.reply("You need Manage Server to do that.")
            return
        db.upsert_channel(message.guild.id, message.channel.id)
        await message.reply(
            f"Daily recap channel set to {message.channel.mention}."
        )
        return
    # Schedule daily recap (admin only)
    if cmd == "schedule_daily_reminder":
        if not is_admin(message.author):
            await message.reply("You need Manage Server to do that.")
            return
        time_arg = args.strip()
        if not TIME_RE.match(time_arg):
            await message.reply("Give me a time like `18:00` (UTC).")
            return
        db.set_schedule(message.guild.id, time_arg)
        await message.reply(
            f"Daily recap scheduled for **{time_arg} UTC**."
        )
        return
    # Unknown command
    await message.reply("Unknown command. Type: @HollowBot help")


if __name__ == "__main__":
    client.run(DISCORD_TOKEN)
