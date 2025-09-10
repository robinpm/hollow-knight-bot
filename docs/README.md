# Hollow Knight Bot

A Discord bot that tracks Hollow Knight progress and provides daily recaps with an authentic gamer personality. The bot maintains character consistency as a seasoned Hollow Knight player who's already 112% the game.

## Features

- **Progress Tracking**: Record and track Hollow Knight achievements
- **Leaderboard System**: Compete with other gamers using a magic algorithm that combines total updates, consistency, recent activity, and longevity
- **Daily Recaps**: AI-generated daily summaries with Hollow Knight lore and gaming memes
- **Character Consistency**: Maintains authentic gamer Hollow Knight personality
- **Spontaneous Chat**: Occasionally replies to regular channel messages
- **Customizable Personality**: Adjust bot's edginess level and random chatter frequency
- **Memory Management**: Server admins can add, list, and delete server memories
- **Custom Context**: Set custom prompt context for personalized bot behavior
- **Robust Error Handling**: Graceful failure handling with in-character responses
- **Input Validation**: Comprehensive validation and sanitization
- **Database Management**: SQLite-based progress storage with proper connection handling

## Architecture

### Core Components

- **`main.py`**: Main bot application with Discord event handlers
- **`config.py`**: Configuration management with environment variable support
- **`database.py`**: Database layer with connection management and error handling
- **`gemini_integration.py`**: AI integration with retry logic and fallback responses
- **`validation.py`**: Input validation and sanitization
- **`logger.py`**: Centralized logging configuration
- **`langchain/`**: LangChain integration for conversation management

### Key Improvements

1. **Robust Error Handling**: All operations wrapped in try-catch blocks with appropriate logging
2. **Input Validation**: Comprehensive validation for all user inputs
3. **Database Safety**: Connection management with context managers and proper error handling
4. **AI Resilience**: Retry logic with exponential backoff for AI API calls
5. **Character Consistency**: All error messages maintain the Hollow Knight gamer persona
6. **Configuration Management**: Centralized config with validation
7. **Logging**: Structured logging with file and console output

## Setup

### Prerequisites

- Python 3.8+
- Discord Bot Token
- Google Gemini API Key

### Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd hollow-knight-bot
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set environment variables:
```bash
export DISCORD_TOKEN="your_discord_bot_token"
export GEMINI_API_KEY="your_gemini_api_key"
export DATABASE_PATH="bot.sqlite3"  # Optional, defaults to bot.sqlite3
export GEMINI_MODEL="gemini-2.0-flash"  # Optional, defaults to gemini-2.0-flash
export LOG_LEVEL="INFO"  # Optional, defaults to INFO
export COMMAND_PREFIX="!"  # Optional, defaults to "!"
export SPONTANEOUS_RESPONSE_CHANCE="0.05"  # Optional, chance bot replies to any message (0-1)
```

4. Run the bot:
```bash
python main.py
```

## Configuration

The bot uses environment variables for configuration:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DISCORD_TOKEN` | Yes | - | Discord bot token |
| `GEMINI_API_KEY` | Yes | - | Google Gemini API key |
| `DATABASE_PATH` | No | `bot.sqlite3` | SQLite database file path |
| `GEMINI_MODEL` | No | `gemini-2.0-flash` | Gemini model to use |
| `LOG_LEVEL` | No | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL) |
| `COMMAND_PREFIX` | No | `!` | Prefix for text commands |
| `MAX_RETRIES` | No | `3` | Maximum retry attempts for API calls |
| `REQUEST_TIMEOUT` | No | `30` | Request timeout in seconds |
| `SPONTANEOUS_RESPONSE_CHANCE` | No | `0.05` | Chance the bot replies to any message |

## Commands

### Core Commands

- `/hollow-bot progress <text>`: Record your latest Hallownest achievement
- `/hollow-bot get_progress [user]`: Check the latest echo from a gamer's journey
- `/hollow-bot leaderboard`: See who's ahead in the Hallownest journey with detailed stats
- `/hollow-bot info`: Bot information and version

### Configuration Commands

- `/hollow-bot rando-talk [0-100]`: View or set chance the bot replies to random messages
- `/hollow-bot edginess [1-10]`: View or set how edgy the bot's replies are
- `/hollow-bot custom-context <action> [text]`: Manage custom prompt context (set/show/clear)
- `/hollow-bot memory <action> [text/id]`: Manage server memories (add/list/delete)
- `/hollow-bot set_reminder_channel`: Set the chronicle channel for daily echoes
- `/hollow-bot schedule_daily_reminder <time>`: Schedule when the chronicle echoes daily (UTC)

### Mention Commands

- `@HollowBot <message>`: Chat with the bot (it remembers your conversations!)
- `@HollowBot progress <achievement>`: Record progress (alternative to slash command)

### Leaderboard Algorithm

The leaderboard uses a magic algorithm that combines multiple metrics:

- **Base Score**: Total updates × 10 (most important factor)
- **Consistency Bonus**: Days active vs total days since first update × 5
- **Recent Activity Bonus**: Updates in last 7 days × 3
- **Longevity Bonus**: Days active × 0.5 (capped at 20 points)

This ensures that both active and consistent players are rewarded appropriately!

## Database Schema

### Tables

- **`progress`**: Stores user progress updates
  - `guild_id`: Discord guild ID
  - `user_id`: Discord user ID
  - `update_text`: Progress description
  - `ts`: Unix timestamp
  - `created_at`: Creation timestamp

- **`guild_config`**: Stores guild-specific settings
  - `guild_id`: Discord guild ID (primary key)
  - `recap_channel_id`: Channel for daily recaps
  - `recap_time_utc`: UTC time for daily recaps (HH:MM format)
  - `created_at`: Creation timestamp
  - `updated_at`: Last update timestamp

## Error Handling

The bot implements comprehensive error handling:

1. **Validation Errors**: Input validation with user-friendly error messages
2. **Database Errors**: Connection management with graceful degradation
3. **API Errors**: Retry logic with exponential backoff
4. **Discord Errors**: Proper error responses and logging
5. **Character Consistency**: All errors maintain the Hollow Knight gamer persona

## Logging

Logs are written to both console and `hollow_bot.log` file with structured formatting:

```
2024-01-15 10:30:45 - hollowbot - INFO - HollowBot logged in as HollowBot#1234
2024-01-15 10:30:46 - hollowbot - DEBUG - Built conversation chain with HollowBot persona
```

## Development

### Code Quality

The codebase follows these principles:

- **Type Hints**: Comprehensive type annotations
- **Error Handling**: Try-catch blocks for all operations
- **Validation**: Input validation and sanitization
- **Logging**: Structured logging throughout
- **Documentation**: Docstrings for all functions and classes

### Testing

Run tests with:
```bash
pytest
```

### Code Formatting

Format code with:
```bash
black .
flake8 .
mypy .
```

## Character Consistency

The bot maintains a consistent Hollow Knight gamer personality:

- **Knowledge**: References specific bosses, locations, and mechanics
- **Voice**: Supportive but playfully snarky about progress
- **Lore Integration**: Natural use of Hollow Knight terminology
- **Error Handling**: Even failures are blamed on in-universe causes
- **Authenticity**: Sounds like a friend who's already mastered the game

## License

This project is licensed under the MIT License.
