"""
browser/ui/script.py — all client-side JavaScript for the Book Library web UI.
"""
import json as _json

def make_js(categories):
    """Return the JS string with MAIN_CATEGORIES injected from config."""
    _cats_js = _json.dumps(list(categories))
    return f"const MAIN_CATEGORIES = {_cats_js};\n" + _JS

_JS = r"""
const SZ = 50;
let sOff = 0, aOff = 0;

const DIR_ICONS = {
  cookbooks:'📖', reading:'📚', home_improvement:'🔧',
  sport_workout_yoga_health:'🏃', other:'📄',
  failed:'⚠️', pdf:'📋', unknown:'❓'
};

function esc(s){
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Nav ──
function show(page, btn) {
  document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b=>b.classList.remove('active'));
  document.getElementById('page-'+page).classList.add('active');
  if(btn) btn.classList.add('active');
  if(page==='stats'  && !document.getElementById('stats-content').dataset.ok) loadStats();
  if(page==='genres' && !document.getElementById('genre-grid').dataset.ok)    loadGenres();
  if(page==='dirs'   && !document.getElementById('dir-grid').dataset.ok)      loadDirs();
  if(page==='langs'  && !document.getElementById('lang-grid').dataset.ok)     loadLangs();
  if(page==='all')   { aOff=0; loadAll(); }
  if(page==='authors') loadSimilarAuthors();
}

// ── Stats ──
async function loadStats() {
  const d = await (await fetch('/api/stats')).json();
  document.getElementById('stats-content').dataset.ok = 1;
  const mxd = Math.max(...d.by_directory.map(r=>r.count),1);
  const mxl = Math.max(...d.by_language.map(r=>r.count),1);
  const mxg = d.top_genres.length ? d.top_genres[0].count : 1;
  const mxc = d.total_cache || 1;

  document.getElementById('stats-content').innerHTML = `
    <div class="stat-row">
      <div class="stat-card" onclick="gotoPage('all')"   title="Browse all books"><div class="accent-line"></div><div class="stat-num">${d.total_books.toLocaleString()}</div><div class="stat-label">Books</div></div>
      <div class="stat-card" onclick="gotoPage('dirs')"  title="Browse by directory"><div class="accent-line"></div><div class="stat-num">${d.by_directory.length}</div><div class="stat-label">Directories</div></div>
      <div class="stat-card" onclick="gotoPage('langs')" title="Browse by language"><div class="accent-line"></div><div class="stat-num">${d.by_language.length}</div><div class="stat-label">Languages</div></div>
      <div class="stat-card" onclick="gotoPage('cache')" title="Browse API cache"><div class="accent-line"></div><div class="stat-num">${d.total_cache.toLocaleString()}</div><div class="stat-label">Cache entries</div></div>
      <div class="stat-card stat-card-dups ${(d.dup_safe+d.dup_suspicious)>0?'has-dups':''}" onclick="toggleDuplicatesPanel()" title="View duplicate files">
        <div class="accent-line ${(d.dup_suspicious>0)?'accent-line-warn':(d.dup_safe>0)?'accent-line-alert':''}"></div>
        <div class="stat-num">${(d.dup_safe+d.dup_suspicious)}</div>
        <div class="stat-label">Duplicates${d.dup_suspicious>0?' ⚠':''}</div>
      </div>
    </div>
    <div class="grid-2">
      <div class="panel">
        <div class="panel-title">By Directory</div>
        ${d.by_directory.map(r=>`<div class="bar-row"><div class="bar-lbl">${esc(r.directory||'—')}</div><div class="bar-trk"><div class="bar-fill" style="width:${Math.round(r.count/mxd*100)}%"></div></div><div class="bar-n">${r.count}</div></div>`).join('')}
      </div>
      <div class="panel">
        <div class="panel-title">By Language</div>
        ${d.by_language.map(r=>`<div class="bar-row"><div class="bar-lbl">${esc(r.language||'—')}</div><div class="bar-trk"><div class="bar-fill" style="width:${Math.round(r.count/mxl*100)}%"></div></div><div class="bar-n">${r.count}</div></div>`).join('')}
      </div>
    </div>
    <div class="grid-2">
      <div class="panel">
        <div class="panel-title">Confidence</div>
        ${d.confidence_bands.map(b=>`<div class="bar-row"><div class="bar-lbl">${b.label} (${b.range})</div><div class="bar-trk"><div class="bar-fill" style="width:${d.total_books?Math.round(b.count/d.total_books*100):0}%"></div></div><div class="bar-n">${b.count}</div></div>`).join('')}
      </div>
      <div class="panel">
        <div class="panel-title">API Cache Sources</div>
        ${Object.entries(d.cache_by_source).map(([s,n])=>`<div class="bar-row"><div class="bar-lbl">${esc(s)}</div><div class="bar-trk"><div class="bar-fill" style="width:${Math.round(n/mxc*100)}%"></div></div><div class="bar-n">${n}</div></div>`).join('')}
      </div>
    </div>
    <div class="panel">
      <div class="panel-title">Top Genres — click to browse</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:0 24px">
        ${d.top_genres.map(g=>`<div class="bar-row" style="cursor:pointer" onclick="gotoGenre('${esc(g.genre)}')">
          <div class="bar-lbl" style="color:var(--accent);font-weight:600">${esc(g.genre)}</div>
          <div class="bar-trk"><div class="bar-fill" style="width:${Math.round(g.count/mxg*100)}%"></div></div>
          <div class="bar-n">${g.count}</div>
        </div>`).join('')}
      </div>
    </div>
    <div class="panel">
      <div class="panel-title">Recently Added</div>
      <div class="book-list">${(d.recent_books||[]).map(b=>bookCard(b,true)).join('')}</div>
    </div>
    <div class="panel" id="duplicates-panel" style="display:none">
      <div class="panel-title">Duplicate Files</div>
      <div id="duplicates-content"><div class="loading">Loading…</div></div>
    </div>`;
}

// ── Book card ──
function confClass(c){ return c>=80?'':c>=55?'med':'low'; }

function bookCard(b, showDate=false) {
  const conf = b.confidence||0;
  const genres = b.genres||[];
  const cardId = 'bc-' + Math.random().toString(36).slice(2,8);
  const genresJson = esc(JSON.stringify(genres));
  return `<div class="book-card" id="${cardId}"
      data-original-path="${esc(b.original_path||'')}"
      data-genres="${genresJson}"
      data-title="${esc(b.title||'')}"
      data-author="${esc(b.author||'')}"
      data-language="${esc(b.language||'')}"
      data-directory="${esc(b.directory||'')}"
      data-rel-path="${esc(b.relative_path||'')}"
      onclick="toggleCard(event,this)">
    <div class="book-row">
      <div class="book-dot ${b.directory||'other'}"></div>
      <div class="book-body">
        <div class="book-title">${esc(b.title||'—')}</div>
        <div class="book-author" id="${cardId}-author-display">${esc(b.author||'—')}</div>
        <div class="book-tags">
          <span class="tag tag-dir" id="${cardId}-dir-display">${b.directory?esc(b.directory):''}</span>
          ${b.language ?`<span class="tag tag-lang" id="${cardId}-lang-display">${esc(b.language)}</span>`:`<span class="tag tag-lang" id="${cardId}-lang-display" style="display:none"></span>`}
          <span class="tag tag-conf ${confClass(conf)}">${conf}/100</span>
          ${showDate && b.ts_fmt ?`<span class="tag tag-date">🕐 ${esc(b.ts_fmt)}</span>`:''}
        </div>
      </div>
    </div>
    <div class="book-detail">
      <div class="cover-wrap" id="${cardId}-cover"><div class="cover-placeholder">📖</div></div>
      <div class="dl">
        <span class="dt">Title</span>
        <span class="dd">
          <div class="edit-row">
            <input class="edit-input" id="${cardId}-title-in" value="${esc(b.title||'')}" placeholder="Book title">
            <button class="btn-edit-save" onclick="saveTitle('${cardId}');event.stopPropagation()">Save</button>
            <span class="save-indicator" id="${cardId}-title-saved">✓ Saved</span>
          </div>
          <div class="edit-error" id="${cardId}-title-err"></div>
        </span>

        <span class="dt">Author</span>
        <span class="dd">
          <div class="edit-row">
            <input class="edit-input" id="${cardId}-author-in" value="${esc(b.author||'')}" placeholder="Author name">
            <button class="btn-edit-save" onclick="saveAuthor('${cardId}');event.stopPropagation()">Save</button>
            <span class="save-indicator" id="${cardId}-author-saved">✓ Saved</span>
          </div>
          <div class="edit-error" id="${cardId}-author-err"></div>
        </span>

        <span class="dt">Directory</span>
        <span class="dd">
          <div class="edit-row">
            <select class="edit-select" id="${cardId}-dir-in" onclick="event.stopPropagation()">
              ${MAIN_CATEGORIES.map(d=>`<option value="${d}" ${d===(b.directory||'')?'selected':''}>${d}</option>`).join('')}
            </select>
            <button class="btn-edit-save" onclick="saveDirectory('${cardId}');event.stopPropagation()">Save</button>
            <span class="save-indicator" id="${cardId}-dir-saved">✓ Saved</span>
          </div>
          <div class="edit-error" id="${cardId}-dir-err"></div>
        </span>

        <span class="dt">Language</span>
        <span class="dd">
          <div class="edit-row">
            <div class="genre-ac-wrap" id="${cardId}-lang-ac-wrap">
              <input class="edit-input" id="${cardId}-lang-in"
                value="${esc(b.language||'')}"
                placeholder="Add existing or create new language\u2026"
                autocomplete="off"
                onclick="event.stopPropagation()"
                oninput="onLangInput('${cardId}')"
                onkeydown="onLangKeydown(event,'${cardId}')">
              <div class="genre-dropdown" id="${cardId}-lang-drop" style="display:none"></div>
            </div>
            <button class="btn-edit-save" onclick="saveLanguage('${cardId}');event.stopPropagation()">Save</button>
            <span class="save-indicator" id="${cardId}-lang-saved">✓ Saved</span>
          </div>
          <div class="edit-error" id="${cardId}-lang-err"></div>
        </span>

        <span class="dt">Path</span><span class="dd" id="${cardId}-path-display">${esc(b.relative_path||'—')}</span>
        <span class="dt">Sources</span><span class="dd">${esc(b.sources||'—')}</span>
        <span class="dt">Cached</span><span class="dd">${esc(b.ts_fmt||'—')}</span>

        <span class="dt">Genres</span>
        <span class="dd">
          <div class="tag-editor" id="${cardId}-tags"></div>
          <div class="tag-add-row">
            <div class="genre-ac-wrap" id="${cardId}-ac-wrap">
              <input class="edit-input" id="${cardId}-genre-in"
                placeholder="Add existing or create new tagâ¦"
                autocomplete="off"
                onclick="event.stopPropagation()"
                oninput="onGenreInput('${cardId}')"
                onkeydown="onGenreKeydown(event,'${cardId}')">
              <div class="genre-dropdown" id="${cardId}-genre-drop" style="display:none"></div>
            </div>
            <button class="btn-add-tag" onclick="addTag('${cardId}');event.stopPropagation()">Add</button>
            <span class="save-indicator" id="${cardId}-saved">✓ Saved</span>
          </div>
        </span>

        <span class="dt">Original</span><span class="dd" style="font-family:monospace;font-size:11px">${esc(b.original_path||'—')}</span>
      </div>
      <button class="btn-delete" onclick="openDeleteModal('${cardId}');event.stopPropagation()">
        🗑️ Delete book
      </button>
    </div>
  </div>`;
}

function renderBooks(container, data, prevFn, nextFn) {
  if(!data.books||!data.books.length){ container.innerHTML='<div class="empty">No books found.</div>'; return; }
  const tot = data.total, off = data.offset, shown = off+data.books.length;
  container.innerHTML = `
    <div class="results-meta">${tot.toLocaleString()} book${tot!==1?'s':''} — showing ${off+1}–${shown}</div>
    <div class="book-list">${data.books.map(bookCard).join('')}</div>
    <div class="pager">
      <button class="pg-btn" onclick="${prevFn}" ${off>0?'':'disabled'}>← Prev</button>
      <span>${Math.floor(off/SZ)+1} / ${Math.ceil(tot/SZ)||1}</span>
      <button class="pg-btn" onclick="${nextFn}" ${shown<tot?'':'disabled'}>Next →</button>
    </div>`;
}

// ── Search ──
async function doSearch(delta=0) {
  const q = document.getElementById('search-q').value.trim();
  const el = document.getElementById('search-res');
  if(!q){ el.innerHTML=''; return; }
  sOff = Math.max(0, sOff+delta);
  el.innerHTML='<div class="loading">Searching…</div>';
  const d = await (await fetch(`/api/books?q=${encodeURIComponent(q)}&limit=${SZ}&offset=${sOff}`)).json();
  renderBooks(el, d, `doSearch(-${SZ})`, `doSearch(${SZ})`);
}

// ── All ──
async function loadAll(delta=0) {
  const el = document.getElementById('all-res');
  aOff = Math.max(0, aOff+delta);
  el.innerHTML='<div class="loading">Loading…</div>';
  const d = await (await fetch(`/api/books?limit=${SZ}&offset=${aOff}`)).json();
  renderBooks(el, d, `loadAll(-${SZ})`, `loadAll(${SZ})`);
}

// ── Genres ──
let curGenre = null;
async function loadGenres() {
  const grid = document.getElementById('genre-grid');
  grid.dataset.ok = 1;
  const genres = await (await fetch('/api/genres')).json();
  grid.innerHTML = genres.map(([g,c])=>
    `<div class="genre-tile" id="gt-${esc(g)}" onclick="selectGenre('${esc(g)}')">
      <span class="genre-name">${esc(g)}</span>
      <span class="genre-count">${c}</span>
    </div>`).join('');
}

async function selectGenre(genre) {
  curGenre = genre;
  document.querySelectorAll('.genre-tile').forEach(t=>t.classList.remove('sel'));
  const tile = document.getElementById('gt-'+genre);
  if(tile){ tile.classList.add('sel'); tile.scrollIntoView({block:'nearest'}); }
  const el = document.getElementById('genre-res');
  el.innerHTML='<div class="loading">Loading…</div>';
  const d = await (await fetch(`/api/books?genre=${encodeURIComponent(genre)}&limit=${SZ}`)).json();
  renderBooks(el, d, `selectGenre('${esc(genre)}')`, `selectGenre('${esc(genre)}')`);
  el.scrollIntoView({behavior:'smooth', block:'start'});
}

function gotoGenre(genre) {
  // Switch to genres tab and select
  document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b=>b.classList.remove('active'));
  document.getElementById('page-genres').classList.add('active');
  document.querySelectorAll('.nav-btn')[2].classList.add('active');
  if(!document.getElementById('genre-grid').dataset.ok) {
    loadGenres().then(()=>selectGenre(genre));
  } else {
    selectGenre(genre);
  }
}

// ── Directories ──
async function loadDirs() {
  const grid = document.getElementById('dir-grid');
  grid.dataset.ok = 1;
  const dirs = await (await fetch('/api/directories')).json();
  grid.innerHTML = dirs.map(d=>
    `<div class="dir-card" id="dc-${esc(d.directory)}" onclick="selectDir('${esc(d.directory)}')">
      <span class="dir-emoji">${DIR_ICONS[d.directory]||'📁'}</span>
      <div><div class="dir-name">${esc(d.directory||'—')}</div><div class="dir-cnt">${d.count} book${d.count!==1?'s':''}</div></div>
    </div>`).join('');
}

async function selectDir(dir) {
  document.querySelectorAll('.dir-card').forEach(c=>c.classList.remove('sel'));
  const card = document.getElementById('dc-'+dir);
  if(card) card.classList.add('sel');
  const el = document.getElementById('dir-res');
  el.innerHTML='<div class="loading">Loading…</div>';
  const d = await (await fetch(`/api/books?dir=${encodeURIComponent(dir)}&limit=${SZ}`)).json();
  renderBooks(el, d, `selectDir('${esc(dir)}')`, `selectDir('${esc(dir)}')`);
  el.scrollIntoView({behavior:'smooth', block:'start'});
}

// ── Cache ──
async function doCache() {
  const q  = document.getElementById('cache-q').value.trim();
  const el = document.getElementById('cache-res');
  if(!q){ el.innerHTML=''; return; }
  el.innerHTML='<div class="loading">Searching…</div>';
  const rows = await (await fetch(`/api/cache?q=${encodeURIComponent(q)}`)).json();
  if(!rows.length){ el.innerHTML='<div class="empty">No entries found.</div>'; return; }
  el.innerHTML = rows.map(r=>`
    <div class="cache-card">
      <div class="cache-key">${esc(r.key)}</div>
      <div class="cache-ts">${esc(r.ts_fmt)}</div>
      <div class="cache-json">${esc(JSON.stringify(r.data,null,2))}</div>
    </div>`).join('');
}

// ── Languages ──
async function loadLangs() {
  const grid = document.getElementById('lang-grid');
  grid.dataset.ok = 1;
  const dirs = await (await fetch('/api/directories')).json(); // reuse for total ref
  const d = await (await fetch('/api/stats')).json();
  grid.innerHTML = d.by_language.map(r =>
    `<div class="genre-tile" id="lt-${esc(r.language||'')}" onclick="selectLang(${r.language == null ? 'null' : `'${esc(r.language)}'`})">
      <span class="genre-name">${esc(r.language||'unknown')}</span>
      <span class="genre-count">${r.count}</span>
    </div>`).join('');
}

async function selectLang(lang) {
  document.querySelectorAll('.genre-tile').forEach(t => {
    if (t.closest('#lang-grid')) t.classList.remove('sel');
  });
  // lang is null for books with no language set
  const tileId = 'lt-' + (lang == null ? '' : lang);
  const tile = document.getElementById(tileId);
  if (tile) { tile.classList.add('sel'); tile.scrollIntoView({block:'nearest'}); }
  const el = document.getElementById('lang-res');
  el.innerHTML = '<div class="loading">Loading…</div>';
  // Use language= filter: empty string means "books with no language set"
  const param = lang == null ? '' : lang;
  const d = await (await fetch(`/api/books?language=${encodeURIComponent(param)}&limit=${SZ}`)).json();
  const reloadExpr = lang == null ? `selectLang(null)` : `selectLang('${esc(lang)}')`;
  renderBooks(el, d, reloadExpr, reloadExpr);
  el.scrollIntoView({behavior:'smooth', block:'start'});
}

// ── Helper: navigate to a page by name ──
function gotoPage(page) {
  const btns = document.querySelectorAll('.nav-btn');
  const pageOrder = ['stats','search','genres','dirs','langs','all','cache'];
  const idx = pageOrder.indexOf(page);
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('page-'+page).classList.add('active');
  if (idx >= 0 && btns[idx]) btns[idx].classList.add('active');
  if (page==='langs' && !document.getElementById('lang-grid').dataset.ok) loadLangs();
  if (page==='dirs'  && !document.getElementById('dir-grid').dataset.ok)  loadDirs();
  if (page==='all')  { aOff=0; loadAll(); }
}

// ── Card expand with cover load ──
async function toggleCard(event, el) {
  // Don't collapse if click was inside the detail (selects, buttons, chips)
  if (event.target.closest('.book-detail') && el.classList.contains('expanded')) return;
  el.classList.toggle('expanded');
  if (!el.classList.contains('expanded')) return;

  // Read title/author from data attributes (avoids single-quote injection in onclick)
  const title  = el.dataset.title  || '';
  const author = el.dataset.author || '';

  // Initialise tag editor (once)
  const cardId = el.id;
  if (!el.dataset.tagsInit) {
    el.dataset.tagsInit = 1;
    const genres = JSON.parse(el.dataset.genres || '[]');
    renderTagEditor(cardId, genres);
  }

  // Cover (once)
  const coverEl = document.getElementById(cardId + '-cover');
  if (coverEl && !coverEl.dataset.loaded) {
    coverEl.dataset.loaded = 1;
    try {
      const c = await (await fetch(`/api/cover?title=${encodeURIComponent(title)}&author=${encodeURIComponent(author)}`)).json();
      if (c.url) { showCover(coverEl, c.url); return; }
    } catch(e) {}
    try {
      const q   = encodeURIComponent(`intitle:"${title}" inauthor:"${author}"`);
      const res = await fetch(`https://www.googleapis.com/books/v1/volumes?q=${q}&maxResults=1`);
      const d   = await res.json();
      const img = d?.items?.[0]?.volumeInfo?.imageLinks?.thumbnail;
      if (img) { showCover(coverEl, img.replace('http://','https://').replace('&zoom=1','&zoom=2')); return; }
    } catch(e) {}
    try {
      const q   = encodeURIComponent(`${title} ${author}`);
      const res = await fetch(`https://openlibrary.org/search.json?q=${q}&limit=1&fields=cover_i`);
      const d   = await res.json();
      const id  = d?.docs?.[0]?.cover_i;
      if (id) { showCover(coverEl, `https://covers.openlibrary.org/b/id/${id}-M.jpg`); return; }
    } catch(e) {}
  }
}

function showCover(el, url) {
  el.innerHTML = `<img class="cover-img" src="${esc(url)}" alt="Cover"
    onerror="this.parentElement.innerHTML='<div class=cover-placeholder>📖</div>'">`;
}

// ── Tag editor ──
let _allGenres = null; // cached genre list (invalidated after saves)

async function _fetchAllGenres() {
  if (_allGenres) return _allGenres;
  const data = await (await fetch('/api/genres')).json();
  _allGenres = data.map(([g]) => g).sort();
  return _allGenres;
}

function renderTagEditor(cardId, genres) {
  const el = document.getElementById(cardId + '-tags');
  if (!el) return;
  el.innerHTML = genres.length
    ? `<div class="chip-row">${genres.map(g => `
        <span class="chip-editable">
          <span onclick="gotoGenre('${esc(g)}');event.stopPropagation()" style="cursor:pointer">${esc(g)}</span>
          <button class="chip-remove" title="Remove" onclick="removeTag('${cardId}','${esc(g)}');event.stopPropagation()">×</button>
        </span>`).join('')}</div>`
    : `<span style="color:var(--text-3);font-size:12px;font-style:italic">No genres — add one below</span>`;
}

function getCardGenres(cardId) {
  const card = document.getElementById(cardId);
  return JSON.parse(card.dataset.genres || '[]');
}

function setCardGenres(cardId, genres) {
  const card = document.getElementById(cardId);
  card.dataset.genres = JSON.stringify(genres);
}

// ── Autocomplete dropdown ──

let _acActive = null; // cardId that currently owns the open dropdown

function hideGenreDropdown(cardId) {
  const drop = document.getElementById(cardId + '-genre-drop');
  if (drop) drop.style.display = 'none';
  if (_acActive === cardId) _acActive = null;
}

function _renderDropdown(cardId, items) {
  const drop = document.getElementById(cardId + '-genre-drop');
  if (!drop) return;
  if (!items.length) { drop.style.display = 'none'; return; }

  drop.innerHTML = items.map((item, idx) => `
    <div class="genre-drop-item${item.isCreate ? ' genre-drop-create' : ''}"
         data-idx="${idx}"
         data-value="${esc(item.value)}"
         onmousedown="event.preventDefault()"
         onclick="_dropSelect('${cardId}',${idx});event.stopPropagation()">
      ${item.isCreate
        ? `<span class="genre-drop-icon">&#10010;</span> Create new tag <strong>&quot;${esc(item.value)}&quot;</strong>`
        : esc(item.label)
      }
    </div>`).join('');

  drop.style.display = 'block';
  _acActive = cardId;
}

function _dropHighlight(cardId, delta) {
  const items = Array.from(
    document.querySelectorAll(`#${cardId}-genre-drop .genre-drop-item`)
  );
  if (!items.length) return;
  const cur = items.findIndex(el => el.classList.contains('active'));
  let next = cur + delta;
  if (next < 0) next = items.length - 1;
  if (next >= items.length) next = 0;
  items.forEach(el => el.classList.remove('active'));
  items[next].classList.add('active');
  items[next].scrollIntoView({block: 'nearest'});
}

function _dropSelect(cardId, idx) {
  const drop = document.getElementById(cardId + '-genre-drop');
  if (!drop) return;
  const item = drop.querySelectorAll('.genre-drop-item')[idx];
  if (!item) return;
  const value = item.dataset.value;
  hideGenreDropdown(cardId);
  _commitTag(cardId, value);
}

async function onGenreInput(cardId) {
  const input = document.getElementById(cardId + '-genre-in');
  const q = (input?.value || '').trim();

  if (!q) { hideGenreDropdown(cardId); return; }

  const all    = await _fetchAllGenres();
  const active = getCardGenres(cardId).map(g => g.toLowerCase());
  const ql     = q.toLowerCase();

  // Prefix matches first, then substring, exclude already-assigned genres
  const matches = all
    .filter(g => !active.includes(g.toLowerCase()))
    .filter(g => g.toLowerCase().includes(ql))
    .sort((a, b) => {
      const aStarts = a.toLowerCase().startsWith(ql);
      const bStarts = b.toLowerCase().startsWith(ql);
      if (aStarts !== bStarts) return aStarts ? -1 : 1;
      return a.localeCompare(b);
    })
    .slice(0, 8);

  const items = matches.map(g => ({label: g, value: g, isCreate: false}));

  // Always show "Create" when typed text is not an exact existing match
  const exactMatch = all.some(g => g.toLowerCase() === ql);
  if (!exactMatch) {
    items.push({label: q, value: q, isCreate: true});
  }

  _renderDropdown(cardId, items);
}

function onGenreKeydown(event, cardId) {
  const drop = document.getElementById(cardId + '-genre-drop');
  const open = drop && drop.style.display !== 'none';

  if (event.key === 'ArrowDown') {
    event.preventDefault();
    if (!open) onGenreInput(cardId);
    else _dropHighlight(cardId, 1);
  } else if (event.key === 'ArrowUp') {
    event.preventDefault();
    if (open) _dropHighlight(cardId, -1);
  } else if (event.key === 'Enter') {
    event.stopPropagation();
    if (open) {
      const activeItem = document.querySelector(`#${cardId}-genre-drop .genre-drop-item.active`);
      if (activeItem) {
        _dropSelect(cardId, parseInt(activeItem.dataset.idx, 10));
      } else {
        addTag(cardId);
      }
    } else {
      addTag(cardId);
    }
  } else if (event.key === 'Escape') {
    hideGenreDropdown(cardId);
  }
}

async function _commitTag(cardId, genre) {
  genre = genre.trim();
  if (!genre) return;
  const genres = getCardGenres(cardId);
  if (genres.map(g => g.toLowerCase()).includes(genre.toLowerCase())) return;
  genres.push(genre);
  setCardGenres(cardId, genres);
  renderTagEditor(cardId, genres);
  const input = document.getElementById(cardId + '-genre-in');
  if (input) input.value = '';
  await persistGenres(cardId, genres);
}

async function removeTag(cardId, genre) {
  const genres = getCardGenres(cardId).filter(g => g !== genre);
  setCardGenres(cardId, genres);
  renderTagEditor(cardId, genres);
  await persistGenres(cardId, genres);
}

async function addTag(cardId) {
  const input = document.getElementById(cardId + '-genre-in');
  const genre = (input?.value || '').trim();
  if (!genre) return;
  hideGenreDropdown(cardId);
  await _commitTag(cardId, genre);
}

// ── Author edit ──
async function saveAuthor(cardId) {
  const card    = document.getElementById(cardId);
  const input   = document.getElementById(cardId + '-author-in');
  const errEl   = document.getElementById(cardId + '-author-err');
  const savedEl = document.getElementById(cardId + '-author-saved');
  const newAuthor = (input?.value || '').trim();
  if (!newAuthor) return;
  errEl.classList.remove('show');
  try {
    const res = await fetch('/api/books/author', {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({original_path: card.dataset.originalPath, author: newAuthor})
    });
    const d = await res.json();
    if (!d.ok) { errEl.textContent = d.error||'Error'; errEl.classList.add('show'); return; }
    card.dataset.author  = d.author;
    card.dataset.relPath = d.relative_path;
    const authorDisplay = document.getElementById(cardId + '-author-display');
    if (authorDisplay) authorDisplay.textContent = d.author;
    const pathDisplay = document.getElementById(cardId + '-path-display');
    if (pathDisplay) pathDisplay.textContent = d.relative_path;
    savedEl.classList.add('show');
    setTimeout(() => savedEl.classList.remove('show'), 1800);
  } catch(e) { errEl.textContent = String(e); errEl.classList.add('show'); }
}

// ── Directory edit ──
async function saveDirectory(cardId) {
  const card    = document.getElementById(cardId);
  const sel     = document.getElementById(cardId + '-dir-in');
  const errEl   = document.getElementById(cardId + '-dir-err');
  const savedEl = document.getElementById(cardId + '-dir-saved');
  const newDir  = sel?.value;
  if (!newDir) return;
  errEl.classList.remove('show');
  try {
    const res = await fetch('/api/books/directory', {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({original_path: card.dataset.originalPath, directory: newDir})
    });
    const d = await res.json();
    if (!d.ok) { errEl.textContent = d.error||'Error'; errEl.classList.add('show'); return; }
    card.dataset.directory = d.directory;
    card.dataset.relPath   = d.relative_path;
    const dot = card.querySelector('.book-dot');
    if (dot) dot.className = `book-dot ${d.directory}`;
    const dirDisplay = document.getElementById(cardId + '-dir-display');
    if (dirDisplay) dirDisplay.textContent = d.directory;
    const pathDisplay = document.getElementById(cardId + '-path-display');
    if (pathDisplay) pathDisplay.textContent = d.relative_path;
    savedEl.classList.add('show');
    setTimeout(() => savedEl.classList.remove('show'), 1800);
  } catch(e) { errEl.textContent = String(e); errEl.classList.add('show'); }
}


// ── Title edit ──
async function saveTitle(cardId) {
  const card    = document.getElementById(cardId);
  const input   = document.getElementById(cardId + '-title-in');
  const errEl   = document.getElementById(cardId + '-title-err');
  const savedEl = document.getElementById(cardId + '-title-saved');
  const newTitle = (input?.value || '').trim();
  if (!newTitle) return;
  errEl.classList.remove('show');
  try {
    const res = await fetch('/api/books/title', {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({original_path: card.dataset.originalPath, title: newTitle})
    });
    const d = await res.json();
    if (!d.ok) { errEl.textContent = d.error||'Error'; errEl.classList.add('show'); return; }
    card.dataset.title = d.title;
    const titleDisplay = card.querySelector('.book-title');
    if (titleDisplay) titleDisplay.textContent = d.title;
    savedEl.classList.add('show');
    setTimeout(() => savedEl.classList.remove('show'), 1800);
  } catch(e) { errEl.textContent = String(e); errEl.classList.add('show'); }
}

// ── Language edit ──
let _allLanguages = null; // cached language list (invalidated after saves)

async function _fetchAllLanguages() {
  if (_allLanguages) return _allLanguages;
  const data = await (await fetch('/api/stats')).json();
  _allLanguages = (data.by_language || []).map(r => r.language).filter(Boolean).sort();
  return _allLanguages;
}

async function onLangInput(cardId) {
  const input = document.getElementById(cardId + '-lang-in');
  const q = (input?.value || '').trim();
  if (!q) { hideLangDropdown(cardId); return; }

  const all = await _fetchAllLanguages();
  const ql  = q.toLowerCase();

  const matches = all
    .filter(l => l.toLowerCase().includes(ql))
    .sort((a, b) => {
      const aStarts = a.toLowerCase().startsWith(ql);
      const bStarts = b.toLowerCase().startsWith(ql);
      if (aStarts !== bStarts) return aStarts ? -1 : 1;
      return a.localeCompare(b);
    })
    .slice(0, 8);

  const items = matches.map(l => ({label: l, value: l, isCreate: false}));
  const exactMatch = all.some(l => l.toLowerCase() === ql);
  if (!exactMatch) items.push({label: q, value: q, isCreate: true});

  _renderLangDropdown(cardId, items);
}

function _renderLangDropdown(cardId, items) {
  const drop = document.getElementById(cardId + '-lang-drop');
  if (!drop) return;
  if (!items.length) { drop.style.display = 'none'; return; }

  drop.innerHTML = items.map((item, idx) => `
    <div class="genre-drop-item${item.isCreate ? ' genre-drop-create' : ''}"
         data-idx="${idx}"
         data-value="${esc(item.value)}"
         onmousedown="event.preventDefault()"
         onclick="_langDropSelect('${cardId}',${idx});event.stopPropagation()">
      ${item.isCreate
        ? `<span class="genre-drop-icon">&#10010;</span> Add new language <strong>&quot;${esc(item.value)}&quot;</strong>`
        : esc(item.label)
      }
    </div>`).join('');
  drop.style.display = 'block';
}

function hideLangDropdown(cardId) {
  const drop = document.getElementById(cardId + '-lang-drop');
  if (drop) drop.style.display = 'none';
}

function _langDropHighlight(cardId, delta) {
  const items = Array.from(
    document.querySelectorAll(`#${cardId}-lang-drop .genre-drop-item`)
  );
  if (!items.length) return;
  const cur = items.findIndex(el => el.classList.contains('active'));
  let next = cur + delta;
  if (next < 0) next = items.length - 1;
  if (next >= items.length) next = 0;
  items.forEach(el => el.classList.remove('active'));
  items[next].classList.add('active');
  items[next].scrollIntoView({block: 'nearest'});
}

function _langDropSelect(cardId, idx) {
  const drop = document.getElementById(cardId + '-lang-drop');
  if (!drop) return;
  const item = drop.querySelectorAll('.genre-drop-item')[idx];
  if (!item) return;
  const input = document.getElementById(cardId + '-lang-in');
  if (input) input.value = item.dataset.value;
  hideLangDropdown(cardId);
}

function onLangKeydown(event, cardId) {
  const drop = document.getElementById(cardId + '-lang-drop');
  const open = drop && drop.style.display !== 'none';

  if (event.key === 'ArrowDown') {
    event.preventDefault();
    if (!open) onLangInput(cardId);
    else _langDropHighlight(cardId, 1);
  } else if (event.key === 'ArrowUp') {
    event.preventDefault();
    if (open) _langDropHighlight(cardId, -1);
  } else if (event.key === 'Enter') {
    event.stopPropagation();
    if (open) {
      const activeItem = document.querySelector(`#${cardId}-lang-drop .genre-drop-item.active`);
      if (activeItem) {
        _langDropSelect(cardId, parseInt(activeItem.dataset.idx, 10));
      } else {
        saveLanguage(cardId);
      }
    } else {
      saveLanguage(cardId);
    }
  } else if (event.key === 'Escape') {
    hideLangDropdown(cardId);
  }
}

async function saveLanguage(cardId) {
  const card    = document.getElementById(cardId);
  const input   = document.getElementById(cardId + '-lang-in');
  const errEl   = document.getElementById(cardId + '-lang-err');
  const savedEl = document.getElementById(cardId + '-lang-saved');
  const newLang = (input?.value || '').trim();
  if (!newLang) return;
  hideLangDropdown(cardId);
  errEl.classList.remove('show');
  try {
    const res = await fetch('/api/books/language', {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({original_path: card.dataset.originalPath, language: newLang})
    });
    const d = await res.json();
    if (!d.ok) { errEl.textContent = d.error||'Error'; errEl.classList.add('show'); return; }
    card.dataset.language = d.language;
    // Update the language badge in the book header
    const langDisplay = document.getElementById(cardId + '-lang-display');
    if (langDisplay) {
      langDisplay.textContent = d.language;
      langDisplay.style.display = '';
    }
    // Invalidate language cache so next card sees the new language if it was created
    _allLanguages = null;
    savedEl.classList.add('show');
    setTimeout(() => savedEl.classList.remove('show'), 1800);
  } catch(e) { errEl.textContent = String(e); errEl.classList.add('show'); }
}

async function persistGenres(cardId, genres) {
  const card         = document.getElementById(cardId);
  const originalPath = card.dataset.originalPath || card.getAttribute('data-original-path');
  const savedEl      = document.getElementById(cardId + '-saved');
  try {
    const res = await fetch('/api/books/genres', {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({original_path: originalPath, genres})
    });
    const d = await res.json();
    if (d.ok && savedEl) {
      savedEl.classList.add('show');
      setTimeout(() => savedEl.classList.remove('show'), 1800);
      // Invalidate global genre cache so next expand sees updated list
      _allGenres = null;
    }
  } catch(e) {
    console.error('Failed to save genres', e);
  }
}

// ── Duplicates panel ──
let _dupsLoaded = false;

function toggleDuplicatesPanel() {
  const panel = document.getElementById('duplicates-panel');
  if (!panel) return;
  const visible = panel.style.display !== 'none';
  panel.style.display = visible ? 'none' : 'block';
  if (!visible) {
    if (!_dupsLoaded) loadDuplicates();
    setTimeout(() => panel.scrollIntoView({behavior:'smooth', block:'start'}), 50);
  }
}

async function loadDuplicates() {
  const el = document.getElementById('duplicates-content');
  if (!el) return;
  _dupsLoaded = true;
  try {
    const d = await (await fetch('/api/duplicates')).json();
    if (!d.length) {
      el.innerHTML = '<div class="empty">No duplicate files found.</div>';
      return;
    }
    const safe       = d.filter(r => r.safe);
    const suspicious = d.filter(r => !r.safe);
    let html = '';
    if (safe.length) {
      html += `<div class="dup-section-title">Safe to delete (${safe.length})</div>`;
      html += safe.map(r => dupRow(r)).join('');
    }
    if (suspicious.length) {
      html += `<div class="dup-section-title dup-warn">⚠ Different size — review manually (${suspicious.length})</div>`;
      html += suspicious.map(r => dupRow(r, true)).join('');
    }
    el.innerHTML = `<div class="dup-note">Run <code>python deduplicate_books.py --delete</code> to remove safe duplicates.</div>${html}`;
  } catch(e) {
    el.innerHTML = `<div class="empty">Error loading duplicates: ${esc(String(e))}</div>`;
  }
}

function dupRow(r, warn=false) {
  return `<div class="dup-row ${warn?'dup-row-warn':''}">
    <span class="dup-icon">${warn?'⚠':'🗑'}</span>
    <div class="dup-info">
      <div class="dup-name">${esc(r.rel)}</div>
      <div class="dup-meta">canonical: ${esc(r.canon_rel)} ${r.has_canon?(warn?'<span class="dup-badge-warn">different size</span>':'<span class="dup-badge-ok">same size</span>'):'<span class="dup-badge-missing">no canonical</span>'}</div>
    </div>
  </div>`;
}

// ── Similar Authors ──
let _authorsLoaded = false;
let _pendingMerges = [];  // [{source, target}, …]

async function loadSimilarAuthors() {
  const res  = document.getElementById('authors-res');
  const tb   = document.getElementById('authors-toolbar');
  if (!res) return;
  _authorsLoaded = false;
  res.innerHTML = '<div class="loading">Scanning authors…</div>';
  if (tb) tb.style.display = 'none';

  try {
    const pairs = await (await fetch('/api/authors/similar')).json();
    if (!pairs.length) {
      res.innerHTML = '<div class="empty">No similar author names detected.</div>';
      return;
    }

    if (tb) tb.style.display = 'flex';
    _authorsLoaded = true;
    updateMergeButton();

    res.innerHTML = `
      <div class="authors-hint">
        For each pair, tick the checkbox to include it in the merge, then pick which name to keep.
      </div>
      <div class="author-pairs">
        ${pairs.map((p, i) => authorPairRow(p, i)).join('')}
      </div>`;
  } catch(e) {
    res.innerHTML = `<div class="empty">Error: ${esc(String(e))}</div>`;
  }
}

function authorPairRow(p, i) {
  const scoreClass = p.score >= 0.97 ? 'sim-high' : p.score >= 0.90 ? 'sim-med' : 'sim-low';
  const scorePct   = Math.round(p.score * 100);
  return `
  <div class="author-pair" id="apair-${i}" data-idx="${i}"
       data-a="${esc(p.author_a)}" data-b="${esc(p.author_b)}">
    <label class="pair-check-wrap" title="Include in merge">
      <input type="checkbox" class="pair-check" onchange="onPairCheck(${i})">
    </label>
    <div class="pair-score ${scoreClass}" title="Similarity score">${scorePct}%</div>
    <div class="pair-authors">
      <label class="author-option">
        <input type="radio" name="target-${i}" value="a" checked
               onchange="onTargetChange(${i})">
        <span class="author-pill author-pill-a">${esc(p.author_a)}</span>
        <span class="author-book-count">${p.books_a} book${p.books_a!==1?'s':''}</span>
      </label>
      <span class="pair-arrow">⇄</span>
      <label class="author-option">
        <input type="radio" name="target-${i}" value="b"
               onchange="onTargetChange(${i})">
        <span class="author-pill author-pill-b">${esc(p.author_b)}</span>
        <span class="author-book-count">${p.books_b} book${p.books_b!==1?'s':''}</span>
      </label>
    </div>
    <div class="pair-status" id="apair-status-${i}"></div>
  </div>`;
}

function onPairCheck(i) {
  updateMergeButton();
}

function onTargetChange(i) {
  // visual cue — highlight the selected target pill
  const row = document.getElementById(`apair-${i}`);
  if (!row) return;
  row.querySelectorAll('.author-pill').forEach(el => el.classList.remove('pill-target'));
  const sel = row.querySelector(`input[name="target-${i}"]:checked`);
  if (sel) {
    const pill = sel.closest('label').querySelector('.author-pill');
    if (pill) pill.classList.add('pill-target');
  }
}

function getCheckedPairs() {
  const pairs = [];
  document.querySelectorAll('.pair-check:checked').forEach(cb => {
    const row = cb.closest('.author-pair');
    const i   = parseInt(row.dataset.idx);
    const sel = row.querySelector(`input[name="target-${i}"]:checked`);
    const target = sel?.value === 'b' ? row.dataset.b : row.dataset.a;
    const source = sel?.value === 'b' ? row.dataset.a : row.dataset.b;
    pairs.push({source, target, idx: i});
  });
  return pairs;
}

function updateMergeButton() {
  const btn  = document.getElementById('btn-merge-selected');
  const hint = document.getElementById('merge-hint');
  if (!btn) return;
  const n = getCheckedPairs().length;
  btn.disabled = n === 0;
  if (hint) hint.textContent = n > 0 ? `${n} pair${n!==1?'s':''} selected` : '';
}

function mergeSelected() {
  _pendingMerges = getCheckedPairs();
  if (!_pendingMerges.length) return;
  const n = _pendingMerges.length;
  const lines = _pendingMerges.map(p =>
    `<div class="merge-preview-row"><b>${esc(p.source)}</b> → <b>${esc(p.target)}</b></div>`
  ).join('');
  document.getElementById('merge-modal-title').textContent =
    `Merge ${n} author pair${n!==1?'s':''}?`;
  document.getElementById('merge-modal-body').innerHTML =
    `${lines}<br>Books will be moved into the target author folder. ` +
    `Identical files already present will be skipped. This cannot be undone.`;
  document.getElementById('merge-modal').classList.add('show');
}

function closeMergeModal() {
  document.getElementById('merge-modal').classList.remove('show');
  _pendingMerges = [];
}

async function confirmMerge() {
  const btn = document.getElementById('merge-confirm-btn');
  btn.textContent = 'Merging…';
  btn.disabled = true;

  let allOk = true;
  for (const p of _pendingMerges) {
    const statusEl = document.getElementById(`apair-status-${p.idx}`);
    try {
      const res = await fetch('/api/authors/merge', {
        method:  'POST',
        headers: {'Content-Type':'application/json'},
        body:    JSON.stringify({source: p.source, target: p.target}),
      });
      const d = await res.json();
      if (d.ok) {
        if (statusEl) statusEl.innerHTML =
          `<span class="merge-ok">✓ Merged — ${d.moved} moved, ${d.skipped} skipped</span>`;
        // grey out the pair row
        const row = document.getElementById(`apair-${p.idx}`);
        if (row) row.classList.add('pair-merged');
      } else {
        if (statusEl) statusEl.innerHTML =
          `<span class="merge-err">✗ ${esc(d.error||'error')}</span>`;
        allOk = false;
      }
    } catch(e) {
      if (statusEl) statusEl.innerHTML =
        `<span class="merge-err">✗ ${esc(String(e))}</span>`;
      allOk = false;
    }
  }

  closeMergeModal();
  btn.textContent = 'Merge';
  btn.disabled = false;

  // Invalidate stats so overview refreshes
  const sc = document.getElementById('stats-content');
  if (sc) sc.dataset.ok = '';

  // Reload pairs (merged ones will be gone or have updated counts)
  if (allOk) {
    setTimeout(loadSimilarAuthors, 400);
  }
}

// Close merge modal on overlay click
document.getElementById('merge-modal')?.addEventListener('click', function(e) {
  if (e.target === this) closeMergeModal();
});

// ── Delete book ──
let _deleteCardId = null;

function openDeleteModal(cardId) {
  _deleteCardId = cardId;
  const card  = document.getElementById(cardId);
  const title = card?.dataset.title || 'this book';
  document.getElementById('modal-book-name').textContent = title;
  document.getElementById('delete-modal').classList.add('show');
}

function closeDeleteModal() {
  document.getElementById('delete-modal').classList.remove('show');
  _deleteCardId = null;
}

async function confirmDelete() {
  if (!_deleteCardId) return;
  const cardId = _deleteCardId;
  const card   = document.getElementById(cardId);
  const originalPath = card?.dataset.originalPath || card?.getAttribute('data-original-path');

  const confirmBtn = document.getElementById('modal-confirm-btn');
  confirmBtn.textContent = 'Deleting…';
  confirmBtn.disabled = true;

  try {
    const res = await fetch('/api/books', {
      method:  'DELETE',
      headers: {'Content-Type': 'application/json'},
      body:    JSON.stringify({original_path: originalPath}),
    });
    const d = await res.json();
    if (!d.ok) {
      confirmBtn.textContent = 'Delete';
      confirmBtn.disabled = false;
      alert('Error: ' + (d.error || 'Unknown error'));
      return;
    }
    closeDeleteModal();
    // Animate card out and remove from DOM
    card.style.transition = 'opacity .25s, transform .25s';
    card.style.opacity    = '0';
    card.style.transform  = 'translateX(-12px)';
    setTimeout(() => card.remove(), 260);
    // Invalidate stats so the overview refreshes on next visit
    document.getElementById('stats-content').dataset.ok = '';
  } catch(e) {
    alert('Error: ' + e);
  } finally {
    confirmBtn.textContent = 'Delete';
    confirmBtn.disabled = false;
  }
}

// Close modal on overlay click
document.getElementById('delete-modal')?.addEventListener('click', function(e) {
  if (e.target === this) closeDeleteModal();
});

// ── Dark mode ──
function toggleTheme() {
  const dark = document.documentElement.getAttribute('data-theme') === 'dark';
  document.documentElement.setAttribute('data-theme', dark ? 'light' : 'dark');
  const btn  = document.getElementById('theme-btn');
  const icon = document.getElementById('theme-icon');
  if (dark) {
    icon.textContent = '🌙';
    btn.innerHTML = '<span id="theme-icon">🌙</span> Dark mode';
  } else {
    btn.innerHTML = '<span id="theme-icon">☀️</span> Light mode';
  }
  localStorage.setItem('theme', dark ? 'light' : 'dark');
}

// ── Init ──
(function() {
  const saved = localStorage.getItem('theme') || 'light';
  document.documentElement.setAttribute('data-theme', saved);
  if (saved === 'dark') {
    document.addEventListener('DOMContentLoaded', () => {
      const btn = document.getElementById('theme-btn');
      if (btn) btn.innerHTML = '<span id="theme-icon">☀️</span> Light mode';
    });
  }
})();
// Close any open genre dropdown when clicking outside it
document.addEventListener('click', () => {
  if (_acActive) hideGenreDropdown(_acActive);
  // Close any open language dropdowns
  document.querySelectorAll('.genre-dropdown[id$="-lang-drop"]').forEach(d => {
    if (d.style.display !== 'none') {
      const cardId = d.id.replace('-lang-drop', '');
      hideLangDropdown(cardId);
    }
  });
});
document.getElementById('nav-db-path').textContent = '{{ db_path }}';
// Load overview immediately on first page visit (don't wait for nav click)
loadStats();
"""
