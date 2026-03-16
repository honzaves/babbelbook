"""
browser/ui/layout.py — HTML shell for the Book Library web UI.

Assembles the full page from CSS (style.py) and JS (script.py).
The {{ db_path }} placeholder is filled by Flask's render_template_string.
"""

from .style  import CSS
from .script import make_js

# Head + opening tags
_HEAD = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Book Library</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
"""

# HTML body (nav sidebar + main content area)
_BODY = r"""</head>
<body>

<nav>
  <div class="logo">
    <div class="logo-mark">B</div>
    <div class="logo-title">Book Library</div>
    <div class="logo-sub">Cache Explorer</div>
  </div>

  <div class="nav-group">
    <div class="nav-label">Explore</div>
    <button class="nav-btn active" onclick="show('stats',this)"><span class="nav-icon">◈</span>Overview</button>
    <button class="nav-btn" onclick="show('search',this)"><span class="nav-icon">⌕</span>Search Books</button>
    <button class="nav-btn" onclick="show('genres',this)"><span class="nav-icon">◉</span>By Genre</button>
    <button class="nav-btn" onclick="show('dirs',this)"><span class="nav-icon">◧</span>By Directory</button>
    <button class="nav-btn" onclick="show('langs',this)"><span class="nav-icon">◎</span>By Language</button>
    <button class="nav-btn" onclick="show('all',this)"><span class="nav-icon">≡</span>All Books</button>
  </div>
  <div class="nav-group">
    <div class="nav-label">Cache</div>
    <button class="nav-btn" onclick="show('cache',this)"><span class="nav-icon">⊛</span>API Cache</button>
  </div>
  <div class="nav-group">
    <div class="nav-label">Tools</div>
    <button class="nav-btn" onclick="show('authors',this)"><span class="nav-icon">⇄</span>Similar Authors</button>
  </div>

  <div class="nav-footer" id="nav-db-path">—</div>

  <div class="theme-toggle">
    <button class="toggle-btn" onclick="toggleTheme()" id="theme-btn">
      <span id="theme-icon">🌙</span> Dark mode
    </button>
  </div>
</nav>

<main>

  <div class="page active" id="page-stats">
    <div class="page-head"><h2>Overview</h2><p>Your processed book collection at a glance</p></div>
    <div id="stats-content"><div class="loading">Loading…</div></div>
  </div>

  <div class="page" id="page-search">
    <div class="page-head"><h2>Search Books</h2><p>Search by title, author, genre, language or path</p></div>
    <div class="search-row">
      <input type="text" id="search-q" placeholder="Type to search…" onkeydown="if(event.key==='Enter'){sOff=0;doSearch()}">
      <button class="btn" onclick="sOff=0;doSearch()">Search</button>
    </div>
    <div id="search-res"></div>
  </div>

  <div class="page" id="page-genres">
    <div class="page-head"><h2>By Genre</h2><p>Click a genre to see all books</p></div>
    <div id="genre-grid" class="genre-grid"></div>
    <div id="genre-res"></div>
  </div>

  <div class="page" id="page-dirs">
    <div class="page-head"><h2>By Directory</h2><p>Top-level folders in your organised library</p></div>
    <div id="dir-grid" class="dir-grid"></div>
    <div id="dir-res"></div>
  </div>

  <div class="page" id="page-langs">
    <div class="page-head"><h2>By Language</h2><p>Click a language to see all books</p></div>
    <div id="lang-grid" class="genre-grid"></div>
    <div id="lang-res"></div>
  </div>

  <div class="page" id="page-all">
    <div class="page-head"><h2>All Books</h2><p>Complete collection sorted by title</p></div>
    <div id="all-res"></div>
  </div>

  <div class="page" id="page-cache">
    <div class="page-head"><h2>API Cache</h2><p>Raw entries from Google Books, Open Library, isbnlib and Ollama</p></div>
    <div class="search-row">
      <input type="text" id="cache-q" placeholder="Search by title, author or key…" onkeydown="if(event.key==='Enter')doCache()">
      <button class="btn" onclick="doCache()">Search</button>
    </div>
    <div id="cache-res"></div>
  </div>

  <div class="page" id="page-authors">
    <div class="page-head">
      <h2>Similar Authors</h2>
      <p>Detect author names that likely refer to the same person and merge their folders</p>
    </div>
    <div id="authors-toolbar" style="display:none">
      <button class="btn btn-merge" id="btn-merge-selected" onclick="mergeSelected()" disabled>
        Merge selected
      </button>
      <span class="merge-hint" id="merge-hint"></span>
    </div>
    <div id="authors-res"><div class="loading">Loading…</div></div>
  </div>

</main>

<!-- ── Delete confirmation modal ── -->
<div class="modal-overlay" id="delete-modal">
  <div class="modal-box">
    <div class="modal-icon">🗑️</div>
    <div class="modal-title">Delete this book?</div>
    <div class="modal-body">
      <span class="modal-book-name" id="modal-book-name"></span><br>
      This will permanently delete the file from disk and remove it from the library. This cannot be undone.
    </div>
    <div class="modal-actions">
      <button class="btn-modal-cancel" onclick="closeDeleteModal()">Cancel</button>
      <button class="btn-modal-confirm" id="modal-confirm-btn" onclick="confirmDelete()">Delete</button>
    </div>
  </div>
</div>
<!-- ── Merge authors confirmation modal ── -->
<div class="modal-overlay" id="merge-modal">
  <div class="modal-box">
    <div class="modal-icon">⇄</div>
    <div class="modal-title" id="merge-modal-title">Merge authors?</div>
    <div class="modal-body" id="merge-modal-body"></div>
    <div class="modal-actions">
      <button class="btn-modal-cancel" onclick="closeMergeModal()">Cancel</button>
      <button class="btn-modal-confirm" id="merge-confirm-btn" onclick="confirmMerge()">Merge</button>
    </div>
  </div>
</div>
"""

def build_html() -> str:
    """Return the complete HTML page as a string."""
    try:
        from babbelbook.config import MAIN_CATEGORIES
    except ModuleNotFoundError:
        from config import MAIN_CATEGORIES
    return (
        _HEAD
        + "<style>\n" + CSS + "\n</style>\n</head>\n"
        + _BODY
        + "\n<script>\n" + make_js(MAIN_CATEGORIES) + "\n</script>\n</body>\n</html>"
    )
