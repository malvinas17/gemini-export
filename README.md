# Gemini Export

将 Gemini 网页版对话批量导出为本地 `.md` + `.html` 文件，并在浏览器里浏览。

## 文件说明

```
export.py       # 爬取 Gemini 对话 → 生成 .md + .html（需要 Edge debug 模式）
render_html.py  # 本地 .md → .html 重渲染（不需要浏览器，仅离线重排样式用）
server.py       # 启动本地 viewer，在浏览器里浏览所有导出的对话
output/         # 导出结果放这里
```

---

## 快速开始

### 第一步：安装依赖

**Mac：**
```bash
pip3 install --break-system-packages playwright html2text markdown
playwright install chromium
```

**Windows（在 PowerShell 里）：**
```powershell
pip install playwright html2text markdown
playwright install chromium
```

---

### 第二步：启动 Edge debug 模式（每次使用前）

**Mac：**
```bash
/Applications/Microsoft\ Edge.app/Contents/MacOS/Microsoft\ Edge \
  --remote-debugging-port=9222 \
  --user-data-dir=$HOME/.edge-gemini &
sleep 4
```

**Windows（在 PowerShell 里，一行）：**
```powershell
Start-Process "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" `
  -ArgumentList "--remote-debugging-port=9222","--user-data-dir=$env:USERPROFILE\.edge-gemini"
Start-Sleep 4
```

> 启动后在 Edge 里手动打开 https://gemini.google.com 并登录。

验证是否成功（有输出且包含 "Edg/" 即可）：
```bash
curl http://localhost:9222/json/version
```

---

### 第三步：导出对话

编辑 `export.py` 顶部的 `CONVERSATIONS` 列表：

```python
CONVERSATIONS = [
    ("对话标题",  "对话ID"),   # ID 从 URL 里取：gemini.google.com/app/这里
]
```

然后运行：
```bash
python3 export.py        # Mac
python export.py         # Windows
```

输出在 `output/` 目录，每个对话生成 `标题.md` 和 `标题.html`。

---

### 第四步：在浏览器里浏览

```bash
python3 server.py        # Mac，打开 http://localhost:3728
python server.py         # Windows
```

浏览器自动打开，左侧是对话列表，右侧显示内容。

---

## 批量导出侧边栏前 N 个对话

如果想自动抓取侧边栏里排在前面的对话（不用手动填 ID），参考：

```python
# 在 Gemini 主页 /app，等侧边栏加载后：
convs = await fetch_sidebar_conversations(page, limit=10)
```

完整示例见同目录下的批量导出脚本（如有）。

---

## 常见问题

**Q: `playwright install` 很慢？**  
A: 只需要 Chromium，跑 `playwright install chromium` 不用装全套。

**Q: Edge 没有找到 / 路径不对？**  
- Windows 默认路径：`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`  
- 也可能在：`C:\Program Files\Microsoft\Edge\Application\msedge.exe`

**Q: 已有 `.md` 文件，只想重新生成 HTML 样式？**  
```bash
python3 render_html.py output/    # 只需要 pip install markdown，不需要 Edge
```

**Q: 端口被占用？**  
```bash
python3 server.py output 3729    # 换一个端口
```
