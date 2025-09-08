"""Discord bot that tracks Hollow Knight progress and posts recaps."""

import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

import database
from gemini_integration import generate_daily_summary, generate_reply

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("hollowbot")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN env var")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix=None, intents=intents)

MENTION_RE = re.compile(r"^<@!?(\d+)>\s*")
TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
PROGRESS_RE = re.compile(r"\b(beat|got|found|upgraded)\b", re.I)
last_sent: Dict[str, datetime.date] = {}


def is_admin(member: discord.Member) -> bool:
    perms = member.guild_permissions
    return perms.administrator or perms.manage_guild or perms.manage_channels


def _parse_mention_command(content: str) -> tuple[bool, str]:
    """Return (mentioned, rest_of_message)."""
    m = MENTION_RE.match(content)
    if not m:
        return False, ""
    return True, content[m.end():]


def _build_updates_context(guild: discord.Guild) -> str:
    updates = database.get_updates_today_by_guild(guild.id)
    lines: List[str] = []
    for uid, texts in updates.items():
        member = guild.get_member(int(uid))
        name = member.display_name if member else f"User {uid}"
        lines.append(f"{name}: {', '.join(texts)}")
    return "\n".join(lines) if lines else "No updates yet today."


def _build_progress_reply(guild: discord.Guild, text: str) -> str:
    context = _build_updates_context(guild)
    riff = generate_reply(f"Recent updates:\n{context}\nNew update: {text}")
    reply = f"Noted: {text}"
    if riff and riff != "Noted.":
        reply += f"\n{riff}"
    return reply


@bot.event
async def on_ready() -> None:
    await bot.tree.sync()
    log.info("Logged in as %s", bot.user)
    recap_tick.start()


@bot.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot or not message.guild or not bot.user:
        return
    mentioned, rest = _parse_mention_command(message.content.strip())
    if not mentioned or message.mentions[0].id != bot.user.id:
        return
    rest = rest.strip()
    if not rest:
        return

    log.info("Mention from %s: %s", message.author.id, rest)

    if PROGRESS_RE.search(rest):
        await handle_progress(message, rest)
        return

    context = _build_updates_context(message.guild)
    prompt = f"Recent updates:\n{context}\nUser said: {rest}"
    reply = generate_reply(prompt)
    await message.reply(reply or "Noted.")


async def handle_progress(message: discord.Message, text: str) -> None:
    if not text:
        await message.reply("Usage: @HollowBot progress <what you did>")
        return
    now_ts = int(time.time())
    last = database.get_last_update(message.guild.id, message.author.id)
    database.add_update(message.guild.id, message.author.id, text, now_ts)
    reply = _build_progress_reply(message.guild, text)
    await message.reply(reply)
    if last:
        days = (now_ts - last[1]) // 86400
        if days > 30:
            await message.channel.send("dang you beat Mantis months ago, slow-poke.")


hollow_group = app_commands.Group(name="hollow-bot", description="Hollow Bot commands")


@hollow_group.command(name="progress", description="Log your progress")
async def slash_progress(interaction: discord.Interaction, text: str) -> None:
    if not interaction.guild:
        await interaction.response.send_message("Guild only", ephemeral=True)
        return
    now_ts = int(time.time())
    last = database.get_last_update(interaction.guild.id, interaction.user.id)
    database.add_update(interaction.guild.id, interaction.user.id, text, now_ts)
    reply = _build_progress_reply(interaction.guild, text)
    await interaction.response.send_message(reply)
    if last:
        days = (now_ts - last[1]) // 86400
        if days > 30 and interaction.channel:
            await interaction.channel.send("dang you beat Mantis months ago, slow-poke.")


@hollow_group.command(name="get_progress", description="Show latest progress")
async def slash_get_progress(
    interaction: discord.Interaction, user: Optional[discord.Member] = None
) -> None:
    if not interaction.guild:
        await interaction.response.send_message("Guild only", ephemeral=True)
        return
    target = user or interaction.user
    result = database.get_last_update(interaction.guild.id, target.id)
    if not result:
        await interaction.response.send_message(
            f"No progress saved for {target.display_name} yet."
        )
        return
    text, ts = result
    age_sec = int(time.time()) - ts
    days = age_sec // 86400
    hours = age_sec // 3600
    age_str = f"{days}d" if days else f"{hours}h"
    await interaction.response.send_message(
        f"Last for **{target.display_name}**: “{text}” ({age_str} ago)"
    )


@hollow_group.command(name="set_reminder_channel", description="Set recap channel")
async def slash_set_channel(interaction: discord.Interaction) -> None:
    if not interaction.guild or not interaction.channel:
        await interaction.response.send_message("Guild only", ephemeral=True)
        return
    if not is_admin(interaction.user):
        await interaction.response.send_message(
            "You need Manage Server to do that.", ephemeral=True
        )
        return
    database.set_recap_channel(interaction.guild.id, interaction.channel.id)
    await interaction.response.send_message(
        f"Daily recap channel set to {interaction.channel.mention}."
    )


@hollow_group.command(
    name="schedule_daily_reminder", description="Schedule daily recap (UTC)"
)
async def slash_schedule(interaction: discord.Interaction, time: str) -> None:
    if not interaction.guild:
        await interaction.response.send_message("Guild only", ephemeral=True)
        return
    if not is_admin(interaction.user):
        await interaction.response.send_message(
            "You need Manage Server to do that.", ephemeral=True
        )
        return
    if not TIME_RE.match(time):
        await interaction.response.send_message(
            "Give me a time like `18:00` (UTC).", ephemeral=True
        )
        return
    database.set_recap_time(interaction.guild.id, time)
    await interaction.response.send_message(
        f"Daily recap scheduled for **{time} UTC**."
    )


bot.tree.add_command(hollow_group)


@tasks.loop(minutes=1)
async def recap_tick() -> None:
    if not bot.user:
        return
    now = datetime.now(timezone.utc)
    hhmm = now.strftime("%H:%M")
    for guild_id, channel_id, recap_time in database.get_all_guild_configs():
        if not channel_id or recap_time != hhmm:
            continue
        if last_sent.get(guild_id) == now.date():
            continue
        updates = database.get_updates_today_by_guild(int(guild_id))
        guild = bot.get_guild(int(guild_id))
        pretty: Dict[str, List[str]] = {}
        if guild:
            for uid, items in updates.items():
                member = guild.get_member(int(uid)) or await guild.fetch_member(int(uid))
                name = member.display_name if member else f"User {uid}"
                pretty[name] = items
        else:
            pretty = {uid: items for uid, items in updates.items()}
        summary = generate_daily_summary(
            guild.name if guild else f"Guild {guild_id}", pretty
        )
        channel = bot.get_channel(int(channel_id)) or await bot.fetch_channel(
            int(channel_id)
        )
        await channel.send(summary)
        last_sent[guild_id] = now.date()


if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
