#!/usr/bin/env python3
"""
Gemini Export Viewer — browse exported conversations in a local web app.

Usage:
    python3 server.py                    # serves ./output/ on port 3728
    python3 server.py path/to/output     # serves that directory
    python3 server.py output 3000        # custom port
"""

import http.server
import json
import sys
import threading
import webbrowser
from pathlib import Path

DEFAULT_PORT = 3728

# ── Viewer HTML (embedded, no external files needed) ─────────────────────────
VIEWER_HTML = """\
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Gemini Export Viewer</title>
<style>
  :root {
    --bg: #1a1a1a; --sidebar-bg: #141414; --sidebar-border: #252525;
    --item-hover: #1e1e1e; --item-active: #1a2a3a;
    --text: #c0c0c0; --text-dim: #555; --text-bright: #e8e8e8;
    --accent: #7ab3f5; --accent-dim: #3a5a8a;
    --font: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { height: 100%; overflow: hidden; background: var(--bg);
    font-family: var(--font); color: var(--text); }

  /* Layout */
  .app { display: flex; height: 100vh; }

  /* Sidebar */
  .sidebar {
    width: 260px; min-width: 220px; flex-shrink: 0;
    background: var(--sidebar-bg); border-right: 1px solid var(--sidebar-border);
    display: flex; flex-direction: column; overflow: hidden;
  }
  .sidebar-header {
    padding: 16px 14px 10px;
    border-bottom: 1px solid var(--sidebar-border); flex-shrink: 0;
  }
  .sidebar-header h1 { font-size: 13px; font-weight: 700; color: var(--text-bright);
    letter-spacing: 0.04em; margin-bottom: 10px; }
  .search {
    width: 100%; background: #1e1e1e; border: 1px solid #2a2a2a;
    border-radius: 5px; padding: 6px 10px; font-size: 12px;
    color: var(--text); outline: none;
  }
  .search::placeholder { color: var(--text-dim); }
  .search:focus { border-color: var(--accent-dim); }
  .count { font-size: 11px; color: var(--text-dim); margin-top: 7px; }

  /* Conversation list */
  .list { flex: 1; overflow-y: auto; padding: 6px 0; }
  .list::-webkit-scrollbar { width: 4px; }
  .list::-webkit-scrollbar-track { background: transparent; }
  .list::-webkit-scrollbar-thumb { background: #333; border-radius: 2px; }
  .item {
    padding: 9px 14px; cursor: pointer; border-left: 2px solid transparent;
    transition: background 0.1s;
  }
  .item:hover { background: var(--item-hover); }
  .item.active {
    background: var(--item-active); border-left-color: var(--accent);
  }
  .item-title {
    font-size: 12px; color: var(--text); line-height: 1.4;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .item.active .item-title { color: var(--text-bright); }
  .item-meta { font-size: 10px; color: var(--text-dim); margin-top: 2px; }

  /* Empty / loading states */
  .empty { padding: 24px 14px; font-size: 12px; color: var(--text-dim);
    text-align: center; line-height: 1.6; }

  /* Main content */
  .main { flex: 1; overflow: hidden; position: relative; }
  .main iframe {
    width: 100%; height: 100%; border: none; display: block;
    background: var(--bg);
  }
  .placeholder {
    display: flex; align-items: center; justify-content: center;
    height: 100%; flex-direction: column; gap: 12px;
    color: var(--text-dim); font-size: 14px;
  }
  .placeholder .big { font-size: 40px; opacity: 0.3; }
</style>
</head>
<body>
<div class="app">
  <aside class="sidebar">
    <div class="sidebar-header">
      <h1>Gemini Exports</h1>
      <input class="search" id="search" placeholder="Search conversations…" autocomplete="off">
      <div class="count" id="count"></div>
    </div>
    <div class="list" id="list">
      <div class="empty">Loading…</div>
    </div>
  </aside>
  <main class="main" id="main">
    <div class="placeholder" id="placeholder">
      <div class="big">💬</div>
      <div>Select a conversation</div>
    </div>
    <iframe id="frame" style="display:none"></iframe>
  </main>
</div>
<script>
var allItems = [];
var currentFile = null;

function load(file, title) {
  currentFile = file;
  document.getElementById('frame').src = '/' + encodeURIComponent(file);
  document.getElementById('frame').style.display = 'block';
  document.getElementById('placeholder').style.display = 'none';
  document.querySelectorAll('.item').forEach(function(el) {
    el.classList.toggle('active', el.dataset.file === file);
  });
  document.title = title + ' — Gemini Viewer';
  location.hash = encodeURIComponent(file);
}

function renderList(items) {
  var list = document.getElementById('list');
  document.getElementById('count').textContent = items.length + ' conversation' + (items.length !== 1 ? 's' : '');
  if (!items.length) {
    list.innerHTML = '<div class="empty">No conversations found.</div>';
    return;
  }
  list.innerHTML = items.map(function(item) {
    return '<div class="item' + (item.file === currentFile ? ' active' : '') + '" ' +
      'data-file="' + item.file + '" data-title="' + item.title.replace(/"/g, '&quot;') + '">' +
      '<div class="item-title">' + item.title + '</div>' +
      '</div>';
  }).join('');
  list.querySelectorAll('.item').forEach(function(el) {
    el.addEventListener('click', function() { load(el.dataset.file, el.dataset.title); });
  });
}

fetch('/api/list')
  .then(function(r) { return r.json(); })
  .then(function(data) {
    allItems = data;
    renderList(allItems);
    // Restore from URL hash
    var hash = decodeURIComponent(location.hash.slice(1));
    var match = allItems.find(function(i) { return i.file === hash; });
    if (match) load(match.file, match.title);
    else if (allItems.length) load(allItems[0].file, allItems[0].title);
  })
  .catch(function() {
    document.getElementById('list').innerHTML =
      '<div class="empty">Could not load conversation list.</div>';
  });

document.getElementById('search').addEventListener('input', function() {
  var q = this.value.toLowerCase();
  renderList(q ? allItems.filter(function(i) {
    return i.title.toLowerCase().includes(q);
  }) : allItems);
});
</script>
</body>
</html>
"""


# ── HTTP Handler ──────────────────────────────────────────────────────────────
class ViewerHandler(http.server.BaseHTTPRequestHandler):
    output_dir: Path = None

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            self._send(200, 'text/html; charset=utf-8', VIEWER_HTML.encode())
        elif self.path == '/api/list':
            self._api_list()
        else:
            self._serve_file()

    def _api_list(self):
        files = sorted(
            self.output_dir.glob('*.html'),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        data = [{'title': f.stem, 'file': f.name} for f in files]
        body = json.dumps(data, ensure_ascii=False).encode()
        self._send(200, 'application/json; charset=utf-8', body)

    def _serve_file(self):
        # Decode percent-encoding and strip leading slash
        from urllib.parse import unquote
        name = unquote(self.path.lstrip('/'))
        path = self.output_dir / name
        if not path.exists() or not path.is_file():
            self._send(404, 'text/plain', b'Not found')
            return
        # Basic path traversal guard
        try:
            path.relative_to(self.output_dir)
        except ValueError:
            self._send(403, 'text/plain', b'Forbidden')
            return
        mime = 'text/html; charset=utf-8' if path.suffix == '.html' else 'application/octet-stream'
        self._send(200, mime, path.read_bytes())

    def _send(self, code, content_type, body: bytes):
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # quiet


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    output_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('output')
    port = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_PORT

    if not output_dir.exists():
        print(f'Error: directory not found: {output_dir}')
        sys.exit(1)

    ViewerHandler.output_dir = output_dir.resolve()

    server = http.server.HTTPServer(('localhost', port), ViewerHandler)
    url = f'http://localhost:{port}'
    print(f'Gemini Export Viewer  →  {url}')
    print(f'Serving: {output_dir.resolve()}')
    print('Press Ctrl+C to stop.')
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')


if __name__ == '__main__':
    main()
