"""
classifier.py — language detection, genre/category classification,
BookMeta dataclass, confidence scoring, and the master resolve() function.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from config import (
    EBOOKLIB_OK, PYMUPDF_OK, MOBI_OK,
    LANGDETECT_OK, LANGUAGE_MAP,
    GENRE_KEYWORDS, GENRE_TO_CATEGORY, SUBJECT_GENRE_MAP,
    OLLAMA_THRESHOLD, OLLAMA_MODEL, UNCERTAIN_THRESHOLD,
    ORGANIZED_DIR,
)
from .extractors import extract_epub, extract_pdf, extract_mobi
from .enrichment import (
    enrich_isbn, enrich_google_books, enrich_open_library, classify_with_ollama,
)

if LANGDETECT_OK:
    from langdetect import detect as _langdetect


# -- Author helpers -----------------------------------------------------------

def normalize_author(name: str) -> str:
    """Flip 'Lastname, Firstname [suffix]' to 'Firstname Lastname [suffix]'."""
    name = (name or "").strip()
    if not name or "," not in name:
        return name
    parts = [p.strip() for p in name.split(",", 1)]
    if len(parts) != 2:
        return name
    lastname, rest = parts
    suffix_re = re.compile(r"\b(Jr\.?|Sr\.?|I{2,3}|IV|V)\b", re.IGNORECASE)
    m = suffix_re.search(rest)
    suffix = ""
    if m:
        suffix = " " + m.group().strip()
        rest   = rest[:m.start()].strip()
    return f"{rest} {lastname}{suffix}".strip()


def sanitize(name: str) -> str:
    name = (name or "").strip()
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = re.sub(r'\s+', " ", name)
    return name or "Unknown"


def first_author(authors: list) -> str:
    if not authors:
        return "Unknown Author"
    return sanitize(normalize_author(authors[0]))


def guess_from_filename(path: Path) -> tuple[str, list]:
    """Heuristic: 'Author - Title.epub' or 'Author_Title.epub'."""
    stem = path.stem.replace("_", " ")
    m = re.match(r"^(.+?)\s*[-\u2013]\s*(.+)$", stem)
    if m:
        return m.group(2).strip(), [m.group(1).strip()]
    return stem, []


# -- Language detection -------------------------------------------------------

def detect_language(text: str) -> str:
    if not (text or "").strip():
        return "unknown"
    if LANGDETECT_OK:
        try:
            code = _langdetect(text[:5000])
            return LANGUAGE_MAP.get(code, "unknown")
        except Exception:
            pass
    # Word-frequency heuristic fallback
    tl = (text or "").lower()
    scores = {
        "english": sum(tl.count(w) for w in [" the ", " and ", " of ", " is ", " in "]),
        "spanish": sum(tl.count(w) for w in [" el ", " la ", " de ", " en ", " es "]),
        "german":  sum(tl.count(w) for w in [" der ", " die ", " das ", " und ", " ist "]),
        "dutch":   sum(tl.count(w) for w in [" de ", " het ", " een ", " van ", " en "]),
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "unknown"


# -- Genre / category detection -----------------------------------------------

def genre_from_subjects(subjects: list) -> str | None:
    for subj in subjects:
        if not subj:
            continue
        for token in re.split(r"[/,&]+", subj.lower()):
            token = token.strip()
            if token in SUBJECT_GENRE_MAP:
                return SUBJECT_GENRE_MAP[token]
    return None


def genre_from_text(title: str, sample: str) -> tuple[str, str]:
    """Returns (genre, source) where source is 'keyword_title' or 'keyword_text'."""
    title_l  = (title  or "").lower()
    sample_l = (sample or "").lower()
    for genre, keywords in GENRE_KEYWORDS.items():
        for kw in keywords:
            if kw in title_l:
                return genre, "keyword_title"
    for genre, keywords in GENRE_KEYWORDS.items():
        for kw in keywords:
            if kw in sample_l:
                return genre, "keyword_text"
    return "other", "default"


def genre_to_main_category(genre: str) -> str:
    return GENRE_TO_CATEGORY.get((genre or "").lower(), "other")


# -- BookMeta -----------------------------------------------------------------

@dataclass
class BookMeta:
    title      : str  = "Unknown"
    author     : str  = "Unknown Author"
    language   : str  = "unknown"
    genre      : str  = "other"        # winning / final genre
    all_genres : list = field(default_factory=list)  # every genre signal found
    category   : str  = "other"
    fallback   : bool = False
    confidence : int  = 0
    sources    : list = field(default_factory=list)


def _add_genre(meta: BookMeta, genre: str):
    """Add genre to all_genres if not already present and not generic."""
    if genre and genre not in ("other", "unknown") and genre not in meta.all_genres:
        meta.all_genres.append(genre)


def _score(meta: BookMeta) -> None:
    score = 0
    if meta.author != "Unknown Author":
        score += 15
        if any("library" in s for s in meta.sources): score += 10
        if any("online"  in s for s in meta.sources): score += 5
    if meta.language != "unknown":
        score += 10
        if "langdetect"     in meta.sources: score += 10
        elif "library_lang" in meta.sources: score += 8
        elif "online_lang"  in meta.sources: score += 5
    if meta.category != "other":
        score += 10
        if "ollama"             in meta.sources: score += 30
        elif "subjects_online"  in meta.sources: score += 25
        elif "subjects_library" in meta.sources: score += 20
        elif "keyword_title"    in meta.sources: score += 8
        elif "keyword_text"     in meta.sources: score += 5
    meta.confidence = min(score, 100)


# -- Master resolver ----------------------------------------------------------

def resolve(path: Path) -> BookMeta:
    ext  = path.suffix.lower()
    meta = BookMeta()

    # 1. Format library extraction
    raw = {"title": None, "authors": [], "language": None,
           "subjects": [], "sample_text": "", "isbn": None}
    if ext == ".epub":
        raw = extract_epub(path)
    elif ext == ".pdf":
        raw = extract_pdf(path)
    elif ext in {".mobi", ".azw"}:
        raw = extract_mobi(path)

    if any([raw["title"], raw["authors"], raw["sample_text"]]):
        meta.sources.append("library")
    if raw.get("language"):
        meta.sources.append("library_lang")

    title    = raw.get("title")
    authors  = raw.get("authors") or []
    lang     = raw.get("language")
    subjects = raw.get("subjects") or []
    sample   = raw.get("sample_text", "")
    isbn     = raw.get("isbn")

    # 2. ISBN enrichment
    if isbn:
        print(f"    [isbnlib] ISBN {isbn} ...")
        im = enrich_isbn(isbn)
        title   = title   or im.get("title")
        authors = authors or im.get("authors") or []
        lang    = lang    or im.get("language")
        if im.get("language"):
            meta.sources.append("online_lang")

    # 3. Google Books
    lookup_title  = title or path.stem
    lookup_author = normalize_author(authors[0]) if authors else ""
    print(f"    [Google Books] '{lookup_title}' ...")
    gm = enrich_google_books(lookup_title, lookup_author)
    gm_subjects = []
    if gm.get("title"):
        title    = title    or gm["title"]
        authors  = authors  or gm["authors"]
        lang     = lang     or gm["language"]
        subjects = subjects or gm["subjects"]
        gm_subjects = gm.get("subjects", [])
        meta.sources.append("online")
        if gm.get("language") and "online_lang" not in meta.sources:
            meta.sources.append("online_lang")
        if gm.get("subjects"):
            meta.sources.append("subjects_online")

    # 4. Open Library fallback
    om_subjects = []
    if not subjects or not title:
        print(f"    [Open Library] '{lookup_title}' ...")
        om = enrich_open_library(lookup_title, lookup_author)
        if om.get("title"):
            title    = title    or om["title"]
            authors  = authors  or om["authors"]
            lang     = lang     or om["language"]
            subjects = subjects or om["subjects"]
            om_subjects = om.get("subjects", [])
            if "online" not in meta.sources:
                meta.sources.append("online")
            if om.get("language") and "online_lang" not in meta.sources:
                meta.sources.append("online_lang")
            if om.get("subjects") and "subjects_online" not in meta.sources:
                meta.sources.append("subjects_online")

    if subjects and "subjects_online" not in meta.sources:
        meta.sources.append("subjects_library")

    # Collect genres from every subject list gathered so far (deduplicated)
    for g in [genre_from_subjects(raw.get("subjects", [])),
              genre_from_subjects(gm_subjects),
              genre_from_subjects(om_subjects)]:
        _add_genre(meta, g)

    # 5. Filename fallback
    fn_title, fn_authors = guess_from_filename(path)
    title   = title   or fn_title
    authors = authors or fn_authors

    # 6. Language detection
    if not lang:
        lang = detect_language(sample)
        if lang != "unknown":
            meta.sources.append("langdetect")

    # 7. Genre → category (keyword pass)
    genre = genre_from_subjects(subjects)
    if not genre:
        genre, kw_source = genre_from_text(title or "", sample)
        meta.sources.append(kw_source)
    else:
        if "subjects_online" not in meta.sources and "subjects_library" not in meta.sources:
            meta.sources.append("subjects_library")

    _add_genre(meta, genre)
    category = genre_to_main_category(genre)

    # 8. Fallback flag
    has_useful = bool(
        (title and title != fn_title) or
        (authors and authors != fn_authors) or
        sample.strip()
    )
    meta.fallback = not has_useful

    meta.title    = sanitize(title or path.stem)
    meta.author   = first_author(authors) if not meta.fallback else "Unknown Author"
    meta.language = lang or "unknown"
    meta.genre    = genre
    meta.category = category if not meta.fallback else "other"
    _score(meta)

    # 9. Ollama pass for low-confidence books
    import config
    if meta.confidence < OLLAMA_THRESHOLD and config.OLLAMA_OK and not meta.fallback:
        print(f"    [Ollama] confidence {meta.confidence}/100 -- asking {OLLAMA_MODEL} ...")
        result = classify_with_ollama(
            meta.title, meta.author, sample,
            meta.category, meta.language
        )
        if result:
            old_cat = meta.category
            meta.category = result.get("category", meta.category)
            meta.genre    = result.get("genre",    meta.genre)
            if result.get("language", "unknown") != "unknown":
                meta.language = result["language"]
            if result.get("author", "Unknown Author") != "Unknown Author":
                meta.author = sanitize(result["author"])
            meta.sources.append("ollama")
            _add_genre(meta, meta.genre)  # add Ollama's genre to the collection
            if old_cat != meta.category:
                print(f"    [Ollama] reclassified: {old_cat} -> {meta.category}  "
                      f"(genre: {meta.genre}, confidence: {result.get('confidence', '?')})")
            _score(meta)

    return meta


def destination(path: Path, meta: BookMeta) -> Path:
    """
    Normal:   books_organized/<category>/<author>/<language>/filename
    Fallback: books_organized/pdf/<author>/filename   (unreadable PDF)
              books_organized/unknown/<author>/filename (other unreadable)
    """
    if meta.fallback:
        base = ORGANIZED_DIR / ("pdf" if path.suffix.lower() == ".pdf" else "unknown")
        return base / meta.author / path.name
    return ORGANIZED_DIR / meta.category / meta.author / meta.language / path.name
