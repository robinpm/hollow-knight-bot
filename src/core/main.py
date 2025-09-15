"""Discord bot that tracks Hollow Knight progress and posts recaps."""

# AI INSTRUCTION: ALWAYS increment BOT_VERSION when making any changes to this file
# Versioning rules:
# - Increment patch version (1.1 -> 1.2) for bug fixes, small features, or improvements
# - Increment minor version (1.x -> 2.0) for major new features or breaking changes
# - This version is used in /hollow-bot info command and health check endpoint
# Bot version - increment this for each release

BOT_VERSION = "2.3"

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

# Track recent bot responses to avoid over-responding
recent_bot_responses: Dict[int, int] = {}  # guild_id -> count of recent bot responses

# Keywords that override the bot response count limit
OVERRIDE_KEYWORDS = [
    'hollow bot', 'hollow-bot', '@hollow-bot', 'hollowbot',
    'are you there', 'are you here', 'is hollow bot', 'is hollowbot',
    'hello', 'hi', 'hey', 'yo', 'what', 'how are you',
    'answer me', 'respond', 'talk to me', 'chat',
    'hollow knight', 'hallownest', 'knight', 'bug', 'vessel',
    'progress', 'save', 'achievement', 'boss', 'area'
]


def is_admin(member: discord.Member) -> bool:
    perms = member.guild_permissions
    return perms.administrator or perms.manage_guild or perms.manage_channels


async def safe_interaction_response(interaction: discord.Interaction, message: str, ephemeral: bool = False) -> bool:
    """Safely send a response to a Discord interaction, handling expired interactions gracefully.
    
    Returns True if the response was sent successfully, False otherwise.
    """
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(message, ephemeral=ephemeral)
            return True
        else:
            await interaction.followup.send(message, ephemeral=ephemeral)
            return True
    except discord.NotFound:
        log.warning(f"Interaction {interaction.id} not found for response")
        return False
    except discord.HTTPException as e:
        log.warning(f"HTTP error in interaction response: {e}")
        return False
    except Exception as e:
        log.error(f"Unexpected error in interaction response: {e}")
        return False


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
        # Only include recent memories (last 5) to avoid overwhelming context
        recent_memories = memories[-5:] if len(memories) > 5 else memories
        lines = [m for _, m in recent_memories]
        return "\n".join(lines) if lines else "No memories yet."
    except (ValidationError, database.DatabaseError) as e:
        log.error(f"Failed to build memories context: {e}")
        return "The Chronicler remembers nothing."


def _build_focused_context(guild: discord.Guild, current_message: str) -> str:
    """Build more focused context based on the current message content."""
    try:
        # Check if message mentions Hollow Knight specific terms
        hk_terms = ['boss', 'charm', 'geo', 'soul', 'nail', 'mask', 'vessel', 'knight', 'hollow', 'radiance', 'infection', 'dream', 'void', 'progress', 'beat', 'defeated', 'upgraded', 'found', 'got']
        message_lower = current_message.lower()
        
        # Check if this is a casual question about the bot itself
        casual_bot_questions = ['are you there', 'is hollow bot', 'are you here', 'hello', 'hi', 'what', 'how are you']
        is_casual_question = any(phrase in message_lower for phrase in casual_bot_questions)
        
        # If it's a casual question about the bot, don't include progress context
        if is_casual_question and not any(term in message_lower for term in hk_terms):
            return "No relevant Hollow Knight context needed for casual conversation."
        
        # If it's about Hollow Knight, include more relevant context
        if any(term in message_lower for term in hk_terms):
            updates = _build_updates_context(guild)
            memories = _build_memories_context(guild)
            
            context_parts = []
            if updates and updates != "No updates yet today.":
                context_parts.append(f"Recent progress updates:\n{updates}")
            if memories and memories != "No memories yet.":
                context_parts.append(f"Server memories:\n{memories}")
            
            return "\n\n".join(context_parts) if context_parts else "No relevant Hollow Knight context."
        else:
            # For non-HK topics, keep context minimal
            return "No recent Hollow Knight updates."
    except Exception as e:
        log.error(f"Failed to build focused context: {e}")
        return "Context unavailable."


def _increment_bot_response_count(guild_id: int) -> None:
    """Increment the count of recent bot responses for this guild."""
    if guild_id not in recent_bot_responses:
        recent_bot_responses[guild_id] = 0
    recent_bot_responses[guild_id] += 1
    print(f"   📈 Bot response count incremented: {recent_bot_responses[guild_id]} for guild {guild_id}")


def _build_system_message(custom_context: str, edginess: int, is_casual_question: bool = False) -> str:
    """Build a proper system message defining the bot's role and behavior."""
    system_parts = [
        "You are HollowBot, a seasoned Hollow Knight gamer and Discord bot.",
        "You're knowledgeable about Hollow Knight lore, mechanics, and the gaming experience.",
        "You speak like a gamer friend who's already 112% the game - supportive but playfully snarky.",
        "You reference bosses, areas, items, and the pain of losing geo naturally in conversation.",
        "You never break character - blame technical issues on 'the Infection'.",
        f"Your edginess level is {edginess}/10 (1=very polite, 10=very snarky)."
    ]
    
    if is_casual_question:
        system_parts.append("For casual questions about your presence or status, respond naturally without mentioning progress percentages or achievements unless specifically asked.")
    
    if custom_context:
        system_parts.append(f"Additional context for this server: {custom_context}")
    
    return "\n".join(system_parts)


async def _get_recent_messages(message: discord.Message, limit: int = 10) -> tuple[str, str, int, bool]:
    """Return previous messages and current message separately for clear context."""
    previous_lines: List[str] = []
    consecutive_bot_responses = 0
    is_conversation_active = False
    
    try:
        messages = []
        async for msg in message.channel.history(limit=limit, before=message):
            if not msg.content:
                continue
            messages.append(msg)
        
        # Process messages in chronological order (oldest first)
        messages.reverse()
        
        # Count consecutive bot responses from the most recent messages
        for msg in reversed(messages):
            if msg.author.bot:
                consecutive_bot_responses += 1
                # Include bot responses but mark them clearly
                previous_lines.append(f"[BOT] {msg.content.strip()}")
            else:
                # Stop counting when we hit a user message
                break
                
        # Check if there's an active conversation (user messages in recent history)
        user_messages_in_recent = sum(1 for msg in messages[-5:] if not msg.author.bot and msg.content)
        is_conversation_active = user_messages_in_recent >= 2
        
        # Add all messages to context (not just the consecutive bot ones)
        for msg in messages:
            if not msg.author.bot:
                previous_lines.append(f"{msg.author.display_name}: {msg.content.strip()}")
                
    except Exception as e:
        log.warning(f"Failed to fetch recent messages: {e}")

    previous_messages = "\n".join(previous_lines) if previous_lines else "No previous messages."
    current_message = f"{message.author.display_name}: {message.content.strip()}"
    
    return previous_messages, current_message, consecutive_bot_responses, is_conversation_active


def _should_respond(
    previous_messages: str, current_message: str, guild_context: str, author: str, custom_context: str, 
    consecutive_bot_responses: int = 0, is_conversation_active: bool = False
) -> bool:
    """Use AI agent to decide if the bot should reply to a message."""
    try:
        # Extract the actual message content (remove author name prefix)
        message_content = current_message.split(": ", 1)[1] if ": " in current_message else current_message
        message_lower = message_content.lower()
        
        # Check for override keywords
        has_override_keyword = any(keyword in message_lower for keyword in OVERRIDE_KEYWORDS)
        
        # Additional stochastic factors
        message_length = len(message_content.strip())
        is_short_message = message_length <= 10
        is_question = message_content.strip().endswith('?')
        is_direct_address = any(phrase in message_lower for phrase in ['hollow bot', 'hollow-bot', '@hollow-bot', 'hollowbot'])
        
        # Calculate response probability based on various factors
        response_probability = 0.0
        
        # Base probability from AI agent
        print(f"      🤖 Calling AI agent for decision...")
        ai_decision = agent_should_respond(previous_messages, current_message, guild_context, author, custom_context)
        print(f"      🧠 AI Agent result: {ai_decision}")
        
        if ai_decision:
            response_probability = 0.8  # High base probability if AI approves
        else:
            response_probability = 0.2  # Low base probability if AI rejects
        
        # Override keyword bonus
        if has_override_keyword:
            response_probability = min(1.0, response_probability + 0.4)
            print(f"      🔑 OVERRIDE KEYWORD DETECTED: '{[kw for kw in OVERRIDE_KEYWORDS if kw in message_lower][:3]}'")
        
        # Conversation context bonus
        if is_conversation_active:
            response_probability = min(1.0, response_probability + 0.2)
            print(f"      💬 ACTIVE CONVERSATION DETECTED")
        
        # Direct address bonus
        if is_direct_address:
            response_probability = min(1.0, response_probability + 0.3)
            print(f"      🎯 DIRECT ADDRESS DETECTED")
        
        # Question bonus
        if is_question:
            response_probability = min(1.0, response_probability + 0.1)
            print(f"      ❓ QUESTION DETECTED")
        
        # Consecutive response penalty (but allow override)
        if consecutive_bot_responses >= 2 and not has_override_keyword:
            response_probability = max(0.1, response_probability - 0.3)
            print(f"      ⚠️  CONSECUTIVE RESPONSE PENALTY: {consecutive_bot_responses} responses")
        
        # Short message bonus (more likely to be casual chat)
        if is_short_message and not has_override_keyword:
            response_probability = max(0.1, response_probability - 0.1)
            print(f"      📏 SHORT MESSAGE PENALTY")
        
        # Final decision with some randomness
        final_decision = response_probability > random.random()
        
        print(f"      📊 Response Probability: {response_probability:.2f} | Final Decision: {final_decision}")
        
        return final_decision
        
    except Exception as e:
        log.error(f"Error deciding to respond: {e}")
        print(f"      ❌ ERROR in AI decision: {e}")
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
            print(f"🔔 MENTION DETECTED - Guild: {message.guild.id} ({message.guild.name})")
            print(f"   💬 Message: '{message.content[:100]}{'...' if len(message.content) > 100 else ''}'")
            print(f"   👤 Author: {message.author.display_name} ({message.author.id})")
            print(f"   ⚡ Bypassing random chance - responding to mention")
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
                print(f"📝 PROGRESS UPDATE DETECTED - Processing progress update")
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

            previous_messages, current_message, consecutive_bot_responses, is_conversation_active = await _get_recent_messages(message)
            focused_context = _build_focused_context(message.guild, current_message)
            
            # Check if this is a casual question about the bot
            casual_bot_questions = ['are you there', 'is hollow bot', 'are you here', 'hello', 'hi', 'what', 'how are you']
            is_casual_question = any(phrase in current_message.lower() for phrase in casual_bot_questions)
            
            # Build properly structured prompt with delimiters
            system_message = _build_system_message(custom_context, edginess, is_casual_question)
            
            prompt = f"""<system>
{system_message}
</system>

<context>
{focused_context if focused_context != "No recent Hollow Knight updates." else "No relevant Hollow Knight context available."}
{user_context if user_context else ""}
</context>

<conversation>
{previous_messages if previous_messages != "No previous messages." else "No previous conversation."}
</conversation>

<message>
{current_message}
</message>

<instructions>
Respond to the message above as HollowBot. Keep your response to 1-2 sentences maximum. Be natural and conversational. Do not include any name prefix in your response.
</instructions>"""
            reply = generate_reply(prompt, edginess=edginess)
            if reply:
                _increment_bot_response_count(message.guild.id)
                print(f"✅ MENTION RESPONSE GENERATED - Sending reply: '{reply[:50]}{'...' if len(reply) > 50 else ''}'")
            else:
                print(f"❌ NO MENTION RESPONSE GENERATED - Using fallback message")
            await message.reply(
                reply or "The echoes of Hallownest have been heard, gamer."
            )
        else:
            chance = guild_spontaneous_chances.get(
                message.guild.id, SPONTANEOUS_RESPONSE_CHANCE
            )
            random_roll = random.random()
            
            # Log the random chance decision
            print(f"🎲 SPONTANEOUS CHATTER CHECK - Guild: {message.guild.id} ({message.guild.name})")
            print(f"   📊 Chance: {chance:.2%} | Roll: {random_roll:.3f} | Triggered: {random_roll < chance}")
            print(f"   💬 Message: '{message.content[:100]}{'...' if len(message.content) > 100 else ''}'")
            print(f"   👤 Author: {message.author.display_name} ({message.author.id})")
            
            if random_roll < chance:
                log.info("Spontaneous response triggered in guild %s", message.guild.id)
                print(f"✅ RANDOM CHANCE PASSED - Proceeding to AI decision...")
                
                guild_context = _build_updates_context(message.guild)
                memories = _build_memories_context(message.guild)
                previous_messages, current_message, consecutive_bot_responses, is_conversation_active = await _get_recent_messages(message)
                custom_context = database.get_custom_context(message.guild.id)
                edginess = database.get_edginess(message.guild.id)
                
                # Log decision factors
                print(f"   🤖 AI Decision Factors:")
                print(f"      - Consecutive bot responses: {consecutive_bot_responses}")
                print(f"      - Active conversation: {is_conversation_active}")
                print(f"      - Guild context available: {bool(guild_context and guild_context != 'No updates yet today.')}")
                print(f"      - Custom context: {bool(custom_context)}")
                print(f"      - Edginess level: {edginess}")
                print(f"      - Message author: {message.author.display_name}")
                
                should_respond = _should_respond(
                    previous_messages, current_message, guild_context, message.author.display_name, custom_context, 
                    consecutive_bot_responses, is_conversation_active
                )
                
                print(f"   🧠 AI Agent Decision: {should_respond}")
                
                if should_respond:
                    print(f"✅ AI AGENT APPROVED - Generating response...")
                    focused_context = _build_focused_context(message.guild, current_message)
                    
                    # Check if this is a casual question about the bot
                    casual_bot_questions = ['are you there', 'is hollow bot', 'are you here', 'hello', 'hi', 'what', 'how are you']
                    is_casual_question = any(phrase in current_message.lower() for phrase in casual_bot_questions)
                    
                    print(f"   📝 Response Details:")
                    print(f"      - Casual question: {is_casual_question}")
                    print(f"      - Focused context: {bool(focused_context and focused_context != 'No recent Hollow Knight updates.')}")
                    
                    # Build properly structured prompt with delimiters
                    system_message = _build_system_message(custom_context, edginess, is_casual_question)
                    
                    prompt = f"""<system>
{system_message}
</system>

<context>
{focused_context if focused_context != "No recent Hollow Knight updates." else "No relevant Hollow Knight context available."}
</context>

<conversation>
{previous_messages if previous_messages != "No previous messages." else "No previous conversation."}
</conversation>

<message>
{current_message}
</message>

<instructions>
Respond to the message above as HollowBot. Keep your response to 1-2 sentences maximum. Be natural and conversational. Do not include any name prefix in your response.
</instructions>"""
                    reply = generate_reply(prompt, edginess=edginess)
                    if reply:
                        _increment_bot_response_count(message.guild.id)
                        print(f"✅ RESPONSE GENERATED - Sending reply: '{reply[:50]}{'...' if len(reply) > 50 else ''}'")
                        await message.reply(reply)
                    else:
                        print(f"❌ NO RESPONSE GENERATED - AI returned empty response")
                else:
                    print(f"❌ AI AGENT REJECTED - Not responding")
                    # Log specific rejection reasons
                    if consecutive_bot_responses >= 2:
                        print(f"   🚫 Reason: Too many consecutive bot responses ({consecutive_bot_responses})")
                    else:
                        print(f"   🚫 Reason: AI agent determined message not suitable for response")
            else:
                print(f"❌ RANDOM CHANCE FAILED - No spontaneous response")


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
        
        # Store detailed save progress with all stats
        now_ts = int(time.time())
        player_hash = database.add_save_progress(
            message.guild.id, 
            message.author.id, 
            message.author.display_name, 
            summary, 
            now_ts
        )
        
        # Generate memory from the save data
        progress_text = f"Uploaded save data: {summary['completion_percent']}% complete, {summary['playtime_hours']}h playtime, {summary['deaths']} deaths"
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
        
        # Also store this as detailed save progress
        now_ts = int(time.time())
        player_hash = database.add_save_progress(
            message.guild.id, 
            message.author.id, 
            message.author.display_name, 
            summary, 
            now_ts
        )
        
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
    name="record", description="Record your latest Hallownest achievement"
)
async def slash_record(interaction: discord.Interaction, text: str) -> None:
    """Handle slash command for progress updates."""
    try:
        if not interaction.guild:
            await safe_interaction_response(
                interaction,
                "Gamer, this command only works in servers. The echoes of Hallownest need a proper gathering place!",
                ephemeral=True
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
        await safe_interaction_response(interaction, reply)

        # Check for long absence
        if last:
            days = (now_ts - last[1]) // 86400
            if days > 30 and interaction.channel:
                await interaction.channel.send(
                    "Bruh, you beat the Mantis Lords months ago and you're still here? That's some serious dedication to the grind, gamer. Respect."
                )

    except ValidationError as e:
        log.warning(f"Validation error in slash_record: {e}")
        await safe_interaction_response(
            interaction,
            "Gamer, that progress update seems corrupted by the Infection. Try again with a cleaner message!",
            ephemeral=True
        )
    except database.DatabaseError as e:
        log.error(f"Database error in slash_record: {e}")
        await safe_interaction_response(
            interaction,
            "The echoes of Hallownest are having trouble reaching the chronicle. Try again later, gamer!",
            ephemeral=True
        )
    except Exception as e:
        log.error(f"Unexpected error in slash_record: {e}")
        await safe_interaction_response(
            interaction,
            "The Infection got to my progress tracking system. But I'll try to remember that, gamer!",
            ephemeral=True
        )


@hollow_group.command(
    name="progress", description="Check save data and progress history"
)
@app_commands.describe(
    user="User to check progress for (defaults to yourself)",
    limit="Number of recent saves to show (default: 1, max: 20)",
    history="Show full history instead of just latest save"
)
async def slash_progress_check(
    interaction: discord.Interaction, 
    user: Optional[discord.Member] = None,
    limit: Optional[int] = 1,
    history: Optional[bool] = False
) -> None:
    """Unified progress command that can show latest save or history."""
    try:
        if not interaction.guild:
            await safe_interaction_response(
                interaction,
                "Gamer, this command only works in servers. The echoes of Hallownest need a proper gathering place!",
                ephemeral=True
            )
            return

        # Validate limit
        if limit is None:
            limit = 1
        elif limit < 1 or limit > 20:
            await safe_interaction_response(
                interaction,
                "Limit must be between 1 and 20, gamer!",
                ephemeral=True
            )
            return

        target = user or interaction.user
        log.info(
            f"Getting progress for user {target.id} in guild {interaction.guild.id}, limit {limit}, history {history}"
        )
        
        # Get the save data for this player
        progress_history = database.get_player_progress_history(interaction.guild.id, target.id, limit=limit)
        
        if not progress_history:
            await safe_interaction_response(
                interaction,
                f"No save data recorded for {target.display_name} yet. Upload a .dat file to start tracking your Hallownest journey, gamer!"
            )
            return

        # If showing just latest save (limit=1 and not history mode)
        if limit == 1 and not history:
            latest_save = progress_history[0]
            
            # Calculate age
            age_sec = int(time.time()) - latest_save['ts']
            days = age_sec // 86400
            hours = age_sec // 3600
            age_str = f"{days}d" if days else f"{hours}h"
            
            # Format the save data summary
            completion = latest_save['completion_percent']
            playtime = latest_save['playtime_hours']
            geo = latest_save['geo']
            health = latest_save['health']
            max_health = latest_save['max_health']
            deaths = latest_save['deaths']
            scene = latest_save['scene']
            zone = latest_save['zone']
            nail_upgrades = latest_save['nail_upgrades']
            soul_vessels = latest_save['soul_vessels']
            mask_shards = latest_save['mask_shards']
            charms_owned = latest_save['charms_owned']
            bosses_defeated = latest_save['bosses_defeated']
            
            # Build the response message
            message = f"📜 **Latest Save Data for {target.display_name}** ({age_str} ago)\n\n"
            message += f"🎮 **Progress**: {completion or 0}% complete\n"
            message += f"⏱️ **Playtime**: {(playtime if playtime is not None else 0):.2f} hours\n"
            message += f"💰 **Geo**: {(geo if geo is not None else 0):,}\n"
            message += f"❤️ **Health**: {health or 0}/{max_health or 0} hearts\n"
            message += f"💀 **Deaths**: {deaths or 0}\n"
            message += f"🗡️ **Nail**: +{nail_upgrades or 0} upgrades\n"
            message += f"💙 **Soul**: {soul_vessels or 0} vessels\n"
            message += f"🎭 **Charms**: {charms_owned or 0} owned\n"
            message += f"👹 **Bosses**: {bosses_defeated or 0} defeated\n"
            message += f"📍 **Location**: {scene or 'Unknown'} ({zone or 'Unknown'})"
        else:
            # Show history
            message = f"📜 **Save History for {target.display_name}** ({len(progress_history)} recent saves)\n\n"
            
            for i, save in enumerate(progress_history, 1):
                # Calculate age
                age_sec = int(time.time()) - save['ts']
                days = age_sec // 86400
                hours = age_sec // 3600
                age_str = f"{days}d" if days else f"{hours}h"
                
                message += f"**#{i}** ({age_str} ago)\n"
                message += f"🎮 {save['completion_percent'] or 0}% complete | ⏱️ {(save['playtime_hours'] if save['playtime_hours'] is not None else 0):.1f}h | 💰 {(save['geo'] if save['geo'] is not None else 0):,} geo\n"
                message += f"❤️ {save['health'] or 0}/{save['max_health'] or 0} hearts | 💀 {save['deaths'] or 0} deaths | 👹 {save['bosses_defeated'] or 0} bosses\n"
                message += f"📍 {save['scene'] or 'Unknown'} ({save['zone'] or 'Unknown'})\n\n"
            
            # Truncate if too long
            if len(message) > 2000:
                message = message[:1900] + "\n\n... (message truncated)"
        
        await safe_interaction_response(interaction, message)
            
    except Exception as e:
        log.error(f"Error in slash_progress_check: {e}")
        await safe_interaction_response(
            interaction,
            "The Infection got to my progress system. Try again later, gamer!",
            ephemeral=True
        )


@hollow_group.command(name="config", description="Configure bot settings")
@app_commands.describe(
    setting="Setting to configure: chatter, edginess, memory, or context",
    action="Action for memory/context: add, list, delete, set, show, clear",
    value="Value to set (number for chatter/edginess, text for memory/context)",
    memory_id="Memory ID to delete (for memory delete action)"
)
async def config_command(
    interaction: discord.Interaction,
    setting: str,
    action: Optional[str] = None,
    value: Optional[str] = None,
    memory_id: Optional[int] = None
) -> None:
    """Unified configuration command for all bot settings."""
    try:
        if not interaction.guild:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Gamer, this command only works in servers. The echoes of Hallownest need a proper gathering place!",
                    ephemeral=True,
                )
            return

        setting = setting.lower()
        
        # Check admin permissions for most settings
        if setting in ["chatter", "edginess", "memory", "context"] and not is_admin(interaction.user):
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Only guild admins can tweak my settings, gamer!",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    "Only guild admins can tweak my settings, gamer!",
                    ephemeral=True,
                )
            return

        # Handle chatter setting
        if setting == "chatter":
            if value is None:
                current = int(
                    guild_spontaneous_chances.get(
                        interaction.guild.id, SPONTANEOUS_RESPONSE_CHANCE
                    ) * 100
                )
                message = f"Spontaneous chatter chance is {current}%"
            else:
                try:
                    chance = int(value)
                    if chance < 0 or chance > 100:
                        message = "Chance must be between 0 and 100, gamer!"
                    else:
                        guild_spontaneous_chances[interaction.guild.id] = chance / 100
                        message = f"Spontaneous chatter set to {chance}%"
                except ValueError:
                    message = "Chance must be a number between 0 and 100, gamer!"

        # Handle edginess setting
        elif setting == "edginess":
            if value is None:
                current = database.get_edginess(interaction.guild.id)
                message = f"Edginess level is {current}"
            else:
                try:
                    level = int(value)
                    if level < 1 or level > 10:
                        message = "Level must be between 1 and 10, gamer!"
                    else:
                        database.set_edginess(interaction.guild.id, level)
                        message = f"Edginess set to {level}"
                except ValueError:
                    message = "Level must be a number between 1 and 10, gamer!"

        # Handle memory setting
        elif setting == "memory":
            if not action:
                message = "Memory actions: `add <text>`, `list`, `delete <id>`"
            else:
                action = action.lower()
                if action == "add":
                    if not value:
                        message = "Gamer, you need to provide memory text! Usage: `/hollow-bot config memory add <text>`"
                    else:
                        mem_id = database.add_memory(interaction.guild.id, value)
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
                        message = "Gamer, you need to provide a memory ID! Usage: `/hollow-bot config memory delete <id>`"
                    else:
                        database.delete_memory(interaction.guild.id, memory_id)
                        message = "Memory deleted."
                else:
                    message = "Invalid memory action! Use: `add`, `list`, or `delete`"

        # Handle context setting
        elif setting == "context":
            if not action:
                message = "Context actions: `set <text>`, `show`, `clear`"
            else:
                action = action.lower()
                if action == "set":
                    if not value:
                        message = "Gamer, you need to provide context text! Usage: `/hollow-bot config context set <text>`"
                    else:
                        validated = validate_custom_context(value)
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
                    previous = database.get_custom_context(interaction.guild.id)
                    database.clear_custom_context(interaction.guild.id)
                    message = "Custom context cleared."
                    if previous:
                        message += f" Previous: {previous}"
                else:
                    message = "Invalid context action! Use: `set`, `show`, or `clear`"

        else:
            message = "Invalid setting! Use: `chatter`, `edginess`, `memory`, or `context`"

        if not interaction.response.is_done():
            await interaction.response.send_message(message, ephemeral=True)
        else:
            await interaction.followup.send(message, ephemeral=True)
            
    except ValidationError as e:
        log.warning(f"Validation error in config_command: {e}")
        if not interaction.response.is_done():
            await interaction.response.send_message(str(e), ephemeral=True)
        else:
            await interaction.followup.send(str(e), ephemeral=True)
    except Exception as e:
        log.error(f"Error in config_command: {e}")
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "The Infection got to my config system. Try again later, gamer!",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                "The Infection got to my config system. Try again later, gamer!",
                ephemeral=True,
            )


# Groups converted to single commands above


@hollow_group.command(
    name="reminders",
    description="Manage daily reminder settings"
)
@app_commands.describe(
    action="Action to perform: setup, schedule, or status",
    time="Time for daily reminders (HH:MM format, for schedule action)",
    timezone="Timezone for reminders (default: UTC, for schedule action)"
)
async def reminders_command(
    interaction: discord.Interaction,
    action: str,
    time: Optional[str] = None,
    timezone: Optional[str] = "UTC"
) -> None:
    """Unified reminders command for setting up daily recaps."""
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
                    "Gamer, you need Manage Server permissions to set up reminders. The Infection won't let just anyone mess with the echoes.",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    "Gamer, you need Manage Server permissions to set up reminders. The Infection won't let just anyone mess with the echoes.",
                    ephemeral=True,
                )
            return

        action = action.lower()

        if action == "setup":
            if not interaction.channel:
                message = "Gamer, I need to know which channel to use! Run this command in the channel where you want daily reminders."
            else:
                database.set_recap_channel(interaction.guild.id, interaction.channel.id)
                message = f"📜 Chronicle channel set to {interaction.channel.mention}. The echoes of Hallownest will be recorded here daily, gamer!"

        elif action == "schedule":
            if not time:
                message = "Gamer, you need to provide a time! Usage: `/hollow-bot reminders schedule <time> [timezone]`"
            else:
                try:
                    validated_time = validate_time_format(time)
                    validated_timezone = validate_timezone(timezone)
                    database.set_recap_time(interaction.guild.id, validated_time, validated_timezone)
                    message = f"⏰ Chronicle scheduled for **{validated_time} {validated_timezone}**. The echoes of Hallownest will be chronicled daily at this time, gamer!"
                except ValidationError as e:
                    message = f"Gamer, {e}. Even the Pale King had better time management than that!"

        elif action == "status":
            # Get current reminder settings
            guild_config = database.get_guild_config(interaction.guild.id)
            if guild_config:
                channel_id, recap_time, timezone_str = guild_config
                if channel_id and recap_time:
                    try:
                        channel = interaction.guild.get_channel(channel_id)
                        channel_name = channel.mention if channel else f"<#{channel_id}>"
                        message = f"📜 **Current Reminder Settings:**\n"
                        message += f"• **Channel**: {channel_name}\n"
                        message += f"• **Time**: {recap_time} {timezone_str}\n"
                        message += f"• **Status**: ✅ Active"
                    except Exception:
                        message = f"📜 **Current Reminder Settings:**\n"
                        message += f"• **Channel**: <#{channel_id}>\n"
                        message += f"• **Time**: {recap_time} {timezone_str}\n"
                        message += f"• **Status**: ⚠️ Channel may be deleted"
                else:
                    message = "📜 **Current Reminder Settings:**\n• **Status**: ❌ Not configured\n\nUse `/hollow-bot reminders setup` to set a channel and `/hollow-bot reminders schedule <time>` to set a time."
            else:
                message = "📜 **Current Reminder Settings:**\n• **Status**: ❌ Not configured\n\nUse `/hollow-bot reminders setup` to set a channel and `/hollow-bot reminders schedule <time>` to set a time."

        else:
            message = "Invalid action! Use: `setup`, `schedule`, or `status`"

        if not interaction.response.is_done():
            await interaction.response.send_message(message)
        else:
            await interaction.followup.send(message)

    except Exception as e:
        log.error(f"Error in reminders_command: {e}")
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "The Infection got to my reminder system. Try again later, gamer!",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                "The Infection got to my reminder system. Try again later, gamer!",
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
    """Show the leaderboard of most accomplished gamers based on game stats."""
    try:
        if not interaction.guild:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Gamer, this command only works in servers. The echoes of Hallownest need a proper gathering place!",
                    ephemeral=True,
                )
            return

        # Get game stats from database
        game_stats = database.get_game_stats_leaderboard(interaction.guild.id)
        
        if not game_stats:
            message = "No gamers have uploaded save data yet! Be the first to upload a .dat file to start tracking your Hallownest journey!"
            if not interaction.response.is_done():
                await interaction.response.send_message(message)
            else:
                await interaction.followup.send(message)
            return

        # Build leaderboard message
        message = "🏆 **Hallownest Game Stats Leaderboard** 🏆\n\n"
        
        for i, (user_id, completion_percent, playtime_hours, bosses_defeated, geo, deaths, nail_upgrades, charms_owned) in enumerate(game_stats[:10]):
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
            
            # Determine game stage based on completion
            if completion_percent >= 100:
                stage = "🏆 Complete"
            elif completion_percent >= 80:
                stage = "🔥 End Game"
            elif completion_percent >= 50:
                stage = "⚔️ Late Game"
            elif completion_percent >= 20:
                stage = "🗡️ Mid Game"
            else:
                stage = "🌱 Early Game"
            
            message += f"{rank_emoji} **{display_name}** - {stage}\n"
            message += f"   🎮 {completion_percent}% complete | ⏱️ {playtime_hours:.1f}h | 👹 {bosses_defeated} bosses\n"
            message += f"   💰 {geo:,} geo | 💀 {deaths} deaths | 🗡️ +{nail_upgrades} nail | 🎭 {charms_owned} charms\n\n"
        
        if len(game_stats) > 10:
            message += f"... and {len(game_stats) - 10} more gamers on their journey!\n\n"
        
        message += "*Leaderboard based on actual game progress: completion %, playtime, bosses defeated, and achievements!* 🗡️"

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
            "**Core Commands:**\n"
            "• `/hollow-bot record <text>` - Record your latest achievement\n"
            "• `/hollow-bot progress [user] [limit] [history]` - Check save data and progress history\n"
            "• `/hollow-bot leaderboard` - See who's ahead in the journey\n"
            "• `/hollow-bot info` - Show this info\n\n"
            "**Configuration Commands:**\n"
            "• `/hollow-bot config <setting> [value]` - Configure bot settings\n"
            "  - `chatter <0-100>` - Set random chatter chance\n"
            "  - `edginess <1-10>` - Set edginess level\n"
            "  - `memory <action> [text/id]` - Manage server memories\n"
            "  - `context <action> [text]` - Manage custom context\n"
            "• `/hollow-bot reminders <action> [args]` - Manage daily reminders\n"
            "  - `setup` - Set reminder channel\n"
            "  - `schedule <time> [timezone]` - Schedule daily recaps\n"
            "  - `status` - Check current settings\n\n"
            "**Save Files:** Upload .dat files to track detailed progress with stats!\n"
            "**Chat:** Just @ me to talk! I remember our conversations and give gamer advice.\n\n"
            "Ready to chronicle your journey through Hallownest, gamer! 🗡️"
        )

        await safe_interaction_response(interaction, info_message)
                
    except Exception as e:
        log.error(f"Error in slash_info: {e}")
        await safe_interaction_response(
            interaction, 
            "The Infection got to my info system. Try again later, gamer!",
            ephemeral=True
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
