#!/usr/bin/env python3
"""
run_tests.py — discover and run the full test suite.

Usage:
    python run_tests.py              # all tests
    python run_tests.py unit         # unit tests only
    python run_tests.py integration  # integration tests only
    python run_tests.py -v           # verbose
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

def main():
    args = sys.argv[1:]
    verbosity = 2 if "-v" in args else 1
    args = [a for a in args if a != "-v"]

    suite = unittest.TestSuite()
    loader = unittest.TestLoader()

    if not args or args[0] == "unit":
        suite.addTests(loader.discover(str(ROOT / "tests" / "unit"), pattern="test_*.py"))
    if not args or args[0] == "integration":
        suite.addTests(loader.discover(str(ROOT / "tests" / "integration"), pattern="test_*.py"))

    runner = unittest.TextTestRunner(verbosity=verbosity, buffer=True)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)

if __name__ == "__main__":
    main()
