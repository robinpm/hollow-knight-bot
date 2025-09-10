"""Database layer for Hollow Knight bot with SQLite and PostgreSQL support."""

import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Union

from config import config

log = logging.getLogger(__name__)


class DatabaseError(Exception):
    """Database operation error."""
    pass


class DatabaseManager:
    """Manages database connections and operations."""
    
    def __init__(self):
        self._use_postgres = bool(config.database_url)
        if self._use_postgres:
            log.info("Using PostgreSQL database")
            self._init_postgres()
        else:
            log.info("Using SQLite database")
            self._init_sqlite()
    
    def _init_sqlite(self):
        """Initialize SQLite database."""
        self._db_path = config.database_path
        self._ensure_sqlite_tables()
    
    def _init_postgres(self):
        """Initialize PostgreSQL database."""
        try:
            import psycopg2
            from psycopg2.extras import RealDictCursor
            self._psycopg2 = psycopg2
            self._RealDictCursor = RealDictCursor
            self._ensure_postgres_tables()
        except ImportError:
            raise DatabaseError("psycopg2-binary is required for PostgreSQL support")
    
    def _ensure_sqlite_tables(self):
        """Create SQLite tables if they don't exist."""
        with self.get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS progress (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    update_text TEXT NOT NULL,
                    ts INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS guild_config (
                    guild_id TEXT PRIMARY KEY,
                    recap_channel_id TEXT,
                    recap_time TEXT,
                    timezone TEXT DEFAULT 'UTC',
                    custom_context TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Ensure custom_context column exists for older databases
            try:
                conn.execute("ALTER TABLE guild_config ADD COLUMN custom_context TEXT")
            except sqlite3.OperationalError:
                pass
            
            # Create indexes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_progress_guild_user ON progress(guild_id, user_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_progress_ts ON progress(ts)")
            conn.commit()
            log.info("SQLite database initialized successfully")
    
    def _ensure_postgres_tables(self):
        """Create PostgreSQL tables if they don't exist."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS progress (
                        id SERIAL PRIMARY KEY,
                        guild_id VARCHAR(255) NOT NULL,
                        user_id VARCHAR(255) NOT NULL,
                        update_text TEXT NOT NULL,
                        ts BIGINT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS guild_config (
                        guild_id VARCHAR(255) PRIMARY KEY,
                        recap_channel_id VARCHAR(255),
                        recap_time VARCHAR(10),
                        timezone VARCHAR(50) DEFAULT 'UTC',
                        custom_context TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Ensure custom_context column exists for older databases
                cur.execute(
                    "ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS custom_context TEXT"
                )
                
                # Create indexes
                cur.execute("CREATE INDEX IF NOT EXISTS idx_progress_guild_user ON progress(guild_id, user_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_progress_ts ON progress(ts)")
                conn.commit()
                log.info("PostgreSQL database initialized successfully")
    
    @contextmanager
    def get_connection(self):
        """Get database connection with proper error handling."""
        if self._use_postgres:
            conn = None
            try:
                conn = self._psycopg2.connect(
                    config.database_url,
                    cursor_factory=self._RealDictCursor
                )
                yield conn
            except Exception as e:
                if conn:
                    conn.rollback()
                log.error(f"PostgreSQL connection error: {e}")
                raise DatabaseError(f"Database connection failed: {e}") from e
            finally:
                if conn:
                    conn.close()
        else:
            conn = None
            try:
                conn = sqlite3.connect(self._db_path)
                conn.row_factory = sqlite3.Row
                yield conn
            except Exception as e:
                log.error(f"SQLite connection error: {e}")
                raise DatabaseError(f"Database connection failed: {e}") from e
            finally:
                if conn:
                    conn.close()


# Global database manager instance
_db_manager = DatabaseManager()


def add_update(guild_id: int, user_id: int, text: str, ts: int) -> None:
    """Store a progress update with proper validation and error handling."""
    if not text or not text.strip():
        raise ValueError("Update text cannot be empty")
    
    if ts <= 0:
        raise ValueError("Timestamp must be positive")
    
    try:
        with _db_manager.get_connection() as conn:
            if _db_manager._use_postgres:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO progress (guild_id, user_id, update_text, ts) VALUES (%s, %s, %s, %s)",
                        (str(guild_id), str(user_id), text.strip(), ts),
                    )
                    conn.commit()
            else:
                conn.execute(
                    "INSERT INTO progress (guild_id, user_id, update_text, ts) VALUES (?, ?, ?, ?)",
                    (str(guild_id), str(user_id), text.strip(), ts),
                )
                conn.commit()
            log.info(f"Added progress update for guild {guild_id}, user {user_id}")
    except Exception as e:
        log.error(f"Failed to add update: {e}")
        raise DatabaseError(f"Failed to add progress update: {e}") from e


def get_last_update(guild_id: int, user_id: int) -> Optional[Tuple[str, int]]:
    """Return the most recent update for a user in a guild."""
    try:
        with _db_manager.get_connection() as conn:
            if _db_manager._use_postgres:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT update_text, ts FROM progress WHERE guild_id=%s AND user_id=%s ORDER BY ts DESC LIMIT 1",
                        (str(guild_id), str(user_id)),
                    )
                    row = cur.fetchone()
                    return (row["update_text"], row["ts"]) if row else None
            else:
                cur = conn.execute(
                    "SELECT update_text, ts FROM progress WHERE guild_id=? AND user_id=? ORDER BY ts DESC LIMIT 1",
                    (str(guild_id), str(user_id)),
                )
                row = cur.fetchone()
                return (row["update_text"], row["ts"]) if row else None
    except Exception as e:
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
            if _db_manager._use_postgres:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT user_id, update_text FROM progress WHERE guild_id=%s AND ts>=%s ORDER BY ts DESC",
                        (str(guild_id), start_ts),
                    )
                    rows = cur.fetchall()
            else:
                cur = conn.execute(
                    "SELECT user_id, update_text FROM progress WHERE guild_id=? AND ts>=? ORDER BY ts DESC",
                    (str(guild_id), start_ts),
                )
                rows = cur.fetchall()
            
            updates_by_user: Dict[str, List[str]] = {}
            for row in rows:
                user_id = row["user_id"]
                if user_id not in updates_by_user:
                    updates_by_user[user_id] = []
                updates_by_user[user_id].append(row["update_text"])
            
            return updates_by_user
    except Exception as e:
        log.error(f"Failed to get today's updates: {e}")
        raise DatabaseError(f"Failed to retrieve today's updates: {e}") from e


def set_recap_channel(guild_id: int, channel_id: int) -> None:
    """Set the recap channel for a guild."""
    try:
        with _db_manager.get_connection() as conn:
            if _db_manager._use_postgres:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO guild_config (guild_id, recap_channel_id) VALUES (%s, %s) ON CONFLICT (guild_id) DO UPDATE SET recap_channel_id=%s, updated_at=CURRENT_TIMESTAMP",
                        (str(guild_id), str(channel_id), str(channel_id)),
                    )
                    conn.commit()
            else:
                conn.execute(
                    "INSERT OR REPLACE INTO guild_config (guild_id, recap_channel_id, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                    (str(guild_id), str(channel_id)),
                )
                conn.commit()
            log.info(f"Set recap channel for guild {guild_id} to {channel_id}")
    except Exception as e:
        log.error(f"Failed to set recap channel: {e}")
        raise DatabaseError(f"Failed to set recap channel: {e}") from e


def set_recap_time(guild_id: int, time_str: str, timezone_str: str = "UTC") -> None:
    """Set the recap time and timezone for a guild."""
    try:
        with _db_manager.get_connection() as conn:
            if _db_manager._use_postgres:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO guild_config (guild_id, recap_time, timezone) VALUES (%s, %s, %s) ON CONFLICT (guild_id) DO UPDATE SET recap_time=%s, timezone=%s, updated_at=CURRENT_TIMESTAMP",
                        (str(guild_id), time_str, timezone_str, time_str, timezone_str),
                    )
                    conn.commit()
            else:
                conn.execute(
                    "INSERT OR REPLACE INTO guild_config (guild_id, recap_time, timezone, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                    (str(guild_id), time_str, timezone_str),
                )
                conn.commit()
            log.info(f"Set recap time for guild {guild_id} to {time_str} {timezone_str}")
    except Exception as e:
        log.error(f"Failed to set recap time: {e}")
        raise DatabaseError(f"Failed to set recap time: {e}") from e


def get_all_guild_configs() -> List[Tuple[int, Optional[int], Optional[str], str]]:
    """Return all guild configurations with timezone."""
    try:
        with _db_manager.get_connection() as conn:
            if _db_manager._use_postgres:
                with conn.cursor() as cur:
                    cur.execute("SELECT guild_id, recap_channel_id, recap_time, timezone FROM guild_config")
                    rows = cur.fetchall()
            else:
                cur = conn.execute("SELECT guild_id, recap_channel_id, recap_time, timezone FROM guild_config")
                rows = cur.fetchall()
            
            configs = []
            for row in rows:
                guild_id = int(row["guild_id"])
                channel_id = int(row["recap_channel_id"]) if row["recap_channel_id"] else None
                recap_time = row["recap_time"]
                timezone_str = row["timezone"] or "UTC"
                configs.append((guild_id, channel_id, recap_time, timezone_str))
            
            return configs
    except Exception as e:
        log.error(f"Failed to get guild configs: {e}")
        raise DatabaseError(f"Failed to retrieve guild configs: {e}") from e


def set_custom_context(guild_id: int, context: str) -> None:
    """Set custom prompt context for a guild."""
    try:
        with _db_manager.get_connection() as conn:
            if _db_manager._use_postgres:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO guild_config (guild_id, custom_context) VALUES (%s, %s) "
                        "ON CONFLICT (guild_id) DO UPDATE SET custom_context=%s, updated_at=CURRENT_TIMESTAMP",
                        (str(guild_id), context, context),
                    )
                    conn.commit()
            else:
                conn.execute(
                    "INSERT INTO guild_config (guild_id, custom_context) VALUES (?, ?) "
                    "ON CONFLICT(guild_id) DO UPDATE SET custom_context=excluded.custom_context, updated_at=CURRENT_TIMESTAMP",
                    (str(guild_id), context),
                )
                conn.commit()
            log.info(f"Set custom context for guild {guild_id}")
    except Exception as e:
        log.error(f"Failed to set custom context: {e}")
        raise DatabaseError(f"Failed to set custom context: {e}") from e


def get_custom_context(guild_id: int) -> str:
    """Get custom prompt context for a guild."""
    try:
        with _db_manager.get_connection() as conn:
            if _db_manager._use_postgres:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT custom_context FROM guild_config WHERE guild_id=%s",
                        (str(guild_id),),
                    )
                    row = cur.fetchone()
                    return row["custom_context"] if row and row["custom_context"] else ""
            else:
                cur = conn.execute(
                    "SELECT custom_context FROM guild_config WHERE guild_id=?",
                    (str(guild_id),),
                )
                row = cur.fetchone()
                return row["custom_context"] if row and row["custom_context"] else ""
    except Exception as e:
        log.error(f"Failed to get custom context: {e}")
        raise DatabaseError(f"Failed to retrieve custom context: {e}") from e


def clear_custom_context(guild_id: int) -> None:
    """Clear custom prompt context for a guild."""
    try:
        with _db_manager.get_connection() as conn:
            if _db_manager._use_postgres:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE guild_config SET custom_context=NULL, updated_at=CURRENT_TIMESTAMP WHERE guild_id=%s",
                        (str(guild_id),),
                    )
                    conn.commit()
            else:
                conn.execute(
                    "UPDATE guild_config SET custom_context=NULL, updated_at=CURRENT_TIMESTAMP WHERE guild_id=?",
                    (str(guild_id),),
                )
                conn.commit()
            log.info(f"Cleared custom context for guild {guild_id}")
    except Exception as e:
        log.error(f"Failed to clear custom context: {e}")
        raise DatabaseError(f"Failed to clear custom context: {e}") from e
