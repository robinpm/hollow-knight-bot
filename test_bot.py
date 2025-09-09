#!/usr/bin/env python3
"""Simple test script to verify bot components work."""

import os
import sys

def test_imports():
    """Test that all modules can be imported."""
    print("Testing imports...")
    
    try:
        import config
        print("✅ config imported")
    except Exception as e:
        print(f"❌ config import failed: {e}")
        return False
    
    try:
        import logger
        print("✅ logger imported")
    except Exception as e:
        print(f"❌ logger import failed: {e}")
        return False
    
    try:
        import validation
        print("✅ validation imported")
    except Exception as e:
        print(f"❌ validation import failed: {e}")
        return False
    
    try:
        import database
        print("✅ database imported")
    except Exception as e:
        print(f"❌ database import failed: {e}")
        return False
    
    try:
        import gemini_integration
        print("✅ gemini_integration imported")
    except Exception as e:
        print(f"❌ gemini_integration import failed: {e}")
        return False
    
    try:
        from langchain import chain
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
        import config
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
        from validation import validate_progress_text, validate_time_format
        
        # Test valid inputs
        result = validate_progress_text("Beat the Mantis Lords!")
        print(f"✅ Valid progress text: {result}")
        
        result = validate_time_format("18:30")
        print(f"✅ Valid time format: {result}")
        
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
        
        return True
    except Exception as e:
        print(f"❌ Validation test failed: {e}")
        return False

def main():
    """Run all tests."""
    print("🧪 Hollow Knight Bot Test Suite")
    print("=" * 40)
    
    tests = [
        test_imports,
        test_config,
        test_validation,
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
