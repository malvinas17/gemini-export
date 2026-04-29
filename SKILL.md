---
name: gemini-export
description: 将 Gemini 网页版对话导出为 Markdown + HTML 文件，含 Round 分轮、User/Gemini 标注、每轮时间戳（BJT）。连接已有 Edge debug session，通过 Playwright 爬取。
---

# Skill: gemini-export

将 Gemini Web 对话批量导出为本地 `.md` + `.html` 文件。

## 触发场景

- 用户说"导出 Gemini 对话"、"保存 Gemini 聊天记录"
- 用户提供 Gemini 对话 URL 并要求导出
- 需要归档多个 Gemini 对话

---

## 前提：Edge 必须在 debug 模式运行

```bash
curl -s http://localhost:9222/json/version | python3 -c "import sys,json; print(json.load(sys.stdin).get('Browser',''))"
# 应输出 Edg/xxx
```

若未启动：
```bash
/Applications/Microsoft\ Edge.app/Contents/MacOS/Microsoft\ Edge \
  --remote-debugging-port=9222 --user-data-dir=$HOME/.edge-vesper &
sleep 4
```

并手动在 Edge 里登录 Gemini，确保已认证。

---

## 快速使用

```bash
# 1. 在 export.py 里修改 CONVERSATIONS 列表
CONVERSATIONS = [
    ("对话标题",  "conv_id_hex"),
    ...
]

# 2. 运行
cd ~/.claude/skills/gemini-export
python3 export.py
```

输出在 `output/` 目录，每个对话生成 `<标题>.md` 和 `<标题>.html`。

### 获取侧边栏所有对话 URL

```python
# 在 Gemini 主页 /app 时运行
# 注意：a.innerText 在 Angular 中是 CSS 隐藏的（永远为空），必须用 a.textContent
await page.evaluate("() => { window.location.href = 'https://gemini.google.com/app'; }")
await page.wait_for_function(
    """() => Array.from(document.querySelectorAll('a'))
        .some(a => /\\/app\\/[a-f0-9]{16}$/.test(a.href))""",
    timeout=15000, polling=400,
)
links = await page.evaluate("""() => {
    const seen = new Set(), result = [];
    for (const a of document.querySelectorAll('a')) {
        if (!/^\\/app\\/[a-f0-9]{16}$/.test(new URL(a.href).pathname)) continue;
        const id = a.href.split('/app/')[1];
        if (seen.has(id)) continue;
        seen.add(id);
        // innerText is CSS-hidden; textContent works; strip "Pinned chat" suffix
        const title = a.textContent.trim()
            .replace(/\\bPinned chat\\b/gi, '').replace(/\\s+/g, ' ').trim() || id;
        result.push({title, id});
    }
    return result;
}""")
```

---

## 输出格式

**Markdown（`.md`）**
```markdown
# 对话标题
> Source: https://gemini.google.com/app/xxx

---
## Round 1  ·  `2026-02-11 10:16 BJT`
### User
[用户消息]
### Gemini
[回复内容，标题从 H4 起（不与 Round H2 冲突）]

---
## Round 2  ·  `2026-02-25 10:48 BJT`
...
```

**HTML（`.html`）**
- 暗色主题
- 用户消息：蓝色气泡右对齐，右上角 `USER` 标签
- Gemini 消息：绿色气泡左对齐，`GEMINI` 标签
- Round 条：左显示轮次编号，右显示时间戳

---

## 关键技术知识（踩坑总结）

### 1. 导航方式：必须用 JS click，不能用 goto()

- `page.goto(gemini_url)` → 触发全页重载，会卡住或破坏虚拟滚动
- 正确：先 `window.location.href = '/app'` 回主页，等侧边栏链接出现，再 `a.click()`
- 每次导航前必须先回主页，否则对话间切换后侧边栏消失

```python
await page.evaluate("() => { window.location.href = 'https://gemini.google.com/app'; }")
await page.wait_for_function(
    "() => Array.from(document.querySelectorAll('a')).some(a => /\\/app\\/[a-f0-9]{16}$/.test(a.href))",
    timeout=15000, polling=400
)
await page.evaluate(f"() => {{ for (const a of document.querySelectorAll('a')) if (a.href === 'https://gemini.google.com/app/{conv_id}') {{ a.click(); return; }} }}")
```

### 2. 侧边栏链接选择器：必须精确匹配

- `a[href*="conv_id"]` 会误匹配 Google 账户的 Sign-out 链接（href 里有 conv_id 作为 continue 参数）
- 正确：`a.href === 'https://gemini.google.com/app/{conv_id}'`（完整精确匹配）

### 3. 虚拟滚动：scrollTop=0 会清空 DOM

- `infinite-scroller.chat-history` 是虚拟滚动容器，直接设 `scrollTop=0` 会卸载所有消息节点
- 正确：`scrollTop = scrollHeight`（滚到底部），等待消息出现后直接提取
- 不需要滚到顶部，SPA 导航后所有消息已在 DOM 中（当前轮数通常全部加载）

### 4. Angular re-render：导航后短暂 0 消息

- 点击对话约 1.5s 后消息才出现（Angular re-render 期间 uq=0）
- 用 `wait_for_function` 轮询等待，不能用固定 sleep

### 5. 时间戳来源：`hNvQHb` API 拦截

- Gemini DOM 和可见 UI 均不暴露时间戳
- 加载对话时调用 `_/BardChatUi/data/batchexecute?rpcids=hNvQHb`
- 响应体里有 `[seconds, nanos]` 格式的 protobuf 时间戳，一个 Round 一个
- **API 返回顺序是倒序（最新在前）**，要 reverse 后和 DOM 消息对齐
- 缓存命中时不会调用 API → 加 reload 回退：导航后若未捕获到响应，`page.reload()` 触发重新请求

```python
pairs = [(int(s), int(n)) for s, n in re.findall(r'\[(\d{9,10}),(\d{6,9})\]', body)
         if 1_700_000_000 <= int(s) <= 1_900_000_000]
timestamps = [to_bjt(s) for s, _ in pairs]
timestamps.reverse()  # API newest-first → DOM oldest-first
```

### 6. 侧边栏标题：`innerText` 永远为空，必须用 `textContent`

- Angular 对 `<a>` 内的文字使用了 CSS opacity/visibility 动画，导致 `a.innerText` 恒为空字符串
- 必须用 `a.textContent`，并去除 `"Pinned chat"` 等多余后缀（`textContent` 包含所有子节点文本）
- `wait_for_function` 条件不能加 `&& a.innerText.trim()`，否则永远超时

### 7. Gemini 标题降级

- Gemini 回复内容含 `# H1`、`## H2` 等标题
- 导出时必须降级（H1→H4，H2→H5），否则与 `## Round N` 的 H2 冲突
- 用正则 post-process markdown：`re.sub(r'^(#{1,6})([ \t])', shift, md, flags=re.MULTILINE)`，shift=3

---

## 脚本路径

```
~/.claude/skills/gemini-export/
├── SKILL.md          # 本文件
└── export.py         # 完整导出脚本（修改 CONVERSATIONS 列表后直接运行）
```

## 常见扩展

- **导出全部对话**：在 `/app` 主页爬取侧边栏所有链接，动态构建 CONVERSATIONS 列表
- **增量导出**：检查 output/ 已存在的文件名，跳过已导出的对话
- **长对话（100+ 轮）**：当前方案提取 DOM 中已渲染的消息，对极长对话可能需要分批滚动收集（参见研究笔记中的 scroll_strategy 测试）
