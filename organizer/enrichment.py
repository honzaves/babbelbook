"""
enrichment.py — online metadata enrichment and local Ollama classification.

Sources:
  isbnlib      → ISBN  → title, authors, language
  Google Books → title + author → title, authors, language, subjects
  Open Library → title + author → title, authors, language, subjects (fallback)
  Ollama       → low-confidence books → category, genre, language, author
"""

import json
import re
import urllib.parse
import urllib.request

from .cache import cache_get, cache_set
from config import (
    ISBNLIB_OK, LANGUAGE_MAP, MAIN_CATEGORIES,
    OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_OK,
)

if ISBNLIB_OK:
    import isbnlib

# -- Shared HTTP helper -------------------------------------------------------

def _http_get(url: str) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "book-organizer/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


# -- Ollama health check ------------------------------------------------------

def check_ollama() -> bool:
    """Returns True if Ollama is reachable and OLLAMA_MODEL is available."""
    import config
    try:
        data = _http_get(f"{OLLAMA_BASE_URL}/api/tags")
        if data is None:
            config.OLLAMA_OK = False
            return False
        models = [m.get("name", "") for m in data.get("models", [])]
        if not any(OLLAMA_MODEL in m for m in models):
            print(f"  WARNING: model '{OLLAMA_MODEL}' not found in Ollama.")
            print(f"  Available: {', '.join(models) or 'none'}")
            print(f"  Run: ollama pull {OLLAMA_MODEL}")
            config.OLLAMA_OK = False
            return False
        return True
    except Exception as e:
        print(f"  WARNING: Ollama not reachable at {OLLAMA_BASE_URL}: {e}")
        config.OLLAMA_OK = False
        return False


# -- isbnlib ------------------------------------------------------------------

def enrich_isbn(isbn: str) -> dict:
    cached = cache_get(f"isbn:{isbn}")
    if cached is not None:
        return cached
    result = {"title": None, "authors": [], "language": None, "subjects": []}
    if not ISBNLIB_OK:
        return result
    try:
        meta = isbnlib.meta(isbn)
        result["title"]    = meta.get("Title") or None
        result["authors"]  = meta.get("Authors") or []
        result["language"] = LANGUAGE_MAP.get(meta.get("Language", "")[:2].lower(), None)
    except Exception:
        pass
    cache_set(f"isbn:{isbn}", result)
    return result


# -- Google Books -------------------------------------------------------------

def enrich_google_books(title: str, author: str) -> dict:
    key    = f"gb:{title}:{author}"
    cached = cache_get(key)
    if cached is not None:
        return cached
    result = {"title": None, "authors": [], "language": None, "subjects": [], "thumbnail": None}
    query  = urllib.parse.quote(f'intitle:"{title}" inauthor:"{author}"')
    data   = _http_get(f"https://www.googleapis.com/books/v1/volumes?q={query}&maxResults=1")
    if data and data.get("totalItems", 0) > 0:
        try:
            info = data["items"][0]["volumeInfo"]
            result["title"]     = info.get("title")
            result["authors"]   = info.get("authors") or []
            result["language"]  = LANGUAGE_MAP.get(info.get("language", ""), None)
            result["subjects"]  = info.get("categories") or []
            result["thumbnail"] = (info.get("imageLinks") or {}).get("thumbnail")
        except (KeyError, IndexError):
            pass
    cache_set(key, result)
    return result


# -- Open Library -------------------------------------------------------------

def enrich_open_library(title: str, author: str) -> dict:
    key    = f"ol:{title}:{author}"
    cached = cache_get(key)
    if cached is not None:
        return cached
    result = {"title": None, "authors": [], "language": None, "subjects": []}
    query  = urllib.parse.quote(f"{title} {author}")
    data   = _http_get(
        f"https://openlibrary.org/search.json?q={query}&limit=1"
        f"&fields=title,author_name,language,subject"
    )
    if data and data.get("docs"):
        try:
            doc = data["docs"][0]
            result["title"]    = doc.get("title")
            result["authors"]  = doc.get("author_name") or []
            langs              = doc.get("language") or []
            result["language"] = LANGUAGE_MAP.get(langs[0] if langs else "", None)
            result["subjects"] = doc.get("subject") or []
        except (KeyError, IndexError):
            pass
    cache_set(key, result)
    return result


# -- Ollama classification ----------------------------------------------------

_OLLAMA_SYSTEM = """You are a book classification assistant.
Given a book title, author, and a short text sample, return ONLY a valid JSON
object with no explanation, no markdown, no extra text whatsoever.

Required keys:
{
  "category": "<one of: cookbooks | reading | home_improvement | sport_workout_yoga_health | other>",
  "genre":    "<specific genre e.g. thriller, fantasy, yoga, gardening, biography>",
  "language": "<one of: english | spanish | german | dutch | unknown>",
  "author":   "<corrected/normalized author name, or Unknown Author>",
  "confidence": <integer 0-100>
}

Rules:
- category must be EXACTLY one of the five listed values.
- Use full context to determine category, not isolated words.
  Example: 'stake' in a vampire novel is NOT woodworking.
  Example: 'Vampireslayer' is horror/fantasy -> reading.
- If uncertain, use 'other' for category.
- confidence reflects certainty about the category assignment.
"""


def classify_with_ollama(title: str, author: str, sample: str,
                          current_category: str, current_language: str) -> dict | None:
    import config
    cache_key = f"ollama:{title}:{author}"
    cached    = cache_get(cache_key)
    if cached is not None:
        return cached

    if not config.OLLAMA_OK:
        return None

    snippet = sample[:1500].strip() if sample else "(no text available)"
    prompt  = (
        f"Title  : {title}\n"
        f"Author : {author}\n"
        f"Current category guess : {current_category}\n"
        f"Current language guess : {current_language}\n\n"
        f"Text sample:\n{snippet}\n"
    )
    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": _OLLAMA_SYSTEM},
            {"role": "user",   "content": prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.1},
    }).encode()

    try:
        req = urllib.request.Request(
            f"{OLLAMA_BASE_URL}/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            response = json.loads(r.read().decode())

        raw = response["choices"][0]["message"]["content"].strip()
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$",        "", raw)
        # Extract JSON blob in case model added preamble
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if json_match:
            raw = json_match.group()

        data = json.loads(raw)
        if data.get("category") not in MAIN_CATEGORIES:
            data["category"] = "other"
        cache_set(cache_key, data)
        return data

    except Exception as e:
        print(f"    [Ollama] error: {e}")
        return None
