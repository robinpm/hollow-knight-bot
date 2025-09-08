"""Gemini model helpers for Hollow Knight bot."""

import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

from google import genai

_client = genai.Client()
DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")


def generate_daily_summary(server_name: str, updates_by_user: Dict[str, List[str]]) -> str:
    """Ask Gemini to draft a playful daily recap.

    Args:
        server_name: Discord server name.
        updates_by_user: Mapping of user display names to their raw updates.

    Returns:
        Gemini's text response or a gentle fallback line.
    """
    if not updates_by_user:
        return "The caverns are quiet today. No new echoes stir in Hallownest."

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines: List[str] = [
        f"Server: {server_name}",
        f"Date (UTC): {date_str}",
        "Style: playful, in-universe, PG-13, no insults.",
        "",
        "RAW UPDATES:",
    ]
    for user, updates in updates_by_user.items():
        for update in updates:
            lines.append(f"- {user}: {update}")
    prompt = "\n".join(lines)

    try:
        resp = _client.models.generate_content(model=DEFAULT_MODEL, contents=prompt)
        return (resp.text or "").strip() or "The Chronicler fell silent. Try again later."
    except Exception:
        return "The Chronicler met a Shade while scribing. Later."


def generate_reply(prompt: str, model: Optional[str] = None) -> str:
    """Return a quick snarky reply from Gemini."""
    model = model or DEFAULT_MODEL
    try:
        resp = _client.models.generate_content(model=model, contents=prompt)
        return (resp.text or "").strip() or "Noted."
    except Exception:
        return "Noted."
