"""
extractors.py — format-specific metadata + text extraction and ISBN finding.

Supported formats:
  .epub  → ebooklib
  .pdf   → pymupdf (fitz)
  .mobi  → mobi library

Each extractor returns a dict:
  { title, authors, language, subjects, sample_text, isbn }
Any key may be None / empty when unavailable.
"""

import re
import shutil
from pathlib import Path

from config import (
    EBOOKLIB_OK, PYMUPDF_OK, MOBI_OK, ISBNLIB_OK, LANGUAGE_MAP,
)

# Conditional imports (only available if libraries are installed)
if EBOOKLIB_OK:
    import ebooklib
    from ebooklib import epub as _epub
if PYMUPDF_OK:
    import fitz
if MOBI_OK:
    import mobi as _mobi
if ISBNLIB_OK:
    import isbnlib

# -- ISBN helpers -------------------------------------------------------------

ISBN_RE = re.compile(r"(?:ISBN[:\s-]*)?(97[89][\d\-]{10,}|\b\d{9}[\dXx]\b)")


def _validate_isbn(candidate: str):
    if not ISBNLIB_OK:
        return None
    clean = re.sub(r"[^\dXx]", "", candidate)
    if isbnlib.is_isbn13(clean):
        return clean
    if isbnlib.is_isbn10(clean):
        return isbnlib.to_isbn13(clean)
    return None


def find_isbn_in_text(text: str):
    for m in ISBN_RE.finditer(text):
        v = _validate_isbn(m.group())
        if v:
            return v
    return None


def find_isbn_epub(path: Path):
    """Check DC identifiers first, then scan first 4 spine items (copyright page territory)."""
    if not EBOOKLIB_OK:
        return None
    try:
        book = _epub.read_epub(str(path))
        for ident, _ in (book.get_metadata("DC", "identifier") or []):
            v = _validate_isbn(ident)
            if v:
                return v
        for i, item in enumerate(book.get_items_of_type(ebooklib.ITEM_DOCUMENT)):
            if i >= 4:
                break
            text = re.sub(r"<[^>]+>", " ",
                          item.get_content().decode("utf-8", errors="ignore"))
            isbn = find_isbn_in_text(text)
            if isbn:
                return isbn
    except Exception:
        pass
    return None


def find_isbn_pdf(doc) -> str | None:
    """Scan pages 0-7 (copyright page is almost always within the first 5)."""
    for i, page in enumerate(doc):
        if i >= 8:
            break
        isbn = find_isbn_in_text(page.get_text())
        if isbn:
            return isbn
    return None


# -- Format extractors --------------------------------------------------------

def extract_epub(path: Path) -> dict:
    out = {"title": None, "authors": [], "language": None,
           "subjects": [], "sample_text": "", "isbn": None}
    if not EBOOKLIB_OK:
        return out
    try:
        book = _epub.read_epub(str(path))

        def dc(tag):
            items = book.get_metadata("DC", tag)
            return [i[0] for i in items] if items else []

        titles   = dc("title");   creators = dc("creator")
        langs    = dc("language"); subjects = dc("subject")
        out["title"]    = titles[0] if titles else None
        out["authors"]  = creators
        out["language"] = LANGUAGE_MAP.get((langs[0] or "")[:2].lower(), None) if langs else None
        out["subjects"] = subjects
        out["isbn"]     = find_isbn_epub(path)

        text_parts = []
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            raw = re.sub(r"<[^>]+>", " ",
                         item.get_content().decode("utf-8", errors="ignore"))
            text_parts.append(raw)
            if sum(len(t) for t in text_parts) > 5000:
                break
        out["sample_text"] = " ".join(text_parts)[:5000]
    except Exception as e:
        print(f"    [ebooklib] {e}")
    return out


def extract_pdf(path: Path) -> dict:
    out = {"title": None, "authors": [], "language": None,
           "subjects": [], "sample_text": "", "isbn": None}
    if not PYMUPDF_OK:
        return out
    try:
        doc        = fitz.open(str(path))
        meta       = doc.metadata or {}
        out["title"]   = meta.get("title") or None
        author_str     = meta.get("author") or ""
        out["authors"] = [a.strip() for a in re.split(r"[,;&]", author_str) if a.strip()]
        out["isbn"]    = find_isbn_pdf(doc)
        text_parts = []
        for i, page in enumerate(doc):
            if i >= 6:
                break
            text_parts.append(page.get_text())
        out["sample_text"] = " ".join(text_parts)[:5000]
    except Exception as e:
        print(f"    [pymupdf] {e}")
    return out


def extract_mobi(path: Path) -> dict:
    out = {"title": None, "authors": [], "language": None,
           "subjects": [], "sample_text": "", "isbn": None}
    if not MOBI_OK:
        return out
    try:
        tempdir, filepath = _mobi.extract(str(path))
        html = Path(filepath).read_text(encoding="utf-8", errors="ignore")
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if m:
            out["title"] = re.sub(r"<[^>]+>", "", m.group(1)).strip() or None
        m = re.search(r'<meta\s+name=["\']author["\']\s+content=["\'](.*?)["\']', html, re.I)
        if m:
            out["authors"] = [m.group(1).strip()]
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
        out["sample_text"] = text[:5000]
        out["isbn"]        = find_isbn_in_text(text)
        shutil.rmtree(tempdir, ignore_errors=True)
    except Exception as e:
        print(f"    [mobi] {e}")
    return out
