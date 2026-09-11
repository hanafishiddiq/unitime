"""Pytest configuration and environment fixtures for UniTime AI Gateway."""

from __future__ import annotations

import sys
from pathlib import Path

# Add ai-gateway root to sys.path
GATEWAY_DIR = Path(__file__).resolve().parent.parent
if str(GATEWAY_DIR) not in sys.path:
    sys.path.insert(0, str(GATEWAY_DIR))
