#!/usr/bin/env python3
"""
babbelbook_flet.py — Flet desktop front-end for the BabbelBook library manager.

Direct SQLite access — no Flask server required.
All write operations (rename, move, delete) mirror the Flask routes exactly.

Requirements:  pip install flet
Run:           python3 babbelbook_flet.py
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import sqlite3
import threading
import unicodedata
from datetime import datetime
from pathlib import Path

import flet as ft

# ── Constants ─────────────────────────────────────────────────────────────────

DB_PATH       = Path.home() / "Documents" / "Books" / "books_organized" / ".cache.db"
ORGANIZED_DIR = DB_PATH.parent
PAGE_SIZE     = 50

LOG_PATH = Path.home() / "babbelbook_merge.log"
_merge_logger = logging.getLogger("babbelbook.merge")
_merge_logger.setLevel(logging.DEBUG)
if not _merge_logger.handlers:
    _fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s",
                                       datefmt="%Y-%m-%d %H:%M:%S"))
    _merge_logger.addHandler(_fh)

MAIN_CATEGORIES = [
    "cookbooks", "reading", "home_improvement",
    "sport_workout_yoga_health", "other",
]

DIR_ICONS = {
    "cookbooks": "📖", "reading": "📚", "home_improvement": "🔧",
    "sport_workout_yoga_health": "🏃", "other": "📄",
    "failed": "⚠️", "pdf": "📋", "unknown": "❓",
}

LANG_FLAGS = {
    "english": "🇬🇧", "dutch": "🇳🇱", "french": "🇫🇷",
    "german": "🇩🇪", "spanish": "🇪🇸", "italian": "🇮🇹",
    "portuguese": "🇵🇹", "japanese": "🇯🇵", "chinese": "🇨🇳",
    "russian": "🇷🇺", "arabic": "🇸🇦", "korean": "🇰🇷",
    "swedish": "🇸🇪", "norwegian": "🇳🇴", "danish": "🇩🇰",
}

# ── Colours ───────────────────────────────────────────────────────────────────

BG         = "#F2F4F9"
CARD       = "#FFFFFF"
SIDEBAR_BG = "#1B2340"
ACCENT     = "#4B6CF7"
ACCENT_DIM = "#EEF2FF"
TEXT       = "#1E2738"
TEXT_DIM   = "#6B7280"
BORDER     = "#E5E7EB"
HEADER_BG  = "#F9FAFB"
GREEN      = "#10B981"
AMBER      = "#F59E0B"
RED_C      = "#EF4444"
PURPLE     = "#7C3AED"
BLUE       = "#0EA5E9"

# ── DB helpers ────────────────────────────────────────────────────────────────

def _db() -> sqlite3.Connection | None:
    if not DB_PATH.exists():
        return None
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _fmt_ts(ts) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "—"


def _row_to_dict(row) -> dict:
    d = dict(row)
    try:
        d["genres"] = json.loads(d.get("genres") or "[]")
    except Exception:
        d["genres"] = []
    if "ts" in d:
        d["ts_fmt"] = _fmt_ts(d["ts"])
    return d


def _file_size(rel: str) -> int:
    if not rel:
        return 0
    p = ORGANIZED_DIR / rel
    try:
        return p.stat().st_size if p.exists() else 0
    except Exception:
        return 0


def _fmt_size(n: int) -> str:
    if n == 0:
        return "—"
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024  # type: ignore[assignment]
    return f"{n:.1f} TB"


# ── Write helpers (mirrors Flask routes exactly) ──────────────────────────────

def _sanitize(name: str) -> str:
    name = (name or "").strip()
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = re.sub(r'\s+', " ", name)
    return name or "Unknown"


def _move_book(old_rel: str, new_rel: str) -> tuple[bool, str]:
    src = ORGANIZED_DIR / old_rel
    dst = ORGANIZED_DIR / new_rel
    if not src.exists():
        return False, f"Source not found: {src}"
    if src == dst:
        return True, ""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        stem, sfx = dst.stem, dst.suffix
        n = 1
        while dst.exists():
            dst = dst.parent / f"{stem}_({n}){sfx}"
            n += 1
    shutil.move(str(src), str(dst))
    for p in [src.parent, src.parent.parent]:
        try:
            if p != ORGANIZED_DIR and not any(p.iterdir()):
                p.rmdir()
        except Exception:
            pass
    return True, str(dst.relative_to(ORGANIZED_DIR))


# ── Author merge ─────────────────────────────────────────────────────────────

def _merge_authors(
    src: str,
    tgt: str,
    organized_dir: Path | None = None,
) -> tuple[int, int, list[str]]:
    """
    Move all books from *src* author into *tgt* author, across every category dir.

    Cross-category awareness: if *tgt* already has an established home in a
    different category from *src*, books are moved there rather than silently
    creating a new folder in *src*'s category.

    Priority per source category:
      1. Target exists in the **same** category  → use it (normal same-cat merge)
      2. Target exists in **another** category   → use that established home
      3. Target exists nowhere yet               → create in same category as source

    Returns (moved, skipped, errors).
    """
    org = organized_dir or ORGANIZED_DIR
    con = _db() if organized_dir is None else sqlite3.connect(
        org / ".cache.db"
    )
    if con is None:
        _merge_logger.error("Could not open DB — aborting")
        return 0, 0, ["Database not found"]
    if organized_dir is not None:
        con.row_factory = sqlite3.Row

    moved = skipped = 0
    errors: list[str] = []

    _merge_logger.info("=== MERGE START: %r -> %r ===", src, tgt)

    # Pre-compute all categories where target already has a folder.
    # Sorted for determinism when target lives in multiple categories.
    tgt_existing: dict[str, Path] = {
        d.name: d / tgt
        for d in sorted(org.iterdir())
        if d.is_dir() and (d / tgt).is_dir()
    }
    _merge_logger.info("  tgt_existing categories: %s", list(tgt_existing.keys()))

    for cat_dir in sorted(org.iterdir()):
        if not cat_dir.is_dir():
            continue
        src_dir = cat_dir / src
        if not src_dir.is_dir():
            _merge_logger.debug("  [%s] no source dir — skipping", cat_dir.name)
            continue

        # Determine destination category (the cross-category fix).
        if cat_dir.name in tgt_existing:
            tgt_dir = tgt_existing[cat_dir.name]           # same-category target
        elif tgt_existing:
            tgt_dir = next(iter(tgt_existing.values()))    # target's established home
        else:
            tgt_dir = cat_dir / tgt                        # target is new; stay in place

        tgt_dir.mkdir(parents=True, exist_ok=True)
        _merge_logger.info("  [%s] src=%s  tgt=%s", cat_dir.name, src_dir, tgt_dir)

        for book_file in sorted(src_dir.rglob("*")):
            if not book_file.is_file():
                continue
            dest    = tgt_dir / book_file.name
            old_rel = str(book_file.relative_to(org))
            _merge_logger.debug("    file: %s", old_rel)

            if dest.exists() and dest.stat().st_size == book_file.stat().st_size:
                _merge_logger.info("    SKIP (identical dest exists): %s", old_rel)
                try:
                    book_file.unlink()
                    rows = con.execute(
                        "DELETE FROM books WHERE relative_path=?", (old_rel,)
                    )
                    _merge_logger.info("    DB DELETE rows affected: %d", rows.rowcount)
                except Exception as ex:
                    _merge_logger.error("    DELETE error: %s", ex)
                    errors.append(str(ex))
                skipped += 1
                continue

            if dest.exists():
                n = 1
                while dest.exists():
                    dest = tgt_dir / f"{book_file.stem}_({n}){book_file.suffix}"
                    n += 1
                _merge_logger.info("    dest renamed to avoid clash: %s", dest.name)

            try:
                shutil.move(str(book_file), dest)
                new_rel = str(dest.relative_to(org))
                _merge_logger.info("    MOVE: %s -> %s", old_rel, new_rel)
                rows = con.execute(
                    "UPDATE books SET author=?, relative_path=?"
                    " WHERE relative_path=?",
                    (tgt, new_rel, old_rel),
                )
                _merge_logger.info(
                    "    DB UPDATE rows affected: %d  (old_rel=%r  new_rel=%r  tgt=%r)",
                    rows.rowcount, old_rel, new_rel, tgt,
                )
                if rows.rowcount == 0:
                    _merge_logger.warning(
                        "    *** ZERO ROWS UPDATED — file moved but DB not updated! "
                        "old_rel=%r", old_rel,
                    )
                moved += 1
            except Exception as ex:
                _merge_logger.error("    MOVE/UPDATE error: %s", ex)
                errors.append(str(ex))

        con.commit()
        _merge_logger.info("  [%s] committed", cat_dir.name)

        # Remove the source author dir and any now-empty subdirs.
        for d in sorted(src_dir.rglob("*"), reverse=True):
            try:
                if d.is_dir() and not any(d.iterdir()):
                    d.rmdir()
            except Exception:
                pass
        try:
            if src_dir.exists() and not any(src_dir.rglob("*")):
                src_dir.rmdir()
                _merge_logger.info("  [%s] removed empty src_dir", cat_dir.name)
            elif src_dir.exists():
                remaining = list(src_dir.rglob("*"))
                _merge_logger.warning(
                    "  [%s] src_dir NOT removed — %d items remain: %s",
                    cat_dir.name, len(remaining),
                    [str(r) for r in remaining[:5]],
                )
        except Exception as ex:
            _merge_logger.error("  rmdir error: %s", ex)

    con.close()
    _merge_logger.info(
        "=== MERGE END: moved=%d skipped=%d errors=%d ===", moved, skipped, len(errors)
    )
    return moved, skipped, errors


# ── Dup / author helpers ──────────────────────────────────────────────────────

_DUP_RE    = re.compile(r"^(.+)_\(\d+\)$")
_BOOK_EXTS = frozenset({".epub", ".pdf", ".mobi", ".azw", ".azw3", ".cbz", ".cbr", ".fb2"})
_DIAC_MAP  = str.maketrans("łøæœðþß", "loaeodt")


def _scan_dups() -> list[dict]:
    items: list[dict] = []
    if not ORGANIZED_DIR.exists():
        return items
    for p in sorted(ORGANIZED_DIR.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in _BOOK_EXTS:
            continue
        m = _DUP_RE.match(p.stem)
        if not m:
            continue
        canon     = p.parent / f"{m.group(1)}{p.suffix}"
        has_canon = canon.exists()
        same_size = not has_canon or canon.stat().st_size == p.stat().st_size
        items.append({
            "rel":       str(p.relative_to(ORGANIZED_DIR)),
            "canon_rel": str(canon.relative_to(ORGANIZED_DIR)),
            "has_canon": has_canon,
            "same_size": same_size,
            "safe":      same_size,
        })
    return items


def _normalize_author(name: str) -> str:
    s      = name.lower().translate(_DIAC_MAP)
    nfkd   = unicodedata.normalize("NFKD", s)
    ascii_ = "".join(c for c in nfkd if not unicodedata.combining(c))
    return  "".join(c for c in ascii_ if c.isalpha())


def _levenshtein(a: str, b: str) -> int:
    if not a: return len(b)
    if not b: return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1,
                            prev[j] + (0 if ca == cb else 1)))
        prev = curr
    return prev[-1]


# ── Small UI helpers ──────────────────────────────────────────────────────────

def _conf_color(conf: int) -> str:
    return GREEN if conf >= 75 else AMBER if conf >= 40 else RED_C


def _heading(title: str, subtitle: str = "") -> ft.Control:
    children: list[ft.Control] = [
        ft.Text(title, size=24, weight=ft.FontWeight.BOLD, color=TEXT)
    ]
    if subtitle:
        children.append(ft.Text(subtitle, size=13, color=TEXT_DIM))
    return ft.Container(
        content=ft.Column(children, spacing=2),
        padding=ft.Padding.only(left=30, top=24, right=30, bottom=16),
    )


def _stat_card(label: str, value, color: str, on_click=None) -> ft.Control:
    return ft.Container(
        content=ft.Column([
            ft.Container(
                height=4,
                bgcolor=color,
                border_radius=ft.BorderRadius.only(top_left=11, top_right=11),
            ),
            ft.Container(
                content=ft.Column([
                    ft.Text(str(value), size=30, weight=ft.FontWeight.BOLD, color=color),
                    ft.Text(label, size=12, color=TEXT_DIM),
                ], spacing=4),
                padding=ft.Padding.only(left=16, top=12, right=16, bottom=16),
            ),
        ], spacing=0),
        bgcolor=CARD,
        border_radius=12,
        border=ft.Border.all(1, BORDER),
        expand=True,
        on_click=on_click,
        ink=on_click is not None,
    )


def _card(content: ft.Control, padding: int = 18) -> ft.Control:
    return ft.Container(
        content=content,
        bgcolor=CARD,
        border_radius=12,
        border=ft.Border.all(1, BORDER),
        padding=padding,
    )


def _genre_chip(label: str, count: int = 0, on_click=None) -> ft.Control:
    text = f"{label}  {count}" if count else label
    return ft.Container(
        content=ft.Text(text, size=12, color=ACCENT),
        bgcolor=ACCENT_DIM,
        border_radius=20,
        padding=ft.Padding.symmetric(horizontal=12, vertical=5),
        on_click=on_click,
        ink=on_click is not None,
    )


def _snack(page: ft.Page, msg: str, color: str = GREEN) -> None:
    page.snack_bar = ft.SnackBar(
        content=ft.Text(msg, color="white"),
        bgcolor=color,
        duration=3000,
    )
    page.snack_bar.open = True
    page.update()


# ── Book Detail Dialog ────────────────────────────────────────────────────────

class BookDetailDialog:
    """Full-featured edit dialog matching all Flask write routes."""

    def __init__(self, page: ft.Page, book: dict, on_saved, on_deleted):
        self._page       = page
        self._book       = book
        self._on_saved   = on_saved
        self._on_deleted = on_deleted
        self._genres     = list(book.get("genres") or [])
        self._del_confirm = False
        self._dlg: ft.AlertDialog | None = None

        # Autocomplete data
        self._all_langs:  list[str] = []
        self._all_genres: list[str] = []
        con = _db()
        if con:
            self._all_langs = [
                r[0] for r in con.execute(
                    "SELECT DISTINCT language FROM books WHERE language IS NOT NULL ORDER BY language"
                ).fetchall()
            ]
            gc: dict[str, int] = {}
            for (gj,) in con.execute(
                "SELECT genres FROM books WHERE genres IS NOT NULL"
            ).fetchall():
                for g in (json.loads(gj) if gj else []):
                    gc[g] = gc.get(g, 0) + 1
            self._all_genres = sorted(gc, key=lambda x: -gc[x])
            con.close()

        self._build()

    # ── build ─────────────────────────────────────────────────────────────────

    def _build(self):
        b   = self._book
        rel = b.get("relative_path") or ""

        DBGD   = "#1B2340"   # dialog background (matches sidebar)
        DINPUT = "#6B82AA"   # input field background — lighter so text is visible
        DTEXT  = "#E8ECF4"   # primary light text
        DDIM   = "#8A9BC0"   # dimmed label text
        DBORD  = "#2B3B60"   # border colour

        def lbl(text):
            return ft.Text(text, size=12, color=DDIM, weight=ft.FontWeight.W_500)

        def dark_field(value):
            return ft.TextField(
                value=value, expand=True,
                text_size=15, color=DTEXT, bgcolor=DINPUT,
                border_color=DBORD, focused_border_color=ACCENT,
                cursor_color=ACCENT,
                content_padding=ft.Padding.all(12),
            )

        def make_autocomplete(initial, suggestions):
            tf = dark_field(initial)
            sug_lv = ft.ListView(spacing=0, visible=False, height=0)
            wrapper = ft.Column([tf, sug_lv], spacing=0)
            def pick(val):
                tf.value = val; sug_lv.visible = False; sug_lv.height = 0
                tf.update(); sug_lv.update()
            def on_change(e):
                q = (tf.value or "").lower().strip()
                matches = [s for s in suggestions if q and q in s.lower()]
                sug_lv.controls.clear()
                for m in matches[:8]:
                    sug_lv.controls.append(
                        ft.Container(ft.Text(m, size=13, color=DTEXT),
                            bgcolor=DINPUT,
                            border=ft.Border.only(bottom=ft.BorderSide(1, DBORD)),
                            padding=ft.Padding.symmetric(horizontal=12, vertical=9),
                            on_click=lambda e, v=m: pick(v), ink=True))
                sug_lv.height = min(len(matches), 8) * 40
                sug_lv.visible = bool(matches)
                sug_lv.update()
            tf.on_change = on_change
            return wrapper, lambda: tf.value or ""

        # editable fields
        self._tf_title  = dark_field(b.get("title") or "")
        self._tf_author = dark_field(b.get("author") or "")
        lang_widget,  self._get_lang      = make_autocomplete(b.get("language") or "", self._all_langs)
        genre_widget, self._get_new_genre = make_autocomplete("", self._all_genres)

        self._dd_dir = ft.Dropdown(
            value=b.get("directory") or MAIN_CATEGORIES[0],
            options=[ft.dropdown.Option(c) for c in MAIN_CATEGORIES],
            expand=True, text_size=15, bgcolor=DINPUT, color=DTEXT,
            border_color=DBORD, focused_border_color=ACCENT,
        )
        self._genres_row = ft.Row(wrap=True, spacing=6, run_spacing=6)
        self._status_txt = ft.Text("", size=12, color=AMBER)
        self._render_genres()

        # read-only right column
        conf = b.get("confidence") or 0
        size = _file_size(rel)

        def info_row(label, val):
            return ft.Row([
                ft.Container(ft.Text(f"{label}:", size=13, color=DDIM,
                    weight=ft.FontWeight.W_500), width=110),
                ft.Text(str(val), size=13, color=DTEXT, expand=True, selectable=True),
            ])

        right_col = ft.Column([
            ft.Text("File Information", size=15, weight=ft.FontWeight.BOLD, color=DTEXT),
            ft.Divider(height=1, color=DBORD),
            info_row("Size",       _fmt_size(size)),
            info_row("Confidence", f"{conf}%"),
            ft.ProgressBar(value=conf/100, bgcolor=DBORD,
                           color=_conf_color(conf), height=8),
            info_row("Sources",  b.get("sources") or "—"),
            info_row("Added",    b.get("ts_fmt") or "—"),
            info_row("Path",     rel or "—"),
            info_row("Original", b.get("original_path") or "—"),
        ], spacing=10, width=480)

        left_col = ft.Column([
            ft.Text("Edit Details", size=17, weight=ft.FontWeight.BOLD, color=DTEXT),
            ft.Divider(height=1, color=DBORD),
            lbl("Title"),   self._tf_title,
            lbl("Author"),  self._tf_author,
            lbl("Language"), lang_widget,
            lbl("Category"), self._dd_dir,
            lbl("Add genre"),
            ft.Row([
                ft.Container(content=genre_widget, expand=True),
                ft.Button("+ Add", on_click=self._add_genre,
                    style=ft.ButtonStyle(bgcolor=ACCENT, color="white")),
            ], vertical_alignment=ft.CrossAxisAlignment.START),
            lbl("Genres"),
            self._genres_row,
        ], spacing=8, width=540)

        icon  = DIR_ICONS.get(b.get("directory", ""), "📄")
        title = b.get("title") or "Book Details"

        action_row = ft.Row([
            ft.Button("💾  Save", on_click=self._save,
                style=ft.ButtonStyle(bgcolor=ACCENT, color="white")),
            ft.Button("🗑  Delete", on_click=self._delete,
                style=ft.ButtonStyle(bgcolor=RED_C, color="white")),
            ft.Container(expand=True),
            self._status_txt,
            ft.Container(expand=True),
            ft.OutlinedButton("✕  Cancel", on_click=lambda e: self._close(),
                style=ft.ButtonStyle(color=DTEXT,
                    side=ft.BorderSide(1, DBORD))),
        ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        body = ft.Container(
            bgcolor=DBGD, border_radius=12, padding=32,
            content=ft.Column([
                ft.Row([
                    ft.Text(f"{icon}  {title}", size=19,
                            weight=ft.FontWeight.BOLD, color=DTEXT, expand=True),
                    ft.TextButton("✕ Close", on_click=lambda e: self._close(),
                        style=ft.ButtonStyle(color=DDIM)),
                ]),
                ft.Divider(height=1, color=DBORD),
                ft.Row([left_col, ft.VerticalDivider(width=1, color=DBORD), right_col],
                    spacing=28, vertical_alignment=ft.CrossAxisAlignment.START),
                ft.Divider(height=1, color=DBORD),
                action_row,
            ], spacing=18, scroll=ft.ScrollMode.AUTO, width=1110, height=750),
        )

        self._dlg = ft.AlertDialog(
            modal=True, content=body, actions=[],
            content_padding=0, bgcolor=DBGD,
            on_dismiss=lambda e: None,
        )

    # ── genre chip helpers ────────────────────────────────────────────────────

    def _render_genres(self):
        self._genres_row.controls.clear()
        for g in self._genres:
            self._genres_row.controls.append(
                ft.Container(
                    content=ft.Row([
                        ft.Text(g, size=12, color=ACCENT),
                        ft.Container(
                            content=ft.Text("✕", size=10, color=ACCENT),
                            on_click=lambda e, genre=g: self._remove_genre(genre),
                            padding=ft.Padding.only(left=4),
                        ),
                    ], spacing=2, tight=True),
                    bgcolor=ACCENT_DIM,
                    border_radius=20,
                    padding=ft.Padding.symmetric(horizontal=10, vertical=5),
                )
            )

    def _add_genre(self, e=None):
        g = self._get_new_genre().strip()
        if g and g not in self._genres:
            self._genres.append(g)
            self._render_genres()
            self._genres_row.update()

    def _remove_genre(self, genre: str):
        if genre in self._genres:
            self._genres.remove(genre)
            self._render_genres()
            self._genres_row.update()

    # ── public ───────────────────────────────────────────────────────────────

    def show(self):
        self._page.overlay.append(self._dlg)
        self._dlg.open = True
        self._page.update()

    # ── private ───────────────────────────────────────────────────────────────

    def _close(self):
        self._dlg.open = False
        self._page.update()

    def _set_status(self, msg: str, color: str = RED_C):
        self._status_txt.value = msg
        self._status_txt.color = color
        self._status_txt.update()

    def _save(self, e):
        b    = self._book
        orig = b.get("original_path", "")
        con  = _db()
        if not con:
            self._set_status("Database not found"); return
        errors: list[str] = []

        # Title (DB-only)
        new_title = self._tf_title.value.strip()
        if new_title and new_title != (b.get("title") or ""):
            con.execute("UPDATE books SET title=? WHERE original_path=?",
                        (new_title, orig))
            b["title"] = new_title

        # Language (DB-only)
        new_lang = self._get_lang().strip()
        if new_lang and new_lang != (b.get("language") or ""):
            con.execute("UPDATE books SET language=? WHERE original_path=?",
                        (new_lang, orig))
            b["language"] = new_lang

        # Author (file move)
        new_author = _sanitize(self._tf_author.value)
        if new_author and new_author != (b.get("author") or ""):
            directory = b.get("directory") or "other"
            new_rel   = str(Path(directory) / new_author
                            / Path(b.get("relative_path", "")).name)
            ok, result = _move_book(b.get("relative_path", ""), new_rel)
            if ok:
                con.execute(
                    "UPDATE books SET author=?, relative_path=? WHERE original_path=?",
                    (new_author, result or new_rel, orig),
                )
                b["author"] = new_author
                b["relative_path"] = result or new_rel
            else:
                errors.append(f"Author rename: {result}")

        # Directory (file move)
        new_dir = self._dd_dir.value
        if new_dir and new_dir != (b.get("directory") or ""):
            author  = b.get("author") or "Unknown Author"
            new_rel = str(Path(new_dir) / author
                          / Path(b.get("relative_path", "")).name)
            ok, result = _move_book(b.get("relative_path", ""), new_rel)
            if ok:
                con.execute(
                    "UPDATE books SET directory=?, relative_path=? WHERE original_path=?",
                    (new_dir, result or new_rel, orig),
                )
                b["directory"] = new_dir
                b["relative_path"] = result or new_rel
            else:
                errors.append(f"Directory move: {result}")

        # Genres (DB-only)
        con.execute("UPDATE books SET genres=? WHERE original_path=?",
                    (json.dumps(self._genres), orig))
        b["genres"] = self._genres

        con.commit()
        con.close()

        if errors:
            self._set_status("Saved with warnings: " + "; ".join(errors), AMBER)
        else:
            self._on_saved()
            self._close()

    def _delete(self, e):
        if not self._del_confirm:
            self._del_confirm = True
            self._set_status(
                "⚠  Click Delete again to permanently remove this book.", AMBER
            )
            return

        b    = self._book
        orig = b.get("original_path")
        con  = _db()
        if not con:
            self._set_status("Database not found"); return

        rel = b.get("relative_path")
        if rel:
            fp = ORGANIZED_DIR / rel
            if fp.exists():
                try:
                    fp.unlink()
                    for p in [fp.parent, fp.parent.parent]:
                        try:
                            if p != ORGANIZED_DIR and not any(p.iterdir()):
                                p.rmdir()
                        except Exception:
                            pass
                except Exception as ex:
                    self._set_status(f"Could not delete file: {ex}")
                    con.close()
                    return

        con.execute("DELETE FROM books WHERE original_path=?", (orig,))
        con.commit()
        con.close()
        self._on_deleted()
        self._close()


# ── Main Application ──────────────────────────────────────────────────────────

class BabbelApp:
    """Flet desktop application — all 8 pages matching the web interface."""

    # ── setup ────────────────────────────────────────────────────────────────

    def __init__(self, page: ft.Page):
        self._page         = page
        self._nav_refs:   dict[str, ft.Container] = {}
        self._current     = ""
        self._books_filter: dict = {"q": "", "genre": "", "directory": "", "language": ""}
        self._content_col = ft.Column(
            expand=True, spacing=0,
            scroll=ft.ScrollMode.AUTO,
        )
        self._setup_page()
        self._build_layout()
        self._nav("overview")

    def _setup_page(self):
        p = self._page
        p.title              = "BabbelBook"
        p.bgcolor            = BG
        p.padding            = 0
        p.window.width       = 2560
        p.window.height      = 1440
        p.window.min_width   = 1400
        p.window.min_height  = 800
        p.window.maximized   = True

    def _build_layout(self):
        sidebar = self._build_sidebar()
        self._page.add(
            ft.Row(
                expand=True,
                spacing=0,
                controls=[
                    sidebar,
                    ft.Container(width=1, bgcolor=BORDER),
                    ft.Column(
                        expand=True, spacing=0,
                        controls=[self._content_col],
                    ),
                ],
            )
        )

    def _build_sidebar(self) -> ft.Control:
        NAV = [
            ("overview",    "📊", "Overview"),
            ("books",       "📚", "Books"),
            ("genres",      "🏷",  "Genres"),
            ("directories", "📁", "Directories"),
            ("languages",   "🌍", "Languages"),
            ("duplicates",  "⚠️", "Duplicates"),
            ("authors",     "👥", "Authors"),
            ("cache",       "🗄",  "Cache"),
        ]
        items: list[ft.Control] = []
        for key, icon, label in NAV:
            container = ft.Container(
                content=ft.Row([
                    ft.Text(icon, size=16, no_wrap=True),
                    ft.Text(label, size=14, color="white",
                            weight=ft.FontWeight.W_400),
                ], spacing=12, tight=True),
                padding=ft.Padding.symmetric(horizontal=18, vertical=11),
                border_radius=8,
                ink=True,
                on_click=lambda e, k=key: self._nav(k),
                margin=ft.Margin.symmetric(horizontal=8),
            )
            self._nav_refs[key] = container
            items.append(container)

        db_status = (
            str(DB_PATH) if DB_PATH.exists()
            else "⚠  DB not found"
        )
        return ft.Container(
            width=230,
            bgcolor=SIDEBAR_BG,
            content=ft.Column(
                expand=True,
                controls=[
                    ft.Container(
                        content=ft.Column([
                            ft.Text("📚 BabbelBook", size=18,
                                    weight=ft.FontWeight.BOLD, color="white"),
                            ft.Text("Library Manager", size=11, color="#5B6F8E"),
                        ], spacing=2),
                        padding=ft.Padding.only(left=20, top=24, right=20, bottom=16),
                    ),
                    ft.Container(height=1, bgcolor="#2B3558"),
                    ft.Container(height=8),
                    ft.Column(controls=items, spacing=2),
                    ft.Container(expand=True),
                    ft.Container(
                        content=ft.Text(db_status, size=9, color="#3B4F73", no_wrap=True),
                        padding=ft.Padding.only(left=12, top=8, right=12, bottom=16),
                    ),
                ],
            ),
        )

    # ── navigation ────────────────────────────────────────────────────────────

    def _nav(self, name: str, **kwargs):
        # Update sidebar highlight
        for key, c in self._nav_refs.items():
            c.bgcolor = ACCENT if key == name else None
        self._current = name

        self._content_col.controls.clear()
        builder = {
            "overview":    self._page_overview,
            "books":       self._page_books,
            "genres":      self._page_genres,
            "directories": self._page_directories,
            "languages":   self._page_languages,
            "duplicates":  self._page_duplicates,
            "authors":     self._page_authors,
            "cache":       self._page_cache,
        }.get(name)
        if builder:
            ctrl = builder(**kwargs)
            if ctrl is not None:
                self._content_col.controls.append(ctrl)
        self._page.update()

    def _open_book(self, book: dict):
        def on_saved():
            _snack(self._page, "✓ Book saved successfully.")
            f = self._books_filter
            self._nav("books", genre=f["genre"], directory=f["directory"], language=f["language"], q=f["q"])
        def on_deleted():
            _snack(self._page, "Book deleted.")
            f = self._books_filter
            self._nav("books", genre=f["genre"], directory=f["directory"], language=f["language"], q=f["q"])
        BookDetailDialog(self._page, book, on_saved, on_deleted).show()

    # ── Overview page ─────────────────────────────────────────────────────────

    def _page_overview(self) -> ft.Control:
        con = _db()
        if not con:
            return ft.Container(
                content=ft.Column([
                    ft.Text("⚠  Database not found", size=20, color=RED_C,
                            weight=ft.FontWeight.BOLD),
                    ft.Text(f"Expected: {DB_PATH}", size=13, color=TEXT_DIM),
                    ft.Text("Run organize_books.py first.", size=13, color=TEXT_DIM),
                ], spacing=10),
                padding=40,
            )

        total     = con.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        cache_tot = con.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
        by_dir    = [dict(r) for r in con.execute(
            "SELECT directory, COUNT(*) count FROM books"
            " GROUP BY directory ORDER BY count DESC"
        ).fetchall()]
        by_lang   = [dict(r) for r in con.execute(
            "SELECT language, COUNT(*) count FROM books"
            " GROUP BY language ORDER BY count DESC LIMIT 14"
        ).fetchall()]
        recent    = [_row_to_dict(r) for r in con.execute(
            "SELECT original_path,title,author,language,genres,directory,"
            "relative_path,confidence,sources,ts"
            " FROM books ORDER BY ts DESC LIMIT 10"
        ).fetchall()]
        gc: dict[str, int] = {}
        for (gj,) in con.execute(
            "SELECT genres FROM books WHERE genres IS NOT NULL"
        ).fetchall():
            for g in (json.loads(gj) if gj else []):
                gc[g] = gc.get(g, 0) + 1
        top_genres = sorted(gc.items(), key=lambda x: -x[1])[:20]
        con.close()

        dup_items = _scan_dups()
        dup_count = len(dup_items)

        # ── stat cards ──────────────────────────────────────────────────────
        stats = ft.Row([
            _stat_card("Books",         f"{total:,}",     ACCENT,
                       lambda e: self._nav("books")),
            _stat_card("Directories",   len(by_dir),      PURPLE,
                       lambda e: self._nav("directories")),
            _stat_card("Languages",     len(by_lang),     BLUE,
                       lambda e: self._nav("languages")),
            _stat_card("Cache entries", f"{cache_tot:,}", GREEN,
                       lambda e: self._nav("cache")),
            _stat_card("Duplicates",    dup_count,
                       AMBER if dup_count else GREEN,
                       lambda e: self._nav("duplicates")),
        ], spacing=12)

        # ── bar panel helper ─────────────────────────────────────────────────
        def bar_panel(title: str, rows: list[dict], key: str,
                      color: str, nav_kwarg: str) -> ft.Control:
            mx = max((r.get("count", 0) for r in rows), default=1)
            bar_rows: list[ft.Control] = []
            for r in rows[:12]:
                val  = r.get("count", 0)
                lbl  = r.get(key) or "—"
                icon = DIR_ICONS.get(lbl, "")
                pct  = val / mx if mx else 0
                bar_rows.append(
                    ft.Container(
                        content=ft.Row([
                            ft.Container(
                                ft.Text(f"{icon} {lbl}", size=11,
                                        color=TEXT, no_wrap=True),
                                width=150,
                            ),
                            ft.Container(
                                ft.ProgressBar(
                                    value=pct, bgcolor=BORDER,
                                    color=color, height=7,
                                ),
                                expand=True,
                            ),
                            ft.Container(
                                ft.Text(str(val), size=11, color=TEXT_DIM,
                                        text_align=ft.TextAlign.RIGHT),
                                width=44,
                            ),
                        ], spacing=8,
                           vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        padding=ft.Padding.symmetric(vertical=4),
                        on_click=lambda e, v=lbl, kw=nav_kwarg:
                            self._nav("books", **{kw: v}),
                        ink=True,
                    )
                )
            return _card(ft.Column([
                ft.Text(title, size=14, weight=ft.FontWeight.BOLD, color=TEXT),
                ft.Divider(height=1, color=BORDER),
                *bar_rows,
            ], spacing=0))

        bars = ft.Row([
            ft.Container(
                bar_panel("By Directory", by_dir,  "directory", ACCENT, "directory"),
                expand=True,
            ),
            ft.Container(
                bar_panel("By Language",  by_lang, "language",  BLUE,   "language"),
                expand=True,
            ),
        ], spacing=12)

        # ── top genres ───────────────────────────────────────────────────────
        genres_card = _card(ft.Column([
            ft.Text("Top Genres", size=14, weight=ft.FontWeight.BOLD, color=TEXT),
            ft.Divider(height=1, color=BORDER),
            ft.Row(
                controls=[
                    _genre_chip(g, cnt,
                                on_click=lambda e, genre=g:
                                    self._nav("books", genre=genre))
                    for g, cnt in top_genres
                ],
                wrap=True, spacing=8, run_spacing=8,
            ),
        ], spacing=12))

        # ── recent books ─────────────────────────────────────────────────────
        recent_rows: list[ft.Control] = []
        for book in recent:
            icon = DIR_ICONS.get(book.get("directory", ""), "📄")
            recent_rows.append(
                ft.Container(
                    content=ft.Row([
                        ft.Text(icon, size=18, width=30),
                        ft.Column([
                            ft.Text(
                                book.get("title") or "—",
                                size=13, color=TEXT,
                                weight=ft.FontWeight.W_500,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                            ft.Text(
                                f"{book.get('author') or '?'}  ·  "
                                f"{book.get('language') or '?'}",
                                size=12, color=TEXT_DIM,
                            ),
                        ], spacing=2, expand=True),
                    ], spacing=12),
                    padding=ft.Padding.symmetric(vertical=8),
                    border=ft.Border.only(bottom=ft.BorderSide(1, BORDER)),
                    on_click=lambda e, b=book: self._open_book(b),
                    ink=True,
                )
            )

        recent_card = _card(ft.Column([
            ft.Text("Recently Added", size=14, weight=ft.FontWeight.BOLD, color=TEXT),
            ft.Divider(height=1, color=BORDER),
            *recent_rows,
        ], spacing=0))

        return ft.Column(
            scroll=ft.ScrollMode.AUTO,
            spacing=0,
            controls=[
                _heading("Overview", "Your library at a glance"),
                ft.Container(
                    content=ft.Column([
                        stats, bars, genres_card, recent_card,
                    ], spacing=16),
                    padding=ft.Padding.only(left=30, top=0, right=30, bottom=30),
                ),
            ],
        )

    # ── Books page ────────────────────────────────────────────────────────────

    def _page_books(
        self,
        genre: str = "",
        directory: str = "",
        language: str = "",
        q: str = "",
    ) -> ft.Control:
        state = {"offset": 0, "total": 0, "books": []}

        # ── filter controls ──────────────────────────────────────────────────
        # Seed from kwargs so nav links (genre/directory/language) pre-fill
        self._books_filter["genre"]     = genre
        self._books_filter["directory"] = directory
        self._books_filter["language"]  = language
        self._books_filter["q"]         = q

        q_field = ft.TextField(
            value=q,
            hint_text="Search title, author, genre, path…",
            expand=True, text_size=14, color=TEXT,
            content_padding=ft.Padding.symmetric(horizontal=14, vertical=4),
            border_color=BORDER, bgcolor=CARD,
            prefix_icon="search",
        )
        chips_row = ft.Row(wrap=True, spacing=8, run_spacing=6)

        # No dropdowns — search box only

        # ── list & pagination controls ───────────────────────────────────────
        book_lv   = ft.ListView(expand=True, spacing=0)
        count_txt = ft.Text("", size=13, color=TEXT_DIM)
        page_txt  = ft.Text("", size=13, color=TEXT_DIM)
        prev_btn  = ft.Button(
            "← Prev", disabled=True, on_click=lambda e: go_prev(),
            style=ft.ButtonStyle(bgcolor=CARD, color=TEXT),
        )
        next_btn  = ft.Button(
            "Next →", disabled=True, on_click=lambda e: go_next(),
            style=ft.ButtonStyle(bgcolor=CARD, color=TEXT),
        )

        def render(update: bool = True):
            book_lv.controls.clear()
            for book in state["books"]:
                b    = book
                conf = b.get("confidence") or 0
                icon = DIR_ICONS.get(b.get("directory", ""), "📄")
                book_lv.controls.append(
                    ft.Container(
                        content=ft.Row([
                            ft.Container(
                                ft.Text(
                                    f"{icon}  {b.get('title') or '—'}",
                                    size=13, color=TEXT,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                ),
                                expand=3,
                            ),
                            ft.Container(
                                ft.Text(
                                    b.get("author") or "—",
                                    size=13, color=TEXT_DIM,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                ),
                                expand=2,
                            ),
                            ft.Container(
                                ft.Text(b.get("directory") or "—",
                                        size=12, color=TEXT_DIM),
                                expand=1,
                            ),
                            ft.Container(
                                ft.Text(b.get("language") or "—",
                                        size=12, color=TEXT_DIM),
                                expand=1,
                            ),
                            ft.Container(
                                ft.Text(
                                    ", ".join(b.get("genres") or []) or "—",
                                    size=11, color=TEXT_DIM,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                ),
                                expand=2,
                            ),
                        ], spacing=12),
                        padding=ft.Padding.symmetric(horizontal=20, vertical=10),
                        border=ft.Border.only(
                            bottom=ft.BorderSide(1, BORDER)),
                        on_click=lambda e, bk=b: self._open_book(bk),
                        ink=True,
                        bgcolor=CARD,
                    )
                )

            tot   = state["total"]
            off   = state["offset"]
            pages = max(1, -(-tot // PAGE_SIZE))
            cur   = off // PAGE_SIZE + 1
            count_txt.value      = f"{tot:,} books"
            page_txt.value       = f"Page {cur} / {pages}"
            prev_btn.disabled    = (off == 0)
            next_btn.disabled    = (off + PAGE_SIZE >= tot)

            if update:
                self._page.update()

        def rebuild_chips():
            chips_row.controls.clear()
            active = {k: v for k, v in self._books_filter.items() if v}
            if not active:
                return
            labels = {"q": "Search", "genre": "Genre", "directory": "Category", "language": "Language"}
            for k, v in active.items():
                chip_k = k
                chips_row.controls.append(
                    ft.Container(
                        content=ft.Row([
                            ft.Text(f"{labels[chip_k]}: {v}", size=12, color=ACCENT),
                            ft.Container(
                                ft.Text("✕", size=10, color=ACCENT),
                                on_click=lambda e, key=chip_k: clear_filter(key),
                                padding=ft.Padding.only(left=4),
                            ),
                        ], spacing=2, tight=True),
                        bgcolor=ACCENT_DIM,
                        border_radius=20,
                        padding=ft.Padding.symmetric(horizontal=10, vertical=5),
                    )
                )
            chips_row.controls.append(
                ft.TextButton(
                    "Reset all",
                    on_click=lambda e: reset_all(),
                    style=ft.ButtonStyle(color=TEXT_DIM),
                )
            )

        def clear_filter(key: str):
            self._books_filter[key] = ""
            if key == "q":
                q_field.value = ""
                q_field.update()
            search(reset=True)

        def reset_all():
            self._books_filter = {"q": "", "genre": "", "directory": "", "language": ""}
            q_field.value = ""
            q_field.update()
            search(reset=True)

        def search(reset: bool = True, update: bool = True):
            if reset:
                state["offset"] = 0
            con = _db()
            if not con:
                state["books"] = []; state["total"] = 0
                render(update); return

            q         = (q_field.value or "").strip()
            f_genre   = self._books_filter["genre"]
            f_dir     = self._books_filter["directory"]
            f_lang    = self._books_filter["language"]
            self._books_filter["q"] = q

            rebuild_chips()

            clauses: list[str] = []
            params:  list      = []
            if q:
                like = f"%{q}%"
                clauses.append(
                    "(title LIKE ? OR author LIKE ? OR genres LIKE ?"
                    " OR relative_path LIKE ? OR language LIKE ?)"
                )
                params.extend([like] * 5)
            if f_genre:
                clauses.append("genres LIKE ?")
                params.append(f'%"{f_genre}"%')
            if f_dir:
                clauses.append("directory = ?")
                params.append(f_dir)
            if f_lang:
                clauses.append("language = ?")
                params.append(f_lang)

            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            state["total"] = con.execute(
                f"SELECT COUNT(*) FROM books {where}", params
            ).fetchone()[0]
            state["books"] = [
                _row_to_dict(r) for r in con.execute(
                    f"SELECT original_path,title,author,language,genres,directory,"
                    f"relative_path,confidence,sources,ts"
                    f" FROM books {where} ORDER BY title ASC LIMIT ? OFFSET ?",
                    params + [PAGE_SIZE, state["offset"]],
                ).fetchall()
            ]
            con.close()
            render(update)

        def go_prev():
            state["offset"] = max(0, state["offset"] - PAGE_SIZE)
            search(reset=False)

        def go_next():
            if state["offset"] + PAGE_SIZE < state["total"]:
                state["offset"] += PAGE_SIZE
                search(reset=False)

        q_field.on_change = lambda e: search(reset=True)
        q_field.on_submit = lambda e: search(reset=True)

        # Column header
        header = ft.Container(
            content=ft.Row([
                ft.Container(
                    ft.Text("Title", size=12, weight=ft.FontWeight.W_600,
                            color=TEXT_DIM),
                    expand=3,
                ),
                ft.Container(
                    ft.Text("Author", size=12, weight=ft.FontWeight.W_600,
                            color=TEXT_DIM),
                    expand=2,
                ),
                ft.Container(
                    ft.Text("Category", size=12, weight=ft.FontWeight.W_600,
                            color=TEXT_DIM),
                    expand=1,
                ),
                ft.Container(
                    ft.Text("Language", size=12, weight=ft.FontWeight.W_600,
                            color=TEXT_DIM),
                    expand=1,
                ),
                ft.Container(
                    ft.Text("Genres", size=12, weight=ft.FontWeight.W_600,
                            color=TEXT_DIM),
                    expand=2,
                ),
            ], spacing=12),
            padding=ft.Padding.symmetric(horizontal=20, vertical=8),
            bgcolor=HEADER_BG,
            border=ft.Border.only(bottom=ft.BorderSide(1, BORDER)),
        )

        search(update=False)  # initial load — populates book_lv before mount

        return ft.Column(
            expand=True, spacing=0,
            controls=[
                _heading("Books", "Browse and edit your library"),
                ft.Container(
                    content=q_field,
                    padding=ft.Padding.only(left=30, top=0, right=30, bottom=6),
                ),
                ft.Container(
                    content=chips_row,
                    padding=ft.Padding.only(left=30, top=0, right=30, bottom=8),
                    visible=True,
                ),
                header,
                book_lv,
                ft.Container(
                    content=ft.Row([
                        prev_btn,
                        page_txt,
                        next_btn,
                        ft.Container(expand=True),
                        count_txt,
                    ], spacing=10),
                    padding=ft.Padding.symmetric(horizontal=20, vertical=8),
                    bgcolor=CARD,
                    border=ft.Border.only(top=ft.BorderSide(1, BORDER)),
                ),
            ],
        )

    # ── Genres page ───────────────────────────────────────────────────────────

    def _page_genres(self) -> ft.Control:
        con = _db()
        if not con:
            return ft.Text("Database not found", color=RED_C)
        gc: dict[str, int] = {}
        for (gj,) in con.execute(
            "SELECT genres FROM books WHERE genres IS NOT NULL"
        ).fetchall():
            for g in (json.loads(gj) if gj else []):
                gc[g] = gc.get(g, 0) + 1
        con.close()
        sorted_genres = sorted(gc.items(), key=lambda x: -x[1])

        return ft.Column(
            scroll=ft.ScrollMode.AUTO,
            spacing=0,
            controls=[
                _heading("Genres", f"{len(sorted_genres)} genres across your library"),
                ft.Container(
                    content=ft.Row(
                        controls=[
                            _genre_chip(
                                g, cnt,
                                on_click=lambda e, genre=g:
                                    self._nav("books", genre=genre),
                            )
                            for g, cnt in sorted_genres
                        ],
                        wrap=True, spacing=10, run_spacing=10,
                    ),
                    padding=ft.Padding.only(left=30, top=0, right=30, bottom=30),
                ),
            ],
        )

    # ── Directories page ──────────────────────────────────────────────────────

    def _page_directories(self) -> ft.Control:
        con = _db()
        if not con:
            return ft.Text("Database not found", color=RED_C)
        rows = [dict(r) for r in con.execute(
            "SELECT directory, COUNT(*) count FROM books"
            " GROUP BY directory ORDER BY count DESC"
        ).fetchall()]
        con.close()

        cards: list[ft.Control] = []
        for r in rows:
            d    = r["directory"] or "—"
            cnt  = r["count"]
            icon = DIR_ICONS.get(d, "📁")
            cards.append(
                ft.Container(
                    content=ft.Column([
                        ft.Text(icon, size=34),
                        ft.Text(d, size=13, weight=ft.FontWeight.BOLD,
                                color=TEXT, text_align=ft.TextAlign.CENTER),
                        ft.Text(f"{cnt:,} books", size=11, color=TEXT_DIM,
                                text_align=ft.TextAlign.CENTER),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                       spacing=6),
                    bgcolor=CARD,
                    border_radius=12,
                    border=ft.Border.all(1, BORDER),
                    padding=20,
                    width=165,
                    height=145,
                    on_click=lambda e, dir=d: self._nav("books", directory=dir),
                    ink=True,
                )
            )

        return ft.Column(
            scroll=ft.ScrollMode.AUTO,
            spacing=0,
            controls=[
                _heading("Directories", "Browse by category"),
                ft.Container(
                    content=ft.Row(controls=cards, wrap=True,
                                   spacing=12, run_spacing=12),
                    padding=ft.Padding.only(left=30, top=0, right=30, bottom=30),
                ),
            ],
        )

    # ── Languages page ────────────────────────────────────────────────────────

    def _page_languages(self) -> ft.Control:
        con = _db()
        if not con:
            return ft.Text("Database not found", color=RED_C)
        rows = [dict(r) for r in con.execute(
            "SELECT language, COUNT(*) count FROM books"
            " GROUP BY language ORDER BY count DESC"
        ).fetchall()]
        con.close()

        cards: list[ft.Control] = []
        for r in rows:
            lang = r["language"] or "unknown"
            cnt  = r["count"]
            flag = LANG_FLAGS.get(lang.lower(), "🌍")
            cards.append(
                ft.Container(
                    content=ft.Column([
                        ft.Text(flag, size=30),
                        ft.Text(lang.title(), size=13, weight=ft.FontWeight.BOLD,
                                color=TEXT, text_align=ft.TextAlign.CENTER),
                        ft.Text(f"{cnt:,} books", size=11, color=TEXT_DIM,
                                text_align=ft.TextAlign.CENTER),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                       spacing=6),
                    bgcolor=CARD,
                    border_radius=12,
                    border=ft.Border.all(1, BORDER),
                    padding=16,
                    width=148,
                    height=128,
                    on_click=lambda e, l=lang: self._nav("books", language=l),
                    ink=True,
                )
            )

        return ft.Column(
            scroll=ft.ScrollMode.AUTO,
            spacing=0,
            controls=[
                _heading("Languages", f"{len(rows)} languages in your library"),
                ft.Container(
                    content=ft.Row(controls=cards, wrap=True,
                                   spacing=10, run_spacing=10),
                    padding=ft.Padding.only(left=30, top=0, right=30, bottom=30),
                ),
            ],
        )

    # ── Duplicates page ───────────────────────────────────────────────────────

    def _page_duplicates(self) -> ft.Control:
        items = _scan_dups()
        safe  = [i for i in items if i["safe"]]
        susp  = [i for i in items if not i["safe"]]

        if not items:
            return ft.Column([
                _heading("Duplicates", "Scan for _(N) pattern files"),
                ft.Container(
                    content=ft.Column([
                        ft.Text("✅", size=48),
                        ft.Text("No duplicates found", size=16, color=GREEN,
                                weight=ft.FontWeight.BOLD),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                       spacing=10),
                    padding=60,
                ),
            ])

        def dup_row(item: dict) -> ft.Control:
            badge_text  = "⚠ Different size" if not item["safe"] else "✓ Same size"
            badge_color = AMBER if not item["safe"] else GREEN
            return ft.Container(
                content=ft.Row([
                    ft.Column([
                        ft.Text(item["rel"],       size=12, color=TEXT,
                                selectable=True),
                        ft.Text(
                            f"Canonical: {item['canon_rel']}",
                            size=11, color=TEXT_DIM, selectable=True,
                        ),
                    ], expand=True, spacing=2),
                    ft.Container(
                        ft.Text(badge_text, size=11, color="white"),
                        bgcolor=badge_color,
                        border_radius=20,
                        padding=ft.Padding.symmetric(horizontal=10, vertical=4),
                    ),
                ], spacing=12,
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
                padding=ft.Padding.symmetric(horizontal=20, vertical=10),
                border=ft.Border.only(bottom=ft.BorderSide(1, BORDER)),
                bgcolor=CARD,
            )

        rows: list[ft.Control] = []
        if susp:
            rows.append(ft.Container(
                ft.Text(
                    f"⚠  Suspicious ({len(susp)} files — size differs from canonical)",
                    size=13, color=AMBER, weight=ft.FontWeight.BOLD,
                ),
                padding=ft.Padding.only(left=20, top=16, right=20, bottom=8),
            ))
            rows.extend(dup_row(i) for i in susp)
        if safe:
            rows.append(ft.Container(
                ft.Text(
                    f"✓  Safe ({len(safe)} files — same size as canonical)",
                    size=13, color=TEXT_DIM, weight=ft.FontWeight.BOLD,
                ),
                padding=ft.Padding.only(left=20, top=16, right=20, bottom=8),
            ))
            rows.extend(dup_row(i) for i in safe)

        return ft.Column(
            expand=True, spacing=0,
            controls=[
                _heading("Duplicates",
                         f"{len(items)} _(N) pattern files found"),
                ft.ListView(controls=rows, expand=True, spacing=0),
            ],
        )

    # ── Authors page ──────────────────────────────────────────────────────────

    def _page_authors(self) -> ft.Control:
        con = _db()
        if not con:
            return ft.Container(
                ft.Text("⚠  Database not found", color=RED_C),
                padding=40,
            )

        rows = con.execute(
            "SELECT author, COUNT(*) cnt FROM books"
            " WHERE author IS NOT NULL AND author != ''"
            "   AND author != 'Unknown Author'"
            " GROUP BY author ORDER BY author"
        ).fetchall()
        con.close()

        authors = [(r["author"], r["cnt"]) for r in rows]
        pairs: list[dict] = []
        for i in range(len(authors)):
            for j in range(i + 1, len(authors)):
                a, ca = authors[i]; b, cb = authors[j]
                na, nb = _normalize_author(a), _normalize_author(b)
                if not na or not nb: continue
                ml   = max(len(na), len(nb))
                dist = _levenshtein(na, nb)
                score = 1.0 if na == nb else 1.0 - dist / ml
                if score >= 0.85:
                    pairs.append({
                        "author_a": a, "books_a": ca,
                        "author_b": b, "books_b": cb,
                        "score":    round(score, 3),
                    })
        pairs.sort(key=lambda x: -x["score"])

        subtitle = f"{len(pairs)} similar pair(s) found"
        pair_cards: list[ft.Control] = []

        if not pairs:
            pair_cards.append(ft.Container(
                ft.Text("✅  No similar author names found.", size=14, color=GREEN),
                padding=ft.Padding.only(left=30, top=0, right=30, bottom=0),
            ))
        else:
            for p in pairs:
                pair = p

                def fetch_books(author: str) -> list[dict]:
                    c = _db()
                    if not c: return []
                    rows = c.execute(
                        "SELECT title, language, directory, genres, confidence"
                        " FROM books WHERE author=? ORDER BY title LIMIT 8",
                        (author,)
                    ).fetchall()
                    c.close()
                    return [_row_to_dict(r) for r in rows]

                def make_detail_col(author: str) -> ft.Column:
                    books = fetch_books(author)
                    rows: list[ft.Control] = []
                    for b in books:
                        genres = ", ".join(b.get("genres") or []) or "—"
                        conf   = b.get("confidence") or 0
                        rows.append(ft.Container(
                            content=ft.Column([
                                ft.Text(b.get("title") or "—", size=12,
                                        color=TEXT, weight=ft.FontWeight.W_500,
                                        overflow=ft.TextOverflow.ELLIPSIS),
                                ft.Text(
                                    f"{b.get('language') or '?'}  ·  "
                                    f"{b.get('directory') or '?'}  ·  {conf}%  ·  {genres}",
                                    size=11, color=TEXT_DIM,
                                    overflow=ft.TextOverflow.ELLIPSIS),
                            ], spacing=2),
                            padding=ft.Padding.symmetric(horizontal=10, vertical=6),
                            border=ft.Border.only(bottom=ft.BorderSide(1, BORDER)),
                        ))
                    return ft.Column(controls=rows, spacing=0)

                src_detail = make_detail_col(pair["author_b"])
                tgt_detail = make_detail_col(pair["author_a"])

                src_dd = ft.Dropdown(
                    options=[
                        ft.dropdown.Option(pair["author_b"]),
                        ft.dropdown.Option(pair["author_a"]),
                    ],
                    value=pair["author_b"],
                    expand=True, text_size=14, color=TEXT,
                )
                tgt_dd = ft.Dropdown(
                    options=[
                        ft.dropdown.Option(pair["author_a"]),
                        ft.dropdown.Option(pair["author_b"]),
                    ],
                    value=pair["author_a"],
                    expand=True, text_size=14, color=TEXT,
                )
                merge_status = ft.Text("", size=11, color=TEXT_DIM)

                def make_on_change(dd, detail_col):
                    def on_change(e):
                        author = dd.value or ""
                        new_detail = make_detail_col(author)
                        detail_col.controls.clear()
                        detail_col.controls.extend(new_detail.controls)
                        self._page.update()
                    return on_change

                src_dd.on_select = make_on_change(src_dd, src_detail)
                tgt_dd.on_select = make_on_change(tgt_dd, tgt_detail)

                def make_merge(pair, src_dd, tgt_dd, merge_status, merge_btn_ref, pair_container):
                    def do_merge(e):
                        src = src_dd.value
                        tgt = tgt_dd.value
                        if not src or not tgt or src == tgt:
                            merge_status.value = "Select different source and target."
                            merge_status.update(); return

                        moved, skipped, errors = _merge_authors(src, tgt)

                        msg = f"✓ Merged: {moved} moved, {skipped} skipped"
                        if errors:
                            msg += f"  |  ⚠ {errors[0]}"
                        merge_status.value = msg
                        merge_status.color = GREEN if not errors else AMBER
                        merge_status.update()
                        if not errors:
                            src_dd.disabled = True
                            tgt_dd.disabled = True
                            merge_btn_ref[0].visible = False
                            if pair_container in pair_lv.controls:
                                pair_lv.controls.remove(pair_container)
                            self._page.update()
                    return do_merge

                score_pct = int(pair["score"] * 100)

                def dd_col(label, dd, detail):
                    return ft.Column([
                        ft.Text(label, size=12, color=TEXT,
                                weight=ft.FontWeight.W_600),
                        dd,
                        ft.Container(
                            content=detail,
                            bgcolor=HEADER_BG,
                            border_radius=6,
                            border=ft.Border.all(1, BORDER),
                            padding=ft.Padding.symmetric(horizontal=4, vertical=4),
                        ),
                    ], spacing=6, expand=True)

                pair_container = ft.Container(None,
                    padding=ft.Padding.only(left=30, top=0, right=30, bottom=12))

                merge_btn_ref: list = [None]
                merge_btn = ft.Button(
                    "Merge",
                    on_click=make_merge(
                        pair, src_dd, tgt_dd, merge_status,
                        merge_btn_ref, pair_container,
                    ),
                    style=ft.ButtonStyle(bgcolor=ACCENT, color="white"),
                )
                merge_btn_ref[0] = merge_btn

                pair_card = _card(ft.Column([
                    ft.Row([
                        ft.Column([
                            ft.Text(pair["author_a"], size=14,
                                    weight=ft.FontWeight.BOLD, color=TEXT),
                            ft.Text(f"{pair['books_a']} books", size=12, color=TEXT_DIM),
                        ], expand=True),
                        ft.Container(
                            ft.Text(f"{score_pct}% match", size=12, color="white"),
                            bgcolor=GREEN if score_pct >= 95 else AMBER,
                            border_radius=20,
                            padding=ft.Padding.symmetric(horizontal=10, vertical=4),
                        ),
                        ft.Column([
                            ft.Text(pair["author_b"], size=14,
                                    weight=ft.FontWeight.BOLD, color=TEXT,
                                    text_align=ft.TextAlign.RIGHT),
                            ft.Text(f"{pair['books_b']} books", size=12, color=TEXT_DIM,
                                    text_align=ft.TextAlign.RIGHT),
                        ], expand=True, horizontal_alignment=ft.CrossAxisAlignment.END),
                    ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    ft.Row([
                        dd_col("Merge from (source)", src_dd, src_detail),
                        ft.Container(
                            ft.Text("→", size=20, color=TEXT_DIM),
                            padding=ft.Padding.only(top=28),
                        ),
                        dd_col("Merge into (target)", tgt_dd, tgt_detail),
                    ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.START),
                    ft.Row([
                        merge_btn,
                        merge_status,
                    ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ], spacing=12))

                pair_container.content = pair_card
                pair_cards.append(pair_container)

        pair_lv = ft.ListView(controls=pair_cards, expand=True, spacing=0)

        return ft.Column(
            expand=True, spacing=0,
            controls=[
                _heading("Similar Authors", subtitle),
                pair_lv,
            ],
        )

    # ── Cache page ────────────────────────────────────────────────────────────

    def _page_cache(self) -> ft.Control:
        results_col = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO, expand=True)
        count_txt   = ft.Text("Type a search term above",
                               size=13, color=TEXT_DIM)

        q_field = ft.TextField(
            hint_text="Search cache by key or value…",
            expand=True, text_size=13, height=44, color=TEXT,
            content_padding=ft.Padding.symmetric(horizontal=14, vertical=4),
            border_color=BORDER, bgcolor=CARD,
            prefix_icon="search",
        )

        def search(e=None):
            q = (q_field.value or "").strip()
            results_col.controls.clear()
            if not q:
                count_txt.value = "Type a search term above"
                count_txt.update()
                self._page.update(); return

            con = _db()
            if not con: return
            like = f"%{q}%"
            rows = con.execute(
                "SELECT key,val,ts FROM cache"
                " WHERE key LIKE ? OR val LIKE ?"
                " ORDER BY ts DESC LIMIT 50",
                (like, like),
            ).fetchall()
            con.close()

            count_txt.value = f"{len(rows)} result(s)"
            count_txt.update()

            for key, val, ts in rows:
                try:
                    data   = json.loads(val)
                    pretty = json.dumps(data, indent=2, ensure_ascii=False)[:600]
                except Exception:
                    pretty = str(val)[:600]

                results_col.controls.append(
                    _card(ft.Column([
                        ft.Row([
                            ft.Text(key, size=13, weight=ft.FontWeight.BOLD,
                                    color=TEXT, expand=True, selectable=True),
                            ft.Text(_fmt_ts(ts), size=11, color=TEXT_DIM),
                        ]),
                        ft.Container(
                            ft.Text(pretty, size=11, color=TEXT_DIM,
                                    selectable=True, font_family="monospace"),
                            bgcolor=HEADER_BG,
                            border_radius=6,
                            padding=10,
                        ),
                    ], spacing=8))
                )

            self._page.update()

        q_field.on_change = search
        q_field.on_submit = search

        return ft.Column(
            expand=True, spacing=0,
            controls=[
                _heading("Cache", "Browse API cache entries"),
                ft.Container(
                    content=ft.Row([q_field, count_txt], spacing=14),
                    padding=ft.Padding.only(left=30, top=0, right=30, bottom=16),
                ),
                ft.Container(
                    content=results_col,
                    padding=ft.Padding.only(left=30, top=0, right=30, bottom=30),
                    expand=True,
                ),
            ],
        )


# ── Entry point ───────────────────────────────────────────────────────────────

def main(page: ft.Page):
    BabbelApp(page)


if __name__ == "__main__":
    ft.run(main)
