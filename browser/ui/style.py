"""
browser/ui/style.py — all CSS for the Book Library web UI.
"""

CSS = r"""
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg:        #f5f6fa;
  --surface:   #ffffff;
  --surface2:  #f0f1f7;
  --border:    #e4e6ef;
  --accent:    #5b5ef5;
  --accent-lt: #ededfe;
  --accent-dk: #3c3ecc;
  --text:      #1a1b2e;
  --text-2:    #6b6e8e;
  --text-3:    #a0a3bc;
  --green:     #22c55e;
  --yellow:    #eab308;
  --red:       #ef4444;
  --r:         10px;
  --shadow:    0 1px 3px rgba(0,0,0,.07), 0 4px 16px rgba(0,0,0,.05);
}

[data-theme="dark"] {
  --bg:        #0f1117;
  --surface:   #1a1d27;
  --surface2:  #222533;
  --border:    #2e3148;
  --accent:    #7b7ef8;
  --accent-lt: #1e2040;
  --accent-dk: #9a9dfa;
  --text:      #e8eaf6;
  --text-2:    #9699be;
  --text-3:    #555878;
  --shadow:    0 1px 3px rgba(0,0,0,.3), 0 4px 16px rgba(0,0,0,.2);
}

/* Theme toggle button */
.theme-toggle {
  margin-top: auto;
  padding: 14px 12px 6px;
  display: flex;
  align-items: center;
}
.toggle-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 10px;
  border: 1.5px solid var(--border);
  background: var(--surface2);
  color: var(--text-2);
  font-family: inherit;
  font-size: 12.5px;
  font-weight: 600;
  border-radius: 8px;
  cursor: pointer;
  transition: border-color .15s, color .15s;
}
.toggle-btn:hover { border-color: var(--accent); color: var(--accent); }

body {
  font-family: 'Plus Jakarta Sans', Arial, sans-serif;
  background: var(--bg);
  color: var(--text);
  display: flex;
  min-height: 100vh;
  font-size: 14px;
}

/* ── Sidebar ── */
nav {
  width: 230px;
  min-width: 230px;
  background: var(--surface);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  position: sticky;
  top: 0;
  height: 100vh;
  overflow-y: auto;
}

.logo {
  padding: 24px 20px 20px;
  border-bottom: 1px solid var(--border);
}
.logo-mark {
  width: 32px; height: 32px;
  background: var(--accent);
  border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  color: #fff;
  font-weight: 700;
  font-size: 15px;
  margin-bottom: 12px;
}
.logo-title { font-weight: 700; font-size: 15px; color: var(--text); }
.logo-sub   { font-size: 11px; color: var(--text-3); margin-top: 2px; }

.nav-group { padding: 16px 10px 4px; }
.nav-label {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: .08em;
  text-transform: uppercase;
  color: var(--text-3);
  padding: 0 10px 8px;
}
.nav-btn {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  padding: 8px 10px;
  border: none;
  background: none;
  color: var(--text-2);
  font-family: inherit;
  font-size: 13.5px;
  font-weight: 500;
  border-radius: 7px;
  cursor: pointer;
  text-align: left;
  transition: background .12s, color .12s;
}
.nav-btn:hover  { background: var(--surface2); color: var(--text); }
.nav-btn.active { background: var(--accent-lt); color: var(--accent); }
.nav-icon { width: 18px; font-size: 15px; flex-shrink: 0; }

.nav-footer {
  margin-top: auto;
  padding: 14px 20px;
  border-top: 1px solid var(--border);
  font-size: 10.5px;
  color: var(--text-3);
  line-height: 1.5;
  word-break: break-all;
}

/* ── Main ── */
main {
  flex: 1;
  padding: 32px 36px;
  overflow-y: auto;
  max-width: 1060px;
}

.page { display: none; }
.page.active { display: block; animation: up .18s ease; }
@keyframes up { from { opacity:0; transform:translateY(8px); } to { opacity:1; transform:none; } }

.page-head { margin-bottom: 24px; }
.page-head h2 { font-size: 22px; font-weight: 700; color: var(--text); }
.page-head p  { font-size: 13px; color: var(--text-2); margin-top: 3px; }

/* ── Stat cards ── */
.stat-row { display: grid; grid-template-columns: repeat(5,1fr); gap: 14px; margin-bottom: 24px; }
.stat-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r);
  padding: 18px 20px;
  box-shadow: var(--shadow);
  cursor: pointer;
  transition: border-color .15s, box-shadow .15s;
}
.stat-card:hover { border-color: var(--accent); box-shadow: 0 2px 12px rgba(91,94,245,.12); }
.stat-num   { font-size: 28px; font-weight: 700; color: var(--text); line-height: 1; }
.stat-label { font-size: 11px; font-weight: 600; color: var(--text-3); margin-top: 4px; text-transform: uppercase; letter-spacing: .06em; }
.stat-card .accent-line { width: 28px; height: 3px; background: var(--accent); border-radius: 2px; margin-bottom: 10px; }
.accent-line-alert { background: var(--yellow) !important; }
.accent-line-warn  { background: var(--red)    !important; }
.stat-card.has-dups { border-color: var(--yellow); }
.stat-card.has-dups:hover { border-color: var(--red); box-shadow: 0 2px 12px rgba(239,68,68,.12); }

/* ── Duplicates panel rows ── */
.dup-note {
  font-size: 12px; color: var(--text-3); margin-bottom: 12px;
  padding: 8px 12px; background: var(--surface2); border-radius: 6px;
}
.dup-note code { font-family: monospace; color: var(--accent); }
.dup-section-title {
  font-size: 11px; font-weight: 700; text-transform: uppercase;
  letter-spacing: .07em; color: var(--text-3);
  margin: 14px 0 6px;
}
.dup-section-title.dup-warn { color: var(--yellow); }
.dup-row {
  display: flex; align-items: flex-start; gap: 10px;
  padding: 8px 10px; border-radius: 7px;
  margin-bottom: 4px; background: var(--surface2);
}
.dup-row-warn { background: #fffbeb; border: 1px solid #fde68a; }
[data-theme="dark"] .dup-row-warn { background: #2a1f00; border-color: #78500a; }
.dup-icon  { font-size: 14px; margin-top: 1px; flex-shrink: 0; }
.dup-info  { min-width: 0; }
.dup-name  { font-size: 12px; font-weight: 600; color: var(--text); word-break: break-all; }
.dup-meta  { font-size: 11px; color: var(--text-3); margin-top: 2px; }
.dup-badge-ok      { background: #dcfce7; color: #16a34a; padding: 1px 6px; border-radius: 4px; font-weight: 600; }
.dup-badge-warn    { background: #fef9c3; color: #a16207; padding: 1px 6px; border-radius: 4px; font-weight: 600; }
.dup-badge-missing { background: var(--surface); color: var(--text-3); padding: 1px 6px; border-radius: 4px; font-weight: 600; }

/* ── Panels ── */
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px; }
.panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r);
  padding: 18px 20px;
  box-shadow: var(--shadow);
}
.panel-title { font-size: 12px; font-weight: 700; color: var(--text-2); text-transform: uppercase; letter-spacing: .07em; margin-bottom: 14px; }

.bar-row { display: flex; align-items: center; gap: 10px; margin-bottom: 9px; font-size: 12.5px; }
.bar-lbl  { width: 130px; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-weight: 500; }
.bar-trk  { flex: 1; height: 5px; background: var(--surface2); border-radius: 3px; overflow: hidden; }
.bar-fill { height: 100%; background: var(--accent); border-radius: 3px; transition: width .4s ease; }
.bar-n    { width: 32px; text-align: right; color: var(--text-3); font-size: 11.5px; font-weight: 600; }

/* ── Search bar ── */
.search-row { display: flex; gap: 8px; margin-bottom: 20px; }
input[type=text], select {
  background: var(--surface);
  border: 1.5px solid var(--border);
  border-radius: 8px;
  color: var(--text);
  font-family: inherit;
  font-size: 13.5px;
  padding: 9px 14px;
  outline: none;
  transition: border-color .15s, box-shadow .15s;
}
input[type=text] { flex: 1; }
input[type=text]::placeholder { color: var(--text-3); }
input[type=text]:focus, select:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(91,94,245,.12);
}
select { cursor: pointer; background: var(--surface); }
select option { background: var(--surface); }

.btn {
  background: var(--accent);
  color: #fff;
  border: none;
  border-radius: 8px;
  padding: 9px 20px;
  font-family: inherit;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background .12s, transform .1s;
  white-space: nowrap;
}
.btn:hover  { background: var(--accent-dk); }
.btn:active { transform: scale(.98); }

/* ── Results meta ── */
.results-meta {
  font-size: 12px;
  color: var(--text-3);
  font-weight: 500;
  margin-bottom: 12px;
}

/* ── Book cards ── */
.book-list { display: flex; flex-direction: column; gap: 8px; }

.book-card {
  background: var(--surface);
  border: 1.5px solid var(--border);
  border-radius: var(--r);
  padding: 14px 18px;
  cursor: pointer;
  transition: border-color .15s, box-shadow .15s;
}
.book-card:hover    { border-color: var(--accent); box-shadow: 0 2px 12px rgba(91,94,245,.1); }
.book-card.expanded { border-color: var(--accent); }

.book-row { display: flex; align-items: flex-start; gap: 14px; }
.book-dot {
  width: 6px; min-width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--accent);
  margin-top: 7px;
}
.book-dot.cookbooks              { background: #f97316; }
.book-dot.reading                { background: #3b82f6; }
.book-dot.home_improvement       { background: #22c55e; }
.book-dot.sport_workout_yoga_health { background: #a855f7; }
.book-dot.other                  { background: var(--text-3); }
.book-dot.failed                 { background: var(--red); }
.book-dot.pdf                    { background: #eab308; }
.book-dot.unknown                { background: var(--text-3); }

.book-body  { flex: 1; min-width: 0; }
.book-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.book-author { font-size: 12.5px; color: var(--text-2); margin-top: 1px; }
.book-tags   { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 7px; }

.tag {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 5px;
  letter-spacing: .02em;
}
.tag-dir  { background: var(--accent-lt); color: var(--accent); }
.tag-lang { background: #eff6ff; color: #2563eb; }
.tag-conf      { background: #f0fdf4; color: #16a34a; }
.tag-conf.med  { background: #fefce8; color: #ca8a04; }
.tag-conf.low  { background: #fef2f2; color: #dc2626; }
.tag-date      { background: var(--surface2); color: var(--text-3); font-weight: 500; }

.book-detail {
  display: none;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
  font-size: 12.5px;
  line-height: 1.8;
}
.book-card.expanded .book-detail { display: block; }

.dl { display: grid; grid-template-columns: 90px 1fr; gap: 2px 12px; }
.dt { color: var(--text-3); font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: .06em; padding-top: 3px; }
.dd { color: var(--text); word-break: break-all; }

.chip-row { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 2px; }
.chip {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 5px;
  padding: 2px 9px;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-2);
  cursor: pointer;
  transition: background .1s, color .1s, border-color .1s;
}
.chip:hover { background: var(--accent-lt); color: var(--accent); border-color: var(--accent); }

/* ── Genre grid ── */
.genre-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 8px;
  margin-bottom: 24px;
}
.genre-tile {
  background: var(--surface);
  border: 1.5px solid var(--border);
  border-radius: 8px;
  padding: 11px 14px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  cursor: pointer;
  transition: border-color .12s, background .12s;
}
.genre-tile:hover   { border-color: var(--accent); background: var(--accent-lt); }
.genre-tile.sel     { border-color: var(--accent); background: var(--accent-lt); }
.genre-name { font-size: 12.5px; font-weight: 600; color: var(--text); }
.genre-tile.sel .genre-name { color: var(--accent); }
.genre-count {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-3);
  background: var(--surface2);
  padding: 1px 6px;
  border-radius: 4px;
  min-width: 24px;
  text-align: center;
}
.genre-tile.sel .genre-count { background: #dcdcfc; color: var(--accent); }

/* ── Dir grid ── */
.dir-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px,1fr));
  gap: 10px;
  margin-bottom: 24px;
}
.dir-card {
  background: var(--surface);
  border: 1.5px solid var(--border);
  border-radius: var(--r);
  padding: 16px 18px;
  cursor: pointer;
  transition: border-color .12s, box-shadow .12s;
  display: flex;
  align-items: center;
  gap: 12px;
}
.dir-card:hover, .dir-card.sel { border-color: var(--accent); box-shadow: 0 2px 12px rgba(91,94,245,.1); }
.dir-emoji { font-size: 22px; }
.dir-name  { font-size: 13px; font-weight: 600; color: var(--text); }
.dir-cnt   { font-size: 11.5px; color: var(--text-3); margin-top: 1px; }

/* ── Cache cards ── */
.cache-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r);
  padding: 14px 18px;
  margin-bottom: 10px;
}
.cache-key { font-size: 12.5px; font-weight: 700; color: var(--accent); margin-bottom: 4px; font-family: 'Courier New', monospace; }
.cache-ts  { font-size: 11px; color: var(--text-3); margin-bottom: 8px; }
.cache-json {
  font-family: 'Courier New', monospace;
  font-size: 11.5px;
  color: var(--text-2);
  background: var(--surface2);
  border-radius: 6px;
  padding: 10px 12px;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 160px;
  overflow-y: auto;
}

/* ── Pagination ── */
.pager {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 18px;
  font-size: 12.5px;
  color: var(--text-3);
  font-weight: 500;
}
.pg-btn {
  background: var(--surface);
  border: 1.5px solid var(--border);
  border-radius: 7px;
  padding: 6px 14px;
  font-family: inherit;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-2);
  cursor: pointer;
  transition: border-color .12s, color .12s;
}
.pg-btn:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); }
.pg-btn:disabled { opacity: .35; cursor: default; }

/* ── States ── */
.loading { text-align:center; padding:40px; color:var(--text-3); font-size:13px; }
.empty   {
  text-align:center; padding:40px; color:var(--text-3); font-size:13px;
  border: 1.5px dashed var(--border); border-radius: var(--r);
}

/* ── Inline edit fields ── */
.edit-row {
  display: flex;
  gap: 6px;
  align-items: center;
  margin-top: 2px;
}
.edit-input {
  flex: 1;
  background: var(--surface);
  border: 1.5px solid var(--border);
  border-radius: 7px;
  color: var(--text);
  font-family: inherit;
  font-size: 12.5px;
  padding: 6px 10px;
  outline: none;
  transition: border-color .15s, box-shadow .15s;
  min-width: 0;
}
.edit-input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(91,94,245,.1);
}
.edit-select {
  flex: 1;
  background: var(--surface);
  border: 1.5px solid var(--border);
  border-radius: 7px;
  color: var(--text);
  font-family: inherit;
  font-size: 12.5px;
  padding: 6px 10px;
  outline: none;
  cursor: pointer;
  transition: border-color .15s;
}
.edit-select:focus { border-color: var(--accent); }
.edit-select option { background: var(--surface); }

.btn-edit-save {
  background: var(--accent);
  color: #fff;
  border: none;
  border-radius: 7px;
  padding: 6px 14px;
  font-family: inherit;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition: background .12s;
}
.btn-edit-save:hover { background: var(--accent-dk); }

.edit-error {
  font-size: 11px;
  font-weight: 600;
  color: var(--red);
  margin-top: 4px;
  display: none;
}
.edit-error.show { display: block; }

/* ── Tag editor ── */
.tag-editor { margin-top: 6px; }

.chip-editable {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 5px;
  padding: 2px 4px 2px 9px;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-2);
  cursor: default;
  transition: border-color .12s;
}
.chip-editable:hover { border-color: var(--accent); }
.chip-remove {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 16px; height: 16px;
  border: none;
  background: none;
  color: var(--text-3);
  font-size: 14px;
  line-height: 1;
  cursor: pointer;
  border-radius: 3px;
  padding: 0;
  transition: background .1s, color .1s;
}
.chip-remove:hover { background: var(--red); color: #fff; }

.tag-add-row {
  display: flex;
  gap: 6px;
  margin-top: 8px;
  align-items: center;
}
.tag-select {
  flex: 1;
  background: var(--surface);
  border: 1.5px solid var(--border);
  border-radius: 7px;
  color: var(--text);
  font-family: inherit;
  font-size: 12.5px;
  padding: 6px 10px;
  outline: none;
  cursor: pointer;
  transition: border-color .15s;
}
.tag-select:focus { border-color: var(--accent); }
.tag-select option { background: var(--surface); }

.btn-add-tag {
  background: var(--accent-lt);
  color: var(--accent);
  border: 1.5px solid var(--accent);
  border-radius: 7px;
  padding: 6px 14px;
  font-family: inherit;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background .12s, color .12s;
  white-space: nowrap;
}
.btn-add-tag:hover { background: var(--accent); color: #fff; }

/* ── Genre autocomplete dropdown ── */
.genre-ac-wrap {
  position: relative;
  flex: 1;
}
.genre-ac-wrap .edit-input {
  width: 100%;
  box-sizing: border-box;
}
.genre-dropdown {
  position: absolute;
  top: calc(100% + 3px);
  left: 0;
  right: 0;
  background: var(--surface);
  border: 1.5px solid var(--accent);
  border-radius: 8px;
  box-shadow: 0 6px 20px rgba(0,0,0,.18);
  z-index: 200;
  overflow: hidden;
  max-height: 220px;
  overflow-y: auto;
}
.genre-drop-item {
  padding: 7px 12px;
  font-size: 12.5px;
  color: var(--text);
  cursor: pointer;
  border-bottom: 1px solid var(--border);
  transition: background .1s;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.genre-drop-item:last-child { border-bottom: none; }
.genre-drop-item:hover,
.genre-drop-item.active { background: var(--accent-lt); color: var(--accent); }
.genre-drop-create {
  color: var(--green, #16a34a);
  font-style: italic;
}
.genre-drop-create:hover,
.genre-drop-create.active {
  background: #f0fdf4;
  color: #15803d;
}
.genre-drop-icon {
  font-style: normal;
  font-weight: 700;
  margin-right: 4px;
}

/* ── Delete button ── */
.btn-delete {
  margin-top: 14px;
  display: flex;
  align-items: center;
  gap: 7px;
  background: none;
  border: 1.5px solid var(--border);
  border-radius: 7px;
  padding: 6px 14px;
  font-family: inherit;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-3);
  cursor: pointer;
  transition: border-color .15s, color .15s, background .15s;
}
.btn-delete:hover { border-color: var(--red); color: var(--red); background: #fff1f1; }
[data-theme="dark"] .btn-delete:hover { background: #2d1515; }

/* ── Confirmation modal ── */
.modal-overlay {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,.45);
  z-index: 1000;
  align-items: center;
  justify-content: center;
}
.modal-overlay.show { display: flex; animation: fadeIn .15s ease; }
@keyframes fadeIn { from { opacity:0; } to { opacity:1; } }

.modal-box {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  box-shadow: 0 8px 40px rgba(0,0,0,.22);
  padding: 28px 32px;
  width: 380px;
  max-width: 90vw;
  animation: slideUp .18s ease;
}
@keyframes slideUp { from { transform: translateY(10px); opacity:0; } to { transform:none; opacity:1; } }

.modal-icon  { font-size: 28px; margin-bottom: 10px; }
.modal-title { font-size: 16px; font-weight: 700; color: var(--text); margin-bottom: 6px; }
.modal-body  { font-size: 13px; color: var(--text-2); line-height: 1.6; margin-bottom: 22px; }
.modal-book-name {
  font-weight: 600;
  color: var(--text);
  word-break: break-word;
}
.modal-actions { display: flex; gap: 10px; justify-content: flex-end; }
.btn-modal-cancel {
  background: var(--surface2);
  border: 1.5px solid var(--border);
  border-radius: 8px;
  padding: 8px 20px;
  font-family: inherit;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-2);
  cursor: pointer;
  transition: border-color .12s, color .12s;
}
.btn-modal-cancel:hover { border-color: var(--accent); color: var(--accent); }
.btn-modal-confirm {
  background: var(--red);
  border: none;
  border-radius: 8px;
  padding: 8px 20px;
  font-family: inherit;
  font-size: 13px;
  font-weight: 600;
  color: #fff;
  cursor: pointer;
  transition: opacity .12s;
}
.btn-modal-confirm:hover { opacity: .85; }

.save-indicator {
  font-size: 11px;
  font-weight: 600;
  color: var(--green);
  opacity: 0;
  transition: opacity .2s;
  margin-left: 4px;
}
.save-indicator.show { opacity: 1; }

/* ── Cover image ── */
.cover-wrap {
  float: right;
  margin: 0 0 10px 16px;
  width: 80px;
}
.cover-img {
  width: 80px;
  border-radius: 5px;
  box-shadow: 0 2px 8px rgba(0,0,0,.18);
  display: block;
}
.cover-placeholder {
  width: 80px; height: 110px;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 5px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  color: var(--text-3);
}

/* ── Similar Authors page ── */
#authors-toolbar {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 18px;
}
.btn-merge {
  background: var(--accent);
  color: #fff;
  border: none;
  border-radius: 8px;
  padding: 8px 20px;
  font-family: inherit;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity .12s;
}
.btn-merge:hover:not(:disabled) { opacity: .85; }
.btn-merge:disabled { opacity: .4; cursor: default; }
.merge-hint { font-size: 12px; color: var(--text-3); }

.authors-hint {
  font-size: 12px; color: var(--text-3);
  margin-bottom: 16px;
  padding: 8px 12px;
  background: var(--surface2);
  border-radius: 6px;
}
.author-pairs { display: flex; flex-direction: column; gap: 10px; }

.author-pair {
  display: flex;
  align-items: center;
  gap: 12px;
  background: var(--surface);
  border: 1.5px solid var(--border);
  border-radius: 10px;
  padding: 12px 16px;
  transition: border-color .15s;
}
.author-pair:has(.pair-check:checked) { border-color: var(--accent); }
.author-pair.pair-merged { opacity: .45; pointer-events: none; }

.pair-check-wrap { flex-shrink: 0; }
.pair-check { width: 16px; height: 16px; accent-color: var(--accent); cursor: pointer; }

.pair-score {
  flex-shrink: 0;
  font-size: 11px; font-weight: 700;
  padding: 2px 7px;
  border-radius: 20px;
  min-width: 38px;
  text-align: center;
}
.sim-high { background: #dcfce7; color: #15803d; }
.sim-med  { background: #fef9c3; color: #a16207; }
.sim-low  { background: #fee2e2; color: #b91c1c; }

.pair-authors {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.author-option {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
}
.author-option input[type="radio"] {
  accent-color: var(--accent);
  width: 14px; height: 14px;
  cursor: pointer;
}
.author-pill {
  display: inline-block;
  padding: 4px 12px;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 500;
  background: var(--surface2);
  border: 1.5px solid var(--border);
  transition: background .12s, border-color .12s;
  cursor: pointer;
  user-select: none;
}
.author-pill.pill-target {
  background: var(--accent-lt);
  border-color: var(--accent);
  color: var(--accent);
  font-weight: 700;
}
.author-book-count {
  font-size: 11px;
  color: var(--text-3);
  white-space: nowrap;
}
.pair-arrow { font-size: 16px; color: var(--text-3); flex-shrink: 0; }

.pair-status { font-size: 12px; flex-shrink: 0; }
.merge-ok  { color: var(--green); font-weight: 600; }
.merge-err { color: var(--red);   font-weight: 600; }

.merge-preview-row {
  font-size: 13px;
  padding: 4px 0;
  border-bottom: 1px solid var(--border);
  color: var(--text-2);
}
.merge-preview-row:last-of-type { border-bottom: none; }
::-webkit-scrollbar { width: 5px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--accent); }
"""
