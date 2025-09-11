"""Discord bot that tracks Hollow Knight progress and posts recaps."""

# AI INSTRUCTION: ALWAYS increment BOT_VERSION when making any changes to this file
# Versioning rules:
# - Increment patch version (1.1 -> 1.2) for bug fixes, small features, or improvements
# - Increment minor version (1.x -> 2.0) for major new features or breaking changes
# - This version is used in /hollow-bot info command and health check endpoint
# Bot version - increment this for each release

BOT_VERSION = "1.10"

import asyncio
import os
import random
import re
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import pytz

import discord
from discord import app_commands
from discord.ext import commands, tasks
from aiohttp import web

from . import database
from .config import config
from ai.gemini_integration import generate_daily_summary, generate_memory, generate_reply
from ai.agents.response_decider import should_respond as agent_should_respond
from save_parsing.save_parser import (
    parse_hk_save,
    format_save_summary,
    generate_save_analysis,
    SaveDataError,
)
from .logger import log

from .validation import (
    ValidationError,
    validate_guild_id,
    validate_user_id,
    validate_progress_text,
    validate_time_format,
    validate_timezone,
    validate_channel_id,
    sanitize_mention_command,
    validate_server_name,
    validate_updates_dict,
    validate_custom_context,
)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix=config.command_prefix, intents=intents)

PROGRESS_RE = re.compile(r"\b(beat|got|found|upgraded)\b", re.I)
last_sent: Dict[str, datetime.date] = {}
  
SPONTANEOUS_RESPONSE_CHANCE = config.spontaneous_response_chance
guild_spontaneous_chances: Dict[int, float] = {}


def is_admin(member: discord.Member) -> bool:
    perms = member.guild_permissions
    return perms.administrator or perms.manage_guild or perms.manage_channels


def _build_updates_context(guild: discord.Guild) -> str:
    """Build context string from today's updates."""
    try:
        validate_guild_id(guild.id)
        updates = database.get_updates_today_by_guild(guild.id)
        validated_updates = validate_updates_dict(updates)

        lines: List[str] = []
        for uid, texts in validated_updates.items():
            try:
                member = guild.get_member(int(uid))
                name = member.display_name if member else f"User {uid}"
                lines.append(f"{name}: {', '.join(texts)}")
            except (ValueError, TypeError) as e:
                log.warning(f"Invalid user ID in updates: {uid}, error: {e}")
                continue

        return "\n".join(lines) if lines else "No updates yet today."
    except (ValidationError, database.DatabaseError) as e:
        log.error(f"Failed to build updates context: {e}")
        return "The echoes of Hallownest are temporarily silent."


def _build_memories_context(guild: discord.Guild) -> str:
    """Build context string from stored memories."""
    try:
        validate_guild_id(guild.id)
        memories = database.get_memories_by_guild(guild.id)
        lines = [m for _, m in memories]
        return "\n".join(lines) if lines else "No memories yet."
    except (ValidationError, database.DatabaseError) as e:
        log.error(f"Failed to build memories context: {e}")
        return "The Chronicler remembers nothing."


async def _get_recent_messages(message: discord.Message, limit: int = 10) -> tuple[str, str]:
    """Return previous messages and current message separately for clear context."""
    previous_lines: List[str] = []
    try:
        async for msg in message.channel.history(limit=limit, before=message):
            if msg.author.bot or not msg.content:
                continue
            previous_lines.append(f"{msg.author.display_name}: {msg.content.strip()}")
    except Exception as e:
        log.warning(f"Failed to fetch recent messages: {e}")

    previous_lines.reverse()
    previous_messages = "\n".join(previous_lines) if previous_lines else "No previous messages."
    current_message = f"{message.author.display_name}: {message.content.strip()}"
    
    return previous_messages, current_message


def _should_respond(
    previous_messages: str, current_message: str, guild_context: str, author: str, custom_context: str
) -> bool:
    """Use AI agent to decide if the bot should reply to a message."""
    try:
        return agent_should_respond(previous_messages, current_message, guild_context, author, custom_context)
    except Exception as e:
        log.error(f"Error deciding to respond: {e}")
        return False


def _build_progress_reply(guild: discord.Guild, text: str) -> str:
    """Build a progress reply with AI-generated commentary."""
    try:
        validated_text = validate_progress_text(text)
        updates = _build_updates_context(guild)
        memories = _build_memories_context(guild)
        custom_context = database.get_custom_context(guild.id)
        edginess = database.get_edginess(guild.id)

        preamble = f"{custom_context}\n" if custom_context else ""
        prompt = (
            f"{preamble}Memories:\n{memories}\n\nRecent updates:\n{updates}\nNew update: {validated_text}\n\n"
            "Give a short, snarky gamer response (1-2 sentences max) about this progress update. Do NOT include 'HollowBot:' or any name prefix in your response."
        )
        riff = generate_reply(prompt, edginess=edginess)

        reply = f"📝 Echo recorded: {validated_text}"
        if riff and riff not in [
            "Noted.",
            "Noted, gamer. The echoes of Hallownest have been recorded.",
        ]:
            reply += f"\n\n{riff}"

        return reply
    except ValidationError as e:
        log.warning(f"Invalid progress text: {e}")
        return "Gamer, that progress update seems corrupted by the Infection. Try again with a cleaner message!"
    except Exception as e:
        log.error(f"Failed to build progress reply: {e}")
        return f"📝 Echo recorded: {text}\n\nThe Chronicler had trouble processing that one, but it's noted!"


@bot.event
async def on_ready() -> None:
    """Handle bot ready event."""
    try:
        await bot.tree.sync()
        log.info("HollowBot logged in as %s", bot.user)
        recap_tick.start()
    except Exception as e:
        log.error(f"Failed to sync commands or start tasks: {e}")
        raise


@bot.event
async def on_message(message: discord.Message) -> None:
    """Handle incoming messages."""
    if message.author.bot or not message.guild or not bot.user:
        return

    content = message.content.strip()
    
    # Check for .dat file attachments (Hollow Knight save data)
    if message.attachments:
        for attachment in message.attachments:
            if attachment.filename.lower().endswith('.dat'):
                # If bot is mentioned with a .dat file, treat it as progress
                if bot.user in message.mentions:
                    await handle_progress_save_data(message, attachment)
                else:
                    await handle_save_data(message, attachment)
                return
    
    if not content:
        return

    try:
        mentioned = bot.user in message.mentions

        if mentioned:
            for mention in message.mentions:
                content = content.replace(f"<@!{mention.id}>", "").replace(
                    f"<@{mention.id}>", ""
                )
            content = content.strip()

            if not content:
                await message.reply(
                    "Hey gamer! What's up? Ready to talk about your Hallownest journey?"
                )
                return

            log.info("Mention from %s: %s", message.author.id, content)
            custom_context = database.get_custom_context(message.guild.id)
            edginess = database.get_edginess(message.guild.id)

            if PROGRESS_RE.search(content):
                await handle_progress(message, content)
                return

            guild_context = _build_updates_context(message.guild)
            user_progress = database.get_last_update(
                message.guild.id, message.author.id
            )
            user_context = ""
            if user_progress:
                text, ts = user_progress
                age_sec = int(time.time()) - ts
                days = age_sec // 86400
                hours = age_sec // 3600
                age_str = f"{days}d" if days else f"{hours}h"
                user_context = f'\nYour last progress: "{text}" ({age_str} ago)'

            previous_messages, current_message = await _get_recent_messages(message)
            memories = _build_memories_context(message.guild)
            preamble = ""
            if custom_context:
                preamble += f"{custom_context}\n"
            preamble += f"Edginess level: {edginess}\n"
            prompt = (
                f"{preamble}Memories:\n{memories}\n\nPrevious conversation:\n{previous_messages}\n\n"
                f"CURRENT MESSAGE (the one you're responding to):\n{current_message}\n\n"
                "Recent updates from everyone:\n"
                f"{guild_context}{user_context}\n"
                "Respond as HollowBot to the CURRENT MESSAGE, referencing their progress if relevant. "
                "Keep it short and gamer-like (1-2 sentences max). Do NOT include 'HollowBot:' or any name prefix in your response."
            )
            reply = generate_reply(prompt, edginess=edginess)
            await message.reply(
                reply or "The echoes of Hallownest have been heard, gamer."
            )
        else:
            chance = guild_spontaneous_chances.get(
                message.guild.id, SPONTANEOUS_RESPONSE_CHANCE
            )
            if random.random() < chance:
                log.info("Spontaneous response triggered in guild %s", message.guild.id)
                guild_context = _build_updates_context(message.guild)
                memories = _build_memories_context(message.guild)
                previous_messages, current_message = await _get_recent_messages(message)
                custom_context = database.get_custom_context(message.guild.id)
                edginess = database.get_edginess(message.guild.id)
                if _should_respond(
                    previous_messages, current_message, guild_context, message.author.display_name, custom_context
                ):
                    preamble = ""
                    if custom_context:
                        preamble += f"{custom_context}\n"
                    preamble += f"Edginess level: {edginess}\n"
                    prompt = (
                        f"{preamble}Memories:\n{memories}\n\nPrevious conversation:\n{previous_messages}\n\n"
                        f"CURRENT MESSAGE (the one you're responding to):\n{current_message}\n\n"
                        "Recent updates from everyone:\n"
                        f"{guild_context}\n"
                        "Respond as HollowBot to the CURRENT MESSAGE. Keep it short and gamer-like (1-2 sentences max). Do NOT include 'HollowBot:' or any name prefix in your response."
                    )
                    reply = generate_reply(prompt, edginess=edginess)
                    if reply:
                        await message.reply(reply)


    except commands.CommandError as e:
        # Ignore command-related errors and let default handlers deal with them
        log.debug(f"Command error in on_message: {e}")
    except Exception as e:
        log.error(f"Error handling message: {e}")
        if bot.user in message.mentions:
            try:
                await message.reply(
                    "The Infection got to my response system. But I heard you, gamer!"
                )
            except Exception as reply_error:
                log.error(f"Failed to send error reply: {reply_error}")
    finally:
        await bot.process_commands(message)


async def handle_progress(message: discord.Message, text: str) -> None:
    """Handle progress updates with validation and error handling."""
    try:
        if not text:
            await message.reply(
                "Gamer, you gotta tell me what you accomplished! Usage: @HollowBot progress <what you did>"
            )
            return

        # Validate inputs
        validate_guild_id(message.guild.id)
        validate_user_id(message.author.id)
        validated_text = validate_progress_text(text)

        now_ts = int(time.time())
        last = database.get_last_update(message.guild.id, message.author.id)
        database.add_update(message.guild.id, message.author.id, validated_text, now_ts)

        # Parse and store achievements
        achievement = parse_hollow_knight_achievement(validated_text)
        if achievement:
            achievement_type, achievement_name = achievement
            database.add_achievement(message.guild.id, message.author.id, achievement_type, achievement_name, validated_text, now_ts)

        mem = generate_memory(validated_text)
        if mem:
            database.add_memory(message.guild.id, mem)

        # Debug: Verify the update was added
        log.info(
            f"Added progress for user {message.author.id} in guild {message.guild.id}: {validated_text}"
        )
        verify = database.get_last_update(message.guild.id, message.author.id)
        log.info(f"Verification - last update: {verify}")

        reply = _build_progress_reply(message.guild, validated_text)
        await message.reply(reply)

        # Check for long absence
        if last:
            days = (now_ts - last[1]) // 86400
            if days > 30:
                await message.channel.send(
                    "Bruh, you beat the Mantis Lords months ago and you're still here? That's some serious dedication to the grind, gamer. Respect."
                )

    except ValidationError as e:
        log.warning(f"Validation error in handle_progress: {e}")
        await message.reply(
            "Gamer, that progress update seems corrupted by the Infection. Try again with a cleaner message!"
        )
    except database.DatabaseError as e:
        log.error(f"Database error in handle_progress: {e}")
        await message.reply(
            "The echoes of Hallownest are having trouble reaching the chronicle. Try again later, gamer!"
        )
    except Exception as e:
        log.error(f"Unexpected error in handle_progress: {e}")
        await message.reply(
            "The Infection got to my progress tracking system. But I'll try to remember that, gamer!"
        )


async def handle_progress_save_data(message: discord.Message, attachment: discord.Attachment) -> None:
    """Handle Hollow Knight save data file uploads as progress updates."""
    try:
        log.info(f"Processing progress save data from {message.author.display_name}: {attachment.filename}")
        
        # Download the file content
        file_content = await attachment.read()
        
        # Parse the save data
        summary = parse_hk_save(file_content)
        
        # Create progress text from save data
        progress_text = f"Uploaded save data: {summary['completion_percent']}% complete, {summary['playtime_hours']}h playtime, {summary['deaths']} deaths"
        
        # Store as progress update
        now_ts = int(time.time())
        database.add_update(message.guild.id, message.author.id, progress_text, now_ts)
        
        # Generate memory from the save data
        mem = generate_memory(progress_text)
        if mem:
            database.add_memory(message.guild.id, mem)
        
        # Format the summary
        formatted_summary = format_save_summary(summary)
        
        # Generate AI analysis
        analysis = generate_save_analysis(summary)
        
        # Send the response
        response = f"{formatted_summary}\n\n{analysis}"
        await message.reply(response)
        
        log.info(f"Successfully processed progress save data for user {message.author.id}")
        
    except SaveDataError as e:
        log.warning(f"Save data parsing error: {e}")
        await message.reply(
            f"Gamer, that save file seems corrupted by the Infection! {e}\n\n"
            "Make sure you're uploading a valid Hollow Knight save file (.dat format)."
        )
    except Exception as e:
        log.error(f"Unexpected error processing progress save data: {e}")
        await message.reply(
            "The Infection got to my save data analyzer! But I heard you uploaded something, gamer!"
        )


async def handle_save_data(message: discord.Message, attachment: discord.Attachment) -> None:
    """Handle Hollow Knight save data file uploads."""
    try:
        log.info(f"Processing save data from {message.author.display_name}: {attachment.filename}")
        
        # Download the file content
        file_content = await attachment.read()
        
        # Parse the save data
        summary = parse_hk_save(file_content)
        
        # Format the summary
        formatted_summary = format_save_summary(summary)
        
        # Generate AI analysis
        analysis = generate_save_analysis(summary)
        
        # Send the response
        response = f"{formatted_summary}\n\n{analysis}"
        await message.reply(response)
        
        # Also store this as a progress update
        progress_text = f"Uploaded save data: {summary['completion_percent']}% complete, {summary['playtime_hours']}h playtime"
        now_ts = int(time.time())
        database.add_update(message.guild.id, message.author.id, progress_text, now_ts)
        
        log.info(f"Successfully processed save data for user {message.author.id}")
        
    except SaveDataError as e:
        log.warning(f"Save data parsing error: {e}")
        await message.reply(
            f"Gamer, that save file seems corrupted by the Infection! {e}\n\n"
            "Make sure you're uploading a valid Hollow Knight save file (.dat format)."
        )
    except Exception as e:
        log.error(f"Unexpected error processing save data: {e}")
        await message.reply(
            "The Infection got to my save data analyzer! But I heard you uploaded something, gamer!"
        )


hollow_group = app_commands.Group(
    name="hollow-bot", description="Chronicle your Hallownest journey with HollowBot"
)


@hollow_group.command(
    name="progress", description="Record your latest Hallownest achievement"
)
async def slash_progress(interaction: discord.Interaction, text: str) -> None:
    """Handle slash command for progress updates."""
    try:
        if not interaction.guild:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Gamer, this command only works in servers. The echoes of Hallownest need a proper gathering place!",
                    ephemeral=True,
                )
            return

        # Validate inputs
        validate_guild_id(interaction.guild.id)
        validate_user_id(interaction.user.id)
        validated_text = validate_progress_text(text)

        now_ts = int(time.time())
        last = database.get_last_update(interaction.guild.id, interaction.user.id)
        database.add_update(
            interaction.guild.id, interaction.user.id, validated_text, now_ts
        )

        # Parse and store achievements
        achievement = parse_hollow_knight_achievement(validated_text)
        if achievement:
            achievement_type, achievement_name = achievement
            database.add_achievement(interaction.guild.id, interaction.user.id, achievement_type, achievement_name, validated_text, now_ts)

        mem = generate_memory(validated_text)
        if mem:
            database.add_memory(interaction.guild.id, mem)

        # Debug: Verify the update was added
        log.info(
            f"Added progress for user {interaction.user.id} in guild {interaction.guild.id}: {validated_text}"
        )
        verify = database.get_last_update(interaction.guild.id, interaction.user.id)
        log.info(f"Verification - last update: {verify}")

        reply = _build_progress_reply(interaction.guild, validated_text)

        if not interaction.response.is_done():
            await interaction.response.send_message(reply)
        else:
            await interaction.followup.send(reply)

        # Check for long absence
        if last:
            days = (now_ts - last[1]) // 86400
            if days > 30 and interaction.channel:
                await interaction.channel.send(
                    "Bruh, you beat the Mantis Lords months ago and you're still here? That's some serious dedication to the grind, gamer. Respect."
                )

    except ValidationError as e:
        log.warning(f"Validation error in slash_progress: {e}")
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "Gamer, that progress update seems corrupted by the Infection. Try again with a cleaner message!",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                "Gamer, that progress update seems corrupted by the Infection. Try again with a cleaner message!",
                ephemeral=True,
            )
    except database.DatabaseError as e:
        log.error(f"Database error in slash_progress: {e}")
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "The echoes of Hallownest are having trouble reaching the chronicle. Try again later, gamer!",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                "The echoes of Hallownest are having trouble reaching the chronicle. Try again later, gamer!",
                ephemeral=True,
            )
    except Exception as e:
        log.error(f"Unexpected error in slash_progress: {e}")
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "The Infection got to my progress tracking system. But I'll try to remember that, gamer!",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                "The Infection got to my progress tracking system. But I'll try to remember that, gamer!",
                ephemeral=True,
            )


@hollow_group.command(
    name="get_progress", description="Check the latest echo from a gamer's journey"
)
async def slash_get_progress(
    interaction: discord.Interaction, user: Optional[discord.Member] = None
) -> None:
    try:
        if not interaction.guild:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Gamer, this command only works in servers. The echoes of Hallownest need a proper gathering place!",
                    ephemeral=True,
                )
            return

        target = user or interaction.user
        log.info(
            f"Getting progress for user {target.id} in guild {interaction.guild.id}"
        )
        result = database.get_last_update(interaction.guild.id, target.id)
        log.info(f"Database returned: {result}")
        if not result:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"No echoes recorded for {target.display_name} yet. Time to start that Hallownest journey, gamer!"
                )
            else:
                await interaction.followup.send(
                    f"No echoes recorded for {target.display_name} yet. Time to start that Hallownest journey, gamer!"
                )
            return

        text, ts = result
        age_sec = int(time.time()) - ts
        days = age_sec // 86400
        hours = age_sec // 3600
        age_str = f"{days}d" if days else f"{hours}h"

        if not interaction.response.is_done():
            await interaction.response.send_message(
                f'📜 Last echo from **{target.display_name}**: "{text}" ({age_str} ago)'
            )
        else:
            await interaction.followup.send(
                f'📜 Last echo from **{target.display_name}**: "{text}" ({age_str} ago)'
            )
    except Exception as e:
        log.error(f"Error in slash_get_progress: {e}")
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "The Infection got to my memory system. Try again later, gamer!",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                "The Infection got to my memory system. Try again later, gamer!",
                ephemeral=True,
            )


@hollow_group.command(
    name="rando-talk",
    description="View or set my random chatter chance (0-100%)",
)
@app_commands.describe(
    chance="Percentage chance (0-100). Leave blank to view current setting"
)
async def slash_rando_talk(
    interaction: discord.Interaction, chance: Optional[int] = None
) -> None:
    try:
        if not interaction.guild:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Gamer, this command only works in servers. The echoes of Hallownest need a proper gathering place!",
                    ephemeral=True,
                )
            return

        if not is_admin(interaction.user):
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Only guild admins can tweak my chatter settings, gamer!",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    "Only guild admins can tweak my chatter settings, gamer!",
                    ephemeral=True,
                )
            return

        if chance is None:
            current = int(
                guild_spontaneous_chances.get(
                    interaction.guild.id, SPONTANEOUS_RESPONSE_CHANCE
                )
                * 100
            )
            message = f"Spontaneous chatter chance is {current}%"
            if not interaction.response.is_done():
                await interaction.response.send_message(message, ephemeral=True)
            else:
                await interaction.followup.send(message, ephemeral=True)
            return

        if chance < 0 or chance > 100:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Chance must be between 0 and 100, gamer!",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    "Chance must be between 0 and 100, gamer!",
                    ephemeral=True,
                )
            return

        guild_spontaneous_chances[interaction.guild.id] = chance / 100

        if not interaction.response.is_done():
            await interaction.response.send_message(
                f"Spontaneous chatter set to {chance}%",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                f"Spontaneous chatter set to {chance}%",
                ephemeral=True,
            )
    except Exception as e:
        log.error(f"Error in slash_rando_talk: {e}")
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "The Infection messed with my settings. Try again later, gamer!",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                "The Infection messed with my settings. Try again later, gamer!",
                ephemeral=True,
            )


@hollow_group.command(
    name="edginess",
    description="View or set my edginess level (1-10)",
)
@app_commands.describe(
    level="Edginess level (1-10). Leave blank to view current level"
)
async def slash_edginess(
    interaction: discord.Interaction, level: Optional[int] = None
) -> None:
    try:
        if not interaction.guild:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Gamer, this command only works in servers. The echoes of Hallownest need a proper gathering place!",
                    ephemeral=True,
                )
            return

        if not is_admin(interaction.user):
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Only guild admins can tweak my edginess, gamer!",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    "Only guild admins can tweak my edginess, gamer!",
                    ephemeral=True,
                )
            return

        if level is None:
            current = database.get_edginess(interaction.guild.id)
            message = f"Edginess level is {current}"
            if not interaction.response.is_done():
                await interaction.response.send_message(message, ephemeral=True)
            else:
                await interaction.followup.send(message, ephemeral=True)
            return

        if level < 1 or level > 10:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Level must be between 1 and 10, gamer!",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    "Level must be between 1 and 10, gamer!",
                    ephemeral=True,
                )
            return

        database.set_edginess(interaction.guild.id, level)

        if not interaction.response.is_done():
            await interaction.response.send_message(
                f"Edginess set to {level}",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                f"Edginess set to {level}",
                ephemeral=True,
            )
    except Exception as e:
        log.error(f"Error in slash_edginess: {e}")
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "The Infection messed with my settings. Try again later, gamer!",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                "The Infection messed with my settings. Try again later, gamer!",
                ephemeral=True,
            )


# Memory group converted to single command below


@hollow_group.command(name="memory", description="Manage server memories")
@app_commands.describe(
    action="Action to perform: add, list, or delete",
    text="Memory text (for add action)",
    memory_id="Memory ID to delete (for delete action)"
)
async def memory_command(
    interaction: discord.Interaction, 
    action: str, 
    text: Optional[str] = None, 
    memory_id: Optional[int] = None
) -> None:
    try:
        if not interaction.guild:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Gamer, this command only works in servers. The echoes of Hallownest need a proper gathering place!",
                    ephemeral=True,
                )
            return

        action = action.lower()
        
        if action == "add":
            if not text:
                message = "Gamer, you need to provide memory text! Usage: `/hollow-bot memory add <text>`"
            else:
                if not is_admin(interaction.user):
                    message = "Only guild admins can tweak my memories, gamer!"
                else:
                    mem_id = database.add_memory(interaction.guild.id, text)
                    message = f"Memory stored with ID {mem_id}."
            
        elif action == "list":
            memories = database.get_memories_by_guild(interaction.guild.id)
            if memories:
                lines = [f"{mid}: {text}" for mid, text in memories]
                message = "Stored memories:\n" + "\n".join(lines)
            else:
                message = "No memories stored."
                
        elif action == "delete":
            if memory_id is None:
                message = "Gamer, you need to provide a memory ID! Usage: `/hollow-bot memory delete <id>`"
            else:
                if not is_admin(interaction.user):
                    message = "Only guild admins can tweak my memories, gamer!"
                else:
                    database.delete_memory(interaction.guild.id, memory_id)
                    message = "Memory deleted."
            
        else:
            message = "Invalid action! Use: `add`, `list`, or `delete`"

        if not interaction.response.is_done():
            await interaction.response.send_message(message, ephemeral=True)
        else:
            await interaction.followup.send(message, ephemeral=True)
            
    except Exception as e:
        log.error(f"Error in memory_command: {e}")
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "The Infection got to my memory system. Try again later, gamer!",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                "The Infection got to my memory system. Try again later, gamer!",
                ephemeral=True,
            )


@hollow_group.command(name="custom-context", description="Manage custom prompt context")
@app_commands.describe(
    action="Action to perform: set, show, or clear",
    text="Custom context text (for set action)"
)
async def custom_context_command(
    interaction: discord.Interaction, 
    action: str, 
    text: Optional[str] = None
) -> None:
    try:
        if not interaction.guild:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Gamer, this command only works in servers. The echoes of Hallownest need a proper gathering place!",
                    ephemeral=True,
                )
            return

        action = action.lower()
        
        if action == "set":
            if not text:
                message = "Gamer, you need to provide context text! Usage: `/hollow-bot custom-context set <text>`"
            else:
                if not is_admin(interaction.user):
                    message = "Only guild admins can tweak my context, gamer!"
                else:
                    validated = validate_custom_context(text)
                    previous = database.get_custom_context(interaction.guild.id)
                    database.set_custom_context(interaction.guild.id, validated)
                    message = "Custom context updated!"
                    if previous:
                        message += f" Previous: {previous}"
                    else:
                        message += " Previous: none"
            
        elif action == "show":
            context = database.get_custom_context(interaction.guild.id)
            message = f"Current custom context: {context}" if context else "No custom context set."
                
        elif action == "clear":
            if not is_admin(interaction.user):
                message = "Only guild admins can tweak my context, gamer!"
            else:
                previous = database.get_custom_context(interaction.guild.id)
                database.clear_custom_context(interaction.guild.id)
                message = "Custom context cleared."
                if previous:
                    message += f" Previous: {previous}"
            
        else:
            message = "Invalid action! Use: `set`, `show`, or `clear`"

        if not interaction.response.is_done():
            await interaction.response.send_message(message, ephemeral=True)
        else:
            await interaction.followup.send(message, ephemeral=True)
            
    except ValidationError as e:
        log.warning(f"Validation error in custom_context_command: {e}")
        if not interaction.response.is_done():
            await interaction.response.send_message(str(e), ephemeral=True)
        else:
            await interaction.followup.send(str(e), ephemeral=True)
    except Exception as e:
        log.error(f"Error in custom_context_command: {e}")
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "The Infection got to my context system. Try again later, gamer!",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                "The Infection got to my context system. Try again later, gamer!",
                ephemeral=True,
            )


# Groups converted to single commands above


@hollow_group.command(
    name="set_reminder_channel",
    description="Set the chronicle channel for daily echoes",
)
async def slash_set_channel(interaction: discord.Interaction) -> None:
    try:
        if not interaction.guild or not interaction.channel:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Gamer, this command only works in servers. The echoes of Hallownest need a proper gathering place!",
                    ephemeral=True,
                )
            return

        if not is_admin(interaction.user):
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Gamer, you need Manage Server permissions to set up the chronicle channel. The Infection won't let just anyone mess with the echoes.",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    "Gamer, you need Manage Server permissions to set up the chronicle channel. The Infection won't let just anyone mess with the echoes.",
                    ephemeral=True,
                )
            return

        database.set_recap_channel(interaction.guild.id, interaction.channel.id)

        if not interaction.response.is_done():
            await interaction.response.send_message(
                f"📜 Chronicle channel set to {interaction.channel.mention}. The echoes of Hallownest will be recorded here daily, gamer!"
            )
        else:
            await interaction.followup.send(
                f"📜 Chronicle channel set to {interaction.channel.mention}. The echoes of Hallownest will be recorded here daily, gamer!"
            )
    except Exception as e:
        log.error(f"Error in slash_set_channel: {e}")
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "The Infection got to my channel setup system. Try again later, gamer!",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                "The Infection got to my channel setup system. Try again later, gamer!",
                ephemeral=True,
            )


def parse_hollow_knight_achievement(progress_text: str) -> Optional[Tuple[str, str]]:
    """Parse Hollow Knight achievement from progress text. Returns (achievement_type, achievement_name) or None."""
    text = progress_text.lower()
    
    # Boss achievements
    boss_patterns = {
        "false knight": ("boss", "False Knight"),
        "hornet": ("boss", "Hornet"),
        "mantis lords": ("boss", "Mantis Lords"),
        "soul master": ("boss", "Soul Master"),
        "crystal guardian": ("boss", "Crystal Guardian"),
        "dung defender": ("boss", "Dung Defender"),
        "broken vessel": ("boss", "Broken Vessel"),
        "watcher knights": ("boss", "Watcher Knights"),
        "nosk": ("boss", "Nosk"),
        "flukemarm": ("boss", "Flukemarm"),
        "collector": ("boss", "The Collector"),
        "hollow knight": ("boss", "Hollow Knight"),
        "radiance": ("boss", "The Radiance"),
        "grimm": ("boss", "Nightmare King Grimm"),
        "pure vessel": ("boss", "Pure Vessel"),
        "absolute radiance": ("boss", "Absolute Radiance"),
        "grey prince zote": ("boss", "Grey Prince Zote"),
        "white defender": ("boss", "White Defender"),
        "failed champion": ("boss", "Failed Champion"),
        "lost kin": ("boss", "Lost Kin"),
        "soul tyrant": ("boss", "Soul Tyrant"),
        "enraged guardian": ("boss", "Enraged Guardian"),
        "god tamer": ("boss", "God Tamer"),
        "troupe master grimm": ("boss", "Troupe Master Grimm"),
        "nailsage sly": ("boss", "Nailsage Sly"),
        "paintmaster sheo": ("boss", "Paintmaster Sheo"),
        "great nailsage sly": ("boss", "Great Nailsage Sly"),
        "pure vessel": ("boss", "Pure Vessel"),
        "winged nosk": ("boss", "Winged Nosk"),
        "marmu": ("boss", "Marmu"),
        "galien": ("boss", "Galien"),
        "markoth": ("boss", "Markoth"),
        "xero": ("boss", "Xero"),
        "gorb": ("boss", "Gorb"),
        "elder hu": ("boss", "Elder Hu"),
        "no eyes": ("boss", "No Eyes"),
        "uumuu": ("boss", "Uumuu"),
        "hive knight": ("boss", "Hive Knight"),
        "sisters of battle": ("boss", "Sisters of Battle"),
        "oblobbles": ("boss", "Oblobbles"),
        "sly": ("boss", "Sly"),
        "sheo": ("boss", "Sheo"),
        "oro and mato": ("boss", "Oro and Mato"),
        "zote": ("boss", "Zote"),
    }
    
    # Area achievements
    area_patterns = {
        "forgotten crossroads": ("area", "Forgotten Crossroads"),
        "greenpath": ("area", "Greenpath"),
        "fungal wastes": ("area", "Fungal Wastes"),
        "city of tears": ("area", "City of Tears"),
        "crystal peak": ("area", "Crystal Peak"),
        "royal waterways": ("area", "Royal Waterways"),
        "deepnest": ("area", "Deepnest"),
        "ancient basin": ("area", "Ancient Basin"),
        "kingdom's edge": ("area", "Kingdom's Edge"),
        "queen's gardens": ("area", "Queen's Gardens"),
        "howling cliffs": ("area", "Howling Cliffs"),
        "resting grounds": ("area", "Resting Grounds"),
        "hive": ("area", "The Hive"),
        "godhome": ("area", "Godhome"),
        "white palace": ("area", "White Palace"),
        "path of pain": ("area", "Path of Pain"),
        "abyss": ("area", "The Abyss"),
        "colosseum": ("area", "Colosseum of Fools"),
    }
    
    # Upgrade achievements
    upgrade_patterns = {
        "nail upgrade": ("upgrade", "Nail Upgrade"),
        "nail art": ("upgrade", "Nail Art"),
        "spell upgrade": ("upgrade", "Spell Upgrade"),
        "vessel fragment": ("upgrade", "Vessel Fragment"),
        "mask shard": ("upgrade", "Mask Shard"),
        "charm": ("upgrade", "Charm"),
        "notch": ("upgrade", "Charm Notch"),
        "soul vessel": ("upgrade", "Soul Vessel"),
        "pale ore": ("upgrade", "Pale Ore"),
        "crystal heart": ("upgrade", "Crystal Heart"),
        "monarch wings": ("upgrade", "Monarch Wings"),
        "mothwing cloak": ("upgrade", "Mothwing Cloak"),
        "mantis claw": ("upgrade", "Mantis Claw"),
        "isma's tear": ("upgrade", "Isma's Tear"),
        "shade cloak": ("upgrade", "Shade Cloak"),
        "king's brand": ("upgrade", "King's Brand"),
        "awoken dream nail": ("upgrade", "Awoken Dream Nail"),
    }
    
    # Collectible achievements
    collectible_patterns = {
        "geo": ("collectible", "Geo"),
        "grub": ("collectible", "Grub"),
        "relic": ("collectible", "Relic"),
        "wanderer's journal": ("collectible", "Wanderer's Journal"),
        "hallownest seal": ("collectible", "Hallownest Seal"),
        "king's idol": ("collectible", "King's Idol"),
        "arcadia egg": ("collectible", "Arcadia Egg"),
        "rancid egg": ("collectible", "Rancid Egg"),
        "lifeblood core": ("collectible", "Lifeblood Core"),
        "lifeblood cocoon": ("collectible", "Lifeblood Cocoon"),
    }
    
    # Check for boss achievements
    for pattern, (achievement_type, name) in boss_patterns.items():
        if pattern in text and any(word in text for word in ["beat", "defeated", "killed", "fought"]):
            return (achievement_type, name)
    
    # Check for area achievements
    for pattern, (achievement_type, name) in area_patterns.items():
        if pattern in text and any(word in text for word in ["explored", "found", "discovered", "reached", "entered"]):
            return (achievement_type, name)
    
    # Check for upgrade achievements
    for pattern, (achievement_type, name) in upgrade_patterns.items():
        if pattern in text and any(word in text for word in ["got", "found", "obtained", "upgraded", "unlocked"]):
            return (achievement_type, name)
    
    # Check for collectible achievements
    for pattern, (achievement_type, name) in collectible_patterns.items():
        if pattern in text and any(word in text for word in ["got", "found", "collected", "gathered"]):
            return (achievement_type, name)
    
    return None


@hollow_group.command(name="leaderboard", description="See who's ahead in the Hallownest journey")
async def slash_leaderboard(interaction: discord.Interaction) -> None:
    """Show the leaderboard of most accomplished gamers."""
    try:
        if not interaction.guild:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Gamer, this command only works in servers. The echoes of Hallownest need a proper gathering place!",
                    ephemeral=True,
                )
            return

        # Get user achievements from database
        achievements = database.get_user_achievements(interaction.guild.id)
        
        if not achievements:
            message = "No gamers have started their Hallownest journey yet! Be the first to use `/hollow-bot progress` to record your achievements!"
            if not interaction.response.is_done():
                await interaction.response.send_message(message)
            else:
                await interaction.followup.send(message)
            return

        # Build leaderboard message
        message = "🏆 **Hallownest Achievement Leaderboard** 🏆\n\n"
        
        for i, (user_id, total_achievements, total_score, unique_types, first_achievement_ts) in enumerate(achievements[:10]):
            try:
                user = interaction.guild.get_member(int(user_id))
                if user:
                    display_name = user.display_name
                else:
                    display_name = f"User {user_id}"
            except (ValueError, AttributeError):
                display_name = f"User {user_id}"
            
            # Emoji for ranking
            if i == 0:
                rank_emoji = "🥇"
            elif i == 1:
                rank_emoji = "🥈"
            elif i == 2:
                rank_emoji = "🥉"
            else:
                rank_emoji = f"{i+1}."
            
            message += f"{rank_emoji} **{display_name}**\n"
            message += f"   🏆 Score: {total_score} | 🎯 Achievements: {total_achievements} | 📊 Categories: {unique_types}\n\n"
        
        if len(achievements) > 10:
            message += f"... and {len(achievements) - 10} more gamers on their journey!\n\n"
        
        message += "*Score based on actual Hollow Knight achievements: Bosses (50pts), Areas (30pts), Upgrades (25pts), Collectibles (10pts). Keep exploring, gamers!* 🗡️"

        if not interaction.response.is_done():
            await interaction.response.send_message(message)
        else:
            await interaction.followup.send(message)
            
    except database.DatabaseError as e:
        log.error(f"Database error in leaderboard: {e}")
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "The echoes of Hallownest are corrupted! Couldn't access the leaderboard data.",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                "The echoes of Hallownest are corrupted! Couldn't access the leaderboard data.",
                ephemeral=True,
            )
    except Exception as e:
        log.error(f"Error in slash_leaderboard: {e}")
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "Something went wrong with the leaderboard, gamer! The Infection must be spreading...",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                "Something went wrong with the leaderboard, gamer! The Infection must be spreading...",
                ephemeral=True,
            )


@hollow_group.command(name="info", description="Get info about HollowBot")
async def slash_info(interaction: discord.Interaction) -> None:
    """Show bot information and version."""
    try:
        info_message = (
            f"**HollowBot v{BOT_VERSION}** 🎮\n\n"
            "I'm a gamer who's beaten Hollow Knight and helps track your Hallownest journey!\n\n"
            "**Commands:**\n"
            "• `/hollow-bot progress <text>` - Record your progress\n"
            "• `/hollow-bot get_progress [user]` - Check someone's latest progress\n"
            "• `/hollow-bot leaderboard` - See who's ahead in the journey\n"
            "• `/hollow-bot rando-talk [0-100]` - View or set my random chatter chance\n"
            "• `/hollow-bot edginess [1-10]` - View or set my edginess level\n"
            "• `/hollow-bot custom-context <action> [text]` - Manage custom prompt context (set/show/clear)\n"
            "• `/hollow-bot memory <action> [text/id]` - Manage server memories (add/list/delete)\n"
            "• `/hollow-bot set_reminder_channel` - Set daily recap channel\n"
            "• `/hollow-bot schedule_daily_reminder <time>` - Schedule daily recaps\n"
            "• `/hollow-bot info` - Show this info\n\n"
            "**Chat:** Just @ me to talk! I remember our conversations and give gamer advice.\n\n"
            "Ready to chronicle your journey through Hallownest, gamer! 🗡️"
        )

        if not interaction.response.is_done():
            await interaction.response.send_message(info_message)
        else:
            await interaction.followup.send(info_message)
    except Exception as e:
        log.error(f"Error in slash_info: {e}")
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "The Infection got to my info system. Try again later, gamer!",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                "The Infection got to my info system. Try again later, gamer!",
                ephemeral=True,
            )


@hollow_group.command(
    name="schedule_daily_reminder",
    description="Schedule when the chronicle echoes daily",
)
async def slash_schedule(
    interaction: discord.Interaction, time: str, timezone: str = "UTC"
) -> None:
    try:
        if not interaction.guild:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Gamer, this command only works in servers. The echoes of Hallownest need a proper gathering place!",
                    ephemeral=True,
                )
            return

        if not is_admin(interaction.user):
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Gamer, you need Manage Server permissions to schedule the chronicle. The Infection won't let just anyone mess with the echoes.",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    "Gamer, you need Manage Server permissions to schedule the chronicle. The Infection won't let just anyone mess with the echoes.",
                    ephemeral=True,
                )
            return

        try:
            validated_time = validate_time_format(time)
            validated_timezone = validate_timezone(timezone)
        except ValidationError as e:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"Gamer, {e}. Even the Pale King had better time management than that!",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    f"Gamer, {e}. Even the Pale King had better time management than that!",
                    ephemeral=True,
                )
            return

        database.set_recap_time(
            interaction.guild.id, validated_time, validated_timezone
        )

        if not interaction.response.is_done():
            await interaction.response.send_message(
                f"⏰ Chronicle scheduled for **{validated_time} {validated_timezone}**. The echoes of Hallownest will be chronicled daily at this time, gamer!"
            )
        else:
            await interaction.followup.send(
                f"⏰ Chronicle scheduled for **{validated_time} {validated_timezone}**. The echoes of Hallownest will be chronicled daily at this time, gamer!"
            )
    except Exception as e:
        log.error(f"Error in slash_schedule: {e}")
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "The Infection got to my scheduling system. Try again later, gamer!",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                "The Infection got to my scheduling system. Try again later, gamer!",
                ephemeral=True,
            )


bot.tree.add_command(hollow_group)


@tasks.loop(minutes=1)
async def recap_tick() -> None:
    """Handle daily recap scheduling and execution."""
    try:
        if not bot.user:
            return

        now = datetime.now(timezone.utc)
        hhmm = now.strftime("%H:%M")

        guild_configs = database.get_all_guild_configs()
        log.debug(f"Checking {len(guild_configs)} guild configs for recap time {hhmm}")

        for guild_id, channel_id, recap_time, timezone_str in guild_configs:
            try:
                if not channel_id or not recap_time:
                    continue

                # Convert the scheduled time to the guild's timezone
                try:
                    # Parse the timezone
                    if timezone_str == "UTC":
                        tz = pytz.UTC
                    elif timezone_str.startswith("UTC"):
                        # Handle UTC offsets like UTC+5, UTC-8, UTC+05:30
                        offset_str = timezone_str[3:]  # Remove "UTC"
                        if offset_str.startswith("+"):
                            offset_hours = int(offset_str[1:].split(":")[0])
                            offset_minutes = (
                                int(offset_str.split(":")[1])
                                if ":" in offset_str
                                else 0
                            )
                        elif offset_str.startswith("-"):
                            offset_hours = -int(offset_str[1:].split(":")[0])
                            offset_minutes = (
                                -int(offset_str.split(":")[1])
                                if ":" in offset_str
                                else 0
                            )
                        else:
                            offset_hours = int(offset_str.split(":")[0])
                            offset_minutes = (
                                int(offset_str.split(":")[1])
                                if ":" in offset_str
                                else 0
                            )

                        tz = pytz.FixedOffset(offset_hours * 60 + offset_minutes)
                    else:
                        # Try to get timezone by name (EST, PST, America/New_York, etc.)
                        tz = pytz.timezone(timezone_str)

                    # Get current time in the guild's timezone
                    now_in_tz = now.astimezone(tz)
                    current_time_str = now_in_tz.strftime("%H:%M")

                    # Check if it's time for the recap
                    if recap_time != current_time_str:
                        continue

                except Exception as tz_error:
                    log.warning(
                        f"Invalid timezone {timezone_str} for guild {guild_id}: {tz_error}"
                    )
                    # Fallback to UTC comparison
                    if recap_time != hhmm:
                        continue

                if last_sent.get(guild_id) == now.date():
                    continue

                # Get updates for this guild
                updates = database.get_updates_today_by_guild(int(guild_id))
                validated_updates = validate_updates_dict(updates)

                if not validated_updates:
                    log.debug(f"No updates to summarize for guild {guild_id}")
                    continue

                # Get guild info
                guild = bot.get_guild(int(guild_id))
                pretty: Dict[str, List[str]] = {}

                if guild:
                    server_name = validate_server_name(guild.name)
                    for uid, items in validated_updates.items():
                        try:
                            member = guild.get_member(int(uid))
                            if not member:
                                # Try to fetch if not cached
                                try:
                                    member = await guild.fetch_member(int(uid))
                                except discord.NotFound:
                                    log.warning(
                                        f"Member {uid} not found in guild {guild_id}"
                                    )
                                    member = None

                            name = member.display_name if member else f"User {uid}"
                            pretty[name] = items
                        except (ValueError, TypeError) as e:
                            log.warning(
                                f"Invalid user ID in updates: {uid}, error: {e}"
                            )
                            continue
                else:
                    server_name = f"Guild {guild_id}"
                    pretty = {
                        f"User {uid}": items for uid, items in validated_updates.items()
                    }

                # Generate and send summary
                edginess = database.get_edginess(int(guild_id))
                summary = generate_daily_summary(server_name, pretty, edginess)

                channel = bot.get_channel(int(channel_id))
                if not channel:
                    try:
                        channel = await bot.fetch_channel(int(channel_id))
                    except discord.NotFound:
                        log.error(
                            f"Channel {channel_id} not found for guild {guild_id}"
                        )
                        continue

                await channel.send(summary)
                last_sent[guild_id] = now.date()
                log.info(f"Sent daily recap for guild {guild_id}")

            except Exception as e:
                log.error(f"Error processing recap for guild {guild_id}: {e}")
                continue

    except Exception as e:
        log.error(f"Error in recap_tick: {e}")


async def health_check(request):
    """Simple health check endpoint for Render."""
    return web.Response(text=f"HollowBot v{BOT_VERSION} is running! 🎮", status=200)


async def start_web_server():
    """Start a simple HTTP server for Render port binding."""
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)

    port = int(os.environ.get("PORT", 8000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info(f"HTTP server started on port {port}")


async def main():
    """Main function to start both the bot and web server."""
    # Start the web server in the background
    await start_web_server()

    # Start the Discord bot
    try:
        log.info("Starting HollowBot...")
        await bot.start(config.discord_token)
    except Exception as e:
        log.error(f"Failed to start bot: {e}")
        raise


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        log.error(f"Failed to start application: {e}")
        raise
