"""Hollow Knight save data parser for Discord bot."""

import json
import io
from typing import Dict, Any, Optional

from core.logger import log
from ai.gemini_integration import generate_reply
from .hollow_knight_decrypt import decrypt_hollow_knight_save


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
            # It's a binary .dat file - try to decrypt it first
            try:
                decrypted_json = decrypt_hollow_knight_save(file_content)
                raw = json.loads(decrypted_json)
            except Exception as decrypt_error:
                log.warning(f"Failed to decrypt save file: {decrypt_error}")
                # Fall back to binary parsing
                raw = _convert_binary_save_to_json(file_content)
        
        # Extract key progress information from the parsed data
        pd = raw.get("playerData", {})
        
        # Extract key progress information
        summary = {
            "playtime_hours": round(pd.get("playTime", 0) / 3600, 2),
            "completion_percent": pd.get("completionPercentage", pd.get("completionPercent", 0)),
            "geo": pd.get("geo", 0),
            "health": pd.get("health", 0),
            "max_health": pd.get("maxHealth", 0),
            "deaths": pd.get("deathCount", 0),
            "scene": pd.get("respawnScene", "Unknown"),
            "zone": pd.get("mapZone", "Unknown"),
            "nail_upgrades": pd.get("nailUpgrades", 0),
            "soul_vessels": pd.get("vesselFragments", 0),
            "mask_shards": pd.get("heartPieces", 0),
            "charms_owned": pd.get("charmsOwned", 0),
            "charms_equipped": _get_equipped_charms_list(pd),
            "charm_slots": pd.get("charmSlots", 0),
            "charm_slots_filled": pd.get("charmSlotsFilled", 0),
            "bosses_defeated": _count_defeated_bosses(pd),
            "bosses_defeated_list": _get_defeated_bosses_list(pd),
            "charms_list": _get_owned_charms_list(pd),
        }
        
        return summary
        
    except Exception as e:
        raise SaveDataError(f"Failed to parse save file: {e}")


def _count_defeated_bosses(pd: Dict[str, Any]) -> int:
    """Count the number of defeated bosses from player data."""
    boss_flags = [
        "falseKnightDefeated", "mawlekDefeated", "giantBuzzerDefeated", "giantFlyDefeated",
        "blocker1Defeated", "blocker2Defeated", "hornet1Defeated", "collectorDefeated",
        "hornetOutskirtsDefeated", "mageLordDreamDefeated", "infectedKnightDreamDefeated",
        "whiteDefenderDefeated", "greyPrinceDefeated", "dungDefenderDefeated",
        "flukeMotherDefeated", "megaBeamMinerDefeated", "mimicSpiderDefeated",
        "hiveKnightDefeated", "traitorLordDefeated", "obblobbleDefeated",
        "zoteDefeated", "lobsterLancerDefeated", "whiteDefenderDefeated",
        "greyPrinceDefeated", "hollowKnightDefeated", "finalBossDefeated",
        "grimmDefeated", "nightmareGrimmDefeated", "paleLurkerDefeated",
        "nailBrosDefeated", "paintmasterDefeated", "nailsageDefeated",
        "hollowKnightPrimeDefeated", "godseekerMaskDefeated"
    ]
    
    count = 0
    for flag in boss_flags:
        if pd.get(flag, False):
            count += 1
    
    return count


def _get_defeated_bosses_list(pd: Dict[str, Any]) -> list:
    """Get list of defeated boss names."""
    boss_mapping = {
        "falseKnightDefeated": "False Knight",
        "mawlekDefeated": "Brooding Mawlek", 
        "giantBuzzerDefeated": "Giant Buzzer",
        "giantFlyDefeated": "Giant Fly",
        "blocker1Defeated": "Blocker",
        "blocker2Defeated": "Blocker",
        "hornet1Defeated": "Hornet Protector",
        "collectorDefeated": "The Collector",
        "hornetOutskirtsDefeated": "Hornet Sentinel",
        "mageLordDreamDefeated": "Soul Tyrant",
        "infectedKnightDreamDefeated": "Lost Kin",
        "whiteDefenderDefeated": "White Defender",
        "greyPrinceDefeated": "Grey Prince Zote",
        "dungDefenderDefeated": "Dung Defender",
        "flukeMotherDefeated": "Flukemarm",
        "megaBeamMinerDefeated": "Mega Beam Miner",
        "mimicSpiderDefeated": "Nosk",
        "hiveKnightDefeated": "Hive Knight",
        "traitorLordDefeated": "Traitor Lord",
        "obblobbleDefeated": "Oblobbles",
        "zoteDefeated": "Grey Prince Zote",
        "lobsterLancerDefeated": "Oblobbles",
        "hollowKnightDefeated": "The Hollow Knight",
        "finalBossDefeated": "The Radiance",
        "grimmDefeated": "Troupe Master Grimm",
        "nightmareGrimmDefeated": "Nightmare King Grimm",
        "paleLurkerDefeated": "Pale Lurker",
        "nailBrosDefeated": "Nail Brothers",
        "paintmasterDefeated": "Paintmaster Sheo",
        "nailsageDefeated": "Nailsage Sly",
        "hollowKnightPrimeDefeated": "Pure Vessel",
        "godseekerMaskDefeated": "Absolute Radiance"
    }
    
    defeated = []
    for flag, name in boss_mapping.items():
        if pd.get(flag, False):
            defeated.append(name)
    
    return defeated


def _get_owned_charms_list(pd: Dict[str, Any]) -> list:
    """Get list of owned charm names."""
    charm_mapping = {
        1: "Gathering Swarm",
        2: "Wayward Compass", 
        3: "Grubsong",
        4: "Stalwart Shell",
        5: "Baldur Shell",
        6: "Fury of the Fallen",
        7: "Quick Focus",
        8: "Lifeblood Heart",
        9: "Lifeblood Core",
        10: "Defender's Crest",
        11: "Flukenest",
        12: "Thorns of Agony",
        13: "Mark of Pride",
        14: "Steady Body",
        15: "Heavy Blow",
        16: "Sharp Shadow",
        17: "Spore Shroom",
        18: "Longnail",
        19: "Shaman Stone",
        20: "Soul Catcher",
        21: "Soul Eater",
        22: "Glowing Womb",
        23: "Fragile Heart",
        24: "Fragile Greed",
        25: "Fragile Strength",
        26: "Nailmaster's Glory",
        27: "Joni's Blessing",
        28: "Shape of Unn",
        29: "Hiveblood",
        30: "Dream Wielder",
        31: "Dashmaster",
        32: "Quick Slash",
        33: "Spell Twister",
        34: "Deep Focus",
        35: "Grubberfly's Elegy",
        36: "Kingsoul",
        37: "Sprintmaster",
        38: "Dreamshield",
        39: "Weaversong",
        40: "Grimmchild"
    }
    
    owned = []
    for charm_id, name in charm_mapping.items():
        if pd.get(f"gotCharm_{charm_id}", False):
            owned.append(name)
    
    return owned


def _get_equipped_charms_list(pd: Dict[str, Any]) -> list:
    """Get list of currently equipped charm names."""
    charm_mapping = {
        1: "Gathering Swarm",
        2: "Wayward Compass", 
        3: "Grubsong",
        4: "Stalwart Shell",
        5: "Baldur Shell",
        6: "Fury of the Fallen",
        7: "Quick Focus",
        8: "Lifeblood Heart",
        9: "Lifeblood Core",
        10: "Defender's Crest",
        11: "Flukenest",
        12: "Thorns of Agony",
        13: "Mark of Pride",
        14: "Steady Body",
        15: "Heavy Blow",
        16: "Sharp Shadow",
        17: "Spore Shroom",
        18: "Longnail",
        19: "Shaman Stone",
        20: "Soul Catcher",
        21: "Soul Eater",
        22: "Glowing Womb",
        23: "Fragile Heart",
        24: "Fragile Greed",
        25: "Fragile Strength",
        26: "Nailmaster's Glory",
        27: "Joni's Blessing",
        28: "Shape of Unn",
        29: "Hiveblood",
        30: "Dream Wielder",
        31: "Dashmaster",
        32: "Quick Slash",
        33: "Spell Twister",
        34: "Deep Focus",
        35: "Grubberfly's Elegy",
        36: "Kingsoul",
        37: "Sprintmaster",
        38: "Dreamshield",
        39: "Weaversong",
        40: "Grimmchild"
    }
    
    equipped = []
    equipped_ids = pd.get("equippedCharms", [])
    for charm_id in equipped_ids:
        if charm_id in charm_mapping:
            equipped.append(charm_mapping[charm_id])
    
    return equipped


def _convert_binary_save_to_json(file_content: bytes) -> Dict[str, Any]:
    """Convert binary Hollow Knight save file to JSON format.
    
    Note: Hollow Knight save files are encrypted/compressed. For full parsing,
    use tools like https://bloodorca.github.io/hollow/ to decrypt first.
    This function extracts what it can from the binary format.
    """
    try:
        data = file_content
        
        # Extract readable strings from the binary data
        text_parts = []
        current_text = ""
        
        for byte in data:
            if 32 <= byte <= 126:  # Printable ASCII
                current_text += chr(byte)
            else:
                if len(current_text) > 3:  # Keep shorter strings too
                    text_parts.append(current_text)
                current_text = ""
        
        # First, try to find embedded JSON in the binary data
        try:
            # Look for the JSON string directly in the binary data
            content_str = file_content.decode('utf-8', errors='ignore')
            if 'playerData' in content_str and '{' in content_str:
                # Find the start of the JSON
                start = content_str.find('{')
                if start != -1:
                    # Find the matching closing brace
                    brace_count = 0
                    end = start
                    for i, char in enumerate(content_str[start:], start):
                        if char == '{':
                            brace_count += 1
                        elif char == '}':
                            brace_count -= 1
                            if brace_count == 0:
                                end = i + 1
                                break
                    
                    json_str = content_str[start:end]
                    parsed = json.loads(json_str)
                    if 'playerData' in parsed:
                        return parsed
        except:
            pass
        
        # If no JSON found, try to extract actual values from the binary data
        player_data = {}
        
        # Look for common Hollow Knight data patterns
        for i, text in enumerate(text_parts):
            # Look for scene names (common patterns)
            if any(scene in text for scene in ['Crossroads', 'Greenpath', 'Fungal', 'City', 'Deepnest', 'Crystal', 'RestingGrounds', 'Abyss', 'White_Palace']):
                if 'respawnScene' not in player_data:
                    player_data['respawnScene'] = text
                if 'mapZone' not in player_data:
                    # Extract zone from scene name
                    zone = text.split('_')[0] if '_' in text else text
                    player_data['mapZone'] = zone
        
        # Try to extract numeric values from the binary data
        # Look for patterns that might be playtime, geo, etc.
        import struct
        
        # Look for 4-byte integers that might be meaningful values
        for i in range(0, len(data) - 4, 4):
            try:
                # Try little-endian 32-bit integer
                value = struct.unpack('<I', data[i:i+4])[0]
                
                # Reasonable ranges for Hollow Knight values
                if 1000 <= value <= 1000000:  # Could be playtime in seconds or geo
                    if 'playTime' not in player_data and 3600 <= value <= 864000:  # 1 hour to 10 days
                        player_data['playTime'] = value
                    elif 'geo' not in player_data and 0 <= value <= 100000:
                        player_data['geo'] = value
                elif 0 <= value <= 1000:  # Smaller values
                    if 'health' not in player_data and 1 <= value <= 9:
                        player_data['health'] = value
                    elif 'maxHealth' not in player_data and 1 <= value <= 9:
                        player_data['maxHealth'] = value
                    elif 'deathCount' not in player_data and 0 <= value <= 1000:
                        player_data['deathCount'] = value
                    elif 'completionPercent' not in player_data and 0 <= value <= 112:
                        player_data['completionPercent'] = value
                    elif 'nailUpgrades' not in player_data and 0 <= value <= 4:
                        player_data['nailUpgrades'] = value
                    elif 'soulVessels' not in player_data and 0 <= value <= 3:
                        player_data['soulVessels'] = value
                    elif 'maskShards' not in player_data and 0 <= value <= 4:
                        player_data['maskShards'] = value
            except:
                continue
        
        # Look for boss names in the text parts
        bosses = []
        charms = []
        boss_names = ['False_Knight', 'Hornet', 'Mantis_Lords', 'Soul_Master', 'Broken_Vessel', 'Dung_Defender', 'Crystal_Guardian', 'Uumuu', 'Watcher_Knights', 'Hollow_Knight', 'Radiance']
        charm_names = ['Wayward_Compass', 'Gathering_Swarm', 'Stalwart_Shell', 'Soul_Catcher', 'Shaman_Stone', 'Soul_Eater', 'Dashmaster', 'Sprintmaster', 'Grubsong', 'Grubberfly_Elegy']
        
        for text in text_parts:
            for boss in boss_names:
                if boss in text and boss not in bosses:
                    bosses.append(boss)
            for charm in charm_names:
                if charm in text and charm not in charms:
                    charms.append(charm)
        
        player_data['bossesDefeated'] = bosses
        player_data['charms'] = charms
        
        # Set defaults for missing values
        defaults = {
            'playTime': 0,
            'completionPercent': 0,
            'geo': 0,
            'health': 5,
            'maxHealth': 5,
            'deathCount': 0,
            'respawnScene': 'Tutorial_01',
            'mapZone': 'Tutorial',
            'nailUpgrades': 0,
            'soulVessels': 0,
            'maskShards': 0
        }
        
        for key, default_value in defaults.items():
            if key not in player_data:
                player_data[key] = default_value
        
        return {"playerData": player_data}
        
    except Exception as e:
        raise SaveDataError(f"Failed to convert binary save file: {e}")


def format_save_summary(summary: Dict[str, Any]) -> str:
    """Format the save data summary into a Discord-friendly message."""
    completion = summary["completion_percent"]
    
    # Determine progress stage
    if completion == 0:
        stage = "Fresh Save"
        emoji = "🌱"
    elif completion < 20:
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
    
    # Format the message - always show detailed stats
    equipped_text = ""
    if summary.get('charms_equipped'):
        equipped_names = ", ".join(summary['charms_equipped'])
        equipped_text = f"\n🎯 **Equipped**: {equipped_names}"
    
    message = f"""🎮 **Hollow Knight Progress Analysis** {emoji}
**Stage**: {stage} ({completion}% complete)

⏱️ **Playtime**: {summary['playtime_hours']} hours
💰 **Geo**: {summary['geo']:,}
❤️ **Health**: {summary['health']}/{summary['max_health']} hearts
💀 **Deaths**: {summary['deaths']}
🗡️ **Nail**: +{summary['nail_upgrades']} upgrades
💙 **Soul**: {summary['soul_vessels']} vessels
🎭 **Charms**: {summary['charms_owned']} owned ({summary.get('charm_slots_filled', 0)}/{summary.get('charm_slots', 0)} slots){equipped_text}
👹 **Bosses**: {summary['bosses_defeated']} defeated

📍 **Current Location**: {summary['scene']} ({summary['zone']})"""
    
    # Add some personality based on stats
    if completion == 0:
        message += "\n\n🎮 Fresh save detected! Time to start your Hallownest journey, gamer!"
    elif summary['deaths'] > 100:
        message += "\n\n💀 Bruh, that's a lot of deaths. The Infection really got to you, huh?"
    elif summary['deaths'] < 10 and completion > 50:
        message += "\n\n🔥 Damn, you're good! Barely any deaths and you're already deep in Hallownest!"
    
    if summary['geo'] > 10000:
        message += "\n💰 You're swimming in geo! Time to spend it on some upgrades, gamer."
    
    return message


def generate_save_analysis(summary: Dict[str, Any]) -> str:
    """Generate AI analysis of the save data."""
    try:
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
