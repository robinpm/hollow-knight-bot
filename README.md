# Hollow Knight Discord Bot

A Discord bot that tracks Hollow Knight progress, analyzes save files, and provides AI-powered insights about your Hallownest journey.

## Features

- **Progress Tracking**: Track your Hollow Knight progress with detailed summaries
- **Achievement-Based Leaderboard**: Compete with other gamers based on actual Hollow Knight game achievements (bosses, areas, upgrades, collectibles)
- **Save File Analysis**: Upload `.dat` save files for automatic progress analysis
- **AI-Powered Insights**: Get personalized analysis and recommendations using Gemini AI
- **Daily Summaries**: Receive daily progress recaps
- **Memory System**: Bot remembers your progress and provides contextual responses
- **Customizable Personality**: Adjust bot's edginess level and random chatter frequency

## Project Structure

```
hollow-knight-bot/
├── main.py                 # Main entry point
├── requirements.txt        # Python dependencies
├── render.yaml            # Deployment configuration
├── src/                   # Source code
│   ├── core/              # Core bot functionality
│   │   ├── main.py        # Main bot logic
│   │   ├── config.py      # Configuration management
│   │   ├── database.py    # Database operations
│   │   ├── logger.py      # Logging configuration
│   │   └── validation.py  # Input validation
│   ├── ai/                # AI and agent functionality
│   │   ├── gemini_integration.py  # Gemini AI integration
│   │   └── agents/        # AI agents
│   │       └── response_decider.py  # Response decision logic
│   └── save_parsing/      # Save file parsing and decryption
│       ├── save_parser.py         # Save file parser
│       └── hollow_knight_decrypt.py  # Save file decryption
├── tests/                 # Test suite
│   ├── test_bot.py        # Bot integration tests
│   └── test_save_parser.py # Save parsing tests
├── docs/                  # Documentation
│   ├── README.md          # This file
│   └── DEPLOYMENT.md      # Deployment guide
└── hollow/                # External hollow repository (for reference)
```

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd hollow-knight-bot
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables:
```bash
export DISCORD_TOKEN="your-discord-bot-token"
export GEMINI_API_KEY="your-gemini-api-key"
```

## Usage

### Running the Bot

```bash
python main.py
```

### Testing

Run the test suite:
```bash
python -m pytest tests/ -v
```

Run individual test files:
```bash
python tests/test_bot.py
python -m pytest tests/test_save_parser.py -v
```

## Bot Commands

### Core Commands
- `/hollow-bot progress <text>` - Record your latest Hallownest achievement
- `/hollow-bot get_progress [user]` - Check someone's latest progress
- `/hollow-bot leaderboard` - See who's ahead based on actual game achievements
- `/hollow-bot info` - Bot information and version

### Configuration Commands
- `/hollow-bot rando-talk [0-100]` - View or set my random chatter chance
- `/hollow-bot edginess [1-10]` - View or set my edginess level
- `/hollow-bot custom-context <action> [text]` - Manage custom prompt context (set/show/clear)
- `/hollow-bot memory <action> [text/id]` - Manage server memories (add/list/delete)
- `/hollow-bot set_reminder_channel` - Set daily recap channel
- `/hollow-bot schedule_daily_reminder <time>` - Schedule daily recaps

### Chat
- `@HollowBot <message>` - Chat with the bot (it remembers your conversations!)

## Save File Support

The bot can analyze Hollow Knight save files (`.dat` files) by:
1. Decrypting the save file using the bloodorca/hollow method
2. Extracting progress data (playtime, completion, geo, health, etc.)
3. Generating AI-powered analysis and recommendations

## Development

The project is organized into logical modules:
- **Core**: Main bot functionality, configuration, database, logging
- **AI**: Gemini integration and AI agents
- **Save Parsing**: Save file decryption and parsing
- **Tests**: Comprehensive test suite

## Deployment

See `docs/DEPLOYMENT.md` for deployment instructions.

## Version

Current version: 1.9

## License

[Add your license here]
