"""
browser/routes_read.py — all read-only GET endpoints.

Blueprint: read_bp
  GET /api/stats
  GET /api/books
  GET /api/genres
  GET /api/directories
  GET /api/cache
  GET /api/duplicates
  GET /api/authors/similar
  GET /api/cover
"""

import json
import re
import time
import unicodedata

from flask import Blueprint, jsonify, request

from .db import _db, _fmt_ts, _row_to_dict, ORGANIZED_DIR

read_bp = Blueprint("read", __name__)

# ---------------------------------------------------------------------------
# Module-level constants (built once, not on every request)
# ---------------------------------------------------------------------------

_SUPPORTED_EXTS = frozenset({
    ".epub", ".pdf", ".mobi", ".azw", ".azw3", ".cbz", ".cbr", ".fb2",
})
_DUP_RE = re.compile(r"^(.+)_\(\d+\)$")

# Translation table for characters with no NFD decomposition (issue #15 in review)
_DIACRITIC_EXTRA = str.maketrans("łøæœðþß", "loaeodt")

# Simple TTL cache for the duplicate scan so Overview loads stay fast.
# Invalidated after _DUP_CACHE_TTL seconds or when a write operation
# calls invalidate_dup_cache().
_DUP_CACHE_TTL = 60  # seconds
_dup_cache: dict | None = None
_dup_cache_ts: float = 0.0


def invalidate_dup_cache() -> None:
    """Called by write routes after any operation that may change duplicate state."""
    global _dup_cache, _dup_cache_ts
    _dup_cache = None
    _dup_cache_ts = 0.0


def _scan_duplicates() -> dict:
    """
    Walk ORGANIZED_DIR for _(N)-pattern files and return
    {'dup_safe': int, 'dup_suspicious': int, 'items': list[dict]}.

    Result is cached for _DUP_CACHE_TTL seconds.
    """
    global _dup_cache, _dup_cache_ts
    now = time.monotonic()
    if _dup_cache is not None and (now - _dup_cache_ts) < _DUP_CACHE_TTL:
        return _dup_cache

    dup_safe = 0
    dup_suspicious = 0
    items = []

    if ORGANIZED_DIR.exists():
        for p in sorted(ORGANIZED_DIR.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in _SUPPORTED_EXTS:
                continue
            m = _DUP_RE.match(p.stem)
            if not m:
                continue
            canonical = p.parent / f"{m.group(1)}{p.suffix}"
            has_canon = canonical.exists()
            same_size = not has_canon or canonical.stat().st_size == p.stat().st_size
            if same_size:
                dup_safe += 1
            else:
                dup_suspicious += 1
            items.append({
                "rel": str(p.relative_to(ORGANIZED_DIR)),
                "canon_rel": str(canonical.relative_to(ORGANIZED_DIR)),
                "has_canon": has_canon,
                "same_size": same_size,
                "safe": same_size,
            })

    _dup_cache = {
        "dup_safe": dup_safe,
        "dup_suspicious": dup_suspicious,
        "items": items,
    }
    _dup_cache_ts = now
    return _dup_cache


def _normalize_author(name: str) -> str:
    """Lowercase, strip diacritics, map special chars → compact ASCII key."""
    s = name.lower().translate(_DIACRITIC_EXTRA)
    nfkd = unicodedata.normalize("NFKD", s)
    ascii_str = "".join(c for c in nfkd if not unicodedata.combining(c))
    return "".join(c for c in ascii_str if c.isalpha())


def _levenshtein(a: str, b: str) -> int:
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1,
                            prev[j] + (0 if ca == cb else 1)))
        prev = curr
    return prev[-1]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@read_bp.route("/api/stats")
def api_stats():
    con = _db()
    if not con:
        return jsonify({"error": "Database not found"}), 404

    total = con.execute("SELECT COUNT(*) FROM books").fetchone()[0]
    cache_total = con.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
    by_dir = [dict(r) for r in con.execute(
        "SELECT directory, COUNT(*) as count FROM books"
        " GROUP BY directory ORDER BY count DESC"
    ).fetchall()]
    by_lang = [dict(r) for r in con.execute(
        "SELECT language, COUNT(*) as count FROM books"
        " GROUP BY language ORDER BY count DESC"
    ).fetchall()]

    conf_bands = []
    for lo, hi, label in [
        (80, 100, "High"), (55, 79, "Medium"), (35, 54, "Low"), (0, 34, "Very Low"),
    ]:
        n = con.execute(
            "SELECT COUNT(*) FROM books WHERE confidence BETWEEN ? AND ?", (lo, hi)
        ).fetchone()[0]
        conf_bands.append({"label": label, "range": f"{lo}–{hi}", "count": n})

    genre_counts = {}
    for (gj,) in con.execute(
        "SELECT genres FROM books WHERE genres IS NOT NULL"
    ).fetchall():
        for g in (json.loads(gj) if gj else []):
            genre_counts[g] = genre_counts.get(g, 0) + 1
    top_genres = sorted(genre_counts.items(), key=lambda x: -x[1])[:20]

    cache_src = {}
    for pfx, lbl in [
        ("gb", "Google Books"), ("ol", "Open Library"),
        ("isbn", "isbnlib"), ("ollama", "Ollama"),
    ]:
        cache_src[lbl] = con.execute(
            "SELECT COUNT(*) FROM cache WHERE key LIKE ?", (f"{pfx}:%",)
        ).fetchone()[0]

    recent_books = [_row_to_dict(r) for r in con.execute(
        "SELECT original_path,title,author,language,genres,directory,relative_path,"
        "confidence,sources,file_size_bytes,ts FROM books ORDER BY ts DESC LIMIT 10"
    ).fetchall()]

    con.close()

    dup_data = _scan_duplicates()

    return jsonify({
        "total_books": total,
        "total_cache": cache_total,
        "by_directory": by_dir,
        "by_language": by_lang,
        "confidence_bands": conf_bands,
        "top_genres": [{"genre": g, "count": c} for g, c in top_genres],
        "cache_by_source": cache_src,
        "recent_books": recent_books,
        "dup_safe": dup_data["dup_safe"],
        "dup_suspicious": dup_data["dup_suspicious"],
    })


@read_bp.route("/api/books")
def api_books():
    con = _db()
    if not con:
        return jsonify({"total": 0, "offset": 0, "books": []})

    q = request.args.get("q", "").strip()
    genre = request.args.get("genre", "").strip()
    direc = request.args.get("dir", "").strip()
    lang  = request.args.get("language", None)  # None = not filtered; "" = match NULL/empty
    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))

    clauses, params = [], []
    if q:
        like = f"%{q}%"
        clauses.append(
            "(title LIKE ? OR author LIKE ? OR genres LIKE ?"
            " OR relative_path LIKE ? OR language LIKE ?)"
        )
        params.extend([like] * 5)
    if genre:
        clauses.append("genres LIKE ?")
        params.append(f'%"{genre}"%')
    if direc:
        clauses.append("directory = ?")
        params.append(direc)
    if lang is not None:
        if lang == "":
            # Explicit filter for books with no language set
            clauses.append("(language IS NULL OR language = '')")
        else:
            clauses.append("language = ?")
            params.append(lang)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    total = con.execute(f"SELECT COUNT(*) FROM books {where}", params).fetchone()[0]
    rows = [_row_to_dict(r) for r in con.execute(
        f"SELECT original_path,title,author,language,genres,directory,relative_path,"
        f"confidence,sources,file_size_bytes,ts FROM books {where} ORDER BY title ASC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()]
    con.close()
    return jsonify({"total": total, "offset": offset, "books": rows})


@read_bp.route("/api/genres")
def api_genres():
    con = _db()
    if not con:
        return jsonify([])
    gc = {}
    for (gj,) in con.execute(
        "SELECT genres FROM books WHERE genres IS NOT NULL"
    ).fetchall():
        for g in (json.loads(gj) if gj else []):
            gc[g] = gc.get(g, 0) + 1
    con.close()
    return jsonify(sorted(gc.items(), key=lambda x: -x[1]))


@read_bp.route("/api/directories")
def api_directories():
    con = _db()
    if not con:
        return jsonify([])
    rows = con.execute(
        "SELECT directory, COUNT(*) as count FROM books"
        " GROUP BY directory ORDER BY count DESC"
    ).fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])


@read_bp.route("/api/cache")
def api_cache():
    con = _db()
    if not con:
        return jsonify([])
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])
    like = f"%{q}%"
    rows = con.execute(
        "SELECT key,val,ts FROM cache"
        " WHERE key LIKE ? OR val LIKE ? ORDER BY ts DESC LIMIT 50",
        (like, like),
    ).fetchall()
    result = []
    for key, val, ts in rows:
        try:
            data = json.loads(val)
        except Exception:
            data = val
        result.append({"key": key, "data": data, "ts_fmt": _fmt_ts(ts)})
    con.close()
    return jsonify(result)


@read_bp.route("/api/duplicates")
def api_duplicates():
    """Return all _(N) duplicate-pattern files with safe/suspicious classification."""
    return jsonify(_scan_duplicates()["items"])


@read_bp.route("/api/authors/similar")
def api_authors_similar():
    """Return pairs of author names that are likely the same person."""
    con = _db()
    if not con:
        return jsonify([])

    rows = con.execute(
        "SELECT author, COUNT(*) as cnt FROM books"
        " WHERE author IS NOT NULL AND author != '' AND author != 'Unknown Author'"
        " GROUP BY author ORDER BY author"
    ).fetchall()
    con.close()

    authors = [(r["author"], r["cnt"]) for r in rows]
    pairs = []

    for i in range(len(authors)):
        for j in range(i + 1, len(authors)):
            a, cnt_a = authors[i]
            b, cnt_b = authors[j]
            na, nb = _normalize_author(a), _normalize_author(b)
            if not na or not nb:
                continue
            if na == nb:
                score = 1.0
            else:
                max_len = max(len(na), len(nb))
                dist = _levenshtein(na, nb)
                score = 1.0 - dist / max_len
            if score >= 0.85:
                pairs.append({
                    "author_a": a, "books_a": cnt_a,
                    "author_b": b, "books_b": cnt_b,
                    "score": round(score, 3),
                })

    pairs.sort(key=lambda x: -x["score"])
    return jsonify(pairs)


@read_bp.route("/api/cover")
def api_cover():
    """Return a cached Google Books thumbnail URL, if available."""
    title = request.args.get("title", "").strip()
    if not title:
        return jsonify({"url": None})
    con = _db()
    if not con:
        return jsonify({"url": None})
    rows = con.execute(
        "SELECT val FROM cache WHERE key LIKE ? LIMIT 10", (f"gb:{title}%",)
    ).fetchall()
    for (val,) in rows:
        try:
            url = json.loads(val).get("thumbnail")
            if url:
                url = url.replace("http://", "https://").replace("&zoom=1", "&zoom=2")
                con.close()
                return jsonify({"url": url})
        except Exception:
            pass
    con.close()
    return jsonify({"url": None})
