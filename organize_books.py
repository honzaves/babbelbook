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
    LLM_THRESHOLD, UNCERTAIN_THRESHOLD,
    LLM_BACKEND, MLX_MODEL, OLLAMA_BASE_URL, OLLAMA_MODEL,
    DEFAULT_WORKERS,
)
from organizer.enrichment import check_llm_backend
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
    model = MLX_MODEL if LLM_BACKEND == "mlx" else OLLAMA_MODEL
    print(f"  LLM backend           : {LLM_BACKEND}  (model: {model})")
    print(f"  LLM threshold         : {LLM_THRESHOLD}/100")
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

    print(f"  Checking LLM backend '{LLM_BACKEND}' ...")
    if check_llm_backend():
        print(f"  LLM OK -- backend '{LLM_BACKEND}' is ready.\n")
    elif LLM_BACKEND == "mlx":
        print("  Aborting: the mlx backend is configured but unavailable.")
        print("  Set BABBELBOOK_LLM_BACKEND=ollama to use Ollama instead.")
        sys.exit(1)
    else:
        print(f"  Ollama unavailable at {OLLAMA_BASE_URL} -- "
              "LLM classification will be skipped.\n")

    scan_and_organize(dry_run=dry_run, workers=workers)


if __name__ == "__main__":
    main()
