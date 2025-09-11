#!/usr/bin/env python3
"""Hollow Knight Discord Bot - Main entry point."""

import asyncio
import sys
import os

# Add the src directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from core.main import main


if __name__ == "__main__":
    asyncio.run(main())
