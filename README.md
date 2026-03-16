# Babbelbook

A personal e-book library manager with two front-ends: a native desktop GUI built with Flet, and a local Flask web UI. Both share the same SQLite database.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Project Structure](#project-structure)
3. [babbelbook\_flet.py — Desktop App](#babbelbook_fletpy--desktop-app)
4. [book\_browser.py — Web UI](#book_browserpy--web-ui)
5. [organize\_books.py — Organiser](#organize_bookspy--organiser)
6. [deduplicate\_books.py — Dedup CLI](#deduplicate_bookspy--dedup-cli)
7. [repair\_db.py — DB / Filesystem Repair](#repair_dbpy--db--filesystem-repair)
8. [Configuration Reference](#configuration-reference)
9. [Output Layout](#output-layout)
10. [Database Schema](#database-schema)
11. [REST API Reference](#rest-api-reference)
12. [Testing](#testing)

---

## Quick Start

```bash
# 1. Install dependencies
pip install flet flask ebooklib pymupdf isbnlib langdetect mobi

# 2. (Optional) Start Ollama for LLM-assisted classification
ollama pull gpt-oss:20b
ollama serve

# 3. Preview the organiser — no files are copied
python organize_books.py --dry-run

# 4. Organise your library
python organize_books.py

# 5a. Open the Flet desktop app (preferred)
python babbelbook_flet.py

# 5b. Or open the web UI
python book_browser.py
# → http://localhost:5000
```

---

## Dependencies

### Required

| Package | Purpose |
|---|---|
| `flet` | Flet desktop app |
| `flask` | Flask web UI |

### Optional — format support

Each package adds support for one or more file formats. The organiser runs without them but falls back to filename heuristics for unsupported formats.

| Package | Formats |
|---|---|
| `ebooklib` | `.epub` metadata and text extraction |
| `pymupdf` | `.pdf` metadata and text extraction |
| `mobi` | `.mobi`, `.azw`, `.azw3` extraction |
| `isbnlib` | ISBN → rich metadata via online APIs |
| `langdetect` | Language detection from extracted text |

### Optional — local LLM

[Ollama](https://ollama.ai) reclassifies books whose confidence falls below `OLLAMA_THRESHOLD`. The organiser works without it — those books use the best available result from other sources.

```bash
ollama pull gpt-oss:20b
ollama serve
```

---

## Project Structure

```
babbelbook/
│
├── babbelbook_flet.py     ← Flet desktop UI (standalone, direct SQLite access)
├── book_browser.py        ← Flask web UI entry point
├── organize_books.py      ← Organiser entry point
├── deduplicate_books.py   ← Duplicate-file CLI
├── repair_db.py           ← DB / filesystem reconciliation utility
├── config.py              ← Single source of truth: paths, thresholds, maps
├── run_tests.py           ← Test runner (stdlib unittest)
│
├── organizer/             ← Classification and file-handling package
│   ├── cache.py           ← SQLite helpers — API cache + book records
│   ├── classifier.py      ← BookMeta dataclass, confidence scoring, resolve()
│   ├── enrichment.py      ← Google Books, Open Library, isbnlib, Ollama
│   ├── extractors.py      ← Format-specific metadata extraction (epub/pdf/mobi)
│   └── organizer.py       ← Orchestration: copy, flatten, CSV logging, summary
│
├── browser/               ← Flask web UI package
│   ├── db.py              ← SQLite helpers for browser (paths + row helpers)
│   ├── routes_read.py     ← Blueprint — all GET /api/* endpoints
│   ├── routes_write.py    ← Blueprint — all mutating endpoints
│   ├── query_cache.py     ← Standalone CLI cache inspector
│   └── ui/
│       ├── layout.py      ← HTML shell
│       ├── style.py       ← All CSS
│       └── script.py      ← All JavaScript
│
└── tests/
    ├── conftest.py        ← Shared fixtures (TempLibrary, make_flask_client)
    ├── unit/              ← Pure-logic tests (no filesystem I/O)
    └── integration/       ← End-to-end tests against a temp library
```

---

## babbelbook\_flet.py — Desktop App

A self-contained Flet desktop application with direct SQLite access. No Flask server required.

### Usage

```bash
python babbelbook_flet.py
```

### Pages

| Page | What it shows |
|---|---|
| **Overview** | Stat tiles, bar charts (by directory / language / confidence), top genres, recently added books |
| **Books** | Full-text search with filters for genre, directory and language; paginated book cards |
| **Genres** | All genre tags with counts; clicking a genre opens a filtered Books view |
| **Directories** | Top-level category folders with counts |
| **Languages** | Detected languages with counts; books with no language set appear under *unknown* |
| **Duplicates** | All `_(N)`-pattern files, classified as safe or suspicious |
| **Authors** | Similar-author detection and merge workflow |
| **Cache** | Raw API/LLM lookup entries, searchable |

### Book cards

Each book opens a detail panel with inline editing:

- **Title** — updates the database; the title is not part of the file path.
- **Author** — renames the author folder and moves the file on save.
- **Language** — updates the database only.
- **Directory** — moves the file to a different top-level category on save.
- **Genres** — add or remove genre chips; supports existing genres or creating new ones.
- **Delete** — removes the file from disk and the database (with confirmation).

### Similar Authors

The Authors page detects name variants:

1. Loads all distinct author names from the database.
2. Normalises each: lowercase, strip diacritics (including `ł`, `ø`, `æ` and other characters without Unicode NFD decomposition), remove punctuation and spaces.
3. Runs Levenshtein distance on all pairs.
4. Surfaces pairs scoring ≥ 85% similarity.

Each pair shows a colour-coded score (green ≥ 97%, amber ≥ 90%, red ≥ 85%) and book counts. Select pairs, choose which name to keep, then click **Merge**. All files are moved and the database is updated atomically.

The merge logic handles cross-category sources correctly: if the target author already has books in `psychology/`, all books from the source are moved to `psychology/<target>/` regardless of which category they came from.

### Debug log

Author-merge operations write a timestamped debug log to `~/babbelbook_merge.log`. This file is appended to (never overwritten) and is safe to inspect while the app is running.

---

## book\_browser.py — Web UI

A Flask-based web UI with identical read/write functionality to the desktop app, served at `http://localhost:5000`. Useful as a fallback or for remote access.

### Usage

```bash
python book_browser.py
# → http://localhost:5000
```

Flask must be installed. Run `organize_books.py` first to populate the database.

### Pages

| Page | How to open |
|---|---|
| **Overview** | Default on load |
| **Search Books** | Left nav |
| **By Genre** | Left nav |
| **By Directory** | Left nav |
| **By Language** | Left nav |
| **All Books** | Left nav |
| **API Cache** | Left nav → Cache |
| **Similar Authors** | Left nav → Tools |

---

## organize\_books.py — Organiser

Scans source folders, classifies each book through a multi-stage pipeline, and copies it into a structured library under `~/Documents/Books/books_organized/`.

### Usage

```bash
python organize_books.py                # live run (copies files)
python organize_books.py --dry-run      # preview only — no files copied
python organize_books.py -n             # same as --dry-run
python organize_books.py --workers 8   # override concurrency (default: 10)
```

### Classification pipeline

Each book passes through these stages in order, stopping early once confidence is high enough:

| Stage | What it does |
|---|---|
| **1. Format extraction** | ebooklib / pymupdf / mobi reads title, author, language, subjects and a text sample |
| **2. ISBN extraction** | Scans the copyright page for an ISBN-10 or ISBN-13 |
| **3. isbnlib lookup** | Uses the ISBN to fetch structured metadata from online registries |
| **4. Google Books** | Searches by title + author |
| **5. Open Library** | Fallback when Google Books returns nothing useful |
| **6. Language detection** | langdetect analyses the text sample |
| **7. Keyword scan** | Title and text matched against `GENRE_KEYWORDS` in `config.py` |
| **8. Ollama LLM** | Books below `OLLAMA_THRESHOLD` sent to the configured model |
| **9. Filename heuristic** | Last resort — parses patterns like `Author - Title.ext` |

### Confidence scoring

| Score | Meaning |
|---|---|
| 80–100 | High — multiple sources agreed |
| 55–79 | Medium — some uncertainty |
| 35–54 | Low — flagged in summary |
| 0–34 | Very low — also written to `uncertain_books.csv` if placed in `other/` or `failed/` |

### Post-processing: folder flattening

After all books are copied, single-language author folders are flattened:

```
Before:  reading/Stephen King/english/It.epub
After:   reading/Stephen King/It.epub
```

Authors with books in multiple languages keep their language subfolders.

---

## deduplicate\_books.py — Dedup CLI

Scans the organised library for `_(N)`-pattern files (e.g. `Dune_(1).epub`) and optionally removes them.

### Usage

```bash
python deduplicate_books.py              # dry-run — shows what would happen
python deduplicate_books.py --delete     # remove safe duplicates
```

### Safe vs. suspicious

| Situation | Classification | Deleted with --delete? |
|---|---|---|
| Canonical exists, **same size** | Safe | Yes |
| Canonical exists, **different size** | Suspicious ⚠ | Never |
| **No canonical** (orphan) | Safe | Yes |

Suspicious duplicates are printed separately and never touched automatically.

---

## repair\_db.py — DB / Filesystem Repair

Detects and fixes two classes of inconsistency between the database and the filesystem:

- **Stale** — DB rows whose `relative_path` no longer exists on disk (file was moved, renamed or deleted externally).
- **Orphan** — Files on disk inside `ORGANIZED_DIR` that have no matching DB row (book was copied in manually, or the DB row was deleted without removing the file).

### Usage

```bash
python repair_db.py          # dry-run — report only, change nothing
python repair_db.py --fix    # apply all fixes
```

### What the fixes do

| Issue | Fix |
|---|---|
| Stale DB row | Row is deleted from the database |
| Orphan file | File is moved to `BOOKS_DIR/___to_reprocess/` |

After running with `--fix`, re-ingest any files in `___to_reprocess/` by running `organize_books.py` with that directory as a source — or move them manually into the organised library and run `repair_db.py` again to pick them up.

### Example output (dry-run)

```
================================================================
  Babbelbook — DB / Filesystem Repair
  Library     : /Users/jan/Documents/Books/books_organized
  Database    : /Users/jan/Documents/Books/books_organized/.cache.db
  Reprocess   : /Users/jan/Documents/Books/___to_reprocess
  Mode        : DRY-RUN  (pass --fix to apply changes)
================================================================

  Scanning database … 1 247 row(s) in books table.
  Scanning filesystem … 1 245 supported file(s) on disk.

  ────────────────────────────────────────────────────────────
  Stale DB rows (file missing from disk) : 2
  Orphan files  (file not in database)   : 0
  ────────────────────────────────────────────────────────────

  STALE — in DB but not on disk (rows will be deleted):
  -------------------------------------------------------
    reading/Cormac McCarthy/Blood Meridian.epub
    history/Antony Beevor/Stalingrad.epub

  ORPHAN — on disk but not in DB (files will be moved to ___to_reprocess/):
  --------------------------------------------------------------------------
    (none)

  DRY-RUN complete — nothing was changed.
  Re-run with --fix to apply the changes shown above.
```

---

## Configuration Reference

All configuration lives in **`config.py`**. No other file needs to be edited for a standard setup change.

### Paths

| Constant | Default | Description |
|---|---|---|
| `BOOKS_DIR` | `~/Documents/Books` | Root of your source collection |
| `ORGANIZED_DIR` | `BOOKS_DIR/books_organized` | Destination for organised books |
| `CACHE_DB` | `ORGANIZED_DIR/.cache.db` | SQLite database |
| `UNCERTAIN_CSV` | `ORGANIZED_DIR/uncertain_books.csv` | CSV log for very low-confidence books |
| `FAILED_DIR` | `ORGANIZED_DIR/failed` | Books that raised an exception |
| `REPROCESS_DIR` | `BOOKS_DIR/___to_reprocess` | Orphan files staged for re-ingestion by `repair_db.py` |

### Thresholds

| Constant | Default | Description |
|---|---|---|
| `OLLAMA_THRESHOLD` | `75` | Confidence below this → send to Ollama |
| `UNCERTAIN_THRESHOLD` | `55` | Confidence below this → flagged in summary |
| `CSV_LOG_THRESHOLD` | `35` | Confidence below this **and** in `other/`/`failed/` → written to CSV |

### Ollama

| Constant | Default | Description |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama HTTP API base URL |
| `OLLAMA_MODEL` | `gpt-oss:20b` | Model name — must be pulled first |

### Concurrency

| Constant | Default | Description |
|---|---|---|
| `DEFAULT_WORKERS` | `10` | Concurrent threads. Override at runtime with `--workers N` |

### Supported formats

```python
SUPPORTED_EXTS = {".epub", ".pdf", ".mobi", ".azw", ".azw3", ".cbz", ".cbr", ".fb2"}
```

### Categories

The `MAIN_CATEGORIES` list in `config.py` controls top-level folder names. The last entry is always the fallback for books that don't match any genre mapping:

```python
MAIN_CATEGORIES = [
    "cookbooks", "reading", "home_improvement",
    "sport_workout_yoga_health", "psychology", "leadership",
    "politics", "history", "textbook", "other",
]
```

`MAIN_DIRS` in `browser/db.py` must be kept in sync with `MAIN_CATEGORIES` — it controls which directories appear in the web UI's Directory dropdown.

#### Adding a new category

1. **`config.py` → `MAIN_CATEGORIES`** — append the folder name. Keep `"other"` last.
2. **`config.py` → `GENRE_TO_CATEGORY`** — map every genre that should go here.
3. **`config.py` → `GENRE_KEYWORDS`** *(optional)* — add keyword lists for local classification.
4. **`config.py` → `SUBJECT_GENRE_MAP`** *(optional)* — map API subject strings to the genre name.
5. **`browser/db.py` → `MAIN_DIRS`** — add the same folder name.

### Language map

`LANGUAGE_MAP` translates ISO language codes into human-readable folder/database names. It covers ISO 639-1 two-letter codes (Google Books, langdetect) and ISO 639-2 three-letter codes (Open Library, epub metadata). To add a language:

```python
# in config.py
LANGUAGE_MAP = {
    ...
    "sv": "swedish", "swe": "swedish",
}
```

Codes not in the map fall through to `None` (stored as unknown).

---

## Output Layout

```
~/Documents/Books/
│
├── <your source folders>/          ← never modified
│
└── books_organized/
    ├── cookbooks/
    │   └── <Author>/
    │       └── <book>.epub
    ├── reading/
    │   └── <Author>/
    │       ├── <book>.epub         ← single language — flattened after organise
    │       ├── english/            ← kept when author has books in multiple languages
    │       └── spanish/
    ├── home_improvement/
    ├── sport_workout_yoga_health/
    ├── psychology/
    ├── leadership/
    ├── politics/
    ├── history/
    ├── textbook/
    ├── other/
    ├── pdf/
    ├── unknown/
    ├── failed/
    ├── .cache.db                   ← SQLite (hidden)
    └── uncertain_books.csv
```

---

## Database Schema

The SQLite database at `books_organized/.cache.db` has two tables.

### `books`

| Column | Type | Description |
|---|---|---|
| `original_path` | TEXT PK | Absolute path of the source file |
| `title` | TEXT | Detected title |
| `author` | TEXT | Normalised author name |
| `language` | TEXT | Detected language (e.g. `english`) |
| `genres` | TEXT | JSON array of genre strings |
| `directory` | TEXT | Top-level category folder name |
| `relative_path` | TEXT | Path relative to `ORGANIZED_DIR` |
| `confidence` | INTEGER | Score 0–100 |
| `sources` | TEXT | Pipe-separated list of contributing sources |
| `ts` | INTEGER | Unix timestamp of when the book was processed |

### `cache`

| Column | Type | Description |
|---|---|---|
| `key` | TEXT PK | Prefixed lookup key: `gb:`, `ol:`, `isbn:`, `ollama:` |
| `val` | TEXT | JSON-encoded result |
| `ts` | INTEGER | Unix timestamp |

---

## REST API Reference

All endpoints are served by `book_browser.py` on `http://localhost:5000`.

### GET /api/stats

Overview statistics: `total_books`, `total_cache`, `by_directory[]`, `by_language[]`, `confidence_bands[]`, `top_genres[]`, `cache_by_source{}`, `recent_books[]`, `dup_safe`, `dup_suspicious`.

### GET /api/books

Paginated book list.

| Parameter | Default | Description |
|---|---|---|
| `q` | — | Full-text search (title, author, genres, language, path) |
| `genre` | — | Filter to a single genre (exact match) |
| `dir` | — | Filter to a top-level directory |
| `language` | — | Filter to an exact language value; empty string returns books with no language set |
| `limit` | `50` | Results per page (max 200) |
| `offset` | `0` | Pagination offset |

### GET /api/genres

All genres with counts, sorted descending.

### GET /api/directories

All top-level directories with counts.

### GET /api/cache?q=\<query\>

Search raw API cache entries by key or value. Returns up to 50 results.

### GET /api/duplicates

All `_(N)`-pattern files with classification (`safe`, `has_canon`, `same_size`).

### GET /api/authors/similar

Author name pairs with similarity ≥ 85%, sorted by score.

### GET /api/cover?title=\<title\>

Google Books thumbnail URL from cache, or `{"url": null}`.

### DELETE /api/books

Remove a book from disk and database.

**Body:** `{"original_path": "/absolute/path/to/source.epub"}`

### PATCH /api/books/title

Update the book title (database only).

**Body:** `{"original_path": "...", "title": "New Title"}`

### PATCH /api/books/author

Rename the author — moves the file to a new folder and updates the database.

**Body:** `{"original_path": "...", "author": "New Author Name"}`

### PATCH /api/books/language

Update the book language (database only).

**Body:** `{"original_path": "...", "language": "french"}`

### PATCH /api/books/directory

Move a book to a different top-level directory.

**Body:** `{"original_path": "...", "directory": "cookbooks"}`

### PATCH /api/books/genres

Replace the genre list for a book.

**Body:** `{"original_path": "...", "genres": ["thriller", "crime"]}`

### POST /api/authors/merge

Move all books from one author folder into another across all category directories.

**Body:** `{"source": "T. R. Napper", "target": "T.R. Napper"}`

**Response:** `{"ok": true, "moved": 3, "skipped": 0}`

---

## Testing

Tests use stdlib `unittest` and are discovered by `run_tests.py`.

```bash
python run_tests.py              # all tests
python run_tests.py unit         # unit tests only
python run_tests.py integration  # integration tests only
python run_tests.py -v           # verbose output
```

Alternatively, use pytest if installed:

```bash
pytest tests/
```

### Test structure

```
tests/
├── conftest.py             ← TempLibrary context manager, make_flask_client()
├── unit/
│   ├── test_browser_helpers.py  ← _sanitize, _move_book, _normalize_author, etc.
│   ├── test_cache.py
│   ├── test_classifier.py
│   ├── test_deduplicator.py
│   ├── test_language_map.py
│   └── test_merge_authors.py   ← Author merge — both Flet and Flask implementations
└── integration/
    ├── test_api_read.py
    ├── test_api_write.py
    └── test_organizer.py
```

`TempLibrary` in `conftest.py` creates an isolated temporary library (real filesystem, real SQLite) for each test. Integration tests for the Flask implementation use `make_flask_client()` which patches `ORGANIZED_DIR` and `CACHE_DB` into the browser modules.
