"""Integration with Google's Gemini GenAI model for generating daily recaps."""

import os
from datetime import datetime, timezone
from typing import Dict, List

from google import genai


# The environment variable GEMINI_MODEL allows overriding the default model name.
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# The client reads the API key from GEMINI_API_KEY or GOOGLE_API_KEY env var automatically.
_client = genai.Client()


def _format_prompt(
    server_name: str, date_str: str, updates_by_user: Dict[str, List[str]]
) -> str:
    """Construct a playful prompt summarizing the day's progress updates."""
    lines: List[str] = [
        "You are 'The Chronicler of Hallownest' writing a short, hype recap.",
        f"Server: {server_name}",
        f"Date (UTC): {date_str}",
        "Write 5–10 sentences max. Make it playful, in-universe, PG-13, and avoid insults.",
        "Mention players by their display names and summarize what each did.",
        "Then end with a one-line rallying cry.",
        "",
        "RAW UPDATES:",
    ]
    for user, items in updates_by_user.items():
        for item in items:
            lines.append(f"- {user}: {item}")
    return "\n".join(lines)


def generate_daily_summary(
    server_name: str, updates_by_user: Dict[str, List[str]]
) -> str:
    """Generate a daily recap using the Gemini model.

    If there are no updates, returns a quiet response. Otherwise constructs a prompt
    and sends it to the Gemini API.
    """
    if not updates_by_user:
        return "The caverns are quiet today. No new echoes stir in Hallownest."
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prompt = _format_prompt(server_name, date_str, updates_by_user)
    response = _client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
    )
    # The SDK returns a TextResult; extract text and ensure fallback.
    text = (response.text or "").strip()
    return text or "The Chronicler fell silent. Try again later."