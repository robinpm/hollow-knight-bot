"""SQLite helpers for tracking Hollow Knight progress."""

import os
import sqlite3
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

DB_PATH = os.getenv("DATABASE_PATH", "bot.sqlite3")
_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
_conn.row_factory = sqlite3.Row

with _conn:
    _conn.execute(
        """CREATE TABLE IF NOT EXISTS progress (
                guild_id TEXT,
                user_id TEXT,
                update TEXT,
                ts INTEGER
            )"""
    )
    _conn.execute(
        """CREATE TABLE IF NOT EXISTS guild_config (
                guild_id TEXT PRIMARY KEY,
                recap_channel_id TEXT,
                recap_time_utc TEXT
            )"""
    )
    _conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_progress ON progress (guild_id, user_id, ts)"""
    )


def add_update(guild_id: int, user_id: int, text: str, ts: int) -> None:
    """Store a progress update."""
    with _conn:
        _conn.execute(
            "INSERT INTO progress (guild_id, user_id, update, ts) VALUES (?, ?, ?, ?)",
            (str(guild_id), str(user_id), text, ts),
        )


def get_last_update(guild_id: int, user_id: int) -> Optional[Tuple[str, int]]:
    """Return the most recent update for a user in a guild."""
    cur = _conn.execute(
        "SELECT update, ts FROM progress WHERE guild_id=? AND user_id=? ORDER BY ts DESC LIMIT 1",
        (str(guild_id), str(user_id)),
    )
    row = cur.fetchone()
    return (row["update"], row["ts"]) if row else None


def get_updates_today_by_guild(guild_id: int) -> Dict[str, List[str]]:
    """Return today's updates grouped by user id."""
    start_of_day = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    start_ts = int(start_of_day.timestamp())
    cur = _conn.execute(
        "SELECT user_id, update FROM progress WHERE guild_id=? AND ts>=? ORDER BY ts",
        (str(guild_id), start_ts),
    )
    updates: Dict[str, List[str]] = {}
    for row in cur.fetchall():
        updates.setdefault(row["user_id"], []).append(row["update"])
    return updates


def set_recap_channel(guild_id: int, channel_id: int) -> None:
    """Persist the channel to post recaps in."""
    with _conn:
        _conn.execute(
            "INSERT INTO guild_config (guild_id, recap_channel_id) VALUES (?, ?)"
            " ON CONFLICT(guild_id) DO UPDATE SET recap_channel_id=excluded.recap_channel_id",
            (str(guild_id), str(channel_id)),
        )


def set_recap_time(guild_id: int, hhmm: str) -> None:
    """Persist the UTC time for daily recaps (format HH:MM)."""
    with _conn:
        _conn.execute(
            "INSERT INTO guild_config (guild_id, recap_time_utc) VALUES (?, ?)"
            " ON CONFLICT(guild_id) DO UPDATE SET recap_time_utc=excluded.recap_time_utc",
            (str(guild_id), hhmm),
        )


def get_all_guild_configs() -> List[Tuple[str, Optional[str], Optional[str]]]:
    """Return all guild configs."""
    cur = _conn.execute(
        "SELECT guild_id, recap_channel_id, recap_time_utc FROM guild_config"
    )
    return [
        (row["guild_id"], row["recap_channel_id"], row["recap_time_utc"])
        for row in cur.fetchall()
    ]
