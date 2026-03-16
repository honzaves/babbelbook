#!/usr/bin/env python3
"""
organize_books.py — entry point.

Usage:
  python organize_books.py               # live run
  python organize_books.py --dry-run     # preview only, no files copied
  python organize_books.py --workers 8   # tune concurrency (default: 6)
"""

import sys

from config import (
    BOOKS_DIR, ORGANIZED_DIR,
    EBOOKLIB_OK, PYMUPDF_OK, MOBI_OK, ISBNLIB_OK, LANGDETECT_OK,
    OLLAMA_THRESHOLD, UNCERTAIN_THRESHOLD, OLLAMA_BASE_URL, OLLAMA_MODEL,
    DEFAULT_WORKERS,
)
from organizer.enrichment import check_ollama
from organizer.organizer import scan_and_organize


def main():
    dry_run = "--dry-run" in sys.argv or "-n" in sys.argv

    workers = DEFAULT_WORKERS
    if "--workers" in sys.argv:
        idx = sys.argv.index("--workers")
        try:
            workers = int(sys.argv[idx + 1])
        except (IndexError, ValueError):
            print("  WARNING: --workers requires a number, using default.")

    print("=" * 65)
    print("  Babbelbook")
    print(f"  Source : {BOOKS_DIR}")
    print(f"  Target : {ORGANIZED_DIR}")
    print(f"  Mode   : {'DRY-RUN' if dry_run else 'LIVE'}")
    print(f"  Ollama threshold      : {OLLAMA_THRESHOLD}/100  (model: {OLLAMA_MODEL})")
    print(f"  Ollama URL            : {OLLAMA_BASE_URL}")
    print(f"  Uncertain threshold   : {UNCERTAIN_THRESHOLD}/100")
    print(f"  Concurrent workers    : {workers}")
    print("=" * 65)

    deps = {
        "ebooklib  (epub)":       EBOOKLIB_OK,
        "pymupdf   (pdf)":        PYMUPDF_OK,
        "mobi      (mobi/azw)":   MOBI_OK,
        "isbnlib   (ISBN lookup)": ISBNLIB_OK,
        "langdetect(language)":   LANGDETECT_OK,
    }
    missing = [n for n, ok in deps.items() if not ok]
    if missing:
        print("\n  Missing packages:")
        for n in missing:
            print(f"   pip install {n.split()[0]}")
        print()
    else:
        print("\n  All packages available.\n")

    print(f"  Checking Ollama at {OLLAMA_BASE_URL} ...")
    if check_ollama():
        print(f"  Ollama OK -- model '{OLLAMA_MODEL}' is ready.\n")
    else:
        print("  Ollama unavailable -- LLM classification will be skipped.\n")

    scan_and_organize(dry_run=dry_run, workers=workers)


if __name__ == "__main__":
    main()
