# CLAUDE.md — Babbelbook Developer Guide

## What This App Does

Babbelbook is a personal e-book library manager with two front-ends:

- **`babbelbook_flet.py`** — a standalone Flet desktop GUI with direct SQLite access. The primary UI.
- **`book_browser.py`** — a Flask web UI (port 5000) with identical read/write functionality via REST API.

Both share the same database (`books_organized/.cache.db`) written by the organiser.

Supporting tools:
- **`organize_books.py`** — scans source folders, classifies books via metadata extraction, external APIs (Google Books, Open Library, isbnlib) and a local LLM (Ollama), then copies each book into a structured library under `~/Documents/Books/books_organized/`.
- **`deduplicate_books.py`** — standalone CLI for detecting/removing `_(N)` duplicate files.
- **`repair_db.py`** — reconciles the database against the filesystem: removes stale DB rows (file gone from disk) and stages orphan files (file on disk but not in DB) in `BOOKS_DIR/___to_reprocess/` for re-ingestion.
- **`config.py`** — the single source of truth for all paths, thresholds, category maps and genre keywords.

---

## Project Layout

```
babbelbook/
├── babbelbook_flet.py      ← Flet desktop app (monolithic, ~1900 lines)
├── book_browser.py         ← Flask browser entry point
├── organize_books.py       ← Organiser entry point
├── deduplicate_books.py    ← Dedup CLI
├── repair_db.py            ← DB / filesystem reconciliation (stale rows + orphan files)
├── config.py               ← All paths, thresholds, category maps, genre keywords
├── run_tests.py            ← Test runner (stdlib unittest)
│
├── organizer/
│   ├── cache.py            ← SQLite helpers: books table + API cache table
│   ├── classifier.py       ← BookMeta dataclass, genre/language detection, resolve()
│   ├── enrichment.py       ← Google Books, Open Library, isbnlib, Ollama
│   ├── extractors.py       ← epub/pdf/mobi metadata extraction
│   └── organizer.py        ← File copy, flatten, CSV logging, summary
│
└── browser/
    ├── db.py               ← Browser-side SQLite helpers + MAIN_DIRS set
    ├── routes_read.py      ← Blueprint: all GET /api/* endpoints
    ├── routes_write.py     ← Blueprint: all mutating endpoints (DELETE, PATCH, POST)
    ├── query_cache.py      ← Standalone CLI cache inspector
    └── ui/
        ├── layout.py       ← HTML shell (assembles CSS + JS)
        ├── style.py        ← All CSS
        └── script.py       ← All JavaScript
```

---

## Database Schema (`books_organized/.cache.db`)

### `books` table

| Column | Type | Notes |
|---|---|---|
| `original_path` | TEXT PK | Absolute path of source file |
| `title` | TEXT | |
| `author` | TEXT | Normalised (Firstname Lastname) |
| `language` | TEXT | e.g. `english` |
| `genres` | TEXT | JSON array |
| `directory` | TEXT | Top-level category folder |
| `relative_path` | TEXT | Relative to `ORGANIZED_DIR` |
| `confidence` | INTEGER | 0–100 |
| `sources` | TEXT | Pipe-separated source list |
| `file_size_bytes` | INTEGER | Not always populated |
| `ts` | INTEGER | Unix timestamp |

### `cache` table

| Column | Type | Notes |
|---|---|---|
| `key` | TEXT PK | Prefixed: `gb:`, `ol:`, `isbn:`, `ollama:` |
| `val` | TEXT | JSON-encoded result |
| `ts` | INTEGER | Unix timestamp |

---

## Key Design Rules

1. **`config.py` is the single source of truth.** All paths, thresholds, category names and genre maps live here. No other file defines these values. Everything imports from `config`. This includes `REPROCESS_DIR` — the staging folder used by `repair_db.py`.

2. **`MAIN_CATEGORIES` (config.py) and `MAIN_DIRS` (browser/db.py) must always be kept in sync.** `MAIN_CATEGORIES` controls where the organiser copies files; `MAIN_DIRS` controls what the browser's Directory dropdown shows.

3. **The last entry in `MAIN_CATEGORIES` is always the fallback** (currently `"other"`). Books that don't match any genre mapping land here.

4. **Original files are never moved or deleted.** The organiser only copies. Your source library is always intact.

5. **`babbelbook_flet.py` mirrors `browser/routes_write.py` exactly** for all write operations (rename author, move directory, delete, merge authors). When fixing a bug in one, check whether the same bug exists in the other.

6. **The Flask `browser/` package is the ground truth** when debugging regressions. If `babbelbook_flet.py` produces a different result for the same operation, the Flask implementation defines the correct behaviour.

---

## babbelbook_flet.py Architecture

The app is a single file, roughly divided into:

### Constants and colours (lines ~26–75)

`DB_PATH`, `ORGANIZED_DIR`, `PAGE_SIZE`, `MAIN_CATEGORIES`, `DIR_ICONS`, `LANG_FLAGS`, and the colour palette used throughout the UI.

### DB helpers (lines ~77–125)

- `_db()` — opens a new SQLite connection; returns `None` if `DB_PATH` does not exist.
- `_fmt_ts(ts)` — formats a Unix timestamp as `"Today HH:MM"`, `"Yesterday HH:MM"` or `"DD Mon YYYY"`.
- `_row_to_dict(row)` — converts a `sqlite3.Row` to a dict, JSON-decoding `genres`.
- `_file_size(rel)` — returns the on-disk size of a relative path.
- `_fmt_size(n)` — formats bytes as `"1.2 MB"` etc.

### Write helpers (lines ~127–160)

- `_sanitize(name)` — strips filesystem-illegal characters, collapses whitespace. Returns `"Unknown"` for empty input.
- `_move_book(old_rel, new_rel)` — moves a file and updates the DB row atomically. Handles the case where source and destination are the same path.

### Author merge (lines ~160–310)

`_merge_authors(source, target, organized_dir)` — the most complex write operation. Key algorithm:

1. Determine all directories where `target` already has books.
2. For each file under every `source` folder across all category directories:
   - If `target` exists in any category: move the source file to `<target_category>/<target>/<filename>`.
   - If `target` has no established home: move to the same category as the current source file.
   - Dedup by size (skip if identical file already at destination).
   - Handle name collisions with `_(N)` suffixes.
   - Update the DB row (author name + relative_path).
3. After all files are moved, remove empty source folders (including language subdirectories).

This function writes a timestamped debug log to `~/babbelbook_merge.log` at `DEBUG` level.

**Critical invariant:** a source book must always land in a category where the target author already has books, not in the category the source came from. The original bug was that cross-category sources were placed into `<source_category>/<target>/` instead of `<target_category>/<target>/`.

### UI helpers (lines ~354–428)

`_conf_color`, `_heading`, `_stat_card`, `_card`, `_genre_chip`, `_snack` — small factory functions for common UI patterns.

### BookDetailDialog (lines ~431–767)

A class encapsulating the book detail modal. Built lazily and reused across opens. Contains:
- `build()` — constructs the `ft.AlertDialog` with all editable fields.
- `open(book)` — populates fields from a book dict and calls `page.open()`.
- Genre chip helpers — add/remove chips, create new tags inline.
- Save handlers — one per field type; each calls the relevant write helper and then the caller-supplied `on_save` callback.

### BabbelApp (lines ~770–1880)

The main application class. Instantiated once and passed to `ft.app()`.

Navigation is handled by `_nav(route, **kwargs)` which stores filter state in `self._state` and calls the appropriate `_page_*` method.

Page methods:
- `_page_overview()` — stats, bar charts, top genres, recently added.
- `_page_books(**kwargs)` — search + filter + paginated book list. Accepts `q`, `genre`, `directory`, `language` kwargs.
- `_page_genres()` — genre tile grid.
- `_page_directories()` — directory tile grid.
- `_page_languages()` — language tile grid.
- `_page_duplicates()` — safe/suspicious duplicate lists with delete buttons.
- `_page_authors()` — similar-author detection, selection checkboxes, merge workflow.
- `_page_cache()` — raw cache table, searchable.

---

## Classification Pipeline (organiser)

Each book passes through these stages, stopping early when confidence is high enough:

1. Format extraction (epub/pdf/mobi)
2. ISBN extraction from text
3. isbnlib lookup
4. Google Books search
5. Open Library search
6. Language detection (langdetect)
7. Keyword scan against `GENRE_KEYWORDS`
8. Ollama LLM (if confidence < `OLLAMA_THRESHOLD = 75`)
9. Filename heuristic (last resort)

Confidence thresholds (all in `config.py`):
- `OLLAMA_THRESHOLD = 75` — below this → send to Ollama
- `UNCERTAIN_THRESHOLD = 55` — below this → flagged in summary
- `CSV_LOG_THRESHOLD = 35` — below this + `other/`/`failed/` → written to CSV

---

## repair_db.py Architecture

A standalone CLI utility — no Flask or Flet dependency. Imports settings directly from `config.py`.

### Two inconsistency classes

| Class | Definition | Fix |
|---|---|---|
| **Stale** | `relative_path` in DB does not exist on disk | Delete the DB row |
| **Orphan** | File on disk has no matching DB row | Move file to `REPROCESS_DIR` |

### Algorithm

1. Collect all `relative_path` values from the `books` table → `db_paths` (set of str).
2. Walk `ORGANIZED_DIR` recursively, collect all files with a `SUPPORTED_EXTS` extension, excluding the `___to_reprocess/` subtree → `fs_paths` (set of str).
3. `stale   = db_paths − fs_paths`
4. `orphans = fs_paths − db_paths`
5. In dry-run mode: print both lists and exit.
6. In `--fix` mode:
   - Delete all stale rows in a single transaction.
   - For each orphan: move to `REPROCESS_DIR/<filename>`, using `_(N)` suffixes to avoid collisions.
   - Exit 0 on success, 1 if any move failed.

### Why `___to_reprocess` starts with underscores

The triple-underscore prefix sorts before all letter characters, making the folder visually prominent at the top of any directory listing. It also ensures `find_orphans` never confuses already-staged files with newly-orphaned ones: the FS scan explicitly skips any path whose first component is in `_SKIP_DIRS = {"___to_reprocess"}`.

### Re-ingesting staged files

After `repair_db.py --fix` moves orphans into `REPROCESS_DIR`:

```bash
# Option A — re-run the organiser (classifies and copies back into the library)
python organize_books.py       # BOOKS_DIR is scanned, which includes ___to_reprocess

# Option B — manual inspection first
ls ~/Documents/Books/___to_reprocess/
# move files back by hand, then re-run repair_db.py to verify
```

---

## REST API (Flask browser)

All on `http://localhost:5000`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/stats` | Overview stats |
| GET | `/api/books` | Paginated list; params: `q`, `genre`, `dir`, `language`, `limit`, `offset` |
| GET | `/api/genres` | All genres with counts |
| GET | `/api/directories` | All directories with counts |
| GET | `/api/duplicates` | All `_(N)`-pattern duplicate files |
| GET | `/api/authors/similar` | Author name pairs with similarity ≥ 85% |
| GET | `/api/cover?title=` | Google Books thumbnail URL from cache |
| DELETE | `/api/books` | Remove book from disk + DB |
| PATCH | `/api/books/title` | Update title (DB only) |
| PATCH | `/api/books/author` | Rename author (moves file) |
| PATCH | `/api/books/language` | Update language (DB only) |
| PATCH | `/api/books/directory` | Move to a different category (moves file) |
| PATCH | `/api/books/genres` | Replace genre list |
| POST | `/api/authors/merge` | Merge two author folders |

---

## Test Suite

Uses stdlib `unittest`. Compatible with pytest if installed.

```bash
python run_tests.py              # all tests
python run_tests.py unit         # unit tests only
python run_tests.py integration  # integration tests only
python run_tests.py -v           # verbose
```

### Shared fixtures (`tests/conftest.py`)

**`TempLibrary`** — context manager that creates a fully isolated temporary library:
- A real temporary directory as `ORGANIZED_DIR`
- A real SQLite database with the two-table schema
- Helper methods: `add_book_file(rel, content)`, `add_book_record(**kw)`
- Exposes `.org` (Path), `.db_path` (Path), `.db` (sqlite3.Connection)

**`make_flask_client(lib)`** — patches `ORGANIZED_DIR` and `CACHE_DB` into all browser modules and returns a Flask test client. Call `stop_patches(client)` in `tearDown`.

### Unit tests

| File | What it covers |
|---|---|
| `test_merge_authors.py` | 10 scenarios for `_merge_authors()` in both Flet and Flask implementations |
| `test_browser_helpers.py` | `_sanitize`, `_move_book`, `_normalize_author`, `_levenshtein`, `_scan_duplicates`, `_fmt_ts`, `_row_to_dict` |
| `test_classifier.py` | `BookMeta`, confidence scoring, `resolve()` |
| `test_cache.py` | SQLite cache helpers |
| `test_deduplicator.py` | `deduplicate_books.py` logic |
| `test_language_map.py` | `LANGUAGE_MAP` coverage |

### Integration tests

Integration tests (`tests/integration/`) exercise the full Flask API or organiser pipeline against a real temp library. They are slower and require Flask to be installed.

---

## Adding a New Top-Level Category

Touch exactly these five places:

1. **`config.py` → `MAIN_CATEGORIES`** — append the folder name. Keep `"other"` last.
2. **`config.py` → `GENRE_TO_CATEGORY`** — map every genre that should route here.
3. **`config.py` → `GENRE_KEYWORDS`** *(optional)* — keyword lists for local classification.
4. **`config.py` → `SUBJECT_GENRE_MAP`** *(optional)* — map API subject strings to the genre name.
5. **`browser/db.py` → `MAIN_DIRS`** — add the same folder name.

---

## Known Gaps / Active Work

- **Author merge debug logging** — `~/babbelbook_merge.log` captures runtime evidence for the merge logic. If the merge is behaving unexpectedly, tail this file while reproducing the issue.
- **`babbelbook_flet.py` is monolithic** — a planned refactor would split it into a `flet_app/` package with dedicated modules (`constants.py`, `db.py`, `helpers.py`, `widgets.py`, `dialog.py`, `app.py`, `__main__.py`). The monolithic file is the current ground truth and the reference implementation for any such refactor.
- **`organizer/` and `browser/` are out of scope** for Flet-related work — treat them as stable dependencies unless a bug is directly traced into them.
- **Flet API compatibility** — Flet's API has changed across versions. If a UI widget behaves unexpectedly, check the installed Flet version first.
