"""Gemini model helpers for Hollow Knight bot."""

import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from google import genai

from config import config
from logger import log


class GeminiError(Exception):
    """Custom exception for Gemini API operations."""
    pass


class GeminiClient:
    """Wrapper for Gemini API with retry logic and error handling."""
    
    def __init__(self, model: str = None, max_retries: int = None, timeout: int = None):
        self.model = model or config.gemini_model
        self.max_retries = max_retries or config.max_retries
        self.timeout = timeout or config.request_timeout
        self._client = genai.Client()
    
    def generate_content(self, prompt: str, model: Optional[str] = None) -> str:
        """Generate content with retry logic and proper error handling."""
        model = model or self.model
        
        for attempt in range(self.max_retries):
            try:
                log.debug(f"Generating content with Gemini (attempt {attempt + 1}/{self.max_retries})")
                resp = self._client.models.generate_content(model=model, contents=prompt)
                
                if not resp or not resp.text:
                    log.warning("Empty response from Gemini")
                    return self._get_fallback_response()
                
                return resp.text.strip()
                
            except Exception as e:
                log.warning(f"Gemini API error on attempt {attempt + 1}: {e}")
                
                if attempt == self.max_retries - 1:
                    log.error(f"All {self.max_retries} attempts failed for Gemini API")
                    return self._get_fallback_response()
                
                # Exponential backoff
                wait_time = 2 ** attempt
                log.info(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
        
        return self._get_fallback_response()
    
    def _get_fallback_response(self) -> str:
        """Get a character-appropriate fallback response."""
        return "The Chronicler met a Shade while scribing. Those things are absolute menaces, even to digital entities. Later, gamer."


# Global Gemini client instance
_gemini_client = GeminiClient()


def generate_daily_summary(server_name: str, updates_by_user: Dict[str, List[str]]) -> str:
    """Ask Gemini to draft a playful daily recap.

    Args:
        server_name: Discord server name.
        updates_by_user: Mapping of user display names to their raw updates.

    Returns:
        Gemini's text response or a gentle fallback line.
    """
    if not updates_by_user:
        return "The caverns are quiet today. No new echoes stir in Hallownest. Even the Primal Aspids are taking a break from being absolute menaces."

    try:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        lines: List[str] = [
            f"Server: {server_name}",
            f"Date (UTC): {date_str}",
            "",
            "You are HollowBot, a seasoned Hollow Knight gamer and digital chronicler of Hallownest. "
            "Write a daily recap that sounds like a gamer friend who's already 112% the game. "
            "Mix Hollow Knight lore with real gaming experiences and memes. Reference bosses, locations, "
            "mechanics, and the pain of losing geo. Be supportive but playfully snarky about progress. "
            "Use gaming terminology naturally. Keep it PG-13 and fun. Never break character - "
            "even if something goes wrong, blame it on the Infection or a particularly nasty Shade.",
            "",
            "RAW UPDATES:",
        ]
        for user, updates in updates_by_user.items():
            for update in updates:
                lines.append(f"- {user}: {update}")
        prompt = "\n".join(lines)

        log.info(f"Generating daily summary for {server_name} with {len(updates_by_user)} users")
        return _gemini_client.generate_content(prompt)
        
    except Exception as e:
        log.error(f"Failed to generate daily summary: {e}")
        return "The Chronicler fell silent. Probably got distracted by a particularly shiny geo deposit. Try again later."


def generate_reply(prompt: str, model: Optional[str] = None) -> str:
    """Return a quick snarky reply from Gemini."""
    try:
        log.debug("Generating reply with Gemini")
        return _gemini_client.generate_content(prompt, model)
    except Exception as e:
        log.error(f"Failed to generate reply: {e}")
        return "The Infection got to my response system. But I noted that, don't worry."
