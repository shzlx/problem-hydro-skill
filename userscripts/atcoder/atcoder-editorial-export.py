#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable

SCRIPT_VERSION = "0.1.0"
BASE = "https://atcoder.jp"
USER_AGENT = "atcoder-editorial-export/0.1.0 (+https://atcoder.jp; python-urllib)"
DEFAULT_DELAY = 0.6
DEFAULT_TIMEOUT = 25.0
JST = timezone(timedelta(hours=9))
HEADING_OFFSET = 0  # 题解正文的 h3 直接映射为 ###

VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}


# ---------------------------------------------------------------------------
# 极简 DOM
# ---------------------------------------------------------------------------

class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag: str, attrs: dict[str, str], parent: "Node | None" = None):
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
    code = find_first(node, "code")
    if code is None:
        return ""
    for cls in code.classes:
        if cls.startswith("language-"):
            return cls[len("language-"):]
    return ""


def abs_url(url: str, base: str) -> str:
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        return url
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return BASE + url
    return base.rstrip("/") + "/" + url


# ---------------------------------------------------------------------------
# HTML -> Markdown / 纯文本
# ---------------------------------------------------------------------------

def md(node: Node | str, base_url: str, in_pre: bool = False) -> str:
    if isinstance(node, str):
        if in_pre:
            return node
        return re.sub(r"\s+", " ", node.replace("\u00a0", " "))

    tag = node.tag
    if tag in ("script", "style"):
        return ""
    if tag == "br":
        return "\n" if in_pre else "  \n"
    if tag == "var":
        body = collapse(node_text(node))
        return body if in_pre or not body else f"${body}$"
    if tag == "pre":
        lang = code_language(node)
        body = pre_text(node)
        return f"\n\n```{lang}\n{body}\n```\n\n"
    if tag == "code":
        return "`" + collapse(node_text(node)) + "`"
    if tag in ("b", "strong"):
        return "**" + md_children(node, base_url, in_pre).strip() + "**"
    if tag in ("i", "em"):
        return "*" + md_children(node, base_url, in_pre).strip() + "*"
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
        level = min(int(tag[1]) + HEADING_OFFSET, 6)
        return "\n" + "#" * level + " " + md_children(node, base_url, in_pre).strip() + "\n\n"
    if tag == "li":
        return "- " + md_children(node, base_url, in_pre).strip() + "\n"
    if tag in ("ul", "ol"):
        return "\n" + md_children(node, base_url, in_pre).rstrip() + "\n\n"
    if tag == "hr":
        return "\n---\n\n"
    if tag == "table":
        return "\n" + table_md(node) + "\n\n"
    if tag in ("p", "div", "section", "blockquote"):
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
        if tag in ("p", "div", "section", "ul", "ol", "table", "blockquote", "hr"):
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


def heading_text(node: Node, skip_tags: tuple[str, ...] = ("a",),
                 skip_classes: tuple[str, ...] = ()) -> str:
    """标题文字，跳过“打印页面 / 作者 / 外部链接”等 <a>。"""
    parts: list[str] = []

    def walk(n: Node):
        for child in n.children:
            if isinstance(child, str):
                parts.append(child)
            elif child.tag in skip_tags or child.tag in ("script", "style"):
                continue
            elif any(child.has_class(name) for name in skip_classes):
                continue
            elif child.tag == "br":
                parts.append(" ")
            else:
                walk(child)

    walk(node)
    return collapse("".join(parts))


def h2_title(node: Node) -> str:
    """题解页 h2：保留题目链接文字与 “Editorial/解説”，去掉作者与打印按钮。"""
    parts: list[str] = []

    def walk(n: Node):
        for child in n.children:
            if isinstance(child, str):
                parts.append(child)
            elif child.tag in ("script", "style"):
                continue
            elif child.tag == "br":
                parts.append(" ")
            elif child.has_class("small") or (child.tag == "a" and child.has_class("btn")):
                continue
            else:
                walk(child)

    walk(node)
    return collapse("".join(parts))


def clone_without(node: Node, skip_tags: set[str]) -> Node:
    copy = Node(node.tag, dict(node.attrs))
    for child in node.children:
        if isinstance(child, str):
            copy.children.append(child)
        elif child.tag in skip_tags or child.tag in ("script", "style"):
            continue
        else:
            copy.children.append(clone_without(child, skip_tags))
    return copy


def serialize_html(node: Node | None, base_url: str) -> str:
    if node is None:
        return ""

    def esc(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def walk(n: Node) -> str:
        if n.tag in ("script", "style"):
            return ""
        attrs = dict(n.attrs)
        attrs.pop("style", None)
        if "href" in attrs:
            attrs["href"] = abs_url(attrs["href"], base_url)
        if "src" in attrs:
            attrs["src"] = abs_url(attrs["src"], base_url)
        attr_text = "".join(f' {k}="{esc(v)}"' for k, v in attrs.items())
        inner = "".join(walk(c) if isinstance(c, Node) else esc(c) for c in n.children)
        if n.tag in VOID_TAGS:
            return f"<{n.tag}{attr_text}>"
        return f"<{n.tag}{attr_text}>{inner}</{n.tag}>"

    return walk(node)


# ---------------------------------------------------------------------------
# 抓取
# ---------------------------------------------------------------------------

class Fetcher:
    def __init__(self, *, delay: float = DEFAULT_DELAY, timeout: float = DEFAULT_TIMEOUT,
                 cache_dir: str | None = None, cache_ttl: float = 3600.0,
                 refresh: bool = False, log: Any = None) -> None:
        self.delay = max(0.0, delay)
        self.timeout = timeout
        self.cache_dir = Path(cache_dir).expanduser() if cache_dir else None
        self.cache_ttl = cache_ttl
        self.refresh = refresh
        self.log = log or (lambda msg: print(msg, file=sys.stderr))
        self._last_request = 0.0

    def _cache_path(self, url: str) -> Path | None:
        if not self.cache_dir:
            return None
        key = hashlib.sha1(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{key}.html"

    def get_html(self, url: str) -> str:
        cache = self._cache_path(url)
        if cache and cache.exists() and not self.refresh:
            if time.time() - cache.stat().st_mtime <= self.cache_ttl:
                self.log(f"cache hit {url}")
                return cache.read_text(encoding="utf-8")

        for attempt in range(3):
            gap = time.time() - self._last_request
            if gap < self.delay:
                time.sleep(self.delay - gap)
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,ja;q=0.8",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read()
                    if resp.headers.get("Content-Encoding", "").lower() == "gzip":
                        raw = gzip.decompress(raw)
                    html = raw.decode(resp.headers.get_content_charset() or "utf-8", "replace")
                self._last_request = time.time()
                if cache:
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    cache.write_text(html, encoding="utf-8")
                return html
            except urllib.error.HTTPError as exc:
                self._last_request = time.time()
                if exc.code in (429, 503) and attempt < 2:
                    wait = 2 + attempt * 3
                    self.log(f"HTTP {exc.code} on {url}, retry in {wait}s")
                    time.sleep(wait)
                    continue
                raise RuntimeError(f"HTTP {exc.code} {url}") from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                self._last_request = time.time()
                if attempt < 2:
                    self.log(f"{type(exc).__name__} on {url}, retry")
                    time.sleep(2 + attempt * 2)
                    continue
                raise RuntimeError(f"{type(exc).__name__}: {exc}") from exc
        raise RuntimeError(f"unreachable: {url}")


# ---------------------------------------------------------------------------
# 解析题解页
# ---------------------------------------------------------------------------

def strip_contest_title(raw: str) -> str:
    text = collapse(raw)
    text = re.sub(r"\s*-\s*AtCoder\s*$", "", text, flags=re.I)
    text = re.sub(r"^Editorial\s*-\s*", "", text, flags=re.I)
    return text.strip()


def parse_epoch(value: str) -> str:
    try:
        return datetime.fromtimestamp(int(value), JST).isoformat()
    except (TypeError, ValueError, OverflowError):
        return ""


def detect_lang(text: str) -> str:
    kana = len(re.findall(r"[\u3040-\u30ff]", text))
    return "ja" if kana > 0 else "en"


def content_root_from_nodes(nodes: list[Any]) -> Node:
    meaningful = [n for n in nodes if isinstance(n, Node) or (isinstance(n, str) and n.strip())]
    if len(meaningful) == 1 and isinstance(meaningful[0], Node) and meaningful[0].tag == "div":
        return meaningful[0]
    root = Node("#content", {})
    root.children = nodes
    return root


def split_sections(root: Node, base_url: str) -> tuple[str, list[dict[str, str]]]:
    """按正文里的 h2/h3/h4 分节，返回 (前言 Markdown, 分节列表)。"""
    intro: list[Any] = []
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for child in root.children:
        if isinstance(child, Node) and child.tag in ("h2", "h3", "h4"):
            current = {"title": heading_text(child), "nodes": []}
            sections.append(current)
        elif current is not None:
            current["nodes"].append(child)
        else:
            intro.append(child)

    intro_node = Node("#intro", {})
    intro_node.children = intro
    intro_md = tidy_markdown(md(intro_node, base_url)) if intro else ""

    result = []
    for sec in sections:
        wrapper = Node("#section", {})
        wrapper.children = sec["nodes"]
        result.append({
            "title": sec["title"],
            "markdown": tidy_markdown(md(wrapper, base_url)),
        })
    return intro_md, result


def parse_editorial_page(html: str, *, url: str, contest_id: str,
                         editorial_id: str, fallback: dict[str, Any] | None = None,
                         include_html: bool = False) -> dict[str, Any]:
    doc = parse_html(html)
    h2 = find_first(doc, "h2")
    if h2 is None or h2.parent is None:
        raise RuntimeError("未找到题解标题（h2），页面可能不是题解页或被访问控制拦截")

    container = h2.parent
    title = h2_title(h2)

    # 题目关联：标题里的 task 链接
    problem: dict[str, Any] = {}
    for anchor in find_all(h2, "a"):
        href = anchor.get("href", "")
        m = re.match(rf"^/contests/{re.escape(contest_id)}/tasks/([A-Za-z0-9_]+)$", href)
        if not m:
            continue
        task_id = m.group(1)
        text = collapse(node_text(anchor))
        idx = ""
        name = text
        mm = re.match(r"^([A-Za-z0-9]+)\s*[-–—]\s*(.+)$", text)
        if mm:
            idx, name = mm.group(1), mm.group(2).strip()
        problem = {
            "index": idx,
            "taskId": task_id,
            "title": text,
            "name": name,
            "url": BASE + href,
        }
        break
    if fallback and fallback.get("problem"):
        for key, value in fallback["problem"].items():
            problem.setdefault(key, value)

    # 作者 / 类型标签
    author_node = find_first(h2, "a", cls="username")
    author = collapse(node_text(author_node)) if author_node is not None else ""
    label_node = find_first(container, "span", cls="label")
    label = collapse(node_text(label_node)) if label_node is not None else ""

    # 正文：<hr class="mt-1"> 之后、<div class="clearfix"> 之前
    content_nodes: list[Any] = []
    started = False
    for child in container.children:
        if isinstance(child, Node) and child.tag == "hr" and not started:
            started = True
            continue
        if not started:
            continue
        if isinstance(child, Node) and child.tag == "div" and child.has_class("clearfix"):
            break
        content_nodes.append(child)

    root = content_root_from_nodes(content_nodes)
    markdown = tidy_markdown(md(root, url))
    if not markdown:
        raise RuntimeError("题解正文为空，可能未公开或页面结构变化")

    intro_md, sections = split_sections(root, url)
    if not sections:
        intro_md = ""  # 没有分节时整篇内容已在 markdown 里，避免重复存储
    text = readable_text(root)

    code_blocks = []
    for pre in find_all(root, "pre"):
        code = pre_text(pre)
        if code:
            code_blocks.append({"language": code_language(pre), "code": code})

    times = find_all(container, "span", cls="tooltip-unix")
    posted = parse_epoch(times[0].get("title")) if times else ""
    updated = parse_epoch(times[1].get("title")) if len(times) > 1 else posted

    title_node = find_first(doc, "title")
    contest_title = strip_contest_title(node_text(title_node) if title_node is not None else "")

    data: dict[str, Any] = {
        "platform": "AtCoder",
        "type": "editorial",
        "scriptVersion": SCRIPT_VERSION,
        "contestId": contest_id,
        "contestTitle": contest_title,
        "contestUrl": f"{BASE}/contests/{contest_id}",
        "editorialId": editorial_id,
        "url": url,
        "lang": detect_lang(text),
        "title": title,
        "label": label,
        "author": author,
        "problem": problem,
        "postedAt": posted,
        "updatedAt": updated,
        "introMarkdown": intro_md,
        "sections": sections,
        "codeBlocks": code_blocks,
        "markdown": markdown,
        "text": text,
    }
    if include_html:
        data["html"] = serialize_html(root, url)
    return data


# ---------------------------------------------------------------------------
# 题解索引页
# ---------------------------------------------------------------------------

def parse_problem_heading(text: str, task_id: str, task_url: str) -> dict[str, Any]:
    idx = ""
    name = text
    m = re.match(r"^([A-Za-z0-9]+)\s*[-–—]\s*(.+)$", text)
    if m:
        idx, name = m.group(1), m.group(2).strip()
    return {"index": idx, "taskId": task_id, "title": text, "name": name, "url": task_url}


def parse_editorial_index(html: str, *, contest_id: str) -> dict[str, Any]:
    doc = parse_html(html)
    main = find_first(doc, "div", id="main-container") or doc

    title_node = find_first(doc, "title")
    contest_title = strip_contest_title(node_text(title_node) if title_node is not None else "")

    groups: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for el in iter_elements(main):
        if el.tag == "h3":
            task_link = None
            for anchor in find_all(el, "a"):
                if re.match(rf"^/contests/{re.escape(contest_id)}/tasks/[A-Za-z0-9_]+$",
                            anchor.get("href", "")):
                    task_link = anchor
                    break
            if task_link is None:
                current = None
                continue
            task_id = task_link.get("href").rsplit("/", 1)[-1]
            heading = heading_text(el)
            current = {
                "problem": parse_problem_heading(heading, task_id, BASE + task_link.get("href")),
                "entries": [],
            }
            groups.append(current)
        elif el.tag == "div" and el.has_class("editorial-section") and current is not None:
            for li in find_all(el, "li"):
                entry_links = [
                    a for a in find_all(li, "a")
                    if re.fullmatch(rf"/contests/{re.escape(contest_id)}/editorial/\d+",
                                    a.get("href", ""))
                ]
                if not entry_links:
                    continue
                a = entry_links[0]
                editorial_id = a.get("href", "").rsplit("/", 1)[-1]
                if any(e["editorialId"] == editorial_id for e in current["entries"]):
                    continue
                author_node = find_first(li, "a", cls="username")
                label_node = find_first(li, "span", cls="label")
                current["entries"].append({
                    "editorialId": editorial_id,
                    "url": BASE + a.get("href"),
                    "entryTitle": collapse(node_text(a)),
                    "label": collapse(node_text(label_node)) if label_node is not None else "",
                    "author": collapse(node_text(author_node)) if author_node is not None else "",
                    "hidden": li.has_class("hidden"),
                })

    return {"contestTitle": contest_title, "groups": groups}


# ---------------------------------------------------------------------------
# 目标解析
# ---------------------------------------------------------------------------

def normalize_target(target: str) -> dict[str, Any]:
    t = target.strip()
    m = re.match(r"^https?://atcoder\.jp/contests/([^/?#]+)/editorial/(\d+)(?:/print)?(?:[?#].*)?$", t)
    if m:
        return {"mode": "single", "contestId": m.group(1), "editorialId": m.group(2)}
    m = re.match(r"^https?://atcoder\.jp/contests/([^/?#]+)/editorial(?:/)?(?:[?#].*)?$", t)
    if m:
        return {"mode": "contest", "contestId": m.group(1)}
    m = re.match(r"^https?://atcoder\.jp/contests/([^/?#]+)/tasks/([A-Za-z0-9_]+)(?:[?#].*)?$", t)
    if m:
        return {"mode": "task", "contestId": m.group(1), "taskId": m.group(2)}
    m = re.match(r"^([A-Za-z0-9]+)_([A-Za-z0-9]+)$", t)
    if m and re.fullmatch(r"[a-z][0-9a-z]*|[0-9]+", m.group(2)):
        return {"mode": "task", "contestId": m.group(1), "taskId": t}
    if re.fullmatch(r"[A-Za-z0-9]+", t):
        return {"mode": "contest", "contestId": t}
    raise ValueError(f"无法识别的目标：{target}（请给题解 URL、比赛 ID 或 task id）")


def select_entries(groups: list[dict[str, Any]], *, tasks: list[str] | None,
                   variants: str, wanted_editorial: str | None) -> list[dict[str, Any]]:
    wanted = {t.strip().upper() for t in (tasks or []) if t.strip()}
    selected: list[dict[str, Any]] = []

    for group in groups:
        problem = group["problem"]
        if wanted and not (problem["index"].upper() in wanted or problem["taskId"] in (tasks or [])):
            continue
        visible = [e for e in group["entries"] if not e["hidden"]]
        pool = visible or group["entries"]
        if wanted_editorial:
            pool = [e for e in pool if e["editorialId"] == wanted_editorial]
        if not pool:
            continue
        chosen = pool if variants == "all" else pool[:1]
        for entry in chosen:
            selected.append({**entry, "problem": problem})
    return selected


# ---------------------------------------------------------------------------
# 对外函数
# ---------------------------------------------------------------------------

def fetch_editorial(target: str, *, lang: str = "en", delay: float = DEFAULT_DELAY,
                    timeout: float = DEFAULT_TIMEOUT, cache_dir: str | None = None,
                    cache_ttl: float = 3600.0, refresh: bool = False,
                    tasks: list[str] | None = None, variants: str = "first",
                    editorial_id: str | None = None, include_html: bool = False,
                    log: Any = None) -> dict[str, Any]:
    info = normalize_target(target)
    fetcher = Fetcher(delay=delay, timeout=timeout, cache_dir=cache_dir,
                      cache_ttl=cache_ttl, refresh=refresh, log=log)
    note = log or (lambda m: print(m, file=sys.stderr))
    contest_id = info["contestId"]

    if info["mode"] == "contest" and editorial_id and not tasks:
        info = {"mode": "single", "contestId": contest_id, "editorialId": editorial_id}

    if info["mode"] == "single":
        eid = info["editorialId"]
        url = f"{BASE}/contests/{contest_id}/editorial/{eid}?lang={lang}"
        note(f"[1/1] editorial {eid}")
        return parse_editorial_page(fetcher.get_html(url), url=url,
                                    contest_id=contest_id, editorial_id=eid,
                                    include_html=include_html)

    index_url = f"{BASE}/contests/{contest_id}/editorial?lang={lang}"
    index = parse_editorial_index(fetcher.get_html(index_url), contest_id=contest_id)

    if info["mode"] == "task":
        groups = [g for g in index["groups"] if g["problem"]["taskId"] == info["taskId"]]
        if not groups:
            raise ValueError(f"{contest_id} 的题解索引里没有 {info['taskId']}")
        selected = select_entries(groups, tasks=None, variants=variants,
                                  wanted_editorial=editorial_id)
    else:
        selected = select_entries(index["groups"], tasks=tasks, variants=variants,
                                  wanted_editorial=editorial_id)

    if not selected:
        raise ValueError("没有匹配的题解（可用 --task 指定题号，或检查 --lang）")

    editorials: list[dict[str, Any]] = []
    failed = 0
    for i, entry in enumerate(selected, 1):
        note(f"[{i}/{len(selected)}] editorial {entry['editorialId']} {entry['problem']['index']}")
        url = f"{BASE}/contests/{contest_id}/editorial/{entry['editorialId']}?lang={lang}"
        try:
            item = parse_editorial_page(
                fetcher.get_html(url), url=url, contest_id=contest_id,
                editorial_id=entry["editorialId"],
                fallback={"problem": entry["problem"]},
                include_html=include_html,
            )
            item["label"] = item["label"] or entry.get("label", "")
            item["author"] = item["author"] or entry.get("author", "")
            item["contestTitle"] = item["contestTitle"] or index["contestTitle"]
            editorials.append(item)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            editorials.append({
                "type": "editorial",
                "contestId": contest_id,
                "editorialId": entry["editorialId"],
                "url": url,
                "problem": entry["problem"],
                "error": str(exc),
            })

    return {
        "platform": "AtCoder",
        "type": "editorial-collection",
        "scriptVersion": SCRIPT_VERSION,
        "lang": lang,
        "contestId": contest_id,
        "contestTitle": index["contestTitle"],
        "contestUrl": f"{BASE}/contests/{contest_id}",
        "editorialIndexUrl": index_url,
        "grabbedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "editorialCount": len(editorials),
        "failedCount": failed,
        "editorials": editorials,
    }


def editorial_markdown(ed: dict[str, Any], level: int = 2) -> str:
    prefix = "#" * level
    title = ed.get("title") or (ed.get("problem", {}).get("title", "") + " 题解")
    lines = [f"{prefix} {title}", ""]
    if ed.get("url"):
        lines.append(f"- 题解链接：{ed['url']}")
    if ed.get("problem", {}).get("url"):
        lines.append(f"- 题目链接：{ed['problem']['url']}")
    if ed.get("label"):
        lines.append(f"- 类型：{ed['label']}")
    if ed.get("author"):
        lines.append(f"- 作者：{ed['author']}")
    if ed.get("postedAt"):
        lines.append(f"- 发布：{ed['postedAt']}")
    if ed.get("updatedAt") and ed["updatedAt"] != ed.get("postedAt"):
        lines.append(f"- 更新：{ed['updatedAt']}")
    lines.append("")
    lines.append(ed.get("markdown", ""))
    return tidy_markdown("\n".join(lines))


def collection_markdown(data: dict[str, Any]) -> str:
    lines = [
        f"# {data.get('contestTitle') or 'AtCoder ' + data['contestId']} 题解",
        "",
        "- 平台：AtCoder",
        f"- 比赛链接：{data['contestUrl']}",
        f"- 题解索引：{data['editorialIndexUrl']}",
        f"- 抓取时间：{data['grabbedAt']}",
        f"- 脚本版本：{data['scriptVersion']}",
        f"- 语言：{data['lang']}",
        "",
    ]
    for ed in data["editorials"]:
        if ed.get("error"):
            lines.extend([
                f"## {ed.get('problem', {}).get('title') or ed['editorialId']}",
                "",
                f"抓取失败：{ed['error']}",
                "",
            ])
            continue
        lines.extend([editorial_markdown(ed, level=2), ""])
    return tidy_markdown("\n".join(lines)) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def default_cache_dir() -> str:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return str(Path(base) / "atcoder-editorial-export")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="atcoder-editorial-export",
        description="抓取 AtCoder 题解（单篇或整场），输出适合 AI / Agent 消费的结构化 JSON 或 Markdown。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python3 atcoder-editorial-export.py https://atcoder.jp/contests/abc248/editorial/3797\n"
            "  python3 atcoder-editorial-export.py abc248 --task B --compact\n"
            "  python3 atcoder-editorial-export.py abc248_b --format markdown --out b.md\n"
        ),
    )
    p.add_argument("target", help="题解 URL、题解索引 URL、比赛 ID（abc248）、task id（abc248_b）或 task URL")
    p.add_argument("--lang", choices=["en", "ja"], default="en",
                   help="优先抓取的题解语言，默认 en（索引里缺英文时自动回落日文）")
    p.add_argument("--format", choices=["json", "jsonl", "markdown"], default="json")
    p.add_argument("--out", default="-", help="输出文件；- 表示 stdout（默认）")
    p.add_argument("--task", action="append", metavar="LETTER|TASKID",
                   help="只导出指定题，可重复：--task B --task Ex --task abc248_c")
    p.add_argument("--editorial", metavar="ID", help="只导出指定 editorial id（如 3797）")
    p.add_argument("--variants", choices=["first", "all"], default="first",
                   help="每题取第一篇（默认）或全部可用题解")
    p.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    p.add_argument("--cache-dir", default=default_cache_dir(),
                   help="HTML 缓存目录，默认 ~/.cache/atcoder-editorial-export")
    p.add_argument("--cache-ttl", type=float, default=3600.0)
    p.add_argument("--refresh", action="store_true", help="忽略缓存强制重抓")
    p.add_argument("--compact", action="store_true", help="JSON 单行紧凑输出")
    p.add_argument("--lean", action="store_true",
                   help="精简 JSON：去掉 text / introMarkdown / sections / codeBlocks / html")
    p.add_argument("--html", action="store_true", help="额外输出题解正文 HTML")
    p.add_argument("--quiet", action="store_true", help="不打印进度日志")
    p.add_argument("--version", action="version", version=f"%(prog)s {SCRIPT_VERSION}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    log = (lambda m: None) if args.quiet else (lambda m: print(m, file=sys.stderr))

    try:
        data = fetch_editorial(
            args.target,
            lang=args.lang,
            delay=args.delay,
            timeout=args.timeout,
            cache_dir=None if args.cache_dir in ("", "-") else args.cache_dir,
            cache_ttl=args.cache_ttl,
            refresh=args.refresh,
            tasks=args.task,
            variants=args.variants,
            editorial_id=args.editorial,
            include_html=args.html,
            log=log,
        )
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2 if isinstance(exc, ValueError) else 3

    if args.lean:
        items = data["editorials"] if data.get("type") == "editorial-collection" else [data]
        for item in items:
            for key in ("text", "introMarkdown", "sections", "codeBlocks", "html"):
                item.pop(key, None)

    if args.format == "json":
        text = json.dumps(data, ensure_ascii=False, indent=None if args.compact else 2) + "\n"
    elif args.format == "jsonl":
        items = data["editorials"] if data.get("type") == "editorial-collection" else [data]
        text = "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in items)
    else:
        text = (collection_markdown(data) if data.get("type") == "editorial-collection"
                else editorial_markdown(data) + "\n")

    if args.out == "-":
        sys.stdout.write(text)
    else:
        out = Path(args.out).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        log(f"written {out} ({len(text)} bytes)")

    if data.get("type") == "editorial-collection":
        total = len(data["editorials"])
        failed = data.get("failedCount", 0)
        if failed and failed == total:
            return 3
        if failed:
            return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
#（注：内容由AI生成）
