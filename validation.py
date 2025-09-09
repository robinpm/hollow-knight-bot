"""Input validation and sanitization for Hollow Knight bot."""

import re
from typing import Optional

from logger import log


class ValidationError(Exception):
    """Custom exception for validation errors."""
    pass


def validate_guild_id(guild_id: int) -> None:
    """Validate guild ID."""
    if not isinstance(guild_id, int) or guild_id <= 0:
        raise ValidationError("Guild ID must be a positive integer")


def validate_user_id(user_id: int) -> None:
    """Validate user ID."""
    if not isinstance(user_id, int) or user_id <= 0:
        raise ValidationError("User ID must be a positive integer")


def validate_progress_text(text: str) -> str:
    """Validate and sanitize progress text."""
    if not text or not isinstance(text, str):
        raise ValidationError("Progress text cannot be empty")
    
    # Strip whitespace
    text = text.strip()
    
    if not text:
        raise ValidationError("Progress text cannot be empty after trimming")
    
    # Check length limits
    if len(text) > 1000:
        raise ValidationError("Progress text is too long (max 1000 characters)")
    
    # Basic sanitization - remove potential harmful content
    # Remove excessive whitespace
    text = re.sub(r'\s+', ' ', text)
    
    # Log validation
    log.debug(f"Validated progress text: {len(text)} characters")
    
    return text


def validate_time_format(time_str: str) -> str:
    """Validate time format (HH:MM)."""
    if not time_str or not isinstance(time_str, str):
        raise ValidationError("Time cannot be empty")
    
    time_str = time_str.strip()
    
    # Check format
    if not re.match(r'^([01]\d|2[0-3]):[0-5]\d$', time_str):
        raise ValidationError("Time must be in HH:MM format (24-hour)")
    
    return time_str


def validate_timezone(timezone_str: str) -> str:
    """Validate timezone string."""
    if not timezone_str or not isinstance(timezone_str, str):
        raise ValidationError("Timezone cannot be empty")
    
    timezone_str = timezone_str.strip()
    
    # Common timezone formats
    timezone_patterns = [
        r'^UTC$',  # UTC
        r'^UTC[+-]\d{1,2}$',  # UTC+5, UTC-8
        r'^UTC[+-]\d{1,2}:\d{2}$',  # UTC+05:30, UTC-08:00
        r'^[A-Z]{3,4}$',  # EST, PST, GMT
        r'^[A-Za-z_/]+$',  # America/New_York, Europe/London
    ]
    
    # Check if it matches any valid timezone pattern
    if not any(re.match(pattern, timezone_str) for pattern in timezone_patterns):
        raise ValidationError("Invalid timezone format. Use UTC, UTC+5, EST, or America/New_York format")
    
    # Check length
    if len(timezone_str) > 50:
        raise ValidationError("Timezone string is too long (max 50 characters)")
    
    return timezone_str


def validate_channel_id(channel_id: int) -> None:
    """Validate channel ID."""
    if not isinstance(channel_id, int) or channel_id <= 0:
        raise ValidationError("Channel ID must be a positive integer")


def sanitize_mention_command(content: str) -> tuple[bool, str]:
    """Parse and validate mention command content."""
    if not content or not isinstance(content, str):
        return False, ""
    
    # Remove leading/trailing whitespace
    content = content.strip()
    
    # Check for mention pattern
    mention_match = re.match(r'^<@!?(\d+)>\s*(.*)$', content)
    if not mention_match:
        return False, ""
    
    # Extract the rest of the message
    rest = mention_match.group(2).strip()
    
    return True, rest


def validate_server_name(server_name: str) -> str:
    """Validate and sanitize server name."""
    if not server_name or not isinstance(server_name, str):
        raise ValidationError("Server name cannot be empty")
    
    server_name = server_name.strip()
    
    if not server_name:
        raise ValidationError("Server name cannot be empty after trimming")
    
    if len(server_name) > 100:
        raise ValidationError("Server name is too long (max 100 characters)")
    
    return server_name


def validate_updates_dict(updates_by_user: dict) -> dict:
    """Validate updates dictionary structure."""
    if not isinstance(updates_by_user, dict):
        raise ValidationError("Updates must be a dictionary")
    
    validated = {}
    for user, updates in updates_by_user.items():
        if not isinstance(user, str) or not user.strip():
            log.warning(f"Skipping invalid user: {user}")
            continue
        
        if not isinstance(updates, list):
            log.warning(f"Skipping invalid updates for user {user}: not a list")
            continue
        
        validated_updates = []
        for update in updates:
            try:
                validated_update = validate_progress_text(update)
                validated_updates.append(validated_update)
            except ValidationError as e:
                log.warning(f"Skipping invalid update for user {user}: {e}")
                continue
        
        if validated_updates:
            validated[user.strip()] = validated_updates
    
    return validated


def validate_custom_context(text: str) -> str:
    """Validate custom context text."""
    if not isinstance(text, str):
        raise ValidationError("Custom context must be a string")

    text = text.strip()

    if not text:
        raise ValidationError("Custom context cannot be empty")

    if len(text) > 1000:
        raise ValidationError("Custom context is too long (max 1000 characters)")

    return text
