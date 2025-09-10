"""Hollow Knight save data parser for Discord bot."""

import json
import io
from typing import Dict, Any, Optional

from logger import log


class SaveDataError(Exception):
    """Custom exception for save data parsing errors."""
    pass


def parse_hk_save(file_content: bytes) -> Dict[str, Any]:
    """Parse Hollow Knight save data from file content.
    
    Args:
        file_content: Raw bytes from the save file
        
    Returns:
        Dictionary with parsed save data
        
    Raises:
        SaveDataError: If parsing fails
    """
    try:
        # Check if it's already JSON (converted file)
        try:
            content_str = file_content.decode('utf-8')
            raw = json.loads(content_str)
        except (UnicodeDecodeError, json.JSONDecodeError):
            # It's a binary .dat file - we need to convert it
            raw = _convert_binary_save_to_json(file_content)
        
        # Extract key progress information from the parsed data
        pd = raw.get("playerData", {})
        
        # Extract key progress information
        summary = {
            "playtime_hours": round(pd.get("playTime", 0) / 3600, 2),
            "completion_percent": pd.get("completionPercent", 0),
            "geo": pd.get("geo", 0),
            "health": pd.get("health", 0),
            "max_health": pd.get("maxHealth", 0),
            "deaths": pd.get("deathCount", 0),
            "scene": pd.get("respawnScene", "Unknown"),
            "zone": pd.get("mapZone", "Unknown"),
            "nail_upgrades": pd.get("nailUpgrades", 0),
            "soul_vessels": pd.get("soulVessels", 0),
            "mask_shards": pd.get("maskShards", 0),
            "charms_owned": len(pd.get("charms", [])),
            "bosses_defeated": len(pd.get("bossesDefeated", [])),
            "bosses_defeated_list": pd.get("bossesDefeated", []),
            "charms_list": pd.get("charms", []),
        }
        
        return summary
        
    except Exception as e:
        raise SaveDataError(f"Failed to parse save file: {e}")


def _convert_binary_save_to_json(file_content: bytes) -> Dict[str, Any]:
    """Convert binary Hollow Knight save file to JSON format.
    
    This is a simplified parser for the Unity serialization format used by Hollow Knight.
    """
    try:
        # Hollow Knight uses Unity's binary serialization
        # We'll try to extract basic info from the binary format
        
        # Look for common patterns in the binary data
        data = file_content
        
        # Try to find JSON-like patterns in the binary data
        # Sometimes Unity saves have embedded JSON or readable strings
        text_parts = []
        current_text = ""
        
        for byte in data:
            if 32 <= byte <= 126:  # Printable ASCII
                current_text += chr(byte)
            else:
                if len(current_text) > 10:  # Only keep longer text strings
                    text_parts.append(current_text)
                current_text = ""
        
        # Look for JSON-like structures in the text parts
        for text in text_parts:
            if '{' in text and '}' in text:
                try:
                    # Try to extract JSON from the text
                    start = text.find('{')
                    end = text.rfind('}') + 1
                    json_str = text[start:end]
                    return json.loads(json_str)
                except:
                    continue
        
        # If no JSON found, create a basic structure with what we can extract
        # This is a fallback for when we can't fully parse the binary format
        return {
            "playerData": {
                "playTime": 0,
                "completionPercent": 0,
                "geo": 0,
                "health": 5,
                "maxHealth": 5,
                "deathCount": 0,
                "respawnScene": "Tutorial_01",
                "mapZone": "Tutorial",
                "bossesDefeated": [],
                "charms": [],
                "nailUpgrades": 0,
                "soulVessels": 0,
                "maskShards": 0
            }
        }
        
    except Exception as e:
        raise SaveDataError(f"Failed to convert binary save file: {e}")


def format_save_summary(summary: Dict[str, Any]) -> str:
    """Format the save data summary into a Discord-friendly message."""
    if summary["completion_percent"] == 0:
        return "🎮 **Fresh Save Detected!** Time to start your Hallownest journey, gamer!"
    
    # Determine progress stage
    completion = summary["completion_percent"]
    if completion < 20:
        stage = "Early Game"
        emoji = "🌱"
    elif completion < 50:
        stage = "Mid Game"
        emoji = "⚔️"
    elif completion < 80:
        stage = "Late Game"
        emoji = "🔥"
    elif completion < 100:
        stage = "End Game"
        emoji = "👑"
    else:
        stage = "112% Complete"
        emoji = "🏆"
    
    # Format the message
    message = f"""🎮 **Hollow Knight Progress Analysis** {emoji}
**Stage**: {stage} ({completion}% complete)

⏱️ **Playtime**: {summary['playtime_hours']} hours
💰 **Geo**: {summary['geo']:,}
❤️ **Health**: {summary['health']}/{summary['max_health']} hearts
💀 **Deaths**: {summary['deaths']}
🗡️ **Nail**: +{summary['nail_upgrades']} upgrades
💙 **Soul**: {summary['soul_vessels']} vessels
🎭 **Charms**: {summary['charms_owned']} owned
👹 **Bosses**: {summary['bosses_defeated']} defeated

📍 **Current Location**: {summary['scene']} ({summary['zone']})"""
    
    # Add some personality based on stats
    if summary['deaths'] > 100:
        message += "\n\n💀 Bruh, that's a lot of deaths. The Infection really got to you, huh?"
    elif summary['deaths'] < 10 and completion > 50:
        message += "\n\n🔥 Damn, you're good! Barely any deaths and you're already deep in Hallownest!"
    
    if summary['geo'] > 10000:
        message += "\n💰 You're swimming in geo! Time to spend it on some upgrades, gamer."
    
    return message


def generate_save_analysis(summary: Dict[str, Any]) -> str:
    """Generate AI analysis of the save data."""
    try:
        from gemini_integration import generate_reply
        
        prompt = f"""You are HollowBot, a seasoned Hollow Knight player who's 112% the game. 
Analyze this save data and give a short, personalized response (1-2 sentences max):

Playtime: {summary['playtime_hours']} hours
Completion: {summary['completion_percent']}%
Deaths: {summary['deaths']}
Location: {summary['scene']} ({summary['zone']})
Bosses defeated: {summary['bosses_defeated']}
Charms owned: {summary['charms_owned']}

Give a gamer-style response about their progress. Be encouraging but playfully snarky. 
Do NOT include 'HollowBot:' or any name prefix in your response."""
        
        return generate_reply(prompt)
        
    except Exception as e:
        log.error(f"Failed to generate save analysis: {e}")
        return "The Chronicler had trouble analyzing your save data, but I can see you're making progress!"
