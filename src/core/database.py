"""Database layer for Hollow Knight bot with SQLite and PostgreSQL support."""

import hashlib
import json
import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Union

from .config import config

log = logging.getLogger(__name__)


class DatabaseError(Exception):
    """Database operation error."""
    pass


class DatabaseManager:
    """Manages database connections and operations."""
    
    def __init__(self):
        self._use_postgres = bool(config.database_url and config.database_url.startswith('postgresql://'))
        self._use_mysql = bool(config.database_url and config.database_url.startswith('mysql://'))
        
        if self._use_postgres:
            log.info("Using PostgreSQL database")
            self._init_postgres()
        elif self._use_mysql:
            log.info("Using MySQL database")
            self._init_mysql()
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
    
    def _init_mysql(self):
        """Initialize MySQL database."""
        try:
            import pymysql
            from pymysql.cursors import DictCursor
            self._pymysql = pymysql
            self._DictCursor = DictCursor
            self._ensure_mysql_tables()
        except ImportError:
            raise DatabaseError("PyMySQL is required for MySQL support")
    
    def _ensure_sqlite_tables(self):
        """Create SQLite tables if they don't exist."""
        with self.get_connection() as conn:
            # Create players table with unique hash-based IDs
            conn.execute("""
                CREATE TABLE IF NOT EXISTS players (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    player_hash TEXT UNIQUE NOT NULL,
                    guild_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    display_name TEXT,
                    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create progress table to store detailed save file stats
            conn.execute("""
                CREATE TABLE IF NOT EXISTS progress (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    player_hash TEXT NOT NULL,
                    guild_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    update_text TEXT,
                    playtime_hours REAL,
                    completion_percent REAL,
                    geo INTEGER,
                    health INTEGER,
                    max_health INTEGER,
                    deaths INTEGER,
                    scene TEXT,
                    zone TEXT,
                    nail_upgrades INTEGER,
                    soul_vessels INTEGER,
                    mask_shards INTEGER,
                    charms_owned INTEGER,
                    bosses_defeated INTEGER,
                    bosses_defeated_list TEXT,
                    charms_list TEXT,
                    ts INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (player_hash) REFERENCES players(player_hash)
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS guild_config (
                    guild_id TEXT PRIMARY KEY,
                    recap_channel_id TEXT,
                    recap_time TEXT,
                    timezone TEXT DEFAULT 'UTC',
                    custom_context TEXT,
                    edginess INTEGER DEFAULT 5,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Ensure custom_context column exists for older databases
            try:
                conn.execute("ALTER TABLE guild_config ADD COLUMN custom_context TEXT")
            except sqlite3.OperationalError:
                pass

            # Ensure edginess column exists for older databases
            try:
                conn.execute(
                    "ALTER TABLE guild_config ADD COLUMN edginess INTEGER DEFAULT 5"
                )
            except sqlite3.OperationalError:
                pass

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT NOT NULL,
                    memory_text TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_guild ON memories(guild_id)"
            )

            # Create achievements table for tracking game progress
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS achievements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    achievement_type TEXT NOT NULL,
                    achievement_name TEXT NOT NULL,
                    progress_text TEXT NOT NULL,
                    ts INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_achievements_guild_user ON achievements(guild_id, user_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_achievements_type ON achievements(achievement_type)"
            )

            # Migrate existing progress table to new structure
            try:
                # Check if old progress table exists and migrate it
                cur = conn.execute("PRAGMA table_info(progress)")
                columns = [row[1] for row in cur.fetchall()]
                
                if 'player_hash' not in columns:
                    log.info("Migrating existing progress table to new structure...")
                    
                    # Create new progress table with all columns
                    conn.execute("""
                        CREATE TABLE progress_new (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            player_hash TEXT NOT NULL,
                            guild_id TEXT NOT NULL,
                            user_id TEXT NOT NULL,
                            update_text TEXT,
                            playtime_hours REAL,
                            completion_percent REAL,
                            geo INTEGER,
                            health INTEGER,
                            max_health INTEGER,
                            deaths INTEGER,
                            scene TEXT,
                            zone TEXT,
                            nail_upgrades INTEGER,
                            soul_vessels INTEGER,
                            mask_shards INTEGER,
                            charms_owned INTEGER,
                            bosses_defeated INTEGER,
                            bosses_defeated_list TEXT,
                            charms_list TEXT,
                            ts INTEGER NOT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                    
                    # Copy existing data to new table with generated player hashes
                    conn.execute("""
                        INSERT INTO progress_new (player_hash, guild_id, user_id, update_text, ts, created_at)
                        SELECT 
                            substr(hex(sha256(guild_id || ':' || user_id)), 1, 16) as player_hash,
                            guild_id, user_id, update_text, ts, created_at 
                        FROM progress
                    """)
                    
                    # Drop old table and rename new one
                    conn.execute("DROP TABLE progress")
                    conn.execute("ALTER TABLE progress_new RENAME TO progress")
                    
                    # Create players table entries for existing users
                    conn.execute("""
                        INSERT OR IGNORE INTO players (player_hash, guild_id, user_id, display_name, first_seen, last_activity)
                        SELECT DISTINCT 
                            substr(hex(sha256(guild_id || ':' || user_id)), 1, 16) as player_hash,
                            guild_id, user_id, 'Unknown User', MIN(created_at), MAX(created_at)
                        FROM progress 
                        GROUP BY guild_id, user_id
                    """)
                    
                    log.info("Successfully migrated progress table and created player records")
                    
            except sqlite3.OperationalError as e:
                log.warning(f"Migration not needed or failed: {e}")

            # Create indexes
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_players_hash ON players(player_hash)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_players_guild_user ON players(guild_id, user_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_progress_player_hash ON progress(player_hash)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_progress_guild_user ON progress(guild_id, user_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_progress_ts ON progress(ts)"
            )
            conn.commit()
            log.info("SQLite database initialized successfully")
    
    def _ensure_postgres_tables(self):
        """Create PostgreSQL tables if they don't exist."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Create players table with unique hash-based IDs
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS players (
                        id SERIAL PRIMARY KEY,
                        player_hash VARCHAR(255) UNIQUE NOT NULL,
                        guild_id VARCHAR(255) NOT NULL,
                        user_id VARCHAR(255) NOT NULL,
                        display_name VARCHAR(255),
                        first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Create progress table to store detailed save file stats
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS progress (
                        id SERIAL PRIMARY KEY,
                        player_hash VARCHAR(255) NOT NULL,
                        guild_id VARCHAR(255) NOT NULL,
                        user_id VARCHAR(255) NOT NULL,
                        update_text TEXT,
                        playtime_hours REAL,
                        completion_percent REAL,
                        geo INTEGER,
                        health INTEGER,
                        max_health INTEGER,
                        deaths INTEGER,
                        scene VARCHAR(255),
                        zone VARCHAR(255),
                        nail_upgrades INTEGER,
                        soul_vessels INTEGER,
                        mask_shards INTEGER,
                        charms_owned INTEGER,
                        bosses_defeated INTEGER,
                        bosses_defeated_list TEXT,
                        charms_list TEXT,
                        ts BIGINT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (player_hash) REFERENCES players(player_hash)
                    )
                """)
                
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS guild_config (
                        guild_id VARCHAR(255) PRIMARY KEY,
                        recap_channel_id VARCHAR(255),
                        recap_time VARCHAR(10),
                        timezone VARCHAR(50) DEFAULT 'UTC',
                        custom_context TEXT,
                        edginess INTEGER DEFAULT 5,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Ensure custom_context column exists for older databases
                cur.execute(
                    "ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS custom_context TEXT"
                )

                # Ensure edginess column exists for older databases
                cur.execute(
                    "ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS edginess INTEGER DEFAULT 5"
                )

                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS memories (
                        id SERIAL PRIMARY KEY,
                        guild_id VARCHAR(255) NOT NULL,
                        memory_text TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )

                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_memories_guild ON memories(guild_id)"
                )

                # Create achievements table for tracking game progress
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS achievements (
                        id SERIAL PRIMARY KEY,
                        guild_id VARCHAR(255) NOT NULL,
                        user_id VARCHAR(255) NOT NULL,
                        achievement_type VARCHAR(100) NOT NULL,
                        achievement_name VARCHAR(255) NOT NULL,
                        progress_text TEXT NOT NULL,
                        ts BIGINT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )

                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_achievements_guild_user ON achievements(guild_id, user_id)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_achievements_type ON achievements(achievement_type)"
                )

                # Create indexes
                cur.execute("CREATE INDEX IF NOT EXISTS idx_players_hash ON players(player_hash)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_players_guild_user ON players(guild_id, user_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_progress_player_hash ON progress(player_hash)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_progress_guild_user ON progress(guild_id, user_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_progress_ts ON progress(ts)")
                conn.commit()
                log.info("PostgreSQL database initialized successfully")
    
    def _ensure_mysql_tables(self):
        """Create MySQL tables if they don't exist."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Create players table with unique hash-based IDs
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS players (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        player_hash VARCHAR(255) UNIQUE NOT NULL,
                        guild_id VARCHAR(255) NOT NULL,
                        user_id VARCHAR(255) NOT NULL,
                        display_name VARCHAR(255),
                        first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Create progress table to store detailed save file stats
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS progress (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        player_hash VARCHAR(255) NOT NULL,
                        guild_id VARCHAR(255) NOT NULL,
                        user_id VARCHAR(255) NOT NULL,
                        update_text TEXT,
                        playtime_hours FLOAT,
                        completion_percent FLOAT,
                        geo INT,
                        health INT,
                        max_health INT,
                        deaths INT,
                        scene VARCHAR(255),
                        zone VARCHAR(255),
                        nail_upgrades INT,
                        soul_vessels INT,
                        mask_shards INT,
                        charms_owned INT,
                        bosses_defeated INT,
                        bosses_defeated_list TEXT,
                        charms_list TEXT,
                        ts BIGINT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (player_hash) REFERENCES players(player_hash)
                    )
                """)
                
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS guild_config (
                        guild_id VARCHAR(255) PRIMARY KEY,
                        recap_channel_id VARCHAR(255),
                        recap_time VARCHAR(10),
                        timezone VARCHAR(50) DEFAULT 'UTC',
                        custom_context TEXT,
                        edginess INT DEFAULT 5,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS memories (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        guild_id VARCHAR(255) NOT NULL,
                        memory_text TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Create indexes (MySQL doesn't support IF NOT EXISTS for indexes)
                try:
                    cur.execute("CREATE INDEX idx_memories_guild ON memories(guild_id)")
                except:
                    pass  # Index already exists

                # Create achievements table for tracking game progress
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS achievements (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        guild_id VARCHAR(255) NOT NULL,
                        user_id VARCHAR(255) NOT NULL,
                        achievement_type VARCHAR(100) NOT NULL,
                        achievement_name VARCHAR(255) NOT NULL,
                        progress_text TEXT NOT NULL,
                        ts BIGINT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Create indexes (MySQL doesn't support IF NOT EXISTS for indexes)
                try:
                    cur.execute("CREATE INDEX idx_achievements_guild_user ON achievements(guild_id, user_id)")
                except:
                    pass  # Index already exists
                try:
                    cur.execute("CREATE INDEX idx_achievements_type ON achievements(achievement_type)")
                except:
                    pass  # Index already exists

                # Create indexes
                try:
                    cur.execute("CREATE INDEX idx_players_hash ON players(player_hash)")
                except:
                    pass  # Index already exists
                try:
                    cur.execute("CREATE INDEX idx_players_guild_user ON players(guild_id, user_id)")
                except:
                    pass  # Index already exists
                try:
                    cur.execute("CREATE INDEX idx_progress_player_hash ON progress(player_hash)")
                except:
                    pass  # Index already exists
                try:
                    cur.execute("CREATE INDEX idx_progress_guild_user ON progress(guild_id, user_id)")
                except:
                    pass  # Index already exists
                try:
                    cur.execute("CREATE INDEX idx_progress_ts ON progress(ts)")
                except:
                    pass  # Index already exists
                conn.commit()
                log.info("MySQL database initialized successfully")
    
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
        elif self._use_mysql:
            conn = None
            try:
                # Parse MySQL URL: mysql://user:pass@host:port/database
                import urllib.parse
                parsed = urllib.parse.urlparse(config.database_url)
                
                conn = self._pymysql.connect(
                    host=parsed.hostname,
                    port=parsed.port or 3306,
                    user=parsed.username,
                    password=parsed.password,
                    database=parsed.path[1:],  # Remove leading slash
                    cursorclass=self._DictCursor,
                    charset='utf8mb4',
                    ssl_disabled=False,
                    ssl_verify_cert=False,
                    ssl_verify_identity=False
                )
                yield conn
            except Exception as e:
                if conn:
                    conn.rollback()
                log.error(f"MySQL connection error: {e}")
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


def generate_player_hash(guild_id: int, user_id: int) -> str:
    """Generate a unique hash for a player based on guild and user ID."""
    combined = f"{guild_id}:{user_id}"
    return hashlib.sha256(combined.encode()).hexdigest()[:16]  # 16 char hash


def get_or_create_player(guild_id: int, user_id: int, display_name: str = None) -> str:
    """Get or create a player record and return the player hash."""
    player_hash = generate_player_hash(guild_id, user_id)
    
    try:
        with _db_manager.get_connection() as conn:
            if _db_manager._use_postgres or _db_manager._use_mysql:
                with conn.cursor() as cur:
                    # Try to get existing player
                    cur.execute(
                        "SELECT player_hash FROM players WHERE player_hash = %s",
                        (player_hash,)
                    )
                    if cur.fetchone():
                        # Update last activity
                        cur.execute(
                            "UPDATE players SET last_activity = CURRENT_TIMESTAMP WHERE player_hash = %s",
                            (player_hash,)
                        )
                        conn.commit()
                        return player_hash
                    
                    # Create new player
                    cur.execute(
                        "INSERT INTO players (player_hash, guild_id, user_id, display_name) VALUES (%s, %s, %s, %s)",
                        (player_hash, str(guild_id), str(user_id), display_name)
                    )
                    conn.commit()
            else:
                # Try to get existing player
                cur = conn.execute(
                    "SELECT player_hash FROM players WHERE player_hash = ?",
                    (player_hash,)
                )
                if cur.fetchone():
                    # Update last activity
                    conn.execute(
                        "UPDATE players SET last_activity = CURRENT_TIMESTAMP WHERE player_hash = ?",
                        (player_hash,)
                    )
                    conn.commit()
                    return player_hash
                
                # Create new player
                conn.execute(
                    "INSERT INTO players (player_hash, guild_id, user_id, display_name) VALUES (?, ?, ?, ?)",
                    (player_hash, str(guild_id), str(user_id), display_name)
                )
                conn.commit()
            
            log.info(f"Created new player: {player_hash} for guild {guild_id}, user {user_id}")
            return player_hash
            
    except Exception as e:
        log.error(f"Failed to get or create player: {e}")
        raise DatabaseError(f"Failed to get or create player: {e}") from e


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


def add_save_progress(guild_id: int, user_id: int, display_name: str, save_stats: Dict, ts: int) -> str:
    """Store detailed save file progress with all stats."""
    try:
        # Get or create player
        player_hash = get_or_create_player(guild_id, user_id, display_name)
        
        # Prepare save stats data
        bosses_list = json.dumps(save_stats.get('bosses_defeated_list', []))
        charms_list = json.dumps(save_stats.get('charms_list', []))
        
        with _db_manager.get_connection() as conn:
            if _db_manager._use_postgres or _db_manager._use_mysql:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO progress (
                            player_hash, guild_id, user_id, update_text,
                            playtime_hours, completion_percent, geo, health, max_health,
                            deaths, scene, zone, nail_upgrades, soul_vessels, mask_shards,
                            charms_owned, bosses_defeated, bosses_defeated_list, charms_list, ts
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        player_hash, str(guild_id), str(user_id), 
                        f"Save file: {save_stats.get('completion_percent', 0)}% complete",
                        save_stats.get('playtime_hours', 0),
                        save_stats.get('completion_percent', 0),
                        save_stats.get('geo', 0),
                        save_stats.get('health', 0),
                        save_stats.get('max_health', 0),
                        save_stats.get('deaths', 0),
                        save_stats.get('scene', 'Unknown'),
                        save_stats.get('zone', 'Unknown'),
                        save_stats.get('nail_upgrades', 0),
                        save_stats.get('soul_vessels', 0),
                        save_stats.get('mask_shards', 0),
                        save_stats.get('charms_owned', 0),
                        save_stats.get('bosses_defeated', 0),
                        bosses_list,
                        charms_list,
                        ts
                    ))
                    conn.commit()
            else:
                conn.execute("""
                    INSERT INTO progress (
                        player_hash, guild_id, user_id, update_text,
                        playtime_hours, completion_percent, geo, health, max_health,
                        deaths, scene, zone, nail_upgrades, soul_vessels, mask_shards,
                        charms_owned, bosses_defeated, bosses_defeated_list, charms_list, ts
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    player_hash, str(guild_id), str(user_id),
                    f"Save file: {save_stats.get('completion_percent', 0)}% complete",
                    save_stats.get('playtime_hours', 0),
                    save_stats.get('completion_percent', 0),
                    save_stats.get('geo', 0),
                    save_stats.get('health', 0),
                    save_stats.get('max_health', 0),
                    save_stats.get('deaths', 0),
                    save_stats.get('scene', 'Unknown'),
                    save_stats.get('zone', 'Unknown'),
                    save_stats.get('nail_upgrades', 0),
                    save_stats.get('soul_vessels', 0),
                    save_stats.get('mask_shards', 0),
                    save_stats.get('charms_owned', 0),
                    save_stats.get('bosses_defeated', 0),
                    bosses_list,
                    charms_list,
                    ts
                ))
                conn.commit()
        
        log.info(f"Added save progress for player {player_hash}: {save_stats.get('completion_percent', 0)}% complete")
        return player_hash
        
    except Exception as e:
        log.error(f"Failed to add save progress: {e}")
        raise DatabaseError(f"Failed to add save progress: {e}") from e


def get_last_update(guild_id: int, user_id: int) -> Optional[Tuple[str, int]]:
    """Return the most recent update for a user in a guild."""
    try:
        with _db_manager.get_connection() as conn:
            if _db_manager._use_postgres or _db_manager._use_mysql:
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


def get_player_progress_history(guild_id: int, user_id: int, limit: int = 10) -> List[Dict]:
    """Get detailed progress history for a player."""
    try:
        player_hash = generate_player_hash(guild_id, user_id)
        
        with _db_manager.get_connection() as conn:
            if _db_manager._use_postgres or _db_manager._use_mysql:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT 
                            playtime_hours, completion_percent, geo, health, max_health,
                            deaths, scene, zone, nail_upgrades, soul_vessels, mask_shards,
                            charms_owned, bosses_defeated, bosses_defeated_list, charms_list,
                            ts, created_at
                        FROM progress 
                        WHERE player_hash = %s 
                        ORDER BY ts DESC 
                        LIMIT %s
                    """, (player_hash, limit))
                    rows = cur.fetchall()
            else:
                cur = conn.execute("""
                    SELECT 
                        playtime_hours, completion_percent, geo, health, max_health,
                        deaths, scene, zone, nail_upgrades, soul_vessels, mask_shards,
                        charms_owned, bosses_defeated, bosses_defeated_list, charms_list,
                        ts, created_at
                    FROM progress 
                    WHERE player_hash = ? 
                    ORDER BY ts DESC 
                    LIMIT ?
                """, (player_hash, limit))
                rows = cur.fetchall()
            
            progress_history = []
            for row in rows:
                progress_entry = {
                    'playtime_hours': row['playtime_hours'],
                    'completion_percent': row['completion_percent'],
                    'geo': row['geo'],
                    'health': row['health'],
                    'max_health': row['max_health'],
                    'deaths': row['deaths'],
                    'scene': row['scene'],
                    'zone': row['zone'],
                    'nail_upgrades': row['nail_upgrades'],
                    'soul_vessels': row['soul_vessels'],
                    'mask_shards': row['mask_shards'],
                    'charms_owned': row['charms_owned'],
                    'bosses_defeated': row['bosses_defeated'],
                    'bosses_defeated_list': json.loads(row['bosses_defeated_list']) if row['bosses_defeated_list'] else [],
                    'charms_list': json.loads(row['charms_list']) if row['charms_list'] else [],
                    'ts': row['ts'],
                    'created_at': row['created_at']
                }
                progress_history.append(progress_entry)
            
            return progress_history
            
    except Exception as e:
        log.error(f"Failed to get player progress history: {e}")
        raise DatabaseError(f"Failed to get player progress history: {e}") from e


def get_updates_today_by_guild(guild_id: int) -> Dict[str, List[str]]:
    """Return today's updates grouped by user id."""
    try:
        start_of_day = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        start_ts = int(start_of_day.timestamp())
        
        with _db_manager.get_connection() as conn:
            if _db_manager._use_postgres or _db_manager._use_mysql:
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


def add_memory(guild_id: int, text: str) -> int:
    """Store a memory snippet for a guild and return its ID."""
    if not text or not text.strip():
        raise ValueError("Memory text cannot be empty")

    try:
        with _db_manager.get_connection() as conn:
            if _db_manager._use_postgres:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO memories (guild_id, memory_text) VALUES (%s, %s) RETURNING id",
                        (str(guild_id), text.strip()),
                    )
                    mem_id = cur.fetchone()["id"]
                    conn.commit()
                    return int(mem_id)
            else:
                cur = conn.execute(
                    "INSERT INTO memories (guild_id, memory_text) VALUES (?, ?)",
                    (str(guild_id), text.strip()),
                )
                conn.commit()
                return int(cur.lastrowid)
    except Exception as e:
        log.error(f"Failed to add memory: {e}")
        raise DatabaseError(f"Failed to add memory: {e}") from e


def get_memories_by_guild(guild_id: int) -> List[Tuple[int, str]]:
    """Return all memories for a guild."""
    try:
        with _db_manager.get_connection() as conn:
            if _db_manager._use_postgres:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, memory_text FROM memories WHERE guild_id=%s ORDER BY id", 
                        (str(guild_id),),
                    )
                    rows = cur.fetchall()
            else:
                cur = conn.execute(
                    "SELECT id, memory_text FROM memories WHERE guild_id=? ORDER BY id",
                    (str(guild_id),),
                )
                rows = cur.fetchall()

            return [(int(r["id"]), r["memory_text"]) for r in rows]
    except Exception as e:
        log.error(f"Failed to get memories: {e}")
        raise DatabaseError(f"Failed to retrieve memories: {e}") from e


def delete_memory(guild_id: int, memory_id: int) -> None:
    """Delete a memory by ID for a guild."""
    try:
        with _db_manager.get_connection() as conn:
            if _db_manager._use_postgres:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM memories WHERE guild_id=%s AND id=%s",
                        (str(guild_id), memory_id),
                    )
                    conn.commit()
            else:
                conn.execute(
                    "DELETE FROM memories WHERE guild_id=? AND id=?",
                    (str(guild_id), memory_id),
                )
                conn.commit()
    except Exception as e:
        log.error(f"Failed to delete memory: {e}")
        raise DatabaseError(f"Failed to delete memory: {e}") from e


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
            if _db_manager._use_postgres or _db_manager._use_mysql:
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


def set_edginess(guild_id: int, level: int) -> None:
    """Set edginess level for a guild."""
    try:
        with _db_manager.get_connection() as conn:
            if _db_manager._use_postgres:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO guild_config (guild_id, edginess) VALUES (%s, %s) "
                        "ON CONFLICT (guild_id) DO UPDATE SET edginess=%s, updated_at=CURRENT_TIMESTAMP",
                        (str(guild_id), level, level),
                    )
                    conn.commit()
            else:
                conn.execute(
                    "INSERT INTO guild_config (guild_id, edginess) VALUES (?, ?) "
                    "ON CONFLICT(guild_id) DO UPDATE SET edginess=excluded.edginess, updated_at=CURRENT_TIMESTAMP",
                    (str(guild_id), level),
                )
                conn.commit()
            log.info(f"Set edginess for guild {guild_id} to {level}")
    except Exception as e:
        log.error(f"Failed to set edginess: {e}")
        raise DatabaseError(f"Failed to set edginess: {e}") from e


def get_edginess(guild_id: int) -> int:
    """Get edginess level for a guild. Defaults to 5."""
    try:
        with _db_manager.get_connection() as conn:
            if _db_manager._use_postgres:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT edginess FROM guild_config WHERE guild_id=%s",
                        (str(guild_id),),
                    )
                    row = cur.fetchone()
                    return int(row["edginess"]) if row and row["edginess"] is not None else 5
            else:
                cur = conn.execute(
                    "SELECT edginess FROM guild_config WHERE guild_id=?",
                    (str(guild_id),),
                )
                row = cur.fetchone()
                return int(row["edginess"]) if row and row["edginess"] is not None else 5
    except Exception as e:
        log.error(f"Failed to get edginess: {e}")
        raise DatabaseError(f"Failed to retrieve edginess: {e}") from e


def add_achievement(guild_id: int, user_id: int, achievement_type: str, achievement_name: str, progress_text: str, ts: int) -> int:
    """Store a game achievement and return its ID."""
    if not achievement_type or not achievement_name or not progress_text:
        raise ValueError("Achievement type, name, and progress text cannot be empty")
    
    if ts <= 0:
        raise ValueError("Timestamp must be positive")
    
    try:
        with _db_manager.get_connection() as conn:
            if _db_manager._use_postgres:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO achievements (guild_id, user_id, achievement_type, achievement_name, progress_text, ts) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                        (str(guild_id), str(user_id), achievement_type, achievement_name, progress_text.strip(), ts),
                    )
                    achievement_id = cur.fetchone()["id"]
                    conn.commit()
                    return int(achievement_id)
            else:
                cur = conn.execute(
                    "INSERT INTO achievements (guild_id, user_id, achievement_type, achievement_name, progress_text, ts) VALUES (?, ?, ?, ?, ?, ?)",
                    (str(guild_id), str(user_id), achievement_type, achievement_name, progress_text.strip(), ts),
                )
                conn.commit()
                return int(cur.lastrowid)
            log.info(f"Added achievement for guild {guild_id}, user {user_id}: {achievement_name}")
    except Exception as e:
        log.error(f"Failed to add achievement: {e}")
        raise DatabaseError(f"Failed to add achievement: {e}") from e


def get_user_achievements(guild_id: int) -> List[Tuple[str, str, int, int, int, int]]:
    """Get user achievement statistics for leaderboard. Returns (user_id, achievement_type, count, total_score, unique_achievements, first_achievement_ts)."""
    try:
        with _db_manager.get_connection() as conn:
            if _db_manager._use_postgres:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT 
                            user_id,
                            achievement_type,
                            COUNT(*) as count,
                            MIN(ts) as first_achievement_ts
                        FROM achievements 
                        WHERE guild_id = %s 
                        GROUP BY user_id, achievement_type
                        ORDER BY user_id, achievement_type
                    """, (str(guild_id),))
                    rows = cur.fetchall()
            else:
                cur = conn.execute("""
                    SELECT 
                        user_id,
                        achievement_type,
                        COUNT(*) as count,
                        MIN(ts) as first_achievement_ts
                    FROM achievements 
                    WHERE guild_id = ? 
                    GROUP BY user_id, achievement_type
                    ORDER BY user_id, achievement_type
                """, (str(guild_id),))
                rows = cur.fetchall()
            
            # Process the data to calculate totals per user
            user_stats = {}
            for row in rows:
                user_id = row["user_id"]
                achievement_type = row["achievement_type"]
                count = row["count"]
                first_ts = row["first_achievement_ts"]
                
                if user_id not in user_stats:
                    user_stats[user_id] = {
                        "total_achievements": 0,
                        "unique_types": set(),
                        "first_achievement_ts": first_ts,
                        "type_counts": {}
                    }
                
                user_stats[user_id]["total_achievements"] += count
                user_stats[user_id]["unique_types"].add(achievement_type)
                user_stats[user_id]["type_counts"][achievement_type] = count
                user_stats[user_id]["first_achievement_ts"] = min(user_stats[user_id]["first_achievement_ts"], first_ts)
            
            # Convert to list format and calculate scores
            result = []
            for user_id, stats in user_stats.items():
                # Calculate score based on achievement types and counts
                total_score = 0
                for achievement_type, count in stats["type_counts"].items():
                    # Different achievement types have different point values
                    if achievement_type == "boss":
                        total_score += count * 50  # Bosses are worth the most
                    elif achievement_type == "area":
                        total_score += count * 30  # Areas are worth medium
                    elif achievement_type == "upgrade":
                        total_score += count * 25  # Upgrades are worth medium
                    elif achievement_type == "collectible":
                        total_score += count * 10  # Collectibles are worth less
                    else:
                        total_score += count * 15  # Default value
                
                result.append((
                    user_id,
                    stats["total_achievements"],
                    total_score,
                    len(stats["unique_types"]),
                    stats["first_achievement_ts"]
                ))
            
            # Sort by total score descending
            result.sort(key=lambda x: x[2], reverse=True)
            return result
            
    except Exception as e:
        log.error(f"Failed to get user achievements: {e}")
        raise DatabaseError(f"Failed to retrieve user achievements: {e}") from e


def get_user_stats(guild_id: int) -> List[Tuple[str, int, int, int, int]]:
    """Get user statistics for leaderboard. Returns (user_id, total_updates, days_active, recent_updates, first_update_ts)."""
    try:
        recent_threshold = int(time.time()) - 7 * 24 * 3600  # 7 days ago
        
        with _db_manager.get_connection() as conn:
            if _db_manager._use_postgres or _db_manager._use_mysql:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT 
                            user_id,
                            COUNT(*) as total_updates,
                            COUNT(DISTINCT DATE(FROM_UNIXTIME(ts))) as days_active,
                            COUNT(CASE WHEN ts >= %s THEN 1 END) as recent_updates,
                            MIN(ts) as first_update_ts
                        FROM progress 
                        WHERE guild_id = %s 
                        GROUP BY user_id 
                        ORDER BY total_updates DESC, days_active DESC, recent_updates DESC
                    """, (recent_threshold, str(guild_id)))
                    rows = cur.fetchall()
            else:
                cur = conn.execute("""
                    SELECT 
                        user_id,
                        COUNT(*) as total_updates,
                        COUNT(DISTINCT DATE(datetime(ts, 'unixepoch'))) as days_active,
                        COUNT(CASE WHEN ts >= ? THEN 1 END) as recent_updates,
                        MIN(ts) as first_update_ts
                    FROM progress 
                    WHERE guild_id = ? 
                    GROUP BY user_id 
                    ORDER BY total_updates DESC, days_active DESC, recent_updates DESC
                """, (recent_threshold, str(guild_id)))
                rows = cur.fetchall()
            
            return [(row["user_id"], row["total_updates"], row["days_active"], row["recent_updates"], row["first_update_ts"]) for row in rows]
    except Exception as e:
        log.error(f"Failed to get user stats: {e}")
        raise DatabaseError(f"Failed to retrieve user stats: {e}") from e


def get_game_stats_leaderboard(guild_id: int) -> List[Tuple[str, float, float, int, int, int, int, int]]:
    """Get game stats leaderboard. Returns (user_id, completion_percent, playtime_hours, bosses_defeated, geo, deaths, nail_upgrades, charms_owned)."""
    try:
        with _db_manager.get_connection() as conn:
            if _db_manager._use_postgres or _db_manager._use_mysql:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT 
                            user_id,
                            MAX(completion_percent) as completion_percent,
                            MAX(playtime_hours) as playtime_hours,
                            MAX(bosses_defeated) as bosses_defeated,
                            MAX(geo) as geo,
                            MAX(deaths) as deaths,
                            MAX(nail_upgrades) as nail_upgrades,
                            MAX(charms_owned) as charms_owned
                        FROM progress 
                        WHERE guild_id = %s 
                        AND completion_percent IS NOT NULL
                        AND playtime_hours IS NOT NULL
                        GROUP BY user_id 
                        ORDER BY 
                            MAX(completion_percent) DESC,
                            MAX(bosses_defeated) DESC,
                            MAX(playtime_hours) DESC,
                            MAX(geo) DESC
                    """, (str(guild_id),))
                    rows = cur.fetchall()
            else:
                cur = conn.execute("""
                    SELECT 
                        user_id,
                        MAX(completion_percent) as completion_percent,
                        MAX(playtime_hours) as playtime_hours,
                        MAX(bosses_defeated) as bosses_defeated,
                        MAX(geo) as geo,
                        MAX(deaths) as deaths,
                        MAX(nail_upgrades) as nail_upgrades,
                        MAX(charms_owned) as charms_owned
                    FROM progress 
                    WHERE guild_id = ? 
                    AND completion_percent IS NOT NULL
                    AND playtime_hours IS NOT NULL
                    GROUP BY user_id 
                    ORDER BY 
                        MAX(completion_percent) DESC,
                        MAX(bosses_defeated) DESC,
                        MAX(playtime_hours) DESC,
                        MAX(geo) DESC
                """, (str(guild_id),))
                rows = cur.fetchall()
            
            return [
                (
                    row["user_id"], 
                    float(row["completion_percent"] or 0),
                    float(row["playtime_hours"] or 0),
                    int(row["bosses_defeated"] or 0),
                    int(row["geo"] or 0),
                    int(row["deaths"] or 0),
                    int(row["nail_upgrades"] or 0),
                    int(row["charms_owned"] or 0)
                ) 
                for row in rows
            ]
    except Exception as e:
        log.error(f"Failed to get game stats leaderboard: {e}")
        raise DatabaseError(f"Failed to retrieve game stats leaderboard: {e}") from e
