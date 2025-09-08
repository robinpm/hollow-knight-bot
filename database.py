from __future__ import annotations
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from sqlalchemy import (
    create_engine,
    String,
    DateTime,
    BigInteger,
    Integer,
    select,
    Index,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session


# Default database URL. Uses SQLite locally unless DATABASE_URL is set (e.g. to a Postgres connection string).
DEFAULT_DB_URL = os.getenv("DATABASE_URL", "sqlite:///data.sqlite")


class Base(DeclarativeBase):
    """Base class for SQLAlchemy ORM models."""
    pass


class UserProgress(Base):
    """Table tracking progress updates per guild and user."""

    __tablename__ = "user_progress"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    content: Mapped[str] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


# Composite index to efficiently retrieve latest entries per guild
Index(
    "idx_progress_guild_time",
    UserProgress.guild_id,
    UserProgress.created_at.desc(),
)


class GuildSettings(Base):
    """Persistent per-guild settings for reminders and scheduling."""

    __tablename__ = "guild_settings"
    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    reminder_channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    reminder_utc_time: Mapped[Optional[str]] = mapped_column(
        String(5), nullable=True
    )  # Format "HH:MM" in 24h UTC
    last_summary_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Database:
    """Data access layer encapsulating engine and sessions."""

    def __init__(self, url: str = DEFAULT_DB_URL) -> None:
        # SQLite requires check_same_thread=False for multi-threaded access.
        connect_args: dict[str, bool] = (
            {"check_same_thread": False} if url.startswith("sqlite") else {}
        )
        self.engine = create_engine(
            url, future=True, echo=False, connect_args=connect_args
        )
        Base.metadata.create_all(self.engine)

    def add_progress(self, guild_id: int, user_id: int, content: str) -> None:
        """Insert a progress update."""
        now = datetime.now(timezone.utc)
        with Session(self.engine) as session:
            session.add(
                UserProgress(
                    guild_id=guild_id,
                    user_id=user_id,
                    content=content,
                    created_at=now,
                )
            )
            session.commit()

    def get_last_progress(
        self, guild_id: int, user_id: int
    ) -> Optional[Tuple[str, datetime]]:
        """Return the most recent progress entry for a given user in a guild."""
        with Session(self.engine) as session:
            stmt = (
                select(UserProgress.content, UserProgress.created_at)
                .where(
                    (UserProgress.guild_id == guild_id)
                    & (UserProgress.user_id == user_id)
                )
                .order_by(UserProgress.created_at.desc())
                .limit(1)
            )
            row = session.execute(stmt).first()
            return (row[0], row[1]) if row else None

    def get_updates_since(
        self, guild_id: int, since: datetime
    ) -> Dict[int, List[str]]:
        """Return all updates since a given time keyed by user ID."""
        with Session(self.engine) as session:
            stmt = (
                select(UserProgress.user_id, UserProgress.content)
                .where(
                    (UserProgress.guild_id == guild_id)
                    & (UserProgress.created_at >= since)
                )
                .order_by(UserProgress.user_id, UserProgress.created_at.asc())
            )
            result: Dict[int, List[str]] = {}
            for user_id, content in session.execute(stmt).all():
                result.setdefault(user_id, []).append(content)
            return result

    def upsert_channel(self, guild_id: int, channel_id: int) -> None:
        """Set or update the reminder channel for a guild."""
        with Session(self.engine) as session:
            settings = session.get(GuildSettings, guild_id)
            if settings is None:
                settings = GuildSettings(
                    guild_id=guild_id, reminder_channel_id=channel_id
                )
                session.add(settings)
            else:
                settings.reminder_channel_id = channel_id
            session.commit()

    def set_schedule(self, guild_id: int, hhmm_utc: str) -> None:
        """Set the daily reminder time for a guild (UTC)."""
        with Session(self.engine) as session:
            settings = session.get(GuildSettings, guild_id)
            if settings is None:
                settings = GuildSettings(
                    guild_id=guild_id, reminder_utc_time=hhmm_utc
                )
                session.add(settings)
            else:
                settings.reminder_utc_time = hhmm_utc
            session.commit()

    def get_settings(self, guild_id: int) -> GuildSettings:
        """Return guild settings, creating defaults if necessary."""
        with Session(self.engine) as session:
            settings = session.get(GuildSettings, guild_id)
            if settings is None:
                settings = GuildSettings(guild_id=guild_id)
                session.add(settings)
                session.commit()
                session.refresh(settings)
            return settings

    def all_schedules(self) -> List[GuildSettings]:
        """Return all guild settings with a scheduled time set."""
        with Session(self.engine) as session:
            stmt = select(GuildSettings).where(
                GuildSettings.reminder_utc_time.is_not(None)
            )
            return [row[0] for row in session.execute(stmt).all()]

    def mark_summary_sent(self, guild_id: int) -> None:
        """Record that today's summary has been sent for the guild."""
        with Session(self.engine) as session:
            settings = session.get(GuildSettings, guild_id)
            if settings is None:
                settings = GuildSettings(guild_id=guild_id)
                session.add(settings)
            settings.last_summary_at = datetime.now(timezone.utc)
            session.commit()