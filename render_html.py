"""
render_html.py — Convert exported .md files → .html locally (no browser needed).

Usage:
    python3 render_html.py                  # converts all .md in ./output/
    python3 render_html.py path/to/dir      # converts all .md in that dir
    python3 render_html.py file.md          # converts one file
"""

import re
import sys
from pathlib import Path
import markdown as md_lib

_parser = md_lib.Markdown(extensions=["tables", "fenced_code", "nl2br"])

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  :root {{
    --bg: #1a1a1a; --surface: #1e1e1e;
    --user-bg: #1e3a5f; --user-border: #2d5a9e; --user-text: #d0e4ff;
    --gem-bg: #1e2d1e; --gem-border: #3a6b3a; --gem-text: #d0f0d0;
    --round-bg: #262626; --round-text: #999;
    --heading: #e8e8e8; --body: #c0c0c0; --meta: #555;
    --code-bg: #111; --link: #7ab3f5;
    --font: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    --mono: "JetBrains Mono", "Fira Code", "Courier New", monospace;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--body); font-family: var(--font);
          font-size: 15px; line-height: 1.75; }}

  /* Layout */
  .layout {{ display: flex; align-items: flex-start; padding: 24px 16px; }}
  .toc {{
    position: sticky; top: 24px; width: 170px; min-width: 150px; flex-shrink: 0;
    max-height: calc(100vh - 48px); overflow-y: auto;
    padding: 14px 10px; margin-right: 28px;
    background: var(--surface); border-radius: 6px; border: 1px solid #2a2a2a;
  }}
  .toc-title {{ color: #555; font-size: 10px; font-weight: 700;
    text-transform: uppercase; letter-spacing: 0.1em;
    padding-bottom: 8px; margin-bottom: 6px; border-bottom: 1px solid #2a2a2a; }}
  .toc a {{
    display: block; text-decoration: none; padding: 5px 8px;
    border-left: 2px solid transparent; border-radius: 0 3px 3px 0;
  }}
  .toc a .rn {{ display: block; font-size: 12px; font-weight: 600; color: #888; }}
  .toc a .rt {{ display: block; font-size: 10px; color: #4a4a4a; margin-top: 1px; }}
  .toc a:hover {{ background: #222; }}
  .toc a:hover .rn {{ color: #bbb; }}
  .toc a.active {{ border-left-color: #7ab3f5; background: #162030; }}
  .toc a.active .rn {{ color: #7ab3f5; }}
  .toc a.active .rt {{ color: #4a6a8a; }}
  @media (max-width: 680px) {{ .toc {{ display: none; }} }}

  /* Main content */
  .main {{ flex: 1; min-width: 0; max-width: 860px; }}
  h1 {{ color: var(--heading); font-size: 1.5rem; margin-bottom: 4px; }}
  .source {{ color: var(--meta); font-size: 13px; margin-bottom: 32px; }}
  .source a {{ color: var(--link); text-decoration: none; }}

  /* Round headers (h2 starting with "Round") */
  h2.round-hdr {{
    display: flex; align-items: center; gap: 12px;
    margin: 36px 0 18px; padding: 8px 14px;
    background: var(--round-bg); border-left: 3px solid #555;
    border-radius: 4px; font-size: 13px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.08em; color: var(--round-text);
  }}
  h2.round-hdr code {{
    font-family: var(--mono); font-size: 11px; font-weight: 400;
    color: #555; background: none; margin-left: auto;
  }}

  /* Role headers (h3 User / Gemini) */
  h3.role-user {{ color: #7ab3f5; font-size: 11px; font-weight: 700;
    letter-spacing: 0.1em; text-transform: uppercase;
    margin: 14px 0 6px; text-align: right; }}
  h3.role-gem  {{ color: #7fc97f; font-size: 11px; font-weight: 700;
    letter-spacing: 0.1em; text-transform: uppercase; margin: 14px 0 6px; }}

  /* Message content blocks */
  .msg-user {{
    background: var(--user-bg); border: 1px solid var(--user-border);
    color: var(--user-text); padding: 12px 16px; border-radius: 12px 4px 12px 12px;
    max-width: 92%; margin-left: auto; margin-bottom: 16px;
    white-space: pre-wrap; word-break: break-word; font-size: 14px;
  }}
  .msg-gem {{
    background: var(--gem-bg); border: 1px solid var(--gem-border);
    color: var(--gem-text); padding: 12px 16px; border-radius: 4px 12px 12px 12px;
    max-width: 92%; margin-bottom: 16px;
  }}

  /* Inline content styling */
  p {{ margin: 6px 0; }}
  ul, ol {{ padding-left: 20px; margin: 6px 0; }}
  li {{ margin: 3px 0; }}
  strong {{ color: #c8e8c8; }}
  em {{ color: #b0d8b0; font-style: italic; }}
  code {{ background: var(--code-bg); padding: 1px 5px;
    border-radius: 3px; font-family: var(--mono); font-size: 13px; color: #f0c080; }}
  pre {{ background: var(--code-bg); padding: 12px; border-radius: 6px;
    overflow-x: auto; margin: 8px 0; }}
  pre code {{ background: none; padding: 0; }}
  a {{ color: var(--link); }}
  hr {{ border: none; border-top: 1px solid #2a2a2a; margin: 24px 0; }}
  blockquote {{ border-left: 3px solid #3a6b3a; padding-left: 12px;
    color: #a0c8a0; margin: 8px 0; font-style: italic; }}
  table {{ border-collapse: collapse; width: 100%; margin: 8px 0; }}
  th, td {{ border: 1px solid #333; padding: 6px 10px; text-align: left; }}
  th {{ background: #1a3a1a; color: #a8d8a8; }}

  /* Non-round h2/h3/h4 (inside Gemini responses) */
  h2:not(.round-hdr) {{ font-size: 1.05rem; color: #a8d8a8;
    margin: 12px 0 6px; border-bottom: 1px solid #3a6b3a; padding-bottom: 3px; }}
  h3:not(.role-user):not(.role-gem) {{ font-size: 1rem; color: #90c890; margin: 10px 0 4px; }}
  h4 {{ font-size: 0.95rem; color: #78b878; margin: 8px 0 4px; }}
</style>
</head>
<body>
<div class="layout">
  <nav class="toc">
    <div class="toc-title">Rounds</div>
    <div id="toc-links"></div>
  </nav>
  <div class="main">
    {body_html}
  </div>
</div>
<script>
(function() {{
  // Add classes to Round h2 and role h3 headers
  document.querySelectorAll('h2').forEach(function(h) {{
    if (/^Round\\s+\\d+/i.test(h.textContent.trim())) h.classList.add('round-hdr');
  }});
  document.querySelectorAll('h3').forEach(function(h) {{
    var t = h.textContent.trim();
    if (t === 'User') h.classList.add('role-user');
    else if (t === 'Gemini') h.classList.add('role-gem');
  }});

  // Wrap content between role headers in message bubbles
  document.querySelectorAll('.role-user, .role-gem').forEach(function(roleH) {{
    var isUser = roleH.classList.contains('role-user');
    var wrapper = document.createElement('div');
    wrapper.className = isUser ? 'msg-user' : 'msg-gem';
    var node = roleH.nextSibling;
    var collected = [];
    while (node && !(node.nodeType === 1 &&
        (node.matches('h2, h3, hr') || node.classList.contains('round-hdr')))) {{
      collected.push(node);
      node = node.nextSibling;
    }}
    if (collected.length) {{
      roleH.after(wrapper);
      collected.forEach(function(n) {{ wrapper.appendChild(n); }});
    }}
  }});

  // Build TOC from round headers
  var tocEl = document.getElementById('toc-links');
  var rounds = document.querySelectorAll('h2.round-hdr');
  rounds.forEach(function(h, i) {{
    h.id = 'round-' + (i + 1);
    var text = h.textContent.trim();
    var parts = text.split(/\\s*·\\s*/);
    var num = parts[0].trim();
    var ts  = parts[1] ? parts[1].trim() : '';
    var a = document.createElement('a');
    a.href = '#round-' + (i + 1);
    a.innerHTML = '<span class="rn">' + num + '</span>' +
      (ts ? '<span class="rt">' + ts + '</span>' : '');
    tocEl.appendChild(a);
  }});

  // Highlight active round in TOC on scroll
  var observer = new IntersectionObserver(function(entries) {{
    entries.forEach(function(e) {{
      var link = tocEl.querySelector('a[href="#' + e.target.id + '"]');
      if (link) link.classList.toggle('active', e.isIntersecting);
    }});
  }}, {{ rootMargin: '-8% 0px -75% 0px' }});
  rounds.forEach(function(h) {{ observer.observe(h); }});
}})();
</script>
</body>
</html>
"""


def md_to_html(md_path: Path) -> str:
    text = md_path.read_text(encoding="utf-8")

    # Extract title from first h1
    title_m = re.match(r"^#\s+(.+)", text)
    title = title_m.group(1).strip() if title_m else md_path.stem

    # Extract source URL from blockquote line
    url_m = re.search(r">\s*Source:\s*(https?://\S+)", text)
    url = url_m.group(1).strip() if url_m else ""

    # Replace the raw "> Source: URL" line with a styled div before markdown parse
    if url:
        text = re.sub(
            r"^> Source:\s*https?://\S+\s*$",
            f'<p class="source">Source: <a href="{url}">{url}</a></p>',
            text,
            flags=re.MULTILINE,
        )

    _parser.reset()
    body_html = _parser.convert(text)
    return HTML_TEMPLATE.format(title=title, body_html=body_html)


def render_path(target: Path, out_dir: Path | None = None):
    if target.is_file():
        files = [target]
        out_dir = out_dir or target.parent
    else:
        files = sorted(target.glob("*.md"))
        out_dir = out_dir or target

    if not files:
        print(f"No .md files found in {target}")
        return

    for md_path in files:
        html = md_to_html(md_path)
        out_path = out_dir / (md_path.stem + ".html")
        out_path.write_text(html, encoding="utf-8")
        print(f"  {out_path.name}  ({out_path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    arg = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("output")
    render_path(arg)
