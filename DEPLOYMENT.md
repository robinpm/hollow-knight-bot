# Render.com Deployment Guide

## Quick Setup

1. **Fork/Clone** this repository to your GitHub account

2. **Create a new Web Service** on Render.com:
   - Connect your GitHub repository
   - Choose "Web Service"
   - Use these settings:
     - **Build Command**: `pip install -r requirements-prod.txt`
     - **Start Command**: `python main.py`
     - **Python Version**: 3.11

3. **Set Environment Variables** in Render dashboard:
   - `DISCORD_TOKEN`: Your Discord bot token
   - `GOOGLE_API_KEY`: Your Google Gemini API key
   - `DATABASE_PATH`: `/tmp/bot.sqlite3` (or leave default)
   - `LOG_LEVEL`: `INFO` (or leave default)

4. **Deploy!** The bot will start automatically

## Environment Variables Required

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_TOKEN` | ✅ Yes | Discord bot token from Discord Developer Portal |
| `GOOGLE_API_KEY` | ✅ Yes | Google Gemini API key |
| `DATABASE_PATH` | ❌ No | Default: `/tmp/bot.sqlite3` |
| `LOG_LEVEL` | ❌ No | Default: `INFO` |

## Important Notes

- **Database**: SQLite database is stored in `/tmp/` which is ephemeral on Render
- **Restarts**: Bot will restart automatically on code changes
- **Logs**: Check Render dashboard for logs
- **Uptime**: Free tier has limitations, consider paid plan for 24/7 uptime

## Troubleshooting

- **Build fails**: Check that all dependencies are in `requirements-prod.txt`
- **Bot doesn't start**: Check environment variables are set correctly
- **Database issues**: Data resets on each deployment (expected behavior)
- **API errors**: Verify your API keys are valid and have proper permissions
