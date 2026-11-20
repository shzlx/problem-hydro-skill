#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import html as html_lib
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SCRIPT_VERSION = "0.1.0"
BASE = "https://codeforces.com"
MSK = timezone(timedelta(hours=3))
DEFAULT_TIMEOUT = 20.0
DEFAULT_CACHE_TTL = 3600.0

VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}

NOISE_CLASSES = {
    "html2md-panel",
    "input-output-copier",
    "ojb_btn",
    "translateButton",
    "popover_content",
    "monaco-editor",
    "source-copier",
}


# ---------------------------------------------------------------------------
# 极简 DOM
# ---------------------------------------------------------------------------

class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag: str, attrs: dict[str, str], parent: "Node | None" = None) -> None:
        self.tag = tag
        self.attrs = attrs
        self.children: list[Any] = []
        self.parent = parent

    @property
    def classes(self) -> list[str]:
        return (self.attrs.get("class") or "").split()

    def has_class(self, name: str) -> bool:
        return name in self.classes

    def get(self, key: str, default: str = "") -> str:
        return self.attrs.get(key, default)


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#document", {})
        self.stack: list[Node] = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, {k: (v if v is not None else "") for k, v in attrs}, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        node = Node(tag, {k: (v if v is not None else "") for k, v in attrs}, self.stack[-1])
        self.stack[-1].children.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        if data:
            self.stack[-1].children.append(data)


def parse_html(html: str) -> Node:
    builder = _TreeBuilder()
    builder.feed(html)
    builder.close()
    return builder.root


def iter_elements(node: Node) -> Iterable[Node]:
    for child in node.children:
        if isinstance(child, Node):
            yield child
            yield from iter_elements(child)


def find_all(node: Node, tag: str | None = None, cls: str | None = None,
             id: str | None = None) -> list[Node]:
    out = []
    for el in iter_elements(node):
        if tag and el.tag != tag:
            continue
        if cls and not el.has_class(cls):
            continue
        if id and el.get("id") != id:
            continue
        out.append(el)
    return out


def find_first(node: Node, tag: str | None = None, cls: str | None = None,
               id: str | None = None) -> Node | None:
    for el in iter_elements(node):
        if tag and el.tag != tag:
            continue
        if cls and not el.has_class(cls):
            continue
        if id and el.get("id") != id:
            continue
        return el
    return None


def collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\u00a0", " ")).strip()


def node_text(node: Node | str) -> str:
    if isinstance(node, str):
        return node
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
        elif child.tag in ("script", "style"):
            continue
        elif child.tag == "br":
            parts.append(" ")
        else:
            parts.append(node_text(child))
    return collapse("".join(parts))


def pre_text(node: Node) -> str:
    chunks: list[str] = []

    def walk(n: Node):
        for child in n.children:
            if isinstance(child, str):
                chunks.append(child)
            elif child.tag == "br":
                chunks.append("\n")
            elif child.tag in ("script", "style"):
                continue
            else:
                walk(child)

    walk(node)
    text = "".join(chunks).replace("\u00a0", " ").replace("\r\n", "\n")
    return text.strip("\n")


def code_language(node: Node) -> str:
    for el in iter_elements(node):
        if el.tag != "code":
            continue
        for cls in el.classes:
            if cls.startswith("language-"):
                return cls[len("language-"):]
            if cls.startswith("lang-"):
                return cls[len("lang-"):]
    for cls in node.classes:
        if cls.startswith("language-"):
            return cls[len("language-"):]
    return ""


def abs_url(url: str, base: str = BASE) -> str:
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        return url
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return BASE + url
    return base.rstrip("/") + "/" + url


def clean_tree(node: Node) -> None:
    """去掉脚本/样式/复制按钮等噪声，链接与图片转绝对地址。"""
    kept: list[Any] = []
    for child in node.children:
        if isinstance(child, Node):
            if child.tag in ("script", "style"):
                continue
            if any(c in NOISE_CLASSES for c in child.classes):
                continue
            clean_tree(child)
            if child.tag == "a" and child.get("href"):
                child.attrs["href"] = abs_url(child.get("href"))
            if child.tag == "img" and child.get("src"):
                child.attrs["src"] = abs_url(child.get("src"))
            child.attrs.pop("style", None)
        kept.append(child)
    node.children = kept


# ---------------------------------------------------------------------------
# HTML -> Markdown / 纯文本
# ---------------------------------------------------------------------------

def md(node: Node | str, base_url: str = BASE, in_pre: bool = False) -> str:
    if isinstance(node, str):
        if in_pre:
            return node
        return re.sub(r"\s+", " ", node.replace("\u00a0", " "))

    tag = node.tag
    if tag in ("script", "style"):
        return ""
    if tag == "br":
        return "\n" if in_pre else "  \n"
    if tag == "pre":
        lang = code_language(node)
        body = pre_text(node)
        return f"\n\n```{lang}\n{body}\n```\n\n"
    if tag == "code":
        return "`" + collapse(node_text(node)) + "`"
    if tag in ("b", "strong"):
        inner = md_children(node, base_url, in_pre).strip()
        return f"**{inner}**" if inner else ""
    if tag in ("i", "em"):
        inner = md_children(node, base_url, in_pre).strip()
        return f"*{inner}*" if inner else ""
    if tag == "sup":
        return "<sup>" + collapse(node_text(node)) + "</sup>"
    if tag == "sub":
        return "<sub>" + collapse(node_text(node)) + "</sub>"
    if tag == "a":
        text = md_children(node, base_url, in_pre).strip() or collapse(node_text(node))
        href = abs_url(node.get("href"), base_url)
        return f"[{text}]({href})" if href else text
    if tag == "img":
        src = abs_url(node.get("src"), base_url)
        if not src:
            return ""
        return f"![{node.get('alt')}]({src})"
    if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
        level = int(tag[1])
        return "\n" + "#" * level + " " + md_children(node, base_url, in_pre).strip() + "\n\n"
    if tag == "li":
        return "- " + md_children(node, base_url, in_pre).strip() + "\n"
    if tag in ("ul", "ol"):
        return "\n" + md_children(node, base_url, in_pre).rstrip() + "\n\n"
    if tag == "hr":
        return "\n---\n\n"
    if tag == "table":
        return "\n" + table_md(node) + "\n\n"
    if tag == "details":
        summary = find_first(node, "summary")
        body = "\n".join(md(c, base_url, in_pre) for c in node.children
                         if not (isinstance(c, Node) and c.tag == "summary"))
        title = collapse(node_text(summary)) if summary else ""
        return "\n\n" + (f"**{title}**\n\n" if title else "") + body.strip() + "\n\n"
    if tag in ("div", "section") and node.has_class("spoiler"):
        # Codeforces 的折叠块：<b class="spoiler-title"> + <div class="spoiler-content">
        title_node = find_first(node, "b", cls="spoiler-title") or find_first(node, "strong", cls="spoiler-title")
        content_node = find_first(node, "div", cls="spoiler-content")
        title = collapse(node_text(title_node)) if title_node else ""
        body = md(content_node, base_url, in_pre).strip() if content_node else ""
        if not body:
            body = md_children(node, base_url, in_pre).strip()
            if title and body.startswith(f"**{title}**"):
                body = body[len(f"**{title}**"):].lstrip()
        return "\n\n" + (f"**{title}**\n\n" if title else "") + body + "\n\n"
    if tag in ("p", "div", "section", "blockquote", "center"):
        inner = md_children(node, base_url, in_pre).strip()
        return "\n" + inner + "\n\n" if inner else ""
    return md_children(node, base_url, in_pre)


def md_children(node: Node, base_url: str, in_pre: bool = False) -> str:
    out = "".join(md(c, base_url, in_pre) for c in node.children)
    return re.sub(r"[ \t]+\n", "\n", out)


def table_md(node: Node) -> str:
    rows = find_all(node, "tr")
    if not rows:
        return collapse(node_text(node))
    lines: list[str] = []
    for i, tr in enumerate(rows):
        cells = [c for c in tr.children if isinstance(c, Node) and c.tag in ("td", "th")]
        lines.append("| " + " | ".join(collapse(node_text(c)) for c in cells) + " |")
        if i == 0:
            lines.append("| " + " | ".join("---" for _ in cells) + " |")
    return "\n".join(lines)


def tidy_markdown(text: str) -> str:
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"(?m)^[ \t]+(- |\* )", r"\1", text)
    lines = text.split("\n")
    in_code = False
    for i, line in enumerate(lines):
        if line.startswith("```"):
            in_code = not in_code
            continue
        if not in_code:
            lines[i] = re.sub(r"^ +(?=\S)", "", line)
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def readable_text(node: Node | str) -> str:
    parts: list[str] = []

    def walk(n: Node | str):
        if isinstance(n, str):
            parts.append(re.sub(r"\s+", " ", n))
            return
        tag = n.tag
        if tag in ("script", "style"):
            return
        if tag == "br":
            parts.append("\n")
            return
        if tag == "pre":
            parts.append("\n" + pre_text(n) + "\n")
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            parts.append("\n")
            for c in n.children:
                walk(c)
            parts.append("\n")
            return
        if tag == "li":
            parts.append("\n- ")
            for c in n.children:
                walk(c)
            parts.append("\n")
            return
        if tag in ("p", "div", "section", "ul", "ol", "table", "blockquote", "center"):
            parts.append("\n")
            for c in n.children:
                walk(c)
            parts.append("\n")
            return
        for c in n.children:
            walk(c)

    walk(node)
    text = "".join(parts).replace("\u00a0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_code_blocks(node: Node) -> list[dict[str, str]]:
    out = []
    for pre in find_all(node, "pre"):
        out.append({"language": code_language(pre), "code": pre_text(pre)})
    return out


# ---------------------------------------------------------------------------
# 元信息 / 抓取
# ---------------------------------------------------------------------------

def normalize_title(title_html: str) -> str:
    if "<" in title_html:
        root = parse_html(title_html)
        title = collapse(node_text(root))
    else:
        title = collapse(html_lib.unescape(title_html))
    return re.sub(r"\s*-\s*Codeforces\s*$", "", title, flags=re.I).strip()


def parse_entry_id(text: str) -> str:
    text = text.strip()
    patterns = [
        r"^https?://(?:www\.)?codeforces\.com/blog/entry/(\d+)",
        r"^https?://(?:www\.)?codeforces\.com/(?:[a-z]{2}/)?blog/entry/(\d+)",
        r"^entry/(\d+)$",
        r"^blog/entry/(\d+)$",
        r"^(\d+)$",
    ]
    for pattern in patterns:
        m = re.match(pattern, text, re.I)
        if m:
            return m.group(1)
    raise ValueError(
        f"无法识别的目标：{text}；请给 blog entry 链接（https://codeforces.com/blog/entry/135181）"
        " 或数字 entry id"
    )


def http_get(url: str, timeout: float, headers: dict[str, str] | None = None) -> bytes:
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        **(headers or {}),
    })
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_api(entry_id: str, timeout: float) -> dict[str, Any]:
    url = f"{BASE}/api/blogEntry.view?blogEntryId={entry_id}"
    raw = http_get(url, timeout)
    payload = json.loads(raw.decode("utf-8"))
    if payload.get("status") != "OK":
        raise RuntimeError(payload.get("comment") or "Codeforces API 返回失败")
    result = payload.get("result") or {}
    if not result.get("content"):
        raise RuntimeError(f"blog entry {entry_id} 没有正文（可能不是题解，或权限受限）")
    return result


def fetch_web(entry_id: str, timeout: float,
              headers: Optional[dict[str, str]] = None) -> dict[str, Any]:
    url = f"{BASE}/blog/entry/{entry_id}"
    raw = http_get(url, timeout, headers)
    page = raw.decode("utf-8", "replace")
    if "Just a moment" in page[:2000] or "cf-challenge" in page:
        raise RuntimeError("Codeforces 网页触发了 Cloudflare 验证；请改用 --source api 或 --input-file")
    root = parse_html(page)
    topic = find_first(root, "div", cls="topic")
    body = None
    for candidate in find_all(root, "div", cls="ttypography"):
        p = candidate.parent
        inside_comment = False
        while p is not None:
            if p.has_class("comment-content"):
                inside_comment = True
                break
            p = p.parent
        if not inside_comment:
            body = candidate
            break
    if body is None:
        raise RuntimeError("网页里没有找到题解正文 .ttypography")

    title = ""
    if topic:
        t = find_first(topic, "div", cls="title")
        if t:
            title = collapse(node_text(t))
    author = ""
    published = ""
    if topic:
        a = find_first(topic, "a", cls="rated-user")
        if a:
            author = collapse(node_text(a))
        h = find_first(topic, "span", cls="format-humantime")
        if h:
            published = h.get("title") or collapse(node_text(h))

    content = content_html(body)
    result: dict[str, Any] = {
        "id": int(entry_id),
        "title": title,
        "content": content,
        "authorHandle": author,
        "publishedAtRaw": published,
        "locale": "en",
        "originalLocale": "en",
        "tags": [],
    }
    if published:
        try:
            dt = datetime.strptime(published, "%b/%d/%Y %H:%M").replace(tzinfo=MSK)
            result["creationTimeSeconds"] = int(dt.timestamp())
        except ValueError:
            pass
    return result


def content_html(node: Node) -> str:
    """只给 --html 用；把节点子树重新序列化。"""
    out: list[str] = []

    def esc_text(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def walk(n: Node):
        for c in n.children:
            if isinstance(c, str):
                out.append(esc_text(c))
            else:
                attrs = "".join(
                    f' {k}="{html_lib.escape(v, quote=True)}"' for k, v in c.attrs.items()
                )
                if c.tag in VOID_TAGS:
                    out.append(f"<{c.tag}{attrs}>")
                else:
                    out.append(f"<{c.tag}{attrs}>")
                    walk(c)
                    out.append(f"</{c.tag}>")

    walk(node)
    return "".join(out)


# ---------------------------------------------------------------------------
# 解析题解
# ---------------------------------------------------------------------------

PROBLEM_URL_RE = re.compile(r"/(?:contest|gym)/(\d+)/problem/([^/?#]+)")


def detect_problem_heading(node: Node) -> dict[str, str] | None:
    """识别题解里的题目分段标题。

    新版题解一般是 <h3><a href="/gym/.../problem/A">A. Garland</a></h3>；
    老版题解则可能是 <p><a href="/contest/412/problem/A">412A - Poster</a></p>。
    只有“整段文字就是题目标题”的段落才算分段，正文里顺带提到题目的链接不拆。
    """
    is_heading = node.tag in ("h2", "h3", "h4")
    text = collapse(node_text(node))

    for a in find_all(node, "a"):
        href = a.get("href") or ""
        m = PROBLEM_URL_RE.search(href)
        if not m:
            continue
        index = m.group(2)
        label = collapse(node_text(a))
        if not is_heading:
            # 段落形态：整段必须很短，且以题号开头（A. / 412A - / A -）
            if len(text) > 160 or not label:
                continue
            if not re.match(rf"^(?:\d{{1,5}})?{re.escape(index)}(?:\b|[.\-–:：])", text, re.I):
                continue
        return {
            "index": index,
            "title": text or label,
            "problemUrl": abs_url(href),
        }

    if not is_heading:
        if len(text) <= 160:
            m = re.match(r"^([A-Z][0-9A-Z]*)[.\-–:：]\s+(.+)", text)
            if m:
                return {"index": m.group(1), "title": text, "problemUrl": ""}
        return None
    m = re.match(r"^(?:Problem\s+)?([A-Z][0-9A-Z]*)[.:\-–]\s*(.*)$", text)
    if m and (m.group(2) or len(text) <= 20):
        return {"index": m.group(1), "title": text, "problemUrl": ""}
    return None


def split_by_problem(root: Node) -> dict[str, Any]:
    intro = Node("#fragment", {})
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for child in list(root.children):
        heading = detect_problem_heading(child) if isinstance(child, Node) else None
        if heading:
            if current:
                sections.append(finalize_section(current, len(sections) + 1))
            current = {**heading, "nodes": []}
            continue
        if current:
            current["nodes"].append(child)
        else:
            intro.children.append(child)

    if current:
        sections.append(finalize_section(current, len(sections) + 1))

    return {
        "introText": readable_text(intro),
        "introMarkdown": tidy_markdown(md(intro)),
        "sections": sections,
    }


def finalize_section(section: dict[str, Any], seq: int) -> dict[str, Any]:
    wrapper = Node("#fragment", {})
    wrapper.children = section["nodes"]
    body_md = tidy_markdown(md(wrapper))
    url = section.get("problemUrl") or ""
    contest_match = re.search(r"/(?:contest|gym)/(\d+)/problem/", url)
    contest_id = contest_match.group(1) if contest_match else ""
    index = section["index"]
    return {
        "seq": seq,
        "index": index,
        "contestId": contest_id,
        "problemKey": f"{contest_id}{index}" if contest_id else index,
        "title": section["title"],
        "problemUrl": url,
        "markdown": body_md,
        "text": readable_text(wrapper),
        "codeBlocks": extract_code_blocks(wrapper),
    }


def format_published(ts: float | None, raw: str = "") -> tuple[str, str]:
    if ts:
        dt = datetime.fromtimestamp(ts, MSK)
        return dt.isoformat(), dt.strftime("%b/%d/%Y %H:%M")
    return raw, raw


def build_editorial(entry: dict[str, Any], entry_id: str, source_url: str,
                    include_html: bool) -> dict[str, Any]:
    content = entry.get("content") or ""
    root = parse_html(content)
    body = find_first(root, "div", cls="ttypography") or root
    clean_tree(body)

    split = split_by_problem(body)
    ts = entry.get("creationTimeSeconds")
    published_iso, published_raw = format_published(ts, entry.get("publishedAtRaw") or "")

    data: dict[str, Any] = {
        "platform": "Codeforces",
        "type": "editorial",
        "entryId": entry_id,
        "title": normalize_title(entry.get("title") or "") or f"Codeforces Blog {entry_id}",
        "sourceUrl": source_url,
        "author": collapse(entry.get("authorHandle") or ""),
        "publishedAt": published_iso,
        "publishedAtRaw": published_raw,
        "grabbedAt": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "scriptVersion": SCRIPT_VERSION,
        "locale": entry.get("locale") or "",
        "originalLocale": entry.get("originalLocale") or "",
        "tags": entry.get("tags") or [],
        "markdown": tidy_markdown(md(body)),
        "text": readable_text(body),
        "introText": split["introText"],
        "introMarkdown": split["introMarkdown"],
        "sections": split["sections"],
        "codeBlocks": extract_code_blocks(body),
    }
    if include_html:
        data["html"] = content
    return data


def editorial_markdown(data: dict[str, Any]) -> str:
    lines = [
        f"# {data.get('title') or 'Codeforces Blog ' + data.get('entryId', '')}",
        "",
        f"- 平台：{data.get('platform')}",
        f"- 题解链接：{data.get('sourceUrl')}",
        f"- 作者：{data.get('author') or '未知'}",
        f"- 发布时间：{data.get('publishedAt') or '未知'}",
        f"- 抓取时间：{data.get('grabbedAt')}",
        f"- 脚本版本：{data.get('scriptVersion')}",
        "",
    ]
    if data.get("introMarkdown"):
        lines += ["## 前言", "", data["introMarkdown"], ""]

    sections = data.get("sections") or []
    if not sections:
        lines += ["## 正文", "", data.get("markdown", ""), ""]
    else:
        for section in sections:
            lines += [f"## {section.get('title') or section.get('index')}", ""]
            if section.get("problemUrl"):
                lines += [f"- 原题链接：{section['problemUrl']}", ""]
            if section.get("markdown"):
                lines += [section["markdown"], ""]

    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"


# ---------------------------------------------------------------------------
# 缓存 / CLI
# ---------------------------------------------------------------------------

def default_cache_dir() -> str:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return str(Path(base) / "cf-editorial-export")


def load_cached(path: Path, ttl: float) -> Optional[bytes]:
    try:
        if time.time() - path.stat().st_mtime <= ttl:
            return path.read_bytes()
    except OSError:
        return None
    return None


def save_cache(path: Path, raw: bytes) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    except OSError:
        pass


def fetch_with_retry(fn, entry_id: str, timeout: float, attempts: int = 3):
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn(entry_id, timeout)
        except (HTTPError, URLError, TimeoutError, RuntimeError) as exc:
            last = exc
            if i + 1 < attempts:
                time.sleep(min(1.5 * (i + 1), 3.0))
    raise last  # type: ignore[misc]


def load_input_file(path: str, entry_id: str) -> dict[str, Any]:
    text = Path(path).expanduser().read_text(encoding="utf-8", errors="replace")
    stripped = text.lstrip()
    if stripped.startswith("{"):
        payload = json.loads(text)
        if payload.get("status") == "OK":
            result = payload["result"]
        elif payload.get("content"):
            result = payload
        else:
            raise RuntimeError("输入 JSON 不是 Codeforces blogEntry.view 的返回结构")
    else:
        root = parse_html(text)
        body = None
        for candidate in find_all(root, "div", cls="ttypography"):
            body = candidate
            p = candidate.parent
            while p is not None:
                if p.has_class("comment-content"):
                    body = None
                    break
                p = p.parent
            if body is not None:
                break
        if body is None:
            raise RuntimeError("输入 HTML 里没有找到 .ttypography")

        topic = find_first(root, "div", cls="topic")
        title = ""
        author = ""
        published = ""
        if topic:
            t = find_first(topic, "div", cls="title")
            title = collapse(node_text(t)) if t else ""
            a = find_first(topic, "a", cls="rated-user")
            author = collapse(node_text(a)) if a else ""
            h = find_first(topic, "span", cls="format-humantime")
            published = (h.get("title") or collapse(node_text(h))) if h else ""

        result = {
            "id": int(entry_id),
            "title": title,
            "content": content_html(body),
            "authorHandle": author,
            "publishedAtRaw": published,
            "locale": "en",
            "originalLocale": "en",
            "tags": [],
        }
        if published:
            try:
                dt = datetime.strptime(published, "%b/%d/%Y %H:%M").replace(tzinfo=MSK)
                result["creationTimeSeconds"] = int(dt.timestamp())
            except ValueError:
                pass
    return result


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cf-editorial-export",
        description="抓取 Codeforces blog 题解，输出适合 AI / Agent 消费的 JSON 或 Markdown。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python3 cf-editorial-export.py 135181\n"
            "  python3 cf-editorial-export.py https://codeforces.com/blog/entry/135181 --compact\n"
            "  python3 cf-editorial-export.py 135181 --format markdown --out editorial.md\n"
            "  python3 cf-editorial-export.py --input-file page.html --entry 135181\n"
        ),
    )
    p.add_argument("target", nargs="?", help="blog entry URL 或数字 entry id")
    p.add_argument("--entry", metavar="ID", help="直接指定 entry id（与 target 二选一）")
    p.add_argument("--format", choices=["json", "jsonl", "markdown"], default="json")
    p.add_argument("--out", default="-", help="输出文件；- 表示 stdout（默认）")
    p.add_argument("--source", choices=["auto", "api", "web"], default="auto",
                   help="抓取来源：api（默认优先）、web、auto")
    p.add_argument("--input-file", help="离线解析本地 HTML 或 API JSON")
    p.add_argument("--cookie", help="网页抓取时附加的 Cookie 字符串")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    p.add_argument("--cache-dir", default=default_cache_dir(),
                   help="响应缓存目录，默认 ~/.cache/cf-editorial-export")
    p.add_argument("--cache-ttl", type=float, default=DEFAULT_CACHE_TTL)
    p.add_argument("--refresh", action="store_true", help="忽略缓存强制重抓")
    p.add_argument("--compact", action="store_true", help="JSON 单行紧凑输出")
    p.add_argument("--lean", action="store_true",
                   help="精简 JSON：去掉 text / introText / introMarkdown / codeBlocks / html，保留 sections")
    p.add_argument("--html", action="store_true", help="额外输出原始正文 HTML")
    p.add_argument("--quiet", action="store_true", help="不打印进度日志")
    p.add_argument("--version", action="version", version=f"%(prog)s {SCRIPT_VERSION}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    log = (lambda m: None) if args.quiet else (lambda m: print(m, file=sys.stderr))

    raw_target = args.entry or args.target
    if not raw_target:
        print("error: 需要 target（entry URL / id）或 --entry", file=sys.stderr)
        return 2

    try:
        entry_id = parse_entry_id(str(raw_target))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    source_url = f"{BASE}/blog/entry/{entry_id}"
    cache_path = Path(args.cache_dir).expanduser() / f"{entry_id}.json" if args.cache_dir not in ("", "-") else None

    try:
        if args.input_file:
            log(f"reading {args.input_file}")
            entry = load_input_file(args.input_file, entry_id)
        else:
            raw = load_cached(cache_path, args.cache_ttl) if (cache_path and not args.refresh) else None
            if raw is not None:
                log(f"cache hit: entry {entry_id}")
                payload = json.loads(raw.decode("utf-8"))
                entry = payload["result"]
            else:
                payload = None
                if args.source in ("auto", "api"):
                    log(f"fetch api: blog/entry/{entry_id}")
                    try:
                        result = fetch_with_retry(fetch_api, entry_id, args.timeout)
                        payload = {"status": "OK", "result": result}
                    except Exception as exc:
                        if args.source == "api":
                            raise
                        log(f"api failed: {exc}; fallback to web")
                if payload is None:
                    log(f"fetch web: blog/entry/{entry_id}")
                    headers = {"Cookie": args.cookie} if args.cookie else None
                    result = fetch_with_retry(
                        lambda eid, timeout: fetch_web(eid, timeout, headers),
                        entry_id, args.timeout,
                    )
                    payload = {"status": "OK", "result": result}
                if cache_path:
                    save_cache(cache_path, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
                entry = payload["result"]
    except (ValueError, RuntimeError, HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3 if not isinstance(exc, ValueError) else 2

    data = build_editorial(entry, entry_id, source_url, args.html)
    section_count = len(data.get("sections") or [])

    if args.lean:
        for key in ("text", "introText", "introMarkdown", "codeBlocks", "html"):
            data.pop(key, None)
        for section in data.get("sections") or []:
            section.pop("text", None)
            section.pop("codeBlocks", None)

    if args.format == "json":
        text = json.dumps(data, ensure_ascii=False, indent=None if args.compact else 2) + "\n"
    elif args.format == "jsonl":
        text = json.dumps(data, ensure_ascii=False) + "\n"
    else:
        text = editorial_markdown(data)

    if args.out == "-":
        sys.stdout.write(text)
    else:
        out = Path(args.out).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        log(f"written {out} ({len(text)} bytes)")

    log(f"entry {entry_id}: {section_count} sections, {len(text)} bytes")
    return 0



if __name__ == "__main__":
    raise SystemExit(main())
#（注：内容由AI生成）
