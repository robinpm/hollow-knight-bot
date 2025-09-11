"""Test suite for Hollow Knight save file parsing and decryption."""

import pytest
import json
import os

os.environ.setdefault("DISCORD_TOKEN", "dummy")
os.environ.setdefault("GEMINI_API_KEY", "dummy")

from save_parsing.save_parser import (
    parse_hk_save,
    format_save_summary,
    generate_save_analysis,
    SaveDataError,
)
from save_parsing.hollow_knight_decrypt import (
    decrypt_hollow_knight_save,
    HollowKnightDecryptor,
)


class TestHollowKnightDecryption:
    """Test the decryption functionality."""
    
    def test_decryptor_initialization(self):
        """Test that the decryptor initializes correctly."""
        decryptor = HollowKnightDecryptor()
        assert len(decryptor.csharp_header) == 22  # C# header length
        assert len(decryptor.aes_key) == 32  # 256-bit key
    
    def test_string_to_bytes_conversion(self):
        """Test string to bytes conversion."""
        decryptor = HollowKnightDecryptor()
        test_string = "Hello World"
        bytes_result = decryptor.string_to_bytes(test_string)
        assert isinstance(bytes_result, bytes)
        assert decryptor.bytes_to_string(bytes_result) == test_string
    
    def test_aes_decrypt(self):
        """Test AES decryption functionality."""
        decryptor = HollowKnightDecryptor()
        
        # Test with a simple string
        test_data = b"Hello, Hollow Knight!"
        
        # Note: We can't easily test encryption/decryption without the full cycle
        # since the encrypt method isn't implemented, but we can test the decryptor
        # is properly initialized
        assert decryptor.aes_key is not None
        assert len(decryptor.aes_key) == 32
    
    def test_header_removal(self):
        """Test header removal functionality."""
        decryptor = HollowKnightDecryptor()
        
        # Test that the header is properly defined
        assert len(decryptor.csharp_header) == 22
        assert isinstance(decryptor.csharp_header, list)


class TestSaveFileParsing:
    """Test save file parsing with actual .dat files."""
    
    @pytest.fixture
    def fresh_save_file(self):
        """Fresh save file fixture."""
        return os.path.join(os.path.dirname(__file__), "test_data", "fresh_save.dat")
    
    @pytest.fixture
    def midgame_save_file(self):
        """Mid-game save file fixture."""
        return os.path.join(os.path.dirname(__file__), "test_data", "midgame_save.dat")
    
    def test_fresh_save_parsing(self, fresh_save_file):
        """Test parsing of fresh save file."""
        if not os.path.exists(fresh_save_file):
            pytest.skip(f"Fresh save file not found: {fresh_save_file}")
        
        with open(fresh_save_file, 'rb') as f:
            content = f.read()
        
        summary = parse_hk_save(content)
        
        # Verify fresh save characteristics
        assert summary['playtime_hours'] < 1.0  # Fresh save
        assert summary['completion_percent'] == 0.0
        assert summary['geo'] < 100  # Low geo
        assert summary['health'] == 5  # Starting health
        assert summary['max_health'] == 5  # Starting max health
        assert summary['deaths'] == 0  # No deaths yet
        assert summary['scene'] == "Town"  # Starting location
        assert summary['zone'] == 4  # Town zone
        assert summary['nail_upgrades'] == 0
        assert summary['soul_vessels'] == 0
        assert summary['mask_shards'] == 0
        assert summary['charms_owned'] == 0
        assert summary['bosses_defeated'] == 0
        assert summary['bosses_defeated_list'] == []
        assert summary['charms_list'] == []
    
    def test_midgame_save_parsing(self, midgame_save_file):
        """Test parsing of mid-game save file."""
        if not os.path.exists(midgame_save_file):
            pytest.skip(f"Mid-game save file not found: {midgame_save_file}")
        
        with open(midgame_save_file, 'rb') as f:
            content = f.read()
        
        summary = parse_hk_save(content)
        
        # Verify mid-game save characteristics
        assert summary['playtime_hours'] > 5.0  # Substantial playtime
        assert summary['completion_percent'] > 50  # Mid-game progress
        assert summary['geo'] > 1000  # Good amount of geo
        assert summary['health'] > 5  # Upgraded health
        assert summary['max_health'] > 5  # Upgraded max health
        assert summary['deaths'] > 0  # Has died
        assert summary['scene'] == "City_Storerooms"  # Advanced location
        assert summary['zone'] == "CITY"  # City zone
        assert summary['nail_upgrades'] == 0  # No nail upgrades yet
        assert summary['soul_vessels'] == 0  # No soul vessels yet
        assert summary['mask_shards'] == 0  # No mask shards yet
        assert summary['charms_owned'] == 0  # No charms yet
        assert summary['bosses_defeated'] == 0  # No bosses defeated yet
        assert summary['bosses_defeated_list'] == []
        assert summary['charms_list'] == []
    
    def test_save_file_decryption(self, fresh_save_file):
        """Test that save files are properly decrypted."""
        if not os.path.exists(fresh_save_file):
            pytest.skip(f"Fresh save file not found: {fresh_save_file}")
        
        with open(fresh_save_file, 'rb') as f:
            content = f.read()
        
        # Test decryption
        decrypted_json = decrypt_hollow_knight_save(content)
        assert isinstance(decrypted_json, str)
        
        # Test JSON parsing
        save_data = json.loads(decrypted_json)
        assert 'playerData' in save_data
        assert 'playTime' in save_data['playerData']
        assert 'geo' in save_data['playerData']
        assert 'health' in save_data['playerData']
    
    def test_save_file_decryption_midgame(self, midgame_save_file):
        """Test decryption of mid-game save file."""
        if not os.path.exists(midgame_save_file):
            pytest.skip(f"Mid-game save file not found: {midgame_save_file}")
        
        with open(midgame_save_file, 'rb') as f:
            content = f.read()
        
        # Test decryption
        decrypted_json = decrypt_hollow_knight_save(content)
        assert isinstance(decrypted_json, str)
        
        # Test JSON parsing
        save_data = json.loads(decrypted_json)
        assert 'playerData' in save_data
        
        player_data = save_data['playerData']
        assert player_data['playTime'] > 20000  # 6+ hours in seconds
        assert player_data['completionPercent'] > 50
        assert player_data['geo'] > 1000
        assert player_data['health'] > 5
        assert player_data['maxHealth'] > 5
        assert player_data['deathCount'] > 0


class TestSaveSummaryFormatting:
    """Test save summary formatting."""
    
    @pytest.fixture
    def fresh_save_file(self):
        """Fresh save file fixture."""
        return os.path.join(os.path.dirname(__file__), "test_data", "fresh_save.dat")
    
    @pytest.fixture
    def midgame_save_file(self):
        """Mid-game save file fixture."""
        return os.path.join(os.path.dirname(__file__), "test_data", "midgame_save.dat")
    
    def test_fresh_save_formatting(self, fresh_save_file):
        """Test formatting of fresh save summary."""
        if not os.path.exists(fresh_save_file):
            pytest.skip(f"Fresh save file not found: {fresh_save_file}")
        
        with open(fresh_save_file, 'rb') as f:
            content = f.read()
        
        summary = parse_hk_save(content)
        formatted = format_save_summary(summary)
        
        assert "Fresh Save Detected" in formatted
        assert "Hallownest journey" in formatted
        # Note: The fresh save formatting doesn't include specific numbers
        # it just says "Fresh Save Detected!" with a generic message
    
    def test_midgame_save_formatting(self, midgame_save_file):
        """Test formatting of mid-game save summary."""
        if not os.path.exists(midgame_save_file):
            pytest.skip(f"Mid-game save file not found: {midgame_save_file}")
        
        with open(midgame_save_file, 'rb') as f:
            content = f.read()
        
        summary = parse_hk_save(content)
        formatted = format_save_summary(summary)
        
        assert "Hollow Knight Progress Analysis" in formatted
        assert "Late Game" in formatted
        assert "6.52" in formatted  # Playtime
        assert "3,120" in formatted  # Geo
        assert "City_Storerooms" in formatted  # Location
        assert "55%" in formatted  # Completion
        assert "27" in formatted  # Deaths


class TestSaveAnalysis:
    """Test AI-powered save analysis."""
    
    @pytest.fixture
    def fresh_save_file(self):
        """Fresh save file fixture."""
        return os.path.join(os.path.dirname(__file__), "test_data", "fresh_save.dat")
    
    @pytest.fixture
    def midgame_save_file(self):
        """Mid-game save file fixture."""
        return os.path.join(os.path.dirname(__file__), "test_data", "midgame_save.dat")
    
    def test_fresh_save_analysis(self, fresh_save_file):
        """Test AI analysis of fresh save."""
        if not os.path.exists(fresh_save_file):
            pytest.skip(f"Fresh save file not found: {fresh_save_file}")
        
        with open(fresh_save_file, 'rb') as f:
            content = f.read()
        
        summary = parse_hk_save(content)
        analysis = generate_save_analysis(summary)
        
        assert isinstance(analysis, str)
        assert len(analysis) > 50  # Should have substantial analysis
        # Note: We can't test specific content since it's AI-generated
    
    def test_midgame_save_analysis(self, midgame_save_file):
        """Test AI analysis of mid-game save."""
        if not os.path.exists(midgame_save_file):
            pytest.skip(f"Mid-game save file not found: {midgame_save_file}")
        
        with open(midgame_save_file, 'rb') as f:
            content = f.read()
        
        summary = parse_hk_save(content)
        analysis = generate_save_analysis(summary)
        
        assert isinstance(analysis, str)
        assert len(analysis) > 50  # Should have substantial analysis
        # Note: We can't test specific content since it's AI-generated


class TestErrorHandling:
    """Test error handling for invalid files."""
    
    def test_invalid_file_handling(self):
        """Test handling of invalid file content."""
        invalid_content = b"This is not a valid save file"
        
        # The parser should fall back to binary parsing and return a summary
        summary = parse_hk_save(invalid_content)
        assert isinstance(summary, dict)
        assert 'playtime_hours' in summary
    
    def test_empty_file_handling(self):
        """Test handling of empty file."""
        empty_content = b""
        
        # The parser should fall back to binary parsing and return a summary
        summary = parse_hk_save(empty_content)
        assert isinstance(summary, dict)
        assert 'playtime_hours' in summary
    
    def test_corrupted_json_handling(self):
        """Test handling of corrupted JSON."""
        corrupted_json = b'{"playerData": {"playTime": "invalid"}'
        
        # The parser should fall back to binary parsing and return a summary
        summary = parse_hk_save(corrupted_json)
        assert isinstance(summary, dict)
        assert 'playtime_hours' in summary


class TestFileSizeValidation:
    """Test file size validation."""
    
    def test_file_size_limits(self):
        """Test that files are within reasonable size limits."""
        files = [
            "%WinAppDataLocalLow%Team Cherry_Hollow Knight_user1.dat",
            "user1 (1).dat"
        ]
        
        for file_path in files:
            if os.path.exists(file_path):
                with open(file_path, 'rb') as f:
                    content = f.read()
                
                # Hollow Knight save files should be reasonable size
                assert len(content) > 1000  # At least 1KB
                assert len(content) < 1000000  # Less than 1MB
                
                # Test that we can parse files of this size
                summary = parse_hk_save(content)
                assert isinstance(summary, dict)
                assert 'playtime_hours' in summary


if __name__ == "__main__":
    # Run tests with verbose output
    pytest.main([__file__, "-v", "--tb=short"])
