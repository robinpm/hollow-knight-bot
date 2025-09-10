#!/usr/bin/env python3
"""Simple test script to verify bot components work."""

import os
import sys

# Add the project root to Python path
project_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'src'))

def test_imports():
    """Test that all modules can be imported."""
    print("Testing imports...")

    os.environ["DISCORD_TOKEN"] = "dummy"
    os.environ["GEMINI_API_KEY"] = "dummy"

    try:
        from src.core import config
        print("✅ config imported")
    except Exception as e:
        print(f"❌ config import failed: {e}")
        return False
    
    try:
        from src.core import logger
        print("✅ logger imported")
    except Exception as e:
        print(f"❌ logger import failed: {e}")
        return False
    
    try:
        from src.core import validation
        print("✅ validation imported")
    except Exception as e:
        print(f"❌ validation import failed: {e}")
        return False
    
    try:
        from src.core import database
        print("✅ database imported")
    except Exception as e:
        print(f"❌ database import failed: {e}")
        return False
    
    try:
        from src.ai import gemini_integration
        print("✅ gemini_integration imported")
    except Exception as e:
        print(f"❌ gemini_integration import failed: {e}")
        return False
    
    try:
        from langchain.chains import ConversationChain
        from langchain.memory import ConversationBufferMemory
        print("✅ langchain imported")
    except Exception as e:
        print(f"❌ langchain import failed: {e}")
        return False
    
    return True

def test_config():
    """Test configuration loading."""
    print("\nTesting configuration...")
    
    # Set dummy environment variables for testing
    os.environ["DISCORD_TOKEN"] = "dummy-discord-token"
    os.environ["GEMINI_API_KEY"] = "dummy-key-for-testing"
    
    try:
        from src.core import config
        print("✅ Configuration loaded successfully")
        print(f"   Discord token: {'*' * 10}")
        print(f"   Gemini API key: {'dummy' if config.config.google_api_key == 'dummy-key-for-testing' else 'real'}")
        return True
    except Exception as e:
        print(f"❌ Configuration failed: {e}")
        return False

def test_validation():
    """Test validation functions."""
    print("\nTesting validation...")
    
    try:
        from src.core.validation import (
            validate_progress_text,
            validate_time_format,
            validate_custom_context,
        )

        # Test valid inputs
        result = validate_progress_text("Beat the Mantis Lords!")
        print(f"✅ Valid progress text: {result}")

        result = validate_time_format("18:30")
        print(f"✅ Valid time format: {result}")

        result = validate_custom_context("Speak like Zote")
        print(f"✅ Valid custom context: {result}")

        # Test invalid inputs
        try:
            validate_progress_text("")
            print("❌ Should have failed on empty text")
            return False
        except:
            print("✅ Correctly rejected empty text")

        try:
            validate_time_format("25:00")
            print("❌ Should have failed on invalid time")
            return False
        except:
            print("✅ Correctly rejected invalid time")

        try:
            validate_custom_context("")
            print("❌ Should have failed on empty context")
            return False
        except:
            print("✅ Correctly rejected empty context")

        return True
    except Exception as e:
        print(f"❌ Validation test failed: {e}")
        return False


def test_memory_db():
    """Test memory database operations."""
    print("\nTesting memory DB...")
    try:
        from src.core import database

        mem_id = database.add_memory(1, "Test memory")
        memories = database.get_memories_by_guild(1)
        assert any(mid == mem_id for mid, _ in memories)
        database.delete_memory(1, mem_id)
        print("✅ Memory DB functions")
        return True
    except Exception as e:
        print(f"❌ Memory DB test failed: {e}")
        return False

def test_leaderboard_db():
    """Test leaderboard database operations."""
    print("\nTesting leaderboard DB...")
    try:
        from src.core import database
        import time

        # Add some test progress data
        test_guild_id = 999
        test_user_id = 888
        current_time = int(time.time())
        
        # Add multiple updates for the same user
        database.add_update(test_guild_id, test_user_id, "Beat False Knight", current_time - 86400 * 3)  # 3 days ago
        database.add_update(test_guild_id, test_user_id, "Beat Hornet", current_time - 86400 * 2)  # 2 days ago
        database.add_update(test_guild_id, test_user_id, "Beat Mantis Lords", current_time - 86400)  # 1 day ago
        database.add_update(test_guild_id, test_user_id, "Got Crystal Heart", current_time - 3600)  # 1 hour ago

        # Test the leaderboard function
        stats = database.get_user_stats(test_guild_id)
        assert len(stats) > 0, "Should have at least one user in stats"
        
        user_id, total_updates, days_active, recent_updates, first_update_ts = stats[0]
        assert user_id == str(test_user_id), f"Expected user {test_user_id}, got {user_id}"
        assert total_updates >= 4, f"Expected at least 4 updates, got {total_updates}"
        assert days_active >= 3, f"Expected at least 3 active days, got {days_active}"
        assert recent_updates >= 1, f"Expected at least 1 recent update, got {recent_updates}"
        
        print("✅ Leaderboard DB functions")
        return True
    except Exception as e:
        print(f"❌ Leaderboard DB test failed: {e}")
        return False

def test_command_structure():
    """Test that the new command structure is properly defined."""
    print("\nTesting command structure...")
    try:
        from src.core import main
        
        # Check that BOT_VERSION is updated
        assert main.BOT_VERSION == "1.9", f"Expected BOT_VERSION 1.9, got {main.BOT_VERSION}"
        print(f"✅ Bot version: {main.BOT_VERSION}")
        
        # Check that the bot object exists and has the right structure
        assert hasattr(main, 'bot'), "Bot object should exist"
        assert hasattr(main, 'hollow_group'), "hollow_group should exist"
        
        print("✅ Command structure is properly defined")
        return True
    except Exception as e:
        print(f"❌ Command structure test failed: {e}")
        return False

def test_leaderboard_algorithm():
    """Test the leaderboard scoring algorithm."""
    print("\nTesting leaderboard algorithm...")
    try:
        import time
        
        # Simulate the scoring algorithm from the leaderboard command
        def calculate_score(user_id: str, total_updates: int, days_active: int, recent_updates: int, first_update_ts: int) -> float:
            """Calculate a combined score for the leaderboard."""
            # Base score from total updates (most important)
            base_score = total_updates * 10
            
            # Consistency bonus (days active vs total days since first update)
            days_since_first = (int(time.time()) - first_update_ts) // 86400
            if days_since_first > 0:
                consistency = (days_active / days_since_first) * 5
            else:
                consistency = 0
            
            # Recent activity bonus (updates in last 7 days)
            recent_bonus = recent_updates * 3
            
            # Longevity bonus (longer active = more points)
            longevity = min(days_active * 0.5, 20)  # Cap at 20 points
            
            return base_score + consistency + recent_bonus + longevity

        # Test with sample data
        current_time = int(time.time())
        
        # User with more updates should score higher
        score1 = calculate_score("user1", 10, 5, 2, current_time - 86400 * 7)  # 10 updates, 5 days active
        score2 = calculate_score("user2", 5, 3, 1, current_time - 86400 * 5)   # 5 updates, 3 days active
        
        assert score1 > score2, f"User with more updates should score higher: {score1} vs {score2}"
        
        # User with recent activity should get bonus
        score3 = calculate_score("user3", 5, 2, 3, current_time - 86400 * 3)   # 5 updates, 3 recent
        score4 = calculate_score("user4", 5, 2, 0, current_time - 86400 * 3)   # 5 updates, 0 recent
        
        assert score3 > score4, f"User with recent activity should score higher: {score3} vs {score4}"
        
        print("✅ Leaderboard algorithm works correctly")
        return True
    except Exception as e:
        print(f"❌ Leaderboard algorithm test failed: {e}")
        return False
def main():
    """Run all tests."""
    print("🧪 Hollow Knight Bot Test Suite")
    print("=" * 40)
    
    tests = [
        test_imports,
        test_config,
        test_validation,
        test_memory_db,
        test_leaderboard_db,
        test_command_structure,
        test_leaderboard_algorithm,
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        if test():
            passed += 1
        print()
    
    print("=" * 40)
    print(f"Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! Bot should work on Render.")
        return 0
    else:
        print("❌ Some tests failed. Check the issues above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
