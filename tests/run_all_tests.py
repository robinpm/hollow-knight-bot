#!/usr/bin/env python3
"""Run all tests for the Hollow Knight bot."""

import os
import sys
import subprocess

def run_test_file(test_file):
    """Run a specific test file and return the exit code."""
    print(f"\n🧪 Running {test_file}...")
    print("-" * 50)
    
    try:
        result = subprocess.run([sys.executable, test_file], 
                              capture_output=False, 
                              text=True, 
                              cwd=os.path.dirname(__file__))
        return result.returncode
    except Exception as e:
        print(f"❌ Failed to run {test_file}: {e}")
        return 1

def main():
    """Run all test files."""
    print("🚀 Hollow Knight Bot - Complete Test Suite")
    print("=" * 60)
    
    # List of test files to run
    test_files = [
        "test_bot.py",
        "test_slash_commands_simple.py",
        "test_formatting.py",
        "test_save_parser.py"
    ]
    
    total_tests = len(test_files)
    passed_tests = 0
    failed_tests = []
    
    for test_file in test_files:
        test_path = os.path.join(os.path.dirname(__file__), test_file)
        if os.path.exists(test_path):
            exit_code = run_test_file(test_path)
            if exit_code == 0:
                passed_tests += 1
                print(f"✅ {test_file} PASSED")
            else:
                failed_tests.append(test_file)
                print(f"❌ {test_file} FAILED")
        else:
            print(f"⚠️  {test_file} not found, skipping...")
    
    print("\n" + "=" * 60)
    print(f"📊 FINAL RESULTS: {passed_tests}/{total_tests} test suites passed")
    
    if failed_tests:
        print(f"❌ Failed tests: {', '.join(failed_tests)}")
        return 1
    else:
        print("🎉 All test suites passed!")
        return 0

if __name__ == "__main__":
    sys.exit(main())
