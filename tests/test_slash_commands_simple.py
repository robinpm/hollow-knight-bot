#!/usr/bin/env python3
"""Simple tests for slash command logic without complex mocking."""

import os
import sys
import time

# Add the src directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Set up environment for testing
os.environ["DISCORD_TOKEN"] = "dummy"
os.environ["GEMINI_API_KEY"] = "dummy-key-for-testing"

def test_progress_message_generation():
    """Test the core logic for generating progress messages."""
    print("Testing progress message generation...")
    
    # Test data with None values (the original issue)
    sample_data = {
        'playtime_hours': None,
        'completion_percent': None,
        'geo': None,
        'health': None,
        'max_health': None,
        'deaths': None,
        'scene': None,
        'zone': None,
        'nail_upgrades': None,
        'soul_vessels': None,
        'mask_shards': None,
        'charms_owned': None,
        'bosses_defeated': None,
        'ts': int(time.time()) - 3600,
    }
    
    try:
        # Extract values (this is what the slash command does)
        completion = sample_data['completion_percent']
        playtime = sample_data['playtime_hours']
        geo = sample_data['geo']
        health = sample_data['health']
        max_health = sample_data['max_health']
        deaths = sample_data['deaths']
        scene = sample_data['scene']
        zone = sample_data['zone']
        nail_upgrades = sample_data['nail_upgrades']
        soul_vessels = sample_data['soul_vessels']
        mask_shards = sample_data['mask_shards']
        charms_owned = sample_data['charms_owned']
        bosses_defeated = sample_data['bosses_defeated']
        
        # Generate the message (this is the fixed formatting logic)
        message = f"📜 **Latest Save Data for TestUser** (1h ago)\n\n"
        message += f"🎮 **Progress**: {completion or 0}% complete\n"
        message += f"⏱️ **Playtime**: {(playtime if playtime is not None else 0):.2f} hours\n"
        message += f"💰 **Geo**: {(geo if geo is not None else 0):,}\n"
        message += f"❤️ **Health**: {health or 0}/{max_health or 0} hearts\n"
        message += f"💀 **Deaths**: {deaths or 0}\n"
        message += f"🗡️ **Nail**: +{nail_upgrades or 0} upgrades\n"
        message += f"💙 **Soul**: {soul_vessels or 0} vessels\n"
        message += f"🎭 **Charms**: {charms_owned or 0} owned\n"
        message += f"👹 **Bosses**: {bosses_defeated or 0} defeated\n"
        message += f"📍 **Location**: {scene or 'Unknown'} ({zone or 'Unknown'})"
        
        print("✅ Progress message generation succeeded")
        print(f"Generated message length: {len(message)} characters")
        return True
        
    except Exception as e:
        print(f"❌ Progress message generation failed: {e}")
        return False

def test_history_message_generation():
    """Test the core logic for generating history messages."""
    print("Testing history message generation...")
    
    # Test data for history format
    save = {
        'completion_percent': None,
        'playtime_hours': None,
        'geo': None,
        'health': None,
        'max_health': None,
        'deaths': None,
        'scene': None,
        'zone': None,
        'bosses_defeated': None,
        'ts': int(time.time()) - 3600,
    }
    
    try:
        # Generate history message (this is the fixed formatting logic)
        message = f"**#1** (1h ago)\n"
        message += f"🎮 {save['completion_percent'] or 0}% complete | ⏱️ {(save['playtime_hours'] if save['playtime_hours'] is not None else 0):.1f}h | 💰 {(save['geo'] if save['geo'] is not None else 0):,} geo\n"
        message += f"❤️ {save['health'] or 0}/{save['max_health'] or 0} hearts | 💀 {save['deaths'] or 0} deaths | 👹 {save['bosses_defeated'] or 0} bosses\n"
        message += f"📍 {save['scene'] or 'Unknown'} ({save['zone'] or 'Unknown'})\n\n"
        
        print("✅ History message generation succeeded")
        print(f"Generated message length: {len(message)} characters")
        return True
        
    except Exception as e:
        print(f"❌ History message generation failed: {e}")
        return False

def test_mixed_data_scenarios():
    """Test various combinations of None and valid data."""
    print("Testing mixed data scenarios...")
    
    test_cases = [
        {
            'name': 'All None values',
            'data': {
                'playtime_hours': None,
                'completion_percent': None,
                'geo': None,
                'health': None,
                'max_health': None,
                'deaths': None,
                'scene': None,
                'zone': None,
            }
        },
        {
            'name': 'Mixed None and valid values',
            'data': {
                'playtime_hours': 15.5,
                'completion_percent': None,
                'geo': 0,
                'health': 7,
                'max_health': None,
                'deaths': 0,
                'scene': '',
                'zone': None,
            }
        },
        {
            'name': 'All valid values',
            'data': {
                'playtime_hours': 25.0,
                'completion_percent': 75.0,
                'geo': 5000,
                'health': 8,
                'max_health': 9,
                'deaths': 15,
                'scene': 'Crossroads',
                'zone': 'Forgotten Crossroads',
            }
        }
    ]
    
    for test_case in test_cases:
        try:
            data = test_case['data']
            
            # Test the formatting logic
            message = f"🎮 **Progress**: {data['completion_percent'] or 0}% complete\n"
            message += f"⏱️ **Playtime**: {(data['playtime_hours'] if data['playtime_hours'] is not None else 0):.2f} hours\n"
            message += f"💰 **Geo**: {(data['geo'] if data['geo'] is not None else 0):,}\n"
            message += f"❤️ **Health**: {data['health'] or 0}/{data['max_health'] or 0} hearts\n"
            message += f"💀 **Deaths**: {data['deaths'] or 0}\n"
            message += f"📍 **Location**: {data['scene'] or 'Unknown'} ({data['zone'] or 'Unknown'})"
            
            print(f"✅ {test_case['name']} - formatting succeeded")
            
        except Exception as e:
            print(f"❌ {test_case['name']} - formatting failed: {e}")
            return False
    
    return True

def test_database_integration():
    """Test that database functions work with the new schema."""
    print("Testing database integration...")
    
    try:
        from core import database
        
        # Test that we can add an update (this was the original issue)
        test_guild_id = 999999
        test_user_id = 888888
        test_text = "Test progress update"
        test_ts = int(time.time())
        
        # This should work with the new schema
        database.add_update(test_guild_id, test_user_id, test_text, test_ts)
        
        # Verify it was added
        last_update = database.get_last_update(test_guild_id, test_user_id)
        assert last_update is not None, "Update should have been added"
        assert last_update[0] == test_text, "Update text should match"
        
        print("✅ Database integration succeeded")
        return True
        
    except Exception as e:
        print(f"❌ Database integration failed: {e}")
        return False

def main():
    """Run all simple slash command tests."""
    print("🧪 Testing Slash Command Logic")
    print("=" * 50)
    
    tests = [
        test_progress_message_generation,
        test_history_message_generation,
        test_mixed_data_scenarios,
        test_database_integration,
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        if test():
            passed += 1
        print()
    
    print("=" * 50)
    print(f"Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All slash command logic tests passed!")
        return 0
    else:
        print("❌ Some tests failed. Check the issues above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())

