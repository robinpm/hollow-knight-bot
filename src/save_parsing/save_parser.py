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
        
        # Debug: Log available fields to help with version detection
        log.debug(f"Available root fields: {list(raw.keys())}")
        log.debug(f"Available playerData fields: {list(pd.keys())}")
        
        # Extract key progress information
        playtime_hours = round(pd.get("playTime", 0) / 3600, 2)
        completion_percent = pd.get("completionPercentage", pd.get("completionPercent", 0))
        completion_per_hour = round(completion_percent / playtime_hours, 2) if playtime_hours > 0 else 0
        
        deaths = (
            pd.get("totalDeaths")
            or pd.get("deathCount")
            or pd.get("deaths")
            or pd.get("deathsCounter")
            or 0
        )

        total_soul_vessels = _calculate_soul_vessels(pd)
        extra_soul_vessels = max(total_soul_vessels - 3, 0)

        owned_charms = _get_owned_charms_list(pd)
        equipped_charms = _get_equipped_charms_list(pd)
        bosses_defeated_list_actual = _get_defeated_bosses_list(pd)
        bosses_defeated_actual = len(bosses_defeated_list_actual)

        summary = {
            "playtime_hours": playtime_hours,
            "playtime_seconds": pd.get("playTime", 0),
            "completion_percent": completion_percent,
            "completion_per_hour": completion_per_hour,
            "geo": pd.get("geo", 0),
            "health": pd.get("health", 0),
            "max_health": pd.get("maxHealth", 0),
            "deaths": int(deaths) if isinstance(deaths, (int, float)) else 0,
            "scene": pd.get("respawnScene", "Unknown"),
            "zone": pd.get("mapZone", "Unknown"),
            "soul_vessels": 0,
            "total_soul_vessels": total_soul_vessels,
            "mask_shards": pd.get("heartPieces", 0),
            "charms_owned": len(owned_charms),
            "charms_owned_actual": pd.get("charmsOwned", len(owned_charms)),
            "charms_equipped": equipped_charms,
            "charm_slots": pd.get("charmSlots", 0),
            "charm_slots_filled": pd.get("charmSlotsFilled", 0),
            "bosses_defeated": 0,
            "bosses_defeated_actual": bosses_defeated_actual,
            "bosses_defeated_list": [],
            "bosses_defeated_list_actual": bosses_defeated_list_actual,
            "charms_list": owned_charms,
            "nail_damage": pd.get("nailDamage", 5),
            "nail_upgrades": _calculate_nail_upgrades(pd),
            "nail_arts": _get_nail_arts_list(pd),
            "abilities": _get_abilities_list(pd),
            "grubs_collected": pd.get("grubsCollected", 0),
            "journal_entries": pd.get("journalEntriesCompleted", 0),
            "journal_total": pd.get("journalEntriesTotal", 146),
            "scenes_visited": len(pd.get("scenesVisited", [])),
            "scenes_mapped": len(pd.get("scenesMapped", [])),
            "save_version": _get_save_version(raw, pd),
            "path_of_pain_completed": "Yes" if pd.get("killedBindingSeal", 0) else "No",
        }
        
        return summary
        
    except Exception as e:
        raise SaveDataError(f"Failed to parse save file: {e}")


def _calculate_soul_vessels(pd: Dict[str, Any]) -> int:
    """Calculate the number of soul vessels from save data."""
    # First, try to get the direct soul vessel count
    direct_count = pd.get("soulVessels", None)
    if direct_count is not None:
        return direct_count
    
    # Fall back to calculating from maxMP
    # In Hollow Knight, you start with 3 soul vessels (99 MP base)
    max_mp = pd.get("maxMP", 99)  # Base soul capacity is 99 (3 vessels)
    
    # Soul vessel calculation:
    # 3 vessels = 99 MP (base)
    # 4 vessels = 132 MP (99 + 33)
    # 5 vessels = 165 MP (99 + 33 + 33)
    # 6 vessels = 198 MP (99 + 33 + 33 + 33)
    if max_mp <= 99:
        return 3  # You start with 3 soul vessels
    # Each additional soul vessel adds 33 MP
    extra_mp = max_mp - 99
    return 3 + (extra_mp // 33)


def _get_save_version(raw: Dict[str, Any], pd: Dict[str, Any]) -> str:
    """Get save version from various possible locations in the save file."""
    # Try different possible field names for version
    version_fields = [
        raw.get("version"),
        raw.get("gameVersion"), 
        raw.get("saveVersion"),
        raw.get("game_version"),
        raw.get("save_version"),
        pd.get("version"),
        pd.get("gameVersion"),
        pd.get("saveVersion"),
        pd.get("game_version"),
        pd.get("save_version")
    ]
    
    for version in version_fields:
        if version and version != "Unknown":
            return str(version)
    
    return "Unknown"


def _calculate_nail_upgrades(pd: Dict[str, Any]) -> int:
    """Calculate nail upgrade level from nail damage."""
    smith_upgrades = pd.get("nailSmithUpgrades")
    if isinstance(smith_upgrades, (int, float)):
        return int(smith_upgrades)

    damage_mapping = {5: 0, 9: 1, 13: 2, 17: 3, 21: 4}
    nail_damage = pd.get("nailDamage", 5)
    return damage_mapping.get(nail_damage, 0)


def _get_nail_arts_list(pd: Dict[str, Any]) -> list:
    """Get list of learned nail arts."""
    nail_arts = []
    if pd.get("hasCyclone", False):
        nail_arts.append("Cyclone Slash")
    if pd.get("hasDashSlash", False):
        nail_arts.append("Dash Slash")
    if pd.get("hasUpwardSlash", False):
        nail_arts.append("Great Slash")
    return nail_arts


def _get_abilities_list(pd: Dict[str, Any]) -> list:
    """Get list of acquired abilities."""
    abilities = []
    if pd.get("canDash", False):
        abilities.append("Mothwing Cloak")
    if pd.get("canWallJump", False):
        abilities.append("Mantis Claw")
    if pd.get("canSuperDash", False):
        abilities.append("Crystal Heart")
    if pd.get("canShadowDash", False):
        abilities.append("Shade Cloak")
    if pd.get("hasDoubleJump", False):
        abilities.append("Monarch Wings")
    if pd.get("hasDreamNail", False):
        abilities.append("Dream Nail")
    if pd.get("hasDreamGate", False):
        abilities.append("Dream Gate")
    if pd.get("hasLantern", False):
        abilities.append("Lumafly Lantern")
    if pd.get("hasTramPass", False):
        abilities.append("Tram Pass")
    if pd.get("hasQuill", False):
        abilities.append("Quill")
    if pd.get("hasCityKey", False):
        abilities.append("City Crest")
    if pd.get("hasKingsBrand", False):
        abilities.append("King's Brand")
    return abilities


def _count_defeated_bosses(pd: Dict[str, Any]) -> int:
    """Count the number of defeated bosses from player data."""
    boss_flags = [
        # Main Bosses (each provides 1% completion)
        "bossGruzMother", "falseKnightDefeated", "hornet1Defeated", "defeatedDungDefender", 
        "bossBroodingMawlek", "mageLordDefeated", "defeatedMantisLords", "killedBlackKnight", 
        "collectorDefeated", "defeatedMegaJelly", "hornetOutskirtsDefeated", "killedInfectedKnight", 
        "killedMimicSpider", "killedTraitorLord", "killedHollowKnight",
        
        # Dream Bosses
        "falseKnightDreamDefeated", "mageLordDreamDefeated", "infectedKnightDreamDefeated",
        "whiteDefenderDefeated", "greyPrinceDefeated",
        
        # Warrior Dreams (Essence Bosses)
        "aladarSlugDefeated", "xeroDefeated", "mumCaterpillarDefeated", "elderHuDefeated",
        "noEyesDefeated", "markothDefeated", "galienDefeated",
        
        # Special/Optional Bosses (for 112% completion & achievements)
        "killedMegaMossCharger", "paleLurkerDefeated",
        
        # Repeatable Bosses (tracked by amount/max)
        "whiteDefenderDefeats", "greyPrinceDefeats"
    ]
    
    count = 0
    for flag in boss_flags:
        if pd.get(flag, False):
            count += 1
    
    return count


def _get_defeated_bosses_list(pd: Dict[str, Any]) -> list:
    """Get list of defeated boss names."""
    boss_mapping = {
        # Main Bosses (each provides 1% completion)
        "bossGruzMother": "Gruz Mother",
        "falseKnightDefeated": "False Knight",
        "hornet1Defeated": "Hornet Protector",
        "defeatedDungDefender": "Dung Defender",
        "bossBroodingMawlek": "Brooding Mawlek",
        "mageLordDefeated": "Soul Master",
        "defeatedMantisLords": "Mantis Lords",
        "killedBlackKnight": "Watcher Knights",
        "collectorDefeated": "The Collector",
        "defeatedMegaJelly": "Uumuu",
        "hornetOutskirtsDefeated": "Hornet Sentinel",
        "killedInfectedKnight": "Broken Vessel",
        "killedMimicSpider": "Nosk",
        "killedTraitorLord": "Traitor Lord",
        "killedHollowKnight": "Hollow Knight",
        
        # Dream Bosses
        "falseKnightDreamDefeated": "Failed Champion",
        "mageLordDreamDefeated": "Soul Tyrant",
        "infectedKnightDreamDefeated": "Lost Kin",
        "whiteDefenderDefeated": "White Defender",
        "greyPrinceDefeated": "Grey Prince Zote",
        
        # Warrior Dreams (Essence Bosses)
        "aladarSlugDefeated": "Gorb",
        "xeroDefeated": "Xero",
        "mumCaterpillarDefeated": "Marmu",
        "elderHuDefeated": "Elder Hu",
        "noEyesDefeated": "No Eyes",
        "markothDefeated": "Markoth",
        "galienDefeated": "Galien",
        
        # Special/Optional Bosses (for 112% completion & achievements)
        "killedMegaMossCharger": "Massive Moss Charger",
        "paleLurkerDefeated": "Pale Lurker",
        
        # Repeatable Bosses (tracked by amount/max)
        "whiteDefenderDefeats": "White Defender (repeatable, up to 5)",
        "greyPrinceDefeats": "Grey Prince Zote (repeatable, up to 10)"
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
    
    # Format playtime
    playtime_seconds = summary.get('playtime_seconds', 0)
    hours = int(playtime_seconds // 3600)
    minutes = int((playtime_seconds % 3600) // 60)
    seconds = int(playtime_seconds % 60)
    playtime_formatted = f"{hours} h {minutes:02d} min {seconds:02d} sec"
    playtime_hours = summary.get('playtime_hours', 0)

    # Stage messaging
    if completion == 0:
        stage_line = "Fresh save detected!"
        journey_line = "Hallownest journey is just beginning!"
    else:
        stage_line = f"**Stage**: {stage}"
        journey_line = f"Hallownest journey: {stage}"

    # Health display with mask images - cleaner format
    health_masks = "❤️" * summary['max_health']
    health_text = f"{health_masks} ({summary['max_health']})"
    
    # Soul display with orb images - cleaner format
    total_vessels = summary.get('total_soul_vessels')
    if total_vessels is None:
        extra_vessels = summary.get('soul_vessels', 0)
        total_vessels = extra_vessels + 3 if extra_vessels else extra_vessels
    if not total_vessels:
        total_vessels = 3  # Base number of vessels
    soul_orbs = "💙" * total_vessels
    soul_text = f"{soul_orbs} ({total_vessels})"
    
    # Notches display - cleaner format
    notches = "🔸" * summary.get('charm_slots', 0)
    notches_text = f"{notches} ({summary.get('charm_slots', 0)})"
    
    # Bosses list
    bosses_text = ""
    bosses_defeated_list = summary.get('bosses_defeated_list_actual', summary.get('bosses_defeated_list')) or []
    if isinstance(bosses_defeated_list, str):
        try:
            bosses_defeated_list = json.loads(bosses_defeated_list)
        except json.JSONDecodeError:
            bosses_defeated_list = []
    if bosses_defeated_list:
        bosses_text = f"**Bosses Defeated**: {', '.join(bosses_defeated_list)}\n"
    
    # Nail arts
    nail_arts_text = ""
    if summary.get('nail_arts'):
        nail_arts_text = f"**Nail Arts**: {', '.join(summary['nail_arts'])}\n"
    
    # Abilities
    abilities_text = ""
    if summary.get('abilities'):
        abilities_text = f"**Abilities**: {', '.join(summary['abilities'])}\n"
    
    # Equipment (charms equipped)
    equipment_text = ""
    charms_equipped = summary.get('charms_equipped') or []
    if isinstance(charms_equipped, str):
        try:
            charms_equipped = json.loads(charms_equipped)
        except json.JSONDecodeError:
            charms_equipped = []
    if charms_equipped:
        equipment_text = f"**Equipment**: {', '.join(charms_equipped)}\n"

    bosses_defeated_count = summary.get('bosses_defeated_actual', summary.get('bosses_defeated', 0))

    message = f"""🎮 **Hollow Knight Progress Analysis** {emoji}

{stage_line}
{journey_line}

**Health**: {health_text}
**Soul**: {soul_text}
**Notches**: {notches_text}
**Geo**: 💰 {summary['geo']:,}
**Playtime**: ⏱️ {playtime_formatted} ({playtime_hours:.2f} hours)
**Game Completion**: 📊 {completion}% (out of 112%) - {summary.get('completion_per_hour', 0)}%/hr
**Deaths**: 💀 {summary.get('deaths', 0)} | 👹 Bosses defeated: {bosses_defeated_count}
**Save Version**: 📝 {summary.get('save_version', 'Unknown')}

**Nail**: ⚔️ +{summary.get('nail_upgrades', 0)} upgrades ({summary.get('nail_damage', 5)} damage)
{nail_arts_text}**Charms**: 🎭 {summary['charms_owned']} owned
{bosses_text}{abilities_text}{equipment_text}
**Collectibles**: 🐛 {summary.get('grubs_collected', 0)} grubs, 📖 {summary.get('journal_entries', 0)}/{summary.get('journal_total', 146)} journal entries
**Exploration**: 🗺️ {summary.get('scenes_visited', 0)} scenes visited, {summary.get('scenes_mapped', 0)} mapped
**Path of Pain Completed**: 💔 {summary.get('path_of_pain_completed', 0)}

📍 **Current Location**: {summary['scene']} ({summary['zone']})"""
    
    return message


def generate_save_analysis(summary: Dict[str, Any]) -> str:
    """Generate AI analysis of the save data."""
    try:
        prompt = f"""You are HollowBot, a seasoned Hollow Knight player who's 112% the game.
Analyze this save data and give a short, personalized response (1-2 sentences max):

Playtime: {summary['playtime_hours']} hours
Completion: {summary['completion_percent']}%
Location: {summary['scene']} ({summary['zone']})
Bosses defeated: {summary['bosses_defeated']}
Charms owned: {summary['charms_owned']}

Give a gamer-style response about their progress. Be encouraging but playfully snarky. 
Do NOT include 'HollowBot:' or any name prefix in your response."""
        
        return generate_reply(prompt)
        
    except Exception as e:
        log.error(f"Failed to generate save analysis: {e}")
        return "The Chronicler had trouble analyzing your save data, but I can see you're making progress!"
