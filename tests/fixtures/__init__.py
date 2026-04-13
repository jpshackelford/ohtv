"""Test fixtures package.

This package contains:
- Sample conversation data (JSON files in conversations/)
- Factory functions for creating test data
- Builders for complex test scenarios
"""

from pathlib import Path

FIXTURES_DIR = Path(__file__).parent
CONVERSATIONS_DIR = FIXTURES_DIR / "conversations"
