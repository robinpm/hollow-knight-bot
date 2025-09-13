#!/usr/bin/env python3
"""Comprehensive tests for slash commands to catch formatting and logic errors."""

import os
import sys
import time
import pytest
from unittest.mock import Mock, AsyncMock, patch

# Add the src directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Set up environment for testing
os.environ["DISCORD_TOKEN"] = "dummy"
os.environ["GEMINI_API_KEY"] = "dummy-key-for-testing"

class TestSlashCommands:
    """Test suite for slash commands."""
    
    def setup_method(self):
        """Set up test environment before each test."""
        # Mock Discord objects
        self.mock_guild = Mock()
        self.mock_guild.id = 123456789
        self.mock_guild.name = "Test Guild"
        self.mock_guild.get_member = Mock(return_value=None)
        
        self.mock_user = Mock()
        self.mock_user.id = 987654321
        self.mock_user.display_name = "TestUser"
        
        self.mock_interaction = Mock()
        self.mock_interaction.guild = self.mock_guild
        self.mock_interaction.user = self.mock_user
        self.mock_interaction.response = Mock()
        self.mock_interaction.response.is_done.return_value = False
        self.mock_interaction.response.send_message = AsyncMock()
        self.mock_interaction.followup = Mock()
        self.mock_interaction.followup.send = AsyncMock()
        self.mock_interaction.channel = Mock()
        self.mock_interaction.channel.send = AsyncMock()
        
        # Mock database responses
        self.sample_progress_data = [
            {
                'playtime_hours': 25.5,
                'completion_percent': 75.0,
                'geo': 5000,
                'health': 8,
                'max_health': 9,
                'deaths': 15,
                'scene': 'Crossroads',
                'zone': 'Forgotten Crossroads',
                'nail_upgrades': 2,
                'soul_vessels': 2,
                'mask_shards': 3,
                'charms_owned': 12,
                'bosses_defeated': 8,
                'bosses_defeated_list': '["False Knight", "Hornet"]',
                'charms_list': '["Wayward Compass", "Gathering Swarm"]',
                'ts': int(time.time()) - 3600,  # 1 hour ago
                'created_at': '2024-01-01 12:00:00'
            }
        ]
        
        self.sample_progress_data_with_nones = [
            {
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
                'bosses_defeated_list': None,
                'charms_list': None,
                'ts': int(time.time()) - 3600,
                'created_at': '2024-01-01 12:00:00'
            }
        ]

    @patch('core.database.get_player_progress_history')
    @patch('core.main.validate_guild_id')
    @patch('core.main.validate_user_id')
    def test_slash_progress_check_with_valid_data(self, mock_validate_user, mock_validate_guild, mock_get_progress):
        """Test slash_progress_check with valid data."""
        from core.main import slash_progress_check
        
        # Setup mocks
        mock_get_progress.return_value = self.sample_progress_data
        
        # Run the function (it's a decorated command, so we need to call it directly)
        import asyncio
        asyncio.run(slash_progress_check.callback(self.mock_interaction, limit=1, history=False))
        
        # Verify interaction was called
        self.mock_interaction.response.send_message.assert_called_once()
        message = self.mock_interaction.response.send_message.call_args[0][0]
        
        # Check that formatting worked correctly
        assert "TestUser" in message
        assert "75.0% complete" in message
        assert "25.50 hours" in message
        assert "5,000" in message  # Formatted geo
        assert "8/9 hearts" in message
        assert "15" in message  # deaths
        assert "Crossroads" in message

    @patch('core.database.get_player_progress_history')
    @patch('core.main.validate_guild_id')
    @patch('core.main.validate_user_id')
    def test_slash_progress_check_with_none_values(self, mock_validate_user, mock_validate_guild, mock_get_progress):
        """Test slash_progress_check with None values to catch formatting errors."""
        from core.main import slash_progress_check
        
        # Setup mocks with None values
        mock_get_progress.return_value = self.sample_progress_data_with_nones
        
        # This should not raise a formatting error
        import asyncio
        asyncio.run(slash_progress_check.callback(self.mock_interaction, limit=1, history=False))
        
        # Verify interaction was called
        self.mock_interaction.response.send_message.assert_called_once()
        message = self.mock_interaction.response.send_message.call_args[0][0]
        
        # Check that None values were handled correctly
        assert "0% complete" in message
        assert "0.00 hours" in message
        assert "0" in message  # geo should be 0, not None
        assert "0/0 hearts" in message
        assert "Unknown" in message  # scene/zone should be "Unknown"

    @patch('core.database.get_player_progress_history')
    @patch('core.main.validate_guild_id')
    @patch('core.main.validate_user_id')
    def test_slash_progress_check_history_with_none_values(self, mock_validate_user, mock_validate_guild, mock_get_progress):
        """Test slash_progress_check history mode with None values."""
        from core.main import slash_progress_check
        
        # Setup mocks with None values
        mock_get_progress.return_value = self.sample_progress_data_with_nones
        
        # This should not raise a formatting error
        import asyncio
        asyncio.run(slash_progress_check.callback(self.mock_interaction, limit=1, history=True))
        
        # Verify interaction was called
        self.mock_interaction.response.send_message.assert_called_once()
        message = self.mock_interaction.response.send_message.call_args[0][0]
        
        # Check that None values were handled correctly in history format
        assert "0% complete" in message
        assert "0.0h" in message  # history format
        assert "0 geo" in message
        assert "0/0 hearts" in message
        assert "Unknown" in message

    @patch('core.database.get_player_progress_history')
    @patch('core.main.validate_guild_id')
    @patch('core.main.validate_user_id')
    def test_slash_progress_check_no_data(self, mock_validate_user, mock_validate_guild, mock_get_progress):
        """Test slash_progress_check when no data exists."""
        from core.main import slash_progress_check
        
        # Setup mocks with no data
        mock_get_progress.return_value = []
        
        import asyncio
        asyncio.run(slash_progress_check.callback(self.mock_interaction, limit=1, history=False))
        
        # Verify interaction was called with no data message
        self.mock_interaction.response.send_message.assert_called_once()
        message = self.mock_interaction.response.send_message.call_args[0][0]
        
        assert "No save data recorded" in message
        assert "TestUser" in message

    @patch('core.database.get_player_progress_history')
    @patch('core.main.validate_guild_id')
    @patch('core.main.validate_user_id')
    def test_slash_progress_check_invalid_limit(self, mock_validate_user, mock_validate_guild, mock_get_progress):
        """Test slash_progress_check with invalid limit values."""
        from core.main import slash_progress_check
        
        # Test limit too high
        import asyncio
        asyncio.run(slash_progress_check.callback(self.mock_interaction, limit=25, history=False))
        
        # Should send error message
        self.mock_interaction.response.send_message.assert_called_once()
        message = self.mock_interaction.response.send_message.call_args[0][0]
        assert "Limit must be between 1 and 20" in message

    @patch('core.database.get_player_progress_history')
    @patch('core.validation.validate_guild_id')
    @patch('core.validation.validate_user_id')
    def test_slash_progress_check_no_guild(self, mock_validate_user, mock_validate_guild, mock_get_progress):
        """Test slash_progress_check when no guild is present."""
        from core.main import slash_progress_check
        
        # Setup interaction without guild
        self.mock_interaction.guild = None
        
        import asyncio
        asyncio.run(slash_progress_check.callback(self.mock_interaction, limit=1, history=False))
        
        # Should send error message
        self.mock_interaction.response.send_message.assert_called_once()
        message = self.mock_interaction.response.send_message.call_args[0][0]
        assert "only works in servers" in message

    @patch('core.database.add_update')
    @patch('core.database.get_last_update')
    @patch('core.main.validate_guild_id')
    @patch('core.main.validate_user_id')
    @patch('core.main.validate_progress_text')
    @patch('core.main._build_progress_reply')
    def test_slash_record_valid_input(self, mock_build_reply, mock_validate_text, mock_validate_user, 
                                    mock_validate_guild, mock_get_last, mock_add_update):
        """Test slash_record with valid input."""
        from core.main import slash_record
        
        # Setup mocks
        mock_validate_text.return_value = "Beat the Mantis Lords"
        mock_get_last.return_value = None
        mock_build_reply.return_value = "Nice work, gamer!"
        
        import asyncio
        asyncio.run(slash_record.callback(self.mock_interaction, "Beat the Mantis Lords"))
        
        # Verify database was called
        mock_add_update.assert_called_once()
        mock_validate_text.assert_called_once_with("Beat the Mantis Lords")
        
        # Verify response was sent
        self.mock_interaction.response.send_message.assert_called_once()
        message = self.mock_interaction.response.send_message.call_args[0][0]
        assert "Nice work, gamer!" in message

    @patch('core.database.add_update')
    @patch('core.database.get_last_update')
    @patch('core.main.validate_guild_id')
    @patch('core.main.validate_user_id')
    @patch('core.main.validate_progress_text')
    @patch('core.main._build_progress_reply')
    def test_slash_record_validation_error(self, mock_build_reply, mock_validate_text, mock_validate_user, 
                                         mock_validate_guild, mock_get_last, mock_add_update):
        """Test slash_record with validation error."""
        from core.main import slash_record
        from core.validation import ValidationError
        
        # Setup mocks to raise validation error
        mock_validate_text.side_effect = ValidationError("Invalid text")
        
        import asyncio
        asyncio.run(slash_record.callback(self.mock_interaction, ""))
        
        # Should send error message
        self.mock_interaction.response.send_message.assert_called_once()
        message = self.mock_interaction.response.send_message.call_args[0][0]
        assert "corrupted by the Infection" in message

    @patch('core.database.add_update')
    @patch('core.database.get_last_update')
    @patch('core.main.validate_guild_id')
    @patch('core.main.validate_user_id')
    @patch('core.main.validate_progress_text')
    @patch('core.main._build_progress_reply')
    def test_slash_record_database_error(self, mock_build_reply, mock_validate_text, mock_validate_user, 
                                       mock_validate_guild, mock_get_last, mock_add_update):
        """Test slash_record with database error."""
        from core.main import slash_record
        from core.database import DatabaseError
        
        # Setup mocks
        mock_validate_text.return_value = "Beat the Mantis Lords"
        mock_add_update.side_effect = DatabaseError("Database connection failed")
        
        import asyncio
        asyncio.run(slash_record.callback(self.mock_interaction, "Beat the Mantis Lords"))
        
        # Should send error message
        self.mock_interaction.response.send_message.assert_called_once()
        message = self.mock_interaction.response.send_message.call_args[0][0]
        assert "trouble reaching the chronicle" in message

    def test_progress_data_formatting_edge_cases(self):
        """Test various edge cases for progress data formatting."""
        from core.main import slash_progress_check
        
        # Test data with mixed None and valid values
        mixed_data = [
            {
                'playtime_hours': 10.5,
                'completion_percent': None,
                'geo': 0,
                'health': 5,
                'max_health': None,
                'deaths': 0,
                'scene': '',
                'zone': None,
                'nail_upgrades': 1,
                'soul_vessels': None,
                'mask_shards': 0,
                'charms_owned': None,
                'bosses_defeated': 0,
                'bosses_defeated_list': None,
                'charms_list': None,
                'ts': int(time.time()) - 3600,
                'created_at': '2024-01-01 12:00:00'
            }
        ]
        
        with patch('core.database.get_player_progress_history', return_value=mixed_data):
            with patch('core.main.validate_guild_id'):
                with patch('core.main.validate_user_id'):
                    import asyncio
                    asyncio.run(slash_progress_check.callback(self.mock_interaction, limit=1, history=False))
                    
                    # Should not raise any formatting errors
                    self.mock_interaction.response.send_message.assert_called_once()
                    message = self.mock_interaction.response.send_message.call_args[0][0]
                    
                    # Check specific formatting
                    assert "10.50 hours" in message
                    assert "0% complete" in message  # None -> 0
                    assert "0" in message  # geo: 0
                    assert "5/0 hearts" in message  # health: 5, max_health: None -> 0
                    assert "0" in message  # deaths: 0
                    assert "Unknown" in message  # empty scene -> Unknown

    @patch('core.database.get_game_stats_leaderboard')
    def test_slash_leaderboard_with_data(self, mock_get_stats):
        """Test slash_leaderboard with sample data."""
        from core.main import slash_leaderboard

        mock_get_stats.return_value = [
            (111, 80.0, 50.0, 10, 1000, 5, 3, 20)
        ]

        import asyncio
        asyncio.run(slash_leaderboard.callback(self.mock_interaction))

        self.mock_interaction.response.send_message.assert_called_once()
        message = self.mock_interaction.response.send_message.call_args[0][0]
        assert "Hallownest Game Stats Leaderboard" in message
        assert "User 111" in message

    @patch('core.database.get_game_stats_leaderboard')
    def test_slash_leaderboard_no_data(self, mock_get_stats):
        """Test slash_leaderboard when no stats are available."""
        from core.main import slash_leaderboard

        mock_get_stats.return_value = []

        import asyncio
        asyncio.run(slash_leaderboard.callback(self.mock_interaction))

        self.mock_interaction.response.send_message.assert_called_once()
        message = self.mock_interaction.response.send_message.call_args[0][0]
        assert "No gamers have uploaded save data" in message

    def test_slash_info(self):
        """Test slash_info outputs bot version info."""
        from core.main import slash_info, BOT_VERSION

        import asyncio
        asyncio.run(slash_info.callback(self.mock_interaction))

        self.mock_interaction.response.send_message.assert_called_once()
        message = self.mock_interaction.response.send_message.call_args[0][0]
        assert f"HollowBot v{BOT_VERSION}" in message


def run_tests():
    """Run all slash command tests."""
    print("🧪 Testing Slash Commands")
    print("=" * 40)
    
    test_instance = TestSlashCommands()
    tests = [
        test_instance.test_slash_progress_check_with_valid_data,
        test_instance.test_slash_progress_check_with_none_values,
        test_instance.test_slash_progress_check_history_with_none_values,
        test_instance.test_slash_progress_check_no_data,
        test_instance.test_slash_progress_check_invalid_limit,
        test_instance.test_slash_progress_check_no_guild,
        test_instance.test_slash_record_valid_input,
        test_instance.test_slash_record_validation_error,
        test_instance.test_slash_record_database_error,
        test_instance.test_progress_data_formatting_edge_cases,
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        try:
            test_instance.setup_method()
            test()
            print(f"✅ {test.__name__}")
            passed += 1
        except Exception as e:
            print(f"❌ {test.__name__}: {e}")
    
    print("=" * 40)
    print(f"Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All slash command tests passed!")
        return 0
    else:
        print("❌ Some tests failed. Check the issues above.")
        return 1


if __name__ == "__main__":
    sys.exit(run_tests())
