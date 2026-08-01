# Ereader Window for Babbelbook (Flet) — Design

**Date:** 2026-08-01
**Status:** Approved
**Scope:** Flet app only (`babbelbook_flet.py` + new `babbelbook_reader.py`). The Flask browser, organiser, and other tools are untouched.

## Goal

From the book detail dialog, a **📖 Read** button opens the book in a separate OS window: an ereader with a clickable chapter sidebar, page navigation, zoom, and remembered reading position.

## Architecture

A new self-contained Flet app, **`babbelbook_reader.py`**, launched from the detail dialog as a subprocess:

```
python babbelbook_reader.py /abs/path/to/book.epub
```

Rationale: Flet cannot open a second native window from one process. A subprocess gives a true independent OS window, keeps the library UI usable while reading, and allows multiple books open at once. `babbelbook_flet.py` gains only the Read button and ~20 lines of launch code.

All rendering goes through **PyMuPDF** (already installed) for every format — one code path for paginated display, TOC extraction, and reflow.

### New constant in `config.py`

`config.py` remains the single source of truth:

```python
READER_EXTS = {".epub", ".pdf", ".mobi", ".fb2", ".cbz"}   # formats babbelbook_reader can open
```

`.azw`, `.azw3`, `.cbr` are excluded (DRM / rar formats PyMuPDF cannot open).

## The reader window (`babbelbook_reader.py`, ~350 lines)

**Layout:** permanent chapter sidebar (~260 px) on the left, page view on the right, slim toolbar on top. Window title = book title (falls back to filename). Same dark palette as the main app.

- **Page display** — current page rendered via `page.get_pixmap()` → PNG bytes → `ft.Image` (base64), at 2× scale for sharpness. An LRU cache of the last 5 rendered pages keeps back/forward turns instant.
- **Chapter sidebar** — `doc.get_toc()` yields `(level, title, page)` triples, rendered as a scrollable list of text buttons, indented per level, current chapter highlighted. Clicking jumps to that page. Books without a TOC (scanned pdfs, cbz) show "No chapters"; everything else still works.
- **Toolbar** — `◀ ▶` page buttons; a `12 / 340` indicator whose page number is an editable field (type + Enter to jump); `−  100%  +` zoom controls.
- **Keyboard** — `←`/`→`/`PageUp`/`PageDown` turn pages; `Home`/`End` jump to first/last page; `+`/`-` zoom.
- **Zoom** — pdf/cbz: scale the render matrix. Reflowable formats (epub/mobi/fb2): `doc.layout(fontsize=…)` re-layouts at the new size; current position is preserved across re-layout via PyMuPDF `make_bookmark`/`find_bookmark` (page numbers shift when text reflows).

## Integration in the detail dialog

In `BookDetailDialog.build()`'s `action_row` (`babbelbook_flet.py:572`), a **📖 Read** button joins Save/Delete on the left:

- Extension in `READER_EXTS` → enabled; click runs
  `subprocess.Popen([sys.executable, reader_path, str(ORGANIZED_DIR / rel)])` — fire-and-forget; the dialog stays open.
- Extension not readable → button shown **disabled** with tooltip "Format not supported by reader".
- File missing on disk → snackbar error instead of launching.

## Reading position persistence

New table in the shared `books_organized/.cache.db`, created on demand by the reader:

```sql
CREATE TABLE IF NOT EXISTS reading_state (
    relative_path TEXT PRIMARY KEY,
    page          INTEGER,
    zoom          REAL,
    ts            INTEGER
);
```

- Saved on every page turn and zoom change (single-row upsert).
- On open: apply saved zoom first, then jump to saved page (order matters for reflowable formats).
- Keyed by `relative_path` computed from the launch path; if the book lives outside `ORGANIZED_DIR`, persistence is silently skipped.
- Browser and organiser ignore the table. CLAUDE.md's schema section is updated to document it.

## Error handling

- Corrupt/unopenable file or password-protected pdf → the reader window shows a centred error message with the exception text instead of crashing.
- Page-render failure mid-session → error placeholder for that page; navigation still works.
- DB unavailable → reading works; position simply isn't saved.

## Testing

Following the project pattern (logic tested, Flet UI not): the reader's pure helpers are module-level functions covered by `tests/unit/test_reader.py`:

- TOC → sidebar-item mapping (levels, empty TOC)
- readable-extension check (`READER_EXTS` membership incl. case-insensitivity)
- relative-path resolution (inside vs outside `ORGANIZED_DIR`)
- `reading_state` load/save round-trip against the `TempLibrary` fixture
- the detail dialog's enabled/disabled decision per extension

## Decisions log

| Decision | Choice |
|---|---|
| Window realisation | Separate OS window via subprocess |
| Rendering | Unified PyMuPDF for all formats |
| Chapter navigation | Permanent sidebar |
| V1 features | Keyboard nav, zoom, remembered position, page-jump box |
| Accepted formats | Everything PyMuPDF opens (epub, pdf, mobi, fb2, cbz) |
| Position storage | `reading_state` table in `.cache.db` |
| Code location | New `babbelbook_reader.py` |
| Unreadable formats | Disabled Read button with tooltip |
