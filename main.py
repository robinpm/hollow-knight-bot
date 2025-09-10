#!/usr/bin/env python3
"""Hollow Knight Discord Bot - Main Entry Point"""

import sys
import os
import asyncio

# Add src directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Import and run the main bot
from src.core.main import main

if __name__ == "__main__":
    asyncio.run(main())
