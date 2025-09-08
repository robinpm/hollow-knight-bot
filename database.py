"""SQLite helpers for tracking Hollow Knight progress."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from config import config
from logger import log


class DatabaseError(Exception):
    """Custom exception for database operations."""
    pass


class DatabaseManager:
    """Manages database connections and operations."""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._initialize_database()
    
    def _initialize_database(self) -> None:
        """Initialize database tables and indexes."""
        try:
            with self.get_connection() as conn:
                conn.execute(
                    """CREATE TABLE IF NOT EXISTS progress (
                        guild_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        update_text TEXT NOT NULL,
                        ts INTEGER NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )"""
                )
                conn.execute(
                    """CREATE TABLE IF NOT EXISTS guild_config (
                        guild_id TEXT PRIMARY KEY,
                        recap_channel_id TEXT,
                        recap_time_utc TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )"""
                )
                conn.execute(
                    """CREATE INDEX IF NOT EXISTS idx_progress_guild_user 
                       ON progress (guild_id, user_id, ts DESC)"""
                )
                conn.execute(
                    """CREATE INDEX IF NOT EXISTS idx_progress_timestamp 
                       ON progress (ts)"""
                )
                log.info("Database initialized successfully")
        except sqlite3.Error as e:
            log.error(f"Failed to initialize database: {e}")
            raise DatabaseError(f"Database initialization failed: {e}") from e
    
    @contextmanager
    def get_connection(self):
        """Get a database connection with proper error handling."""
        conn = None
        try:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            yield conn
        except sqlite3.Error as e:
            log.error(f"Database connection error: {e}")
            raise DatabaseError(f"Database operation failed: {e}") from e
        finally:
            if conn:
                conn.close()


# Global database manager instance
_db_manager = DatabaseManager(config.database_path)


def add_update(guild_id: int, user_id: int, text: str, ts: int) -> None:
    """Store a progress update with proper validation and error handling."""
    if not text or not text.strip():
        raise ValueError("Update text cannot be empty")
    
    if ts <= 0:
        raise ValueError("Timestamp must be positive")
    
    try:
        with _db_manager.get_connection() as conn:
            conn.execute(
                "INSERT INTO progress (guild_id, user_id, update_text, ts) VALUES (?, ?, ?, ?)",
                (str(guild_id), str(user_id), text.strip(), ts),
            )
            log.info(f"Added progress update for guild {guild_id}, user {user_id}")
    except sqlite3.Error as e:
        log.error(f"Failed to add update: {e}")
        raise DatabaseError(f"Failed to add progress update: {e}") from e


def get_last_update(guild_id: int, user_id: int) -> Optional[Tuple[str, int]]:
    """Return the most recent update for a user in a guild."""
    try:
        with _db_manager.get_connection() as conn:
            cur = conn.execute(
                "SELECT update_text, ts FROM progress WHERE guild_id=? AND user_id=? ORDER BY ts DESC LIMIT 1",
                (str(guild_id), str(user_id)),
            )
            row = cur.fetchone()
            return (row["update_text"], row["ts"]) if row else None
    except sqlite3.Error as e:
        log.error(f"Failed to get last update: {e}")
        raise DatabaseError(f"Failed to retrieve last update: {e}") from e


def get_updates_today_by_guild(guild_id: int) -> Dict[str, List[str]]:
    """Return today's updates grouped by user id."""
    try:
        start_of_day = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        start_ts = int(start_of_day.timestamp())
        
        with _db_manager.get_connection() as conn:
            cur = conn.execute(
                "SELECT user_id, update_text FROM progress WHERE guild_id=? AND ts>=? ORDER BY ts",
                (str(guild_id), start_ts),
            )
            updates: Dict[str, List[str]] = {}
            for row in cur.fetchall():
                updates.setdefault(row["user_id"], []).append(row["update_text"])
            
            log.debug(f"Retrieved {len(updates)} users with updates for guild {guild_id}")
            return updates
    except sqlite3.Error as e:
        log.error(f"Failed to get today's updates: {e}")
        raise DatabaseError(f"Failed to retrieve today's updates: {e}") from e


def set_recap_channel(guild_id: int, channel_id: int) -> None:
    """Persist the channel to post recaps in."""
    try:
        with _db_manager.get_connection() as conn:
            conn.execute(
                """INSERT INTO guild_config (guild_id, recap_channel_id, updated_at) 
                   VALUES (?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(guild_id) DO UPDATE SET 
                   recap_channel_id=excluded.recap_channel_id,
                   updated_at=CURRENT_TIMESTAMP""",
                (str(guild_id), str(channel_id)),
            )
            log.info(f"Set recap channel for guild {guild_id} to {channel_id}")
    except sqlite3.Error as e:
        log.error(f"Failed to set recap channel: {e}")
        raise DatabaseError(f"Failed to set recap channel: {e}") from e


def set_recap_time(guild_id: int, hhmm: str) -> None:
    """Persist the UTC time for daily recaps (format HH:MM)."""
    # Validate time format
    if not hhmm or len(hhmm) != 5 or hhmm[2] != ':':
        raise ValueError("Time must be in HH:MM format")
    
    try:
        hour, minute = hhmm.split(':')
        hour_int, minute_int = int(hour), int(minute)
        if not (0 <= hour_int <= 23 and 0 <= minute_int <= 59):
            raise ValueError("Invalid time values")
    except ValueError as e:
        raise ValueError(f"Invalid time format: {e}") from e
    
    try:
        with _db_manager.get_connection() as conn:
            conn.execute(
                """INSERT INTO guild_config (guild_id, recap_time_utc, updated_at) 
                   VALUES (?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(guild_id) DO UPDATE SET 
                   recap_time_utc=excluded.recap_time_utc,
                   updated_at=CURRENT_TIMESTAMP""",
                (str(guild_id), hhmm),
            )
            log.info(f"Set recap time for guild {guild_id} to {hhmm}")
    except sqlite3.Error as e:
        log.error(f"Failed to set recap time: {e}")
        raise DatabaseError(f"Failed to set recap time: {e}") from e


def get_all_guild_configs() -> List[Tuple[str, Optional[str], Optional[str]]]:
    """Return all guild configs."""
    try:
        with _db_manager.get_connection() as conn:
            cur = conn.execute(
                "SELECT guild_id, recap_channel_id, recap_time_utc FROM guild_config"
            )
            configs = [
                (row["guild_id"], row["recap_channel_id"], row["recap_time_utc"])
                for row in cur.fetchall()
            ]
            log.debug(f"Retrieved {len(configs)} guild configurations")
            return configs
    except sqlite3.Error as e:
        log.error(f"Failed to get guild configs: {e}")
        raise DatabaseError(f"Failed to retrieve guild configurations: {e}") from e


def get_guild_config(guild_id: int) -> Optional[Tuple[Optional[str], Optional[str]]]:
    """Get configuration for a specific guild."""
    try:
        with _db_manager.get_connection() as conn:
            cur = conn.execute(
                "SELECT recap_channel_id, recap_time_utc FROM guild_config WHERE guild_id = ?",
                (str(guild_id),)
            )
            row = cur.fetchone()
            return (row["recap_channel_id"], row["recap_time_utc"]) if row else None
    except sqlite3.Error as e:
        log.error(f"Failed to get guild config for {guild_id}: {e}")
        raise DatabaseError(f"Failed to retrieve guild configuration: {e}") from e