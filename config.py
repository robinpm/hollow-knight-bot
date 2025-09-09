"""Configuration management for Hollow Knight bot."""

import os
from dataclasses import dataclass
from typing import Optional

# Load .env file for local development
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # dotenv not installed, that's fine for production
    pass


@dataclass
class BotConfig:
    """Bot configuration settings."""
    
    # Required settings (no defaults)
    discord_token: str
    google_api_key: str
    
    # Optional settings (with defaults)
    command_prefix: Optional[str] = None
    database_path: str = "bot.sqlite3"
    gemini_model: str = "gemini-2.0-flash"
    log_level: str = "INFO"
    max_retries: int = 3
    request_timeout: int = 30
    
    @classmethod
    def from_env(cls) -> "BotConfig":
        """Create configuration from environment variables."""
        discord_token = os.getenv("DISCORD_TOKEN")
        if not discord_token:
            raise ValueError("DISCORD_TOKEN environment variable is required")
        
        google_api_key = os.getenv("GEMINI_API_KEY", "dummy-key-for-testing")
        if not google_api_key or google_api_key == "dummy-key-for-testing":
            print("WARNING: GEMINI_API_KEY not set, AI features will be limited")
        
        return cls(
            discord_token=discord_token,
            google_api_key=google_api_key,
            command_prefix=os.getenv("COMMAND_PREFIX"),
            database_path=os.getenv("DATABASE_PATH", "bot.sqlite3"),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            max_retries=int(os.getenv("MAX_RETRIES", "3")),
            request_timeout=int(os.getenv("REQUEST_TIMEOUT", "30")),
        )
    
    def validate(self) -> None:
        """Validate configuration values."""
        if not self.discord_token:
            raise ValueError("Discord token is required")
        
        # Only validate API key if it's not a dummy key
        if not self.google_api_key or self.google_api_key == "dummy-key-for-testing":
            print("WARNING: GEMINI_API_KEY not set, AI features will be limited")
        
        if self.max_retries < 1:
            raise ValueError("max_retries must be at least 1")
        
        if self.request_timeout < 1:
            raise ValueError("request_timeout must be at least 1")
        
        valid_log_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if self.log_level.upper() not in valid_log_levels:
            raise ValueError(f"log_level must be one of {valid_log_levels}")


# Global configuration instance
config = BotConfig.from_env()
config.validate()
