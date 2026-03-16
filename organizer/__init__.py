"""
organizer — book scanning, classification and file-organisation package.

This __init__ ensures the project root (which contains config.py) is on
sys.path so every submodule can do ``from config import …`` without needing
its own path-manipulation block.
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
