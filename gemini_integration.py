"""Gemini model helpers for Hollow Knight bot."""

import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

import google.generativeai as genai

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
        
        # Only initialize client if we have a real API key
        if config.google_api_key and config.google_api_key != "dummy-key-for-testing":
            try:
                genai.configure(api_key=config.google_api_key)
                self._client = genai
            except Exception as e:
                log.warning(f"Failed to initialize Gemini client: {e}")
                self._client = None
        else:
            self._client = None
    
    def generate_content(self, prompt: str, model: Optional[str] = None) -> str:
        """Generate content with retry logic and proper error handling."""
        # Return fallback if no client available
        if not self._client:
            return self._get_fallback_response()
        
        model = model or self.model
        
        for attempt in range(self.max_retries):
            try:
                log.debug(f"Generating content with Gemini (attempt {attempt + 1}/{self.max_retries})")
                model_instance = self._client.GenerativeModel(model)
                resp = model_instance.generate_content(prompt)
                
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


def generate_daily_summary(server_name: str, updates_by_user: Dict[str, List[str]], edginess: int = 5) -> str:
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
            f"Edginess level: {edginess}",
            "",
            "You are HollowBot, a seasoned Hollow Knight gamer. Write a SHORT daily recap (2-3 sentences max) "
            "that sounds like a gamer friend who's already 112% the game. Mix Hollow Knight lore with real "
            "gaming experiences. Reference bosses, locations, and the pain of losing geo. Be supportive but "
            "playfully snarky. Keep it concise and fun. Never break character - blame issues on the Infection.",
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


def generate_reply(
    prompt: str, model: Optional[str] = None, edginess: Optional[int] = None
) -> str:
    """Return a quick snarky reply from Gemini."""
    try:
        log.debug("Generating reply with Gemini")
        extra = f"\nEdginess level: {edginess}" if edginess is not None else ""
        short_prompt = (
            f"{prompt}{extra}\n\nIMPORTANT: Keep your response SHORT - maximum 1-2 sentences. Be concise and to the point. Do NOT include 'HollowBot:' or any name prefix in your response."
        )
        return _gemini_client.generate_content(short_prompt, model)
    except Exception as e:
        log.error(f"Failed to generate reply: {e}")
        return "The Infection got to my response system. But I noted that, don't worry."


def generate_memory(text: str) -> str:
    """Create a concise memory from a progress update."""
    try:
        prompt = (
            "You are HollowBot. Given the following progress update, create a short memory to "
            "remember about this server. Keep it under one sentence and avoid generic replies.\n"
            f"Progress update: {text}\nMemory:"
        )
        return _gemini_client.generate_content(prompt)
    except Exception as e:
        log.error(f"Failed to generate memory: {e}")
        return ""
