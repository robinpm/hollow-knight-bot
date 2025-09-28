#!/usr/bin/env python3
"""Simple test script to verify bot components work."""

import os
import sys
import pytest

# Add the src directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


def test_imports():
    """Test that all modules can be imported."""
    os.environ["DISCORD_TOKEN"] = "dummy"
    os.environ["GEMINI_API_KEY"] = "dummy"

    from core import config, logger, validation, database
    from ai import gemini_integration
    from langchain.chains import ConversationChain
    from langchain.memory import ConversationBufferMemory

    assert config is not None
    assert logger is not None
    assert validation is not None
    assert database is not None
    assert gemini_integration is not None
    assert ConversationChain is not None and ConversationBufferMemory is not None


def test_config():
    """Test configuration loading."""
    os.environ["DISCORD_TOKEN"] = "dummy-discord-token"
    os.environ["GEMINI_API_KEY"] = "dummy-key-for-testing"

    import importlib
    from core import config as config_module
    importlib.reload(config_module)

    assert config_module.config.discord_token == "dummy-discord-token"
    assert config_module.config.google_api_key == "dummy-key-for-testing"


def test_validation():
    """Test validation functions."""
    from core.validation import (
        validate_progress_text,
        validate_time_format,
        validate_custom_context,
        ValidationError,
    )

    # Test valid inputs
    assert validate_progress_text("Beat the Mantis Lords!")
    assert validate_time_format("18:30") == "18:30"
    assert validate_custom_context("Speak like Zote") == "Speak like Zote"

    # Test invalid inputs
    with pytest.raises(ValidationError):
        validate_progress_text("")
    with pytest.raises(ValidationError):
        validate_time_format("25:00")
    with pytest.raises(ValidationError):
        validate_custom_context("")


def test_memory_db():
    """Test memory database operations."""
    from core import database

    mem_id = database.add_memory(1, "Test memory")
    memories = database.get_memories_by_guild(1)
    assert any(mid == mem_id for mid, _ in memories)
    database.delete_memory(1, mem_id)


def test_leaderboard_db():
    """Test leaderboard database operations."""
    from core import database
    import time

    test_guild_id = 999
    test_user_id = 888
    current_time = int(time.time())

    database.add_update(test_guild_id, test_user_id, "Beat False Knight", current_time - 86400 * 3)
    database.add_update(test_guild_id, test_user_id, "Beat Hornet", current_time - 86400 * 2)
    database.add_update(test_guild_id, test_user_id, "Beat Mantis Lords", current_time - 86400)
    database.add_update(test_guild_id, test_user_id, "Got Crystal Heart", current_time - 3600)

    stats = database.get_user_stats(test_guild_id)
    assert len(stats) > 0

    user_id, total_updates, days_active, recent_updates, first_update_ts = stats[0]
    assert user_id == str(test_user_id)
    assert total_updates >= 4
    assert days_active >= 3
    assert recent_updates >= 1


def test_command_structure():
    """Test that the new command structure is properly defined."""
    from core import main

    assert main.BOT_VERSION == "3.3"
    assert hasattr(main, 'bot')
    assert hasattr(main, 'hollow_group')


def test_bot_only_reacts_to_direct_mentions():
    """Ensure mention detection only triggers for the HollowBot account."""
    from types import SimpleNamespace

    from core import main

    bot_user = SimpleNamespace(id=1234)

    message_with_other_mentions = SimpleNamespace(
        mentions=[SimpleNamespace(id=9999)],
        raw_mentions=[9999],
        content="<@9999> hello there",
    )

    message_with_bot_mention = SimpleNamespace(
        mentions=[],
        raw_mentions=[],
        content=f"<@{bot_user.id}> fight!",
    )

    assert not main._is_bot_mentioned(message_with_other_mentions, bot_user)
    assert main._is_bot_mentioned(message_with_bot_mention, bot_user)


def test_strip_bot_mention_preserves_other_mentions():
    """Ensure we only remove the bot mention token and keep other mentions intact."""
    from types import SimpleNamespace

    from core import main

    bot_user = SimpleNamespace(id=1234)
    other_user_id = 4321

    content = f"<@{bot_user.id}> fight <@{other_user_id}>"
    cleaned = main._strip_bot_mention(content, bot_user)

    assert cleaned == f"fight <@{other_user_id}>"

    content_with_bang = f"<@!{bot_user.id}>   hello"
    cleaned_with_bang = main._strip_bot_mention(content_with_bang, bot_user)

    assert cleaned_with_bang == "hello"


def test_leaderboard_algorithm():
    """Test the leaderboard scoring algorithm."""
    import time

    def calculate_score(user_id: str, total_updates: int, days_active: int, recent_updates: int, first_update_ts: int) -> float:
        base_score = total_updates * 10
        days_since_first = (int(time.time()) - first_update_ts) // 86400
        consistency = (days_active / days_since_first) * 5 if days_since_first > 0 else 0
        recent_bonus = recent_updates * 3
        longevity = min(days_active * 0.5, 20)
        return base_score + consistency + recent_bonus + longevity

    current_time = int(time.time())
    score1 = calculate_score("user1", 10, 5, 2, current_time - 86400 * 7)
    score2 = calculate_score("user2", 5, 3, 1, current_time - 86400 * 5)
    assert score1 > score2

    score3 = calculate_score("user3", 5, 2, 3, current_time - 86400 * 3)
    score4 = calculate_score("user4", 5, 2, 0, current_time - 86400 * 3)
    assert score3 > score4
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
