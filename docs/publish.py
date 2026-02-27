#!/usr/bin/env python3
"""
publish.py — 把 .docx 文章转换成博客 HTML 并更新 index.html

用法：
  python publish.py article.docx
  python publish.py article.docx --date 2025-02-01 --tags "llm,data"

docx 写作约定：
  - 第一行 Heading 1 = 文章标题
  - 第二行普通段落（可选）= 摘要（以"摘要："或"Abstract:"开头，或直接作为第一段）
  - 其余内容正常写，支持：标题/正文/代码块/粗体/斜体/列表/引用/表格
  - 代码块：在 Word 里用"代码"样式，或用等宽字体段落
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from html import escape


# ─────────────────────────────────────────────
# 1. 解析 docx → 结构化数据
# ─────────────────────────────────────────────

def docx_to_markdown(docx_path: Path) -> str:
    """用 pandoc 把 docx 转成 Markdown"""
    result = subprocess.run(
        ["pandoc", str(docx_path), "-t", "markdown", "--wrap=none"],
        capture_output=True, text=True, check=True
    )
    return result.stdout


def parse_article(md: str) -> dict:
    """
    从 Markdown 中提取：标题、摘要、正文
    返回 dict: {title, abstract, body_md}
    """
    lines = md.strip().split("\n")

    # 标题：第一个 # 开头的行
    title = ""
    title_idx = 0
    for i, line in enumerate(lines):
        if line.startswith("# "):
            title = line[2:].strip()
            title_idx = i
            break

    remaining = "\n".join(lines[title_idx + 1:]).strip()

    # 摘要：第一个非空段落，如果以"摘要："等开头则剥离前缀
    abstract = ""
    body_start = 0
    paragraphs = remaining.split("\n\n")
    if paragraphs:
        first = paragraphs[0].strip()
        # 不是标题、不是代码块，视为摘要
        if first and not first.startswith("#") and not first.startswith("```"):
            # 剥离前缀标记
            first = re.sub(r'^(摘要[：:]|Abstract[：:])\s*', '', first, flags=re.IGNORECASE)
            abstract = first
            body_start = 1

    body_md = "\n\n".join(paragraphs[body_start:])
    return {"title": title, "abstract": abstract, "body_md": body_md}


# ─────────────────────────────────────────────
# 2. Markdown → HTML prose
# ─────────────────────────────────────────────

def md_to_html(md: str) -> str:
    """用 pandoc 把 Markdown 正文转成 HTML 片段"""
    result = subprocess.run(
        ["pandoc", "-f", "markdown", "-t", "html", "--wrap=none"],
        input=md, capture_output=True, text=True, check=True
    )
    html = result.stdout

    # 给每个 h2/h3 加上 id（供目录使用）
    def add_id(m):
        tag = m.group(1)
        content = m.group(2)
        text = re.sub(r'<[^>]+>', '', content)   # 去掉内部标签
        slug = re.sub(r'[^\w\u4e00-\u9fff]+', '-', text.lower()).strip('-')
        return f'<{tag} id="{slug}">{content}</{tag}>'

    html = re.sub(r'<(h[23])>(.*?)</h[23]>', add_id, html, flags=re.DOTALL)

    # 给代码块加上 blog 风格（pandoc 生成 <pre><code>，保持即可）
    return html


def extract_toc(html: str) -> list[dict]:
    """从 HTML 中提取 h2/h3 生成目录"""
    toc = []
    for m in re.finditer(r'<(h[23]) id="([^"]+)">(.*?)</h[23]>', html, re.DOTALL):
        tag, slug, content = m.group(1), m.group(2), m.group(3)
        text = re.sub(r'<[^>]+>', '', content)
        toc.append({"level": tag, "id": slug, "text": text})
    return toc


# ─────────────────────────────────────────────
# 3. 生成完整 HTML 页面
# ─────────────────────────────────────────────

TOC_HTML_TMPL = """
    <div class="toc-title">// 目录</div>
    <ul class="toc-list" id="toc">
{items}
    </ul>
"""

def render_toc(toc: list[dict]) -> str:
    items = []
    for item in toc:
        cls = "toc-item sub" if item["level"] == "h3" else "toc-item"
        items.append(f'      <li class="{cls}"><a href="#{item["id"]}">{escape(item["text"])}</a></li>')
    return TOC_HTML_TMPL.format(items="\n".join(items))


def render_tags(tags: list[str]) -> str:
    if not tags:
        return ""
    chips = "".join(f'<span class="tag hl">{escape(t)}</span>' for t in tags)
    return f'<div class="post-tags">{chips}</div>'


def generate_post_html(article: dict, tags: list[str], date_str: str,
                       body_html: str, toc: list[dict]) -> str:
    title_esc = escape(article["title"])
    abstract_esc = escape(article["abstract"]) if article["abstract"] else ""
    toc_html = render_toc(toc) if toc else ""
    tags_html = render_tags(tags)

    # 预估阅读时间（按中文 300字/分钟）
    word_count = len(re.sub(r'<[^>]+>', '', body_html))
    reading_min = max(1, round(word_count / 300))

    desc_block = f'<div class="post-desc">{abstract_esc}</div>' if abstract_esc else ""

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title_esc} · 深渊研究室</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Lora:ital,wght@0,400;0,600;1,400&family=JetBrains+Mono:wght@400;500&family=Source+Sans+3:wght@300;400;600&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg:#faf8f4;--surface:#f2ede5;--border:#ddd8cc;--text:#1a1814;
      --muted:#7a7268;--accent:#c0392b;--accent-light:#f5e6e4;
      --link:#2c5282;--code-bg:#ece8e0;--shadow:rgba(0,0,0,.06);
    }}
    [data-theme="dark"] {{
      --bg:#141210;--surface:#1e1c18;--border:#2e2b24;--text:#e8e4dc;
      --muted:#8a8278;--accent:#e05a4e;--accent-light:#2a1a18;
      --link:#7eb8e8;--code-bg:#1a1814;--shadow:rgba(0,0,0,.3);
    }}
    *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:'Source Sans 3',sans-serif;background:var(--bg);color:var(--text);font-size:17px;line-height:1.7;transition:background .3s,color .3s}}
    .topbar{{position:sticky;top:0;z-index:100;background:var(--bg);border-bottom:1px solid var(--border);padding:.9rem 2rem;display:flex;justify-content:space-between;align-items:center;backdrop-filter:blur(8px)}}
    .back-link{{font-family:'JetBrains Mono',monospace;font-size:.8rem;color:var(--muted);text-decoration:none;transition:color .15s}}
    .back-link:hover{{color:var(--accent)}}
    .theme-btn{{background:none;border:1px solid var(--border);border-radius:6px;padding:.25rem .55rem;font-size:.75rem;color:var(--muted);cursor:pointer;font-family:'JetBrains Mono',monospace;transition:all .15s}}
    .theme-btn:hover{{border-color:var(--accent);color:var(--accent)}}
    .progress-bar{{position:fixed;top:0;left:0;height:2px;background:var(--accent);z-index:200;transition:width .1s}}
    .page{{max-width:1100px;margin:0 auto;display:grid;grid-template-columns:1fr 220px;gap:4rem;padding:4rem 2rem 8rem}}
    .post-meta{{margin-bottom:2rem}}
    .post-date{{font-family:'JetBrains Mono',monospace;font-size:.8rem;color:var(--muted);margin-bottom:.8rem}}
    .post-title{{font-family:'Lora',serif;font-size:2.2rem;font-weight:600;line-height:1.3;margin-bottom:1rem}}
    .post-tags{{display:flex;flex-wrap:wrap;gap:.4rem;margin-bottom:1.5rem}}
    .tag{{font-size:.72rem;padding:.2rem .55rem;border-radius:100px;background:var(--surface);color:var(--muted);font-family:'JetBrains Mono',monospace}}
    .tag.hl{{background:var(--accent-light);color:var(--accent)}}
    .post-desc{{font-size:1.05rem;color:var(--muted);line-height:1.7;padding:1.2rem 1.5rem;border-left:3px solid var(--accent);background:var(--surface);border-radius:0 8px 8px 0}}
    .divider{{height:1px;background:var(--border);margin:2.5rem 0}}
    .prose{{max-width:680px}}
    .prose h2{{font-family:'Lora',serif;font-size:1.5rem;font-weight:600;margin:2.5rem 0 1rem}}
    .prose h3{{font-family:'Lora',serif;font-size:1.15rem;font-weight:600;margin:2rem 0 .7rem}}
    .prose p{{margin-bottom:1.2rem}}
    .prose a{{color:var(--link);text-decoration:underline;text-underline-offset:3px}}
    .prose a:hover{{color:var(--accent)}}
    .prose strong{{font-weight:600}}
    .prose em{{font-style:italic;font-family:'Lora',serif}}
    .prose ul,.prose ol{{padding-left:1.5rem;margin-bottom:1.2rem}}
    .prose li{{margin-bottom:.4rem}}
    .prose pre{{background:var(--code-bg);border:1px solid var(--border);border-radius:8px;padding:1.2rem 1.4rem;overflow-x:auto;margin:1.5rem 0;font-size:.82rem;line-height:1.65}}
    .prose code{{font-family:'JetBrains Mono',monospace;font-size:.85em}}
    .prose p code,.prose li code{{background:var(--code-bg);padding:.1em .4em;border-radius:4px;font-size:.83em}}
    .prose blockquote{{border-left:3px solid var(--accent);padding:.8rem 1.2rem;margin:1.5rem 0;background:var(--surface);border-radius:0 6px 6px 0;color:var(--muted);font-style:italic;font-family:'Lora',serif}}
    .prose table{{width:100%;border-collapse:collapse;font-size:.88rem;margin:1.5rem 0}}
    .prose th{{background:var(--surface);font-family:'JetBrains Mono',monospace;font-size:.75rem;padding:.6rem 1rem;text-align:left;border-bottom:2px solid var(--border);color:var(--muted)}}
    .prose td{{padding:.6rem 1rem;border-bottom:1px solid var(--border)}}
    .prose tr:last-child td{{border-bottom:none}}
    .toc-sidebar{{position:sticky;top:5rem;height:fit-content}}
    .toc-title{{font-family:'JetBrains Mono',monospace;font-size:.72rem;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;margin-bottom:.8rem}}
    .toc-list{{list-style:none;display:flex;flex-direction:column;gap:0}}
    .toc-item a{{display:block;font-size:.82rem;color:var(--muted);text-decoration:none;padding:.3rem .7rem;border-left:2px solid var(--border);transition:all .15s;line-height:1.4}}
    .toc-item a:hover,.toc-item.active a{{color:var(--accent);border-left-color:var(--accent)}}
    .toc-item.sub a{{padding-left:1.4rem;font-size:.78rem}}
    @media(max-width:900px){{.page{{grid-template-columns:1fr;gap:0}}.toc-sidebar{{display:none}}.post-title{{font-size:1.7rem}}}}
    @media(max-width:600px){{.page{{padding:2rem 1.2rem 6rem}}}}
    @keyframes fadeIn{{from{{opacity:0;transform:translateY(10px)}}to{{opacity:1;transform:translateY(0)}}}}
    article{{animation:fadeIn .5s ease}}
  </style>
</head>
<body>
<div class="progress-bar" id="progress"></div>
<nav class="topbar">
  <a href="index.html" class="back-link">← 所有文章</a>
  <button class="theme-btn" onclick="toggleTheme()">◑ theme</button>
</nav>
<div class="page">
  <article>
    <div class="post-meta">
      <div class="post-date">{date_str} · 预计阅读 {reading_min} 分钟</div>
      <h1 class="post-title">{title_esc}</h1>
      {tags_html}
      {desc_block}
    </div>
    <div class="divider"></div>
    <div class="prose" id="prose">
{body_html}
    </div>
    <div class="divider"></div>
    <div style="font-size:.85rem;color:var(--muted);font-family:'JetBrains Mono',monospace;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:1rem;">
      <span>// 如有错误请通过 GitHub Issues 指正</span>
      <a href="index.html" style="color:var(--accent);text-decoration:none;">← 返回文章列表</a>
    </div>
  </article>
  <aside class="toc-sidebar">
    {toc_html}
  </aside>
</div>
<script>
  function toggleTheme(){{const c=document.documentElement.getAttribute('data-theme');document.documentElement.setAttribute('data-theme',c==='dark'?'light':'dark');localStorage.setItem('theme',c==='dark'?'light':'dark');}}
  const saved=localStorage.getItem('theme');if(saved)document.documentElement.setAttribute('data-theme',saved);
  window.addEventListener('scroll',()=>{{
    const d=document.documentElement,s=d.scrollTop,t=d.scrollHeight-d.clientHeight;
    document.getElementById('progress').style.width=(s/t*100)+'%';
    const hs=document.querySelectorAll('.prose h2,.prose h3'),ti=document.querySelectorAll('.toc-item');
    let cur='';hs.forEach(h=>{{if(h.offsetTop-100<=s)cur=h.id;}});
    ti.forEach(i=>{{const a=i.querySelector('a');i.classList.toggle('active',a&&a.getAttribute('href')==='#'+cur);}});
  }});
</script>
</body>
</html>"""


# ─────────────────────────────────────────────
# 4. 更新 index.html 的文章列表
# ─────────────────────────────────────────────

def update_index(index_path: Path, post_filename: str, title: str,
                 abstract: str, tags: list[str], date_str: str):
    """在 index.html 的文章列表最前面插入新文章"""
    if not index_path.exists():
        print(f"  ⚠ 未找到 index.html，跳过更新")
        return

    html = index_path.read_text(encoding="utf-8")

    tags_html = "".join(
        f'<span class="post-tag{"  featured" if i < 2 else ""}">{escape(t)}</span>'
        for i, t in enumerate(tags)
    )

    excerpt = (abstract[:120] + "…") if len(abstract) > 120 else abstract
    date_display = date_str.replace("-", " · ")

    new_item = f"""        <a href="{post_filename}" class="post-item" data-title="{escape(title)}" data-tags="{escape(' '.join(tags))}">
          <div class="post-date">{date_display[5:]}</div>
          <div class="post-content">
            <div class="post-title">{escape(title)}</div>
            <div class="post-excerpt">{escape(excerpt)}</div>
            <div class="post-tags">{tags_html}</div>
          </div>
        </a>"""

    # 插入到第一个 post-list div 的开头
    marker = '<div class="post-list">'
    if marker in html:
        html = html.replace(marker, marker + "\n" + new_item, 1)
        index_path.write_text(html, encoding="utf-8")
        print(f"  ✓ index.html 已更新")
    else:
        print(f"  ⚠ 未找到插入位置，请手动添加到 index.html")


# ─────────────────────────────────────────────
# 5. 主流程
# ─────────────────────────────────────────────

def slugify(title: str) -> str:
    """生成 URL 友好的文件名"""
    # 保留英文、数字、中文
    s = re.sub(r'[^\w\u4e00-\u9fff]+', '-', title.lower())
    return s.strip('-')[:60]


def main():
    parser = argparse.ArgumentParser(description="发布 docx 文章到博客")
    parser.add_argument("docx", help="docx 文件路径")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"),
                        help="发布日期，格式 YYYY-MM-DD（默认今天）")
    parser.add_argument("--tags", default="",
                        help="标签，逗号分隔，如 'llm,data,inference'")
    parser.add_argument("--out", default=".",
                        help="输出目录（博客根目录，默认当前目录）")
    parser.add_argument("--slug", default="",
                        help="自定义文件名（不含.html）")
    args = parser.parse_args()

    docx_path = Path(args.docx)
    if not docx_path.exists():
        print(f"✗ 文件不存在: {docx_path}")
        sys.exit(1)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    tags = [t.strip() for t in args.tags.split(",") if t.strip()]

    print(f"📄 正在处理: {docx_path.name}")

    # Step 1: docx → markdown
    print("  → 解析 docx...")
    md = docx_to_markdown(docx_path)

    # Step 2: 提取结构
    article = parse_article(md)
    if not article["title"]:
        print("  ⚠ 未找到标题（请在 docx 中用 Heading 1 写标题）")
        article["title"] = docx_path.stem

    print(f"  标题: {article['title']}")
    print(f"  摘要: {article['abstract'][:60]}..." if article['abstract'] else "  摘要: (无)")

    # Step 3: markdown → HTML
    print("  → 转换为 HTML...")
    body_html = md_to_html(article["body_md"])
    toc = extract_toc(body_html)
    print(f"  目录条目: {len(toc)} 个")

    # Step 4: 生成文件名
    slug = args.slug or slugify(article["title"])
    post_filename = f"{slug}.html"
    out_path = out_dir / post_filename

    # Step 5: 渲染完整页面
    date_str = args.date
    post_html = generate_post_html(article, tags, date_str, body_html, toc)
    out_path.write_text(post_html, encoding="utf-8")
    print(f"  ✓ 生成: {out_path}")

    # Step 6: 更新 index.html
    print("  → 更新 index.html...")
    update_index(out_dir / "index.html", post_filename,
                 article["title"], article["abstract"], tags, date_str)

    print(f"\n✅ 发布完成！")
    print(f"   文件: {out_path}")
    print(f"\n   下一步：")
    print(f"   git add {post_filename} index.html")
    print(f"   git commit -m 'post: {article['title']}'")
    print(f"   git push")


if __name__ == "__main__":
    main()
