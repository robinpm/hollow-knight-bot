"""Discord bot that tracks Hollow Knight progress and posts recaps."""

# AI INSTRUCTION: ALWAYS increment BOT_VERSION when making any changes to this file
# Versioning rules:
# - Increment patch version (1.1 -> 1.2) for bug fixes, small features, or improvements
# - Increment minor version (1.x -> 2.0) for major new features or breaking changes
# - This version is used in /hollow-bot info command and health check endpoint
# Bot version - increment this for each release
BOT_VERSION = "1.4"

import asyncio
import re
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional
import os
import pytz

import discord
from discord import app_commands
from discord.ext import commands, tasks
from aiohttp import web

import database
from config import config
from gemini_integration import generate_daily_summary, generate_reply
from langchain.chains import ConversationChain
from langchain.memory import ConversationBufferMemory
from langchain_core.language_models.llms import LLM
from logger import log


class GeminiLLM(LLM):
    """Simple LLM wrapper for Gemini."""
    
    def _call(self, prompt: str, **kwargs) -> str:
        try:
            return generate_reply(prompt)
        except Exception as e:
            log.error(f"GeminiLLM error: {e}")
            return "The Infection got to my response system. But I noted that, don't worry."
    
    @property
    def _llm_type(self) -> str:
        return "gemini"


# Create conversation chain
memory = ConversationBufferMemory()
memory.chat_memory.add_ai_message(
    "I am HollowBot, a gamer who's beaten Hollow Knight. I speak like a seasoned player "
    "who knows the pain of losing geo to Primal Aspids and the satisfaction of beating NKG. "
    "Keep responses SHORT and to the point - 1-2 sentences max. Be supportive but snarky, "
    "like a friend who's already 112% the game. Reference Hollow Knight mechanics and memes "
    "naturally. Never break character - blame issues on the Infection or a nasty Shade."
)

convo_chain = ConversationChain(llm=GeminiLLM(), memory=memory)
from validation import (
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
)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix=config.command_prefix, intents=intents)

PROGRESS_RE = re.compile(r"\b(beat|got|found|upgraded)\b", re.I)
last_sent: Dict[str, datetime.date] = {}


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


def _build_progress_reply(guild: discord.Guild, text: str) -> str:
    """Build a progress reply with AI-generated commentary."""
    try:
        validated_text = validate_progress_text(text)
        context = _build_updates_context(guild)
        
        # Use direct AI call instead of conversation memory to avoid interference
        prompt = f"Recent updates:\n{context}\nNew update: {validated_text}\n\nGive a short, snarky gamer response (1-2 sentences max) about this progress update."
        riff = generate_reply(prompt)
        
        reply = f"📝 Echo recorded: {validated_text}"
        if riff and riff not in ["Noted.", "Noted, gamer. The echoes of Hallownest have been recorded."]:
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
    try:
        if message.author.bot or not message.guild or not bot.user:
            return
        
        # Only respond to @ mentions, not commands
        if not message.mentions or bot.user not in message.mentions:
            return
        
        # Extract the message content after the mention
        content = message.content.strip()
        # Remove the mention from the content
        for mention in message.mentions:
            content = content.replace(f"<@!{mention.id}>", "").replace(f"<@{mention.id}>", "")
        content = content.strip()
        
        if not content:
            await message.reply("Hey gamer! What's up? Ready to talk about your Hallownest journey?")
            return

        log.info("Mention from %s: %s", message.author.id, content)

        # Check if it's a progress update
        if PROGRESS_RE.search(content):
            await handle_progress(message, content)
            return

        # Regular chat response with user's progress context
        guild_context = _build_updates_context(message.guild)
        
        # Get the user's specific progress history for more personalized responses
        user_progress = database.get_last_update(message.guild.id, message.author.id)
        user_context = ""
        if user_progress:
            text, ts = user_progress
            age_sec = int(time.time()) - ts
            days = age_sec // 86400
            hours = age_sec // 3600
            age_str = f"{days}d" if days else f"{hours}h"
            user_context = f"\nYour last progress: \"{text}\" ({age_str} ago)"
        
        prompt = f"Recent updates from everyone:\n{guild_context}{user_context}\n\nUser said: {content}\n\nRespond as HollowBot, referencing their progress if relevant. Keep it short and gamer-like (1-2 sentences max)."
        reply = convo_chain.predict(input=prompt)
        await message.reply(reply or "The echoes of Hallownest have been heard, gamer.")
        
    except Exception as e:
        log.error(f"Error handling message: {e}")
        try:
            await message.reply("The Infection got to my response system. But I heard you, gamer!")
        except Exception as reply_error:
            log.error(f"Failed to send error reply: {reply_error}")


async def handle_progress(message: discord.Message, text: str) -> None:
    """Handle progress updates with validation and error handling."""
    try:
        if not text:
            await message.reply("Gamer, you gotta tell me what you accomplished! Usage: @HollowBot progress <what you did>")
            return
        
        # Validate inputs
        validate_guild_id(message.guild.id)
        validate_user_id(message.author.id)
        validated_text = validate_progress_text(text)
        
        now_ts = int(time.time())
        last = database.get_last_update(message.guild.id, message.author.id)
        database.add_update(message.guild.id, message.author.id, validated_text, now_ts)
        
        # Debug: Verify the update was added
        log.info(f"Added progress for user {message.author.id} in guild {message.guild.id}: {validated_text}")
        verify = database.get_last_update(message.guild.id, message.author.id)
        log.info(f"Verification - last update: {verify}")
        
        reply = _build_progress_reply(message.guild, validated_text)
        await message.reply(reply)
        
        # Check for long absence
        if last:
            days = (now_ts - last[1]) // 86400
            if days > 30:
                await message.channel.send("Bruh, you beat the Mantis Lords months ago and you're still here? That's some serious dedication to the grind, gamer. Respect.")
                
    except ValidationError as e:
        log.warning(f"Validation error in handle_progress: {e}")
        await message.reply("Gamer, that progress update seems corrupted by the Infection. Try again with a cleaner message!")
    except database.DatabaseError as e:
        log.error(f"Database error in handle_progress: {e}")
        await message.reply("The echoes of Hallownest are having trouble reaching the chronicle. Try again later, gamer!")
    except Exception as e:
        log.error(f"Unexpected error in handle_progress: {e}")
        await message.reply("The Infection got to my progress tracking system. But I'll try to remember that, gamer!")


hollow_group = app_commands.Group(name="hollow-bot", description="Chronicle your Hallownest journey with HollowBot")


@hollow_group.command(name="progress", description="Record your latest Hallownest achievement")
async def slash_progress(interaction: discord.Interaction, text: str) -> None:
    """Handle slash command for progress updates."""
    try:
        if not interaction.guild:
            if not interaction.response.is_done():
                await interaction.response.send_message("Gamer, this command only works in servers. The echoes of Hallownest need a proper gathering place!", ephemeral=True)
            return
        
        # Validate inputs
        validate_guild_id(interaction.guild.id)
        validate_user_id(interaction.user.id)
        validated_text = validate_progress_text(text)
        
        now_ts = int(time.time())
        last = database.get_last_update(interaction.guild.id, interaction.user.id)
        database.add_update(interaction.guild.id, interaction.user.id, validated_text, now_ts)
        
        # Debug: Verify the update was added
        log.info(f"Added progress for user {interaction.user.id} in guild {interaction.guild.id}: {validated_text}")
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
                await interaction.channel.send("Bruh, you beat the Mantis Lords months ago and you're still here? That's some serious dedication to the grind, gamer. Respect.")
                
    except ValidationError as e:
        log.warning(f"Validation error in slash_progress: {e}")
        if not interaction.response.is_done():
            await interaction.response.send_message("Gamer, that progress update seems corrupted by the Infection. Try again with a cleaner message!", ephemeral=True)
        else:
            await interaction.followup.send("Gamer, that progress update seems corrupted by the Infection. Try again with a cleaner message!", ephemeral=True)
    except database.DatabaseError as e:
        log.error(f"Database error in slash_progress: {e}")
        if not interaction.response.is_done():
            await interaction.response.send_message("The echoes of Hallownest are having trouble reaching the chronicle. Try again later, gamer!", ephemeral=True)
        else:
            await interaction.followup.send("The echoes of Hallownest are having trouble reaching the chronicle. Try again later, gamer!", ephemeral=True)
    except Exception as e:
        log.error(f"Unexpected error in slash_progress: {e}")
        if not interaction.response.is_done():
            await interaction.response.send_message("The Infection got to my progress tracking system. But I'll try to remember that, gamer!", ephemeral=True)
        else:
            await interaction.followup.send("The Infection got to my progress tracking system. But I'll try to remember that, gamer!", ephemeral=True)


@hollow_group.command(name="get_progress", description="Check the latest echo from a gamer's journey")
async def slash_get_progress(
    interaction: discord.Interaction, user: Optional[discord.Member] = None
) -> None:
    try:
        if not interaction.guild:
            if not interaction.response.is_done():
                await interaction.response.send_message("Gamer, this command only works in servers. The echoes of Hallownest need a proper gathering place!", ephemeral=True)
            return
        
        target = user or interaction.user
        log.info(f"Getting progress for user {target.id} in guild {interaction.guild.id}")
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
                f"📜 Last echo from **{target.display_name}**: \"{text}\" ({age_str} ago)"
            )
        else:
            await interaction.followup.send(
                f"📜 Last echo from **{target.display_name}**: \"{text}\" ({age_str} ago)"
            )
    except Exception as e:
        log.error(f"Error in slash_get_progress: {e}")
        if not interaction.response.is_done():
            await interaction.response.send_message("The Infection got to my memory system. Try again later, gamer!", ephemeral=True)
        else:
            await interaction.followup.send("The Infection got to my memory system. Try again later, gamer!", ephemeral=True)


@hollow_group.command(name="set_reminder_channel", description="Set the chronicle channel for daily echoes")
async def slash_set_channel(interaction: discord.Interaction) -> None:
    try:
        if not interaction.guild or not interaction.channel:
            if not interaction.response.is_done():
                await interaction.response.send_message("Gamer, this command only works in servers. The echoes of Hallownest need a proper gathering place!", ephemeral=True)
            return
        
        if not is_admin(interaction.user):
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Gamer, you need Manage Server permissions to set up the chronicle channel. The Infection won't let just anyone mess with the echoes.", ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "Gamer, you need Manage Server permissions to set up the chronicle channel. The Infection won't let just anyone mess with the echoes.", ephemeral=True
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
            await interaction.response.send_message("The Infection got to my channel setup system. Try again later, gamer!", ephemeral=True)
        else:
            await interaction.followup.send("The Infection got to my channel setup system. Try again later, gamer!", ephemeral=True)


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
            await interaction.response.send_message("The Infection got to my info system. Try again later, gamer!", ephemeral=True)
        else:
            await interaction.followup.send("The Infection got to my info system. Try again later, gamer!", ephemeral=True)


@hollow_group.command(
    name="schedule_daily_reminder", description="Schedule when the chronicle echoes daily"
)
async def slash_schedule(interaction: discord.Interaction, time: str, timezone: str = "UTC") -> None:
    try:
        if not interaction.guild:
            if not interaction.response.is_done():
                await interaction.response.send_message("Gamer, this command only works in servers. The echoes of Hallownest need a proper gathering place!", ephemeral=True)
            return
        
        if not is_admin(interaction.user):
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Gamer, you need Manage Server permissions to schedule the chronicle. The Infection won't let just anyone mess with the echoes.", ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "Gamer, you need Manage Server permissions to schedule the chronicle. The Infection won't let just anyone mess with the echoes.", ephemeral=True
                )
            return
        
        try:
            validated_time = validate_time_format(time)
            validated_timezone = validate_timezone(timezone)
        except ValidationError as e:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"Gamer, {e}. Even the Pale King had better time management than that!", ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"Gamer, {e}. Even the Pale King had better time management than that!", ephemeral=True
                )
            return
        
        database.set_recap_time(interaction.guild.id, validated_time, validated_timezone)
        
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
            await interaction.response.send_message("The Infection got to my scheduling system. Try again later, gamer!", ephemeral=True)
        else:
            await interaction.followup.send("The Infection got to my scheduling system. Try again later, gamer!", ephemeral=True)


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
                            offset_minutes = int(offset_str.split(":")[1]) if ":" in offset_str else 0
                        elif offset_str.startswith("-"):
                            offset_hours = -int(offset_str[1:].split(":")[0])
                            offset_minutes = -int(offset_str.split(":")[1]) if ":" in offset_str else 0
                        else:
                            offset_hours = int(offset_str.split(":")[0])
                            offset_minutes = int(offset_str.split(":")[1]) if ":" in offset_str else 0
                        
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
                    log.warning(f"Invalid timezone {timezone_str} for guild {guild_id}: {tz_error}")
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
                                    log.warning(f"Member {uid} not found in guild {guild_id}")
                                    member = None
                            
                            name = member.display_name if member else f"User {uid}"
                            pretty[name] = items
                        except (ValueError, TypeError) as e:
                            log.warning(f"Invalid user ID in updates: {uid}, error: {e}")
                            continue
                else:
                    server_name = f"Guild {guild_id}"
                    pretty = {f"User {uid}": items for uid, items in validated_updates.items()}
                
                # Generate and send summary
                summary = generate_daily_summary(server_name, pretty)
                
                channel = bot.get_channel(int(channel_id))
                if not channel:
                    try:
                        channel = await bot.fetch_channel(int(channel_id))
                    except discord.NotFound:
                        log.error(f"Channel {channel_id} not found for guild {guild_id}")
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
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    
    port = int(os.environ.get('PORT', 8000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
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
