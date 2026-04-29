"""
Gemini Web Chat Exporter
- SPA click navigation (not goto) to avoid virtual-scroll DOM wipe
- Scrolls to bottom then extracts all messages in DOM
- Converts model HTML -> Markdown via html2text
- Saves each conversation as .md
"""

import asyncio
import re
import html2text
from datetime import datetime, timezone, timedelta
from pathlib import Path
from playwright.async_api import async_playwright

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

CONVERSATIONS = [
    # Format: ("Conversation Title", "conv_id_from_url")
    # URL example: https://gemini.google.com/app/abcdef1234567890
    #                                                ^^^^^^^^^^^^^^^^ this part
    ("My First Conversation",  "abcdef1234567890"),
    ("Another Conversation",   "1234567890abcdef"),
]

h = html2text.HTML2Text()
h.ignore_links = False
h.ignore_images = True
h.body_width = 0


def html_to_md(raw_html: str) -> str:
    md = h.handle(raw_html).strip()
    return _downgrade_headings(md, shift=3)


def _downgrade_headings(md: str, shift: int = 3) -> str:
    """Shift Gemini's # H1 → #### H4, ## H2 → ##### H5, etc.
    This keeps ## Round N as the dominant heading level in the final doc.
    """
    def replacer(m):
        new_level = min(len(m.group(1)) + shift, 6)
        return "#" * new_level + m.group(2)
    return re.sub(r"^(#{1,6})([ \t])", replacer, md, flags=re.MULTILINE)


def safe_filename(title: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', '_', title)


def parse_round_timestamps(body: str) -> list[str]:
    """Extract per-round timestamps from hNvQHb API response.

    The response lists rounds newest-first, so we reverse to get
    chronological order matching DOM extraction order.
    Returns list of 'YYYY-MM-DD HH:MM BJT' strings, one per round.
    """
    pairs = [
        (int(s), int(n))
        for s, n in re.findall(r'\[(\d{9,10}),(\d{6,9})\]', body)
        if 1_700_000_000 <= int(s) <= 1_900_000_000
    ]
    # Convert to BJT (UTC+8) strings
    result = []
    for s, _ in pairs:
        dt = datetime.fromtimestamp(s, tz=timezone.utc) + timedelta(hours=8)
        result.append(dt.strftime('%Y-%m-%d %H:%M BJT'))
    result.reverse()  # API is newest-first; DOM is oldest-first
    return result


async def navigate_via_click(page, conv_id: str) -> bool:
    """Navigate to a conversation by: JS-goto home → click sidebar link."""
    url = f"https://gemini.google.com/app/{conv_id}"

    if conv_id in page.url:
        return True  # already here

    # Go to home page via JS (goto() hangs; window.location works)
    await page.evaluate("() => { window.location.href = 'https://gemini.google.com/app'; }")
    # Wait for conversation links to appear in sidebar
    await page.wait_for_function(
        """() => Array.from(document.querySelectorAll('a'))
            .some(a => /\\/app\\/[a-f0-9]{16}$/.test(a.href))""",
        timeout=15000, polling=400,
    )

    # Scroll sidebar to find and click the target link
    for _ in range(20):
        result = await page.evaluate(f"""() => {{
            for (const a of document.querySelectorAll('a')) {{
                if (a.href === '{url}') {{ a.click(); return 'clicked'; }}
            }}
            const sidebar = document.querySelector('infinite-scroller:not(.chat-history)');
            if (sidebar) sidebar.scrollTop += 300;
            return 'not_found';
        }}""")
        if result == 'clicked':
            break
        await asyncio.sleep(0.3)
    else:
        return False

    # Wait for right URL + messages loaded
    await page.wait_for_function(
        f"() => window.location.href.includes('{conv_id}') "
        f"&& document.querySelectorAll('user-query').length > 0",
        timeout=20000,
        polling=300,
    )
    return True


async def load_all_messages(page) -> int:
    """Scroll to bottom so the most recent messages are rendered, return count."""
    # Poll until initial render is done
    for _ in range(30):
        n = await page.evaluate(
            "() => document.querySelectorAll('user-query').length"
        )
        if n > 0:
            break
        await asyncio.sleep(0.4)

    # Scroll to bottom (safe: doesn't wipe virtual DOM)
    await page.evaluate("""() => {
        const el = document.querySelector('infinite-scroller.chat-history');
        if (el) el.scrollTop = el.scrollHeight;
    }""")
    await asyncio.sleep(1.0)

    return await page.evaluate(
        "() => document.querySelectorAll('user-query').length"
    )


async def extract_messages(page) -> list[dict]:
    return await page.evaluate("""() => {
        const results = [];
        for (const el of document.querySelectorAll('user-query, model-response')) {
            const role = el.tagName.toLowerCase();
            if (role === 'user-query') {
                let text = el.innerText || '';
                text = text.replace(/^You said\\s*/i, '').trim();
                results.push({role: 'user', text});
            } else {
                const mc = el.querySelector('.markdown-main-panel, message-content .markdown');
                if (mc) {
                    results.push({role: 'model', html: mc.innerHTML, text: mc.innerText || ''});
                } else {
                    let text = (el.innerText || '')
                        .replace(/^Gemini said\\s*/i, '')
                        .replace(/^Show thinking\\s*/i, '')
                        .trim();
                    results.push({role: 'model', text});
                }
            }
        }
        return results;
    }""")


def pair_messages(messages: list[dict]) -> list[tuple]:
    """Group alternating user/model messages into (user, model) Round pairs."""
    rounds, i = [], 0
    while i < len(messages):
        user_msg = messages[i] if messages[i]['role'] == 'user' else None
        if user_msg:
            i += 1
        gemini_msg = messages[i] if i < len(messages) and messages[i]['role'] == 'model' else None
        if gemini_msg:
            i += 1
        if user_msg or gemini_msg:
            rounds.append((user_msg, gemini_msg))
    return rounds


def build_markdown(title: str, conv_id: str, messages: list[dict],
                   timestamps: list[str] | None = None) -> str:
    url = f"https://gemini.google.com/app/{conv_id}"
    lines = [f"# {title}", "", f"> Source: {url}", ""]

    rounds = pair_messages(messages)
    for n, (user_msg, gemini_msg) in enumerate(rounds, 1):
        ts = timestamps[n - 1] if timestamps and n - 1 < len(timestamps) else ""
        ts_suffix = f"  ·  `{ts}`" if ts else ""
        lines += ["---", "", f"## Round {n}{ts_suffix}", ""]

        if user_msg:
            lines += ["### User", ""]
            lines += [user_msg['text'], ""]

        if gemini_msg:
            lines += ["### Gemini", ""]
            body = html_to_md(gemini_msg['html']) if gemini_msg.get('html') else gemini_msg['text']
            lines += [body, ""]

    return "\n".join(lines)


HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  :root {{
    --bg: #1a1a1a; --surface: #242424; --border: #333;
    --user-bg: #1e3a5f; --user-border: #2d5a9e; --user-text: #d0e4ff;
    --gem-bg: #1e2d1e; --gem-border: #3a6b3a; --gem-text: #d0f0d0;
    --round-bg: #2a2a2a; --round-text: #aaa;
    --heading: #e8e8e8; --body: #c8c8c8; --meta: #666;
    --code-bg: #111; --link: #7ab3f5;
    --font: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    --mono: "JetBrains Mono", "Fira Code", "Courier New", monospace;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--body); font-family: var(--font);
          font-size: 15px; line-height: 1.7; }}

  /* Layout: TOC sidebar + main content */
  .layout {{ display: flex; align-items: flex-start; padding: 24px 16px; gap: 0; }}
  .toc {{
    position: sticky; top: 24px; width: 170px; min-width: 150px; flex-shrink: 0;
    max-height: calc(100vh - 48px); overflow-y: auto;
    padding: 14px 10px; margin-right: 24px;
    background: #1c1c1c; border-radius: 6px; border: 1px solid #2a2a2a;
  }}
  .toc-title {{ color: #555; font-size: 10px; font-weight: 700;
    text-transform: uppercase; letter-spacing: 0.1em;
    padding-bottom: 8px; margin-bottom: 6px; border-bottom: 1px solid #2a2a2a; }}
  .toc a {{
    display: block; text-decoration: none; padding: 4px 8px;
    border-left: 2px solid transparent; border-radius: 0 3px 3px 0;
    transition: color 0.12s;
  }}
  .toc a .rn {{ display: block; font-size: 12px; font-weight: 600; color: #888; }}
  .toc a .rt {{ display: block; font-size: 10px; color: #4a4a4a; margin-top: 1px; }}
  .toc a:hover .rn {{ color: #bbb; }}
  .toc a:hover {{ background: #222; }}
  .toc a.active {{ border-left-color: #7ab3f5; background: #162030; }}
  .toc a.active .rn {{ color: #7ab3f5; }}
  .toc a.active .rt {{ color: #4a6a8a; }}
  @media (max-width: 680px) {{ .toc {{ display: none; }} }}

  /* Main */
  .main {{ flex: 1; min-width: 0; max-width: 860px; padding-top: 0; }}
  h1.conv-title {{ color: var(--heading); font-size: 1.5rem; margin-bottom: 4px; }}
  .meta {{ color: var(--meta); font-size: 13px; margin-bottom: 28px; }}
  .meta a {{ color: var(--link); text-decoration: none; }}

  /* Round header */
  .round-header {{
    display: flex; align-items: center; gap: 12px;
    margin: 32px 0 16px; padding: 8px 14px;
    background: var(--round-bg); border-left: 3px solid #555;
    border-radius: 4px;
  }}
  .round-header .round-num {{ color: var(--round-text); font-size: 13px;
    font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; }}
  .round-header .round-ts {{ color: #555; font-size: 12px; margin-left: auto; }}

  /* Message bubbles */
  .message {{ margin-bottom: 16px; }}
  .msg-label {{ font-size: 11px; font-weight: 700; letter-spacing: 0.1em;
    text-transform: uppercase; margin-bottom: 6px; padding: 0 4px; }}
  .user-label {{ color: #7ab3f5; text-align: right; }}
  .gem-label  {{ color: #7fc97f; }}
  .msg-body {{
    padding: 14px 18px; border-radius: 12px;
    max-width: 92%; white-space: pre-wrap; word-break: break-word;
  }}
  .user-body {{
    background: var(--user-bg); border: 1px solid var(--user-border);
    color: var(--user-text); margin-left: auto; border-radius: 12px 4px 12px 12px;
  }}
  .gem-body {{
    background: var(--gem-bg); border: 1px solid var(--gem-border);
    color: var(--gem-text); border-radius: 4px 12px 12px 12px;
  }}
  /* Gemini rendered markdown inside bubble */
  .gem-body h1,.gem-body h2 {{ font-size: 1.1rem; color: #a8d8a8;
    margin: 14px 0 6px; border-bottom: 1px solid #3a6b3a; padding-bottom: 4px; }}
  .gem-body h3,.gem-body h4 {{ font-size: 1rem; color: #90c890; margin: 10px 0 4px; }}
  .gem-body h5,.gem-body h6 {{ font-size: 0.95rem; color: #78b878; margin: 8px 0 4px; }}
  .gem-body p {{ margin: 6px 0; }}
  .gem-body ul, .gem-body ol {{ padding-left: 20px; margin: 6px 0; }}
  .gem-body li {{ margin: 3px 0; }}
  .gem-body strong {{ color: #c8e8c8; }}
  .gem-body em {{ color: #b0d8b0; font-style: italic; }}
  .gem-body code {{ background: var(--code-bg); padding: 1px 5px;
    border-radius: 3px; font-family: var(--mono); font-size: 13px; color: #f0c080; }}
  .gem-body pre {{ background: var(--code-bg); padding: 12px; border-radius: 6px;
    overflow-x: auto; margin: 8px 0; }}
  .gem-body pre code {{ background: none; padding: 0; }}
  .gem-body a {{ color: var(--link); }}
  .gem-body hr {{ border: none; border-top: 1px solid #3a6b3a; margin: 12px 0; }}
  .gem-body blockquote {{ border-left: 3px solid #3a6b3a; padding-left: 12px;
    color: #a0c8a0; margin: 8px 0; }}
  .gem-body table {{ border-collapse: collapse; width: 100%; margin: 8px 0; }}
  .gem-body th, .gem-body td {{ border: 1px solid #3a6b3a; padding: 6px 10px;
    text-align: left; }}
  .gem-body th {{ background: #1a3a1a; color: #a8d8a8; }}
</style>
</head>
<body>
<div class="layout">
  <nav class="toc">
    <div class="toc-title">Rounds</div>
    <div id="toc-links"></div>
  </nav>
  <div class="main">
    <h1 class="conv-title">{title}</h1>
    <p class="meta">Source: <a href="{url}">{url}</a></p>
    {rounds_html}
  </div>
</div>
<script>
(function() {{
  var tocEl = document.getElementById('toc-links');
  var headers = document.querySelectorAll('.round-header');
  headers.forEach(function(h, i) {{
    h.id = 'round-' + (i + 1);
    var a = document.createElement('a');
    var num = h.querySelector('.round-num');
    var ts  = h.querySelector('.round-ts');
    a.href = '#round-' + (i + 1);
    a.innerHTML =
      '<span class="rn">' + (num ? num.textContent : 'Round ' + (i+1)) + '</span>' +
      (ts && ts.textContent ? '<span class="rt">' + ts.textContent + '</span>' : '');
    tocEl.appendChild(a);
  }});
  var observer = new IntersectionObserver(function(entries) {{
    entries.forEach(function(e) {{
      var link = tocEl.querySelector('a[href="#' + e.target.id + '"]');
      if (link) link.classList.toggle('active', e.isIntersecting);
    }});
  }}, {{ rootMargin: '-8% 0px -75% 0px' }});
  headers.forEach(function(h) {{ observer.observe(h); }});
}})();
</script>
</body>
</html>
"""


def build_html(title: str, conv_id: str, messages: list[dict],
               timestamps: list[str] | None = None) -> str:
    url = f"https://gemini.google.com/app/{conv_id}"
    rounds_parts = []

    for n, (user_msg, gemini_msg) in enumerate(pair_messages(messages), 1):
        ts = timestamps[n - 1] if timestamps and n - 1 < len(timestamps) else ""
        ts_html = f'<span class="round-ts">{ts}</span>' if ts else ""
        parts = [f'<div class="round-header"><span class="round-num">Round {n}</span>{ts_html}</div>']

        if user_msg:
            text = user_msg['text'].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            parts.append(
                f'<div class="message">'
                f'<div class="msg-label user-label">User</div>'
                f'<div class="msg-body user-body">{text}</div>'
                f'</div>'
            )

        if gemini_msg:
            # Use raw HTML from Gemini's own renderer — already sanitized by browser
            body = gemini_msg.get('html') or (
                gemini_msg['text'].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            )
            parts.append(
                f'<div class="message">'
                f'<div class="msg-label gem-label">Gemini</div>'
                f'<div class="msg-body gem-body">{body}</div>'
                f'</div>'
            )

        rounds_parts.append("\n".join(parts))

    return HTML_TEMPLATE.format(
        title=title,
        url=url,
        rounds_html="\n".join(rounds_parts),
    )


async def export_conversation(page, title: str, conv_id: str):
    print(f"\n{'='*60}")
    print(f"Exporting: {title}  (id={conv_id})")

    # Set up timestamp interceptor BEFORE navigation
    ts_body: dict = {}

    async def on_response(resp):
        if 'rpcids=hNvQHb' in resp.url and not ts_body:
            try:
                ts_body['data'] = await resp.text()
            except Exception:
                pass

    page.on('response', on_response)

    ok = await navigate_via_click(page, conv_id)
    if not ok:
        page.remove_listener('response', on_response)
        print("  ERROR: sidebar link not found")
        return 0

    count = await load_all_messages(page)
    print(f"  {count} turns loaded")

    # If hNvQHb wasn't triggered (cached SPA load), force a reload to get it
    if not ts_body.get('data'):
        await page.reload(wait_until="domcontentloaded")
        await asyncio.sleep(5)

    page.remove_listener('response', on_response)

    # Extract timestamps from hNvQHb response
    timestamps: list[str] = []
    if ts_body.get('data'):
        timestamps = parse_round_timestamps(ts_body['data'])
        print(f"  Timestamps: {timestamps}")
    else:
        print("  Timestamps: not captured")

    messages = await extract_messages(page)
    print(f"  Extracted {len(messages)} messages "
          f"({sum(1 for m in messages if m['role']=='user')} user, "
          f"{sum(1 for m in messages if m['role']=='model')} model)")

    stem = safe_filename(title)

    md = build_markdown(title, conv_id, messages, timestamps)
    md_path = OUTPUT_DIR / (stem + ".md")
    md_path.write_text(md, encoding="utf-8")
    print(f"  MD  : {md_path.name}  ({md_path.stat().st_size:,} bytes)")

    html = build_html(title, conv_id, messages, timestamps)
    html_path = OUTPUT_DIR / (stem + ".html")
    html_path.write_text(html, encoding="utf-8")
    print(f"  HTML: {html_path.name}  ({html_path.stat().st_size:,} bytes)")

    return len(messages)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://localhost:9222")
        context = browser.contexts[0]

        page = next((pg for pg in context.pages if 'gemini.google.com' in pg.url), None)
        if not page:
            page = await context.new_page()
            await page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
            await asyncio.sleep(2)

        for title, conv_id in CONVERSATIONS:
            await export_conversation(page, title, conv_id)

        print(f"\n{'='*60}")
        print(f"Done. Output: {OUTPUT_DIR}")
        for f in sorted(OUTPUT_DIR.glob("*.md")):
            print(f"  {f.name}  ({f.stat().st_size:,} bytes)")


if __name__ == "__main__":
    asyncio.run(main())
