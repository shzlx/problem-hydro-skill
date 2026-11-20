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
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable

SCRIPT_VERSION = "0.1.0"
BASE = "https://atcoder.jp"
USER_AGENT = (
    "atcoder-contest-export/0.1.0 (+https://atcoder.jp; python-urllib)"
)
DEFAULT_DELAY = 0.6
DEFAULT_TIMEOUT = 25.0

# ---------------------------------------------------------------------------
# 极简 DOM：AtCoder 的题面结构固定，够用即可，避免引入 bs4/lxml 依赖
# ---------------------------------------------------------------------------

VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}


class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag: str, attrs: dict[str, str], parent: "Node | None" = None):
        self.tag = tag
        self.attrs = attrs
        self.children: list[Any] = []
        self.parent = parent

    def __repr__(self) -> str:  # pragma: no cover
        return f"<{self.tag} {self.attrs}>"

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
        elif child.tag == "var":
            parts.append(collapse(node_text(child)))
        else:
            parts.append(node_text(child))
    return collapse("".join(parts))


def pre_text(node: Node) -> str:
    """样例 / 输入格式代码块：<var> 去壳保留原字面量。"""
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
# HTML -> Markdown
# ---------------------------------------------------------------------------

def md(node: Node | str, base_url: str, in_pre: bool = False) -> str:
    if isinstance(node, str):
        if in_pre:
            return node
        # 保留首尾单个空格，避免 There are<var>N</var>people 这种粘连
        return re.sub(r"\s+", " ", node.replace("\u00a0", " "))

    tag = node.tag
    if tag in ("script", "style"):
        return ""
    if tag == "br":
        return "\n" if in_pre else "  \n"
    if tag == "var":
        body = collapse(node_text(node))
        if not body:
            return ""
        return body if in_pre else f"${body}$"
    if tag == "pre":
        body = pre_text(node)
        return f"\n\n```\n{body}\n```\n\n"
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
        level = min(int(tag[1]) + 2, 4)
        return "\n" + "#" * level + " " + md_children(node, base_url, in_pre).strip() + "\n\n"
    if tag == "li":
        return "- " + md_children(node, base_url, in_pre).strip() + "\n"
    if tag in ("ul", "ol"):
        return "\n" + md_children(node, base_url, in_pre).rstrip() + "\n\n"
    if tag == "hr":
        return "\n---\n\n"
    if tag == "table":
        return "\n" + table_md(node, base_url) + "\n\n"
    if tag in ("p", "div", "section", "blockquote"):
        inner = md_children(node, base_url, in_pre).strip()
        return "\n" + inner + "\n\n" if inner else ""
    return md_children(node, base_url, in_pre)


def md_children(node: Node, base_url: str, in_pre: bool = False) -> str:
    out = "".join(md(c, base_url, in_pre) for c in node.children)
    return re.sub(r"[ \t]+\n", "\n", out)


def table_md(node: Node, base_url: str) -> str:
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
    text = re.sub(r"(?m)^[ \t]+(- |\* )", r"\1", text)  # 列表行去掉从缩进带进来的前导空格
    # <br> 后的续行常带缩进空格，去掉行首空格（代码块内保持原样）
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


# ---------------------------------------------------------------------------
# AtCoder 解析
# ---------------------------------------------------------------------------

TIME_RE = re.compile(r"Time\s*Limit\s*:\s*([0-9.]+)\s*sec", re.I)
MEM_RE = re.compile(r"Memory\s*Limit\s*:\s*([0-9.]+)\s*(MiB|MB|GiB|GB)", re.I)
SCORE_EN_RE = re.compile(r"Score\s*:\s*\$?([0-9.]+)\$?\s*points?", re.I)
SCORE_JA_RE = re.compile(r"配点\s*:\s*\$?([0-9.]+)\$?\s*点")


class Fetcher:
    def __init__(self, *, lang: str = "en", delay: float = DEFAULT_DELAY,
                 timeout: float = DEFAULT_TIMEOUT, cache_dir: str | None = None,
                 cache_ttl: float = 3600.0, refresh: bool = False,
                 log: Any = None) -> None:
        self.lang = lang
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
            age = time.time() - cache.stat().st_mtime
            if age <= self.cache_ttl:
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


def split_title(raw: str) -> str:
    text = collapse(raw)
    text = re.sub(r"\s*-\s*AtCoder\s*$", "", text, flags=re.I)
    text = re.sub(r"^Tasks\s*-\s*", "", text, flags=re.I)
    return text


def parse_tasks_table(doc: Node, contest_id: str) -> dict[str, dict[str, Any]]:
    table: dict[str, dict[str, Any]] = {}
    for anchor in find_all(doc, "a"):
        href = anchor.get("href")
        m = re.match(rf"^/contests/{re.escape(contest_id)}/tasks/([A-Za-z0-9_]+)$", href)
        if not m:
            continue
        task_id = m.group(1)
        letter = collapse(node_text(anchor))
        if len(letter) > 8 or not re.fullmatch(r"[A-Za-z0-9]+", letter):
            continue  # 只要左侧的 A / B / C ... 那一格
        row = anchor.parent
        cells: list[Node] = []
        while row is not None and row.tag != "tr":
            row = row.parent
        if row is not None:
            cells = [c for c in row.children if isinstance(c, Node) and c.tag == "td"]
        info = table.setdefault(task_id, {"index": letter, "taskId": task_id, "name": "", "url": ""})
        info["url"] = BASE + href
        if len(cells) >= 2:
            name_cell = cells[1]
            link = find_first(name_cell, "a")
            info["name"] = collapse(node_text(link or name_cell))
        if len(cells) >= 3:
            info["timeLimit"] = collapse(node_text(cells[2]))
        if len(cells) >= 4:
            info["memoryLimit"] = collapse(node_text(cells[3]))
    return table


def pick_lang_span(statement: Node, lang: str) -> tuple[Node, str]:
    preferred = find_first(statement, "span", cls=f"lang-{lang}")
    if preferred is not None:
        return preferred, lang
    other = "ja" if lang != "ja" else "en"
    fallback = find_first(statement, "span", cls=f"lang-{other}")
    if fallback is not None:
        return fallback, other
    # 老题没有 lang 包裹层，正文就是日文原题
    return statement, "ja"


def collect_parts(container: Node) -> list[Node]:
    parts: list[Node] = []

    def walk(n: Node):
        for child in n.children:
            if not isinstance(child, Node):
                continue
            if child.tag == "div" and child.has_class("part"):
                parts.append(child)
                continue  # 不深入，避免嵌套 part 重复
            walk(child)

    walk(container)
    return parts


def read_section(part: Node, base_url: str) -> dict[str, Any]:
    """兼容两代 AtCoder 版式：
    新版 <section><h3>标题</h3>内容…</section>；
    旧版 <h3>标题</h3><section>内容…</section>，且 h3/h4 可能平级出现在 part 里。
    """
    head = find_first(part, "h3") or find_first(part, "h4")
    title = heading_text(head) if head is not None else ""

    # 就地摘掉标题节点，剩下的就是正文
    if head is not None and head.parent is not None:
        try:
            head.parent.children.remove(head)
        except ValueError:
            pass

    markdown = tidy_markdown(md(part, base_url))
    pre = find_first(part, "pre")
    pre_block_text = pre_text(pre) if pre is not None else ""

    # 样例说明：去掉 <pre> 后剩下的部分
    explanation = ""
    if pre is not None:
        explanation = tidy_markdown(md_excluding(part, base_url, {"pre"}))
    return {
        "title": title,
        "markdown": markdown,
        "preText": pre_block_text,
        "explanation": explanation,
    }


def first_pre(nodes: list[Any]) -> Node | None:
    for n in nodes:
        if isinstance(n, Node):
            if n.tag == "pre":
                return n
            found = find_first(n, "pre")
            if found is not None:
                return found
    return None


def read_loose_sections(container: Node, base_url: str) -> list[dict[str, Any]]:
    """最老的题面版式：没有 div.part，h3/h4 与正文、样例说明混排，
    以「下一个 h3/h4」为分节边界。"""
    groups: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for child in container.children:
        if isinstance(child, Node) and child.tag in ("h3", "h4"):
            current = {"title": heading_text(child), "nodes": []}
            groups.append(current)
        elif current is not None:
            current["nodes"].append(child)

    result: list[dict[str, Any]] = []
    for group in groups:
        nodes = group["nodes"]
        markdown = tidy_markdown("".join(md(n, base_url) for n in nodes))
        pre = first_pre(nodes)
        pre_block_text = pre_text(pre) if pre is not None else ""
        explanation = ""
        if pre is not None:
            explanation = tidy_markdown("".join(
                md(clone_without(n, {"pre"}), base_url) if isinstance(n, Node) else md(n, base_url)
                for n in nodes
                if not (isinstance(n, Node) and n.tag in ("hr", "pre"))
            ))
        result.append({
            "title": group["title"],
            "markdown": markdown,
            "preText": pre_block_text,
            "explanation": explanation,
        })
    return result


def clone_without(node: Node | str, skip_tags: set[str]) -> Node:
    if isinstance(node, str):
        return Node("#text", {})  # 不会走到这里
    copy = Node(node.tag, dict(node.attrs))
    for child in node.children:
        if isinstance(child, str):
            copy.children.append(child)
        elif child.tag in skip_tags or child.tag in ("script", "style"):
            continue
        else:
            copy.children.append(clone_without(child, skip_tags))
    return copy


def md_excluding(node: Node, base_url: str, skip_tags: set[str]) -> str:
    return md(clone_without(node, skip_tags), base_url)


def heading_text(node: Node, skip_tags: tuple[str, ...] = ("a",)) -> str:
    """取标题文字，跳过 Editorial 按钮等链接。"""
    parts: list[str] = []

    def walk(n: Node):
        for child in n.children:
            if isinstance(child, str):
                parts.append(child)
            elif child.tag in skip_tags or child.tag in ("script", "style"):
                continue
            elif child.tag == "br":
                parts.append(" ")
            else:
                walk(child)

    walk(node)
    return collapse("".join(parts))


def classify(title: str) -> tuple[str, int]:
    t = title.lower()
    m = re.search(r"(?:sample\s*input|入力例)\s*(\d+)", t)
    if m:
        return "sample_input", int(m.group(1))
    m = re.search(r"(?:sample\s*output|出力例)\s*(\d+)", t)
    if m:
        return "sample_output", int(m.group(1))
    if re.search(r"problem statement|問題文|题目描述", t):
        return "statement", 0
    if re.search(r"constraints?|制約|限制", t):
        return "constraints", 0
    if re.fullmatch(r"(input|入力|输入)(\s*(format|形式))?.*", t):
        return "input", 0
    if re.fullmatch(r"(output|出力|输出)(\s*(format|形式))?.*", t):
        return "output", 0
    if re.search(r"note|注意|提示", t):
        return "note", 0
    if re.search(r"scoring|配点|score", t):
        return "scoring", 0
    if re.search(r"subtasks?|小課題", t):
        return "subtasks", 0
    return "extra", 0


def parse_problem(html: str, *, task_id: str, contest_id: str, lang: str,
                  meta: dict[str, Any] | None = None) -> dict[str, Any]:
    doc = parse_html(html)
    url = f"{BASE}/contests/{contest_id}/tasks/{task_id}"
    statement = find_first(doc, "div", id="task-statement")
    if statement is None:
        raise RuntimeError("未找到 #task-statement，可能题目不存在或页面结构变化")

    span, used_lang = pick_lang_span(statement, lang)

    heading = find_first(doc, "span", cls="h2")
    raw_title = heading_text(heading) if heading is not None else ""
    if not raw_title:
        title_node = find_first(doc, "title")
        raw_title = split_title(node_text(title_node) if title_node is not None else "")

    letter = ""
    name = ""
    if raw_title:
        m = re.match(r"^([A-Za-z0-9]+)\.?\s*[-–—]\s*(.+)$", raw_title)
        if m:
            letter, name = m.group(1), m.group(2).strip()
        else:
            name = raw_title.strip()

    page_text = collapse(node_text(doc))
    time_limit = ""
    memory_limit = ""
    tm = TIME_RE.search(page_text)
    if tm:
        time_limit = f"{tm.group(1)} sec"
    mm = MEM_RE.search(page_text)
    if mm:
        memory_limit = f"{mm.group(1)} {mm.group(2)}"
    if meta:
        time_limit = time_limit or meta.get("timeLimit", "")
        memory_limit = memory_limit or meta.get("memoryLimit", "")

    time_ms = None
    try:
        if time_limit:
            time_ms = int(float(time_limit.split()[0]) * 1000)
    except ValueError:
        pass
    memory_mib = None
    try:
        if memory_limit:
            num = float(memory_limit.split()[0])
            unit = memory_limit.split()[1].lower()
            memory_mib = int(num * (1024 if unit.startswith("gi") else 1))
    except (ValueError, IndexError):
        pass

    raw_parts = collect_parts(span)
    if raw_parts:
        parts = [read_section(p, url) for p in raw_parts]
    else:
        parts = read_loose_sections(span, url)

    # 题面顶部游离内容（AtCoder 把 “Score : 100 points” 放在 part 之外），到第一个分节为止
    prelude_nodes: list[Any] = []
    for child in span.children:
        if isinstance(child, Node) and (
            child.tag in ("h3", "h4") or (child.tag == "div" and child.has_class("part"))
        ):
            break
        prelude_nodes.append(child)
    prelude_md = tidy_markdown("".join(md(c, url) for c in prelude_nodes))

    sections: list[dict[str, str]] = []
    samples: dict[int, dict[str, str]] = {}
    statement_md = constraints_md = input_md = output_md = note_md = ""
    score = None

    sm = SCORE_EN_RE.search(prelude_md) or SCORE_JA_RE.search(prelude_md)
    if sm:
        score = sm.group(1)

    for part in parts:
        kind, number = classify(part["title"])
        if kind not in ("sample_input", "sample_output"):
            # 样例已在 samples 字段中结构化，sections 只保留正文各节，避免重复
            sections.append({"title": part["title"], "markdown": part["markdown"]})
        if kind == "statement":
            statement_md = part["markdown"]
        elif kind == "constraints":
            constraints_md = part["markdown"]
        elif kind == "input":
            input_md = part["markdown"]
        elif kind == "output":
            output_md = part["markdown"]
        elif kind == "note":
            note_md = part["markdown"]
        elif kind == "sample_input":
            samples.setdefault(number, {"index": number, "input": "", "output": "", "explanation": ""})
            samples[number]["input"] = part["preText"]
        elif kind == "sample_output":
            samples.setdefault(number, {"index": number, "input": "", "output": "", "explanation": ""})
            samples[number]["output"] = part["preText"]
            if part["explanation"]:
                samples[number]["explanation"] = part["explanation"]
        else:
            # 分值常写在正文第一段，顺带兜底解析
            if score is None:
                sm = SCORE_EN_RE.search(part["markdown"]) or SCORE_JA_RE.search(part["markdown"])
                if sm:
                    score = sm.group(1)

    if score is None:
        sm = SCORE_EN_RE.search(statement_md) or SCORE_JA_RE.search(statement_md)
        if sm:
            score = sm.group(1)
    if score is not None:
        try:
            score = int(float(score))
        except ValueError:
            score = None

    ordered_samples = [samples[k] for k in sorted(samples)]
    interactive = bool(re.search(r"interactive problem|インタラクティブ|交互题",
                                  collapse(node_text(span)), re.I))

    index = (meta or {}).get("index") or letter or task_id.rsplit("_", 1)[-1].upper()
    display_title = f"{index} - {name}" if name else raw_title or index

    problem = {
        "index": index,
        "taskId": task_id,
        "title": display_title,
        "name": name,
        "url": url,
        "score": score,
        "timeLimit": time_limit,
        "timeLimitMs": time_ms,
        "memoryLimit": memory_limit,
        "memoryLimitMiB": memory_mib,
        "interactive": interactive,
        "lang": used_lang,
        "statementMarkdown": statement_md,
        "constraintsMarkdown": constraints_md,
        "inputMarkdown": input_md,
        "outputMarkdown": output_md,
        "noteMarkdown": note_md,
        "sections": sections,
        "samples": ordered_samples,
    }
    problem["markdown"] = problem_markdown(problem)
    if not problem["statementMarkdown"] and not ordered_samples:
        raise RuntimeError("题面为空，可能被反爬或页面改版")
    return problem


def problem_markdown(problem: dict[str, Any]) -> str:
    lines: list[str] = [f"## {problem['title']}", ""]
    lines.append(f"- 题目链接：{problem['url']}")
    if problem.get("score") is not None:
        lines.append(f"- 分值：{problem['score']}")
    if problem.get("timeLimit"):
        lines.append(f"- 时间限制：{problem['timeLimit']}")
    if problem.get("memoryLimit"):
        lines.append(f"- 内存限制：{problem['memoryLimit']}")
    if problem.get("interactive"):
        lines.append("- 类型：交互题")
    lines.append("")

    def section(title: str, body: str):
        if body:
            lines.extend([f"### {title}", "", body, ""])

    section("题目描述", problem.get("statementMarkdown", ""))
    section("约束", problem.get("constraintsMarkdown", ""))
    section("输入格式", problem.get("inputMarkdown", ""))
    section("输出格式", problem.get("outputMarkdown", ""))

    samples = problem.get("samples") or []
    if samples:
        lines.extend(["### 样例", ""])
        for sample in samples:
            lines.extend([
                f"#### 样例 {sample['index']} 输入", "",
                f"```input{sample['index']}",
                sample["input"],
                "```", "",
                f"#### 样例 {sample['index']} 输出", "",
                f"```output{sample['index']}",
                sample["output"],
                "```", "",
            ])
            if sample.get("explanation"):
                lines.extend([sample["explanation"], ""])

    section("说明", problem.get("noteMarkdown", ""))
    return tidy_markdown("\n".join(lines))


# ---------------------------------------------------------------------------
# 比赛级导出
# ---------------------------------------------------------------------------

def normalize_target(target: str) -> tuple[str, str | None]:
    """返回 (contest_id, single_task_id 或 None)。"""
    target = target.strip()
    m = re.match(r"^https?://atcoder\.jp/contests/([^/?#]+)(?:/tasks/([^/?#]+))?", target)
    if m:
        return m.group(1), m.group(2)
    m = re.match(r"^([A-Za-z0-9]+)_([A-Za-z0-9]+)$", target)
    if m and re.fullmatch(r"[a-z][0-9a-z]*|[0-9]+", m.group(2)):
        # 形如 abc478_a / typical90_a / abc001_1：按单题处理
        return m.group(1), target
    if re.fullmatch(r"[A-Za-z0-9]+", target):
        return target, None
    raise ValueError(f"无法识别的目标：{target}（请给比赛 URL 或 abc478 这种 ID）")


def fetch_contest(target: str, *, lang: str = "en", delay: float = DEFAULT_DELAY,
                  timeout: float = DEFAULT_TIMEOUT, cache_dir: str | None = None,
                  cache_ttl: float = 3600.0, refresh: bool = False,
                  tasks: list[str] | None = None, include_html: bool = False,
                  log: Any = None) -> dict[str, Any]:
    contest_id, single_task = normalize_target(target)
    fetcher = Fetcher(lang=lang, delay=delay, timeout=timeout, cache_dir=cache_dir,
                      cache_ttl=cache_ttl, refresh=refresh, log=log)

    tasks_url = f"{BASE}/contests/{contest_id}/tasks?lang={lang}"
    contest_url = f"{BASE}/contests/{contest_id}?lang={lang}"

    table: dict[str, dict[str, Any]] = {}
    contest_title = ""
    try:
        doc = parse_html(fetcher.get_html(tasks_url))
        table = parse_tasks_table(doc, contest_id)
        title_node = find_first(doc, "title")
        if title_node is not None:
            contest_title = split_title(node_text(title_node))
    except RuntimeError as exc:
        if not single_task:
            raise
        (log or (lambda m: print(m, file=sys.stderr)))(f"比赛页读取失败，仅抓单题：{exc}")

    if not contest_title:
        contest_title = contest_id

    if single_task:
        targets = [single_task]
    elif tasks:
        wanted = {t.strip() for t in tasks if t.strip()}
        targets = []
        for task_id, info in table.items():
            if task_id in wanted or (info.get("index") or "").upper() in {w.upper() for w in wanted}:
                targets.append(task_id)
        if not targets:
            raise ValueError(f"没有匹配的题目：{', '.join(sorted(wanted))}")
    else:
        targets = list(table.keys())

    if not targets:
        raise ValueError(f"未在 {contest_id} 的 tasks 页面解析到题目链接，请确认比赛 ID")

    order = sorted(table.keys(), key=lambda t: table[t].get("index", t))
    targets.sort(key=lambda t: order.index(t) if t in order else t)

    problems: list[dict[str, Any]] = []
    failed = 0

    def note(msg: str):
        (log or (lambda m: print(m, file=sys.stderr)))(msg)

    for i, task_id in enumerate(targets, 1):
        meta = table.get(task_id, {})
        label = meta.get("index") or task_id
        note(f"[{i}/{len(targets)}] {task_id} {label} {meta.get('name', '')}".rstrip())
        try:
            html = fetcher.get_html(f"{BASE}/contests/{contest_id}/tasks/{task_id}?lang={lang}")
            problem = parse_problem(html, task_id=task_id, contest_id=contest_id,
                                    lang=lang, meta=meta)
            if include_html:
                statement = find_first(parse_html(html), "div", id="task-statement")
                problem["statementHtml"] = serialize_html(statement, problem["url"]) if statement else ""
            problems.append(problem)
        except Exception as exc:  # noqa: BLE001 —— 单题失败不影响整场
            failed += 1
            problems.append({
                "index": meta.get("index", task_id.rsplit("_", 1)[-1].upper()),
                "taskId": task_id,
                "title": meta.get("name", task_id),
                "url": f"{BASE}/contests/{contest_id}/tasks/{task_id}",
                "error": str(exc),
            })

    data = {
        "platform": "AtCoder",
        "type": "contest-problems",
        "scriptVersion": SCRIPT_VERSION,
        "lang": lang,
        "contestId": contest_id,
        "contestTitle": contest_title,
        "contestUrl": f"{BASE}/contests/{contest_id}",
        "grabbedAt": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "problemCount": len(problems),
        "failedCount": failed,
        "problems": problems,
    }
    return data


def serialize_html(node: Node | None, base_url: str) -> str:
    if node is None:
        return ""

    def esc(text: str) -> str:
        return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

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


def contest_markdown(data: dict[str, Any]) -> str:
    lines = [
        f"# {data.get('contestTitle') or 'AtCoder ' + data['contestId']}",
        "",
        f"- 平台：AtCoder",
        f"- 比赛链接：{data['contestUrl']}",
        f"- 抓取时间：{data['grabbedAt']}",
        f"- 脚本版本：{data['scriptVersion']}",
        f"- 题面语言：{data['lang']}",
        "",
    ]
    for problem in data["problems"]:
        if problem.get("error"):
            lines.extend([f"## {problem['index']} {problem.get('title', '')}".strip(), "",
                          f"抓取失败：{problem['error']}", ""])
            continue
        lines.extend([problem["markdown"], ""])
    return tidy_markdown("\n".join(lines)) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def default_cache_dir() -> str:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return str(Path(base) / "atcoder-export")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="atcoder-contest-export",
        description="抓取 AtCoder 比赛题面，输出适合 AI / Agent 消费的结构化 JSON 或 Markdown。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python3 atcoder-contest-export.py abc478 --compact\n"
            "  python3 atcoder-contest-export.py https://atcoder.jp/contests/abc478 --format markdown --out abc478.md\n"
            "  python3 atcoder-contest-export.py abc478 --task A --task C --lang ja\n"
        ),
    )
    p.add_argument("target", help="比赛 URL、比赛 ID（abc478），或单题 ID / 单题 URL（abc478_a）")
    p.add_argument("--lang", choices=["en", "ja"], default="en", help="题面语言，默认 en（缺英文时自动回落日文）")
    p.add_argument("--format", choices=["json", "jsonl", "markdown"], default="json",
                   help="输出格式：json(默认)、jsonl(每题一行)、markdown")
    p.add_argument("--out", default="-", help="输出文件；- 表示 stdout（默认）")
    p.add_argument("--task", action="append", metavar="LETTER|TASKID",
                   help="只导出指定题，可重复：--task A --task abc478_c")
    p.add_argument("--delay", type=float, default=DEFAULT_DELAY, help=f"请求间隔秒数，默认 {DEFAULT_DELAY}")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="单请求超时秒数")
    p.add_argument("--cache-dir", default=default_cache_dir(), help="HTML 缓存目录，默认 ~/.cache/atcoder-export")
    p.add_argument("--cache-ttl", type=float, default=3600.0, help="缓存有效期秒数，默认 3600")
    p.add_argument("--refresh", action="store_true", help="忽略缓存强制重新抓取")
    p.add_argument("--compact", action="store_true", help="JSON 单行紧凑输出（省 token）")
    p.add_argument("--lean", action="store_true", help="精简 JSON：去掉可推导的 sections 与整篇 markdown，只留结构化字段")
    p.add_argument("--html", action="store_true", help="额外输出 statementHtml（整段题面原始 HTML）")
    p.add_argument("--quiet", action="store_true", help="不打印进度日志到 stderr")
    p.add_argument("--version", action="version", version=f"%(prog)s {SCRIPT_VERSION}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    log = (lambda m: None) if args.quiet else (lambda m: print(m, file=sys.stderr))

    try:
        data = fetch_contest(
            args.target,
            lang=args.lang,
            delay=args.delay,
            timeout=args.timeout,
            cache_dir=None if args.cache_dir in ("", "-") else args.cache_dir,
            cache_ttl=args.cache_ttl,
            refresh=args.refresh,
            tasks=args.task,
            include_html=args.html,
            log=log,
        )
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2 if isinstance(exc, ValueError) else 3

    if args.lean and args.format != "markdown":
        for problem in data["problems"]:
            problem.pop("sections", None)
            problem.pop("markdown", None)

    if args.format == "json":
        text = json.dumps(data, ensure_ascii=False, indent=None if args.compact else 2)
        text += "\n"
    elif args.format == "jsonl":
        text = "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in data["problems"])
    else:
        text = contest_markdown(data)

    if args.out == "-":
        sys.stdout.write(text)
    else:
        out = Path(args.out).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        log(f"written {out} ({len(text)} bytes)")

    if data["failedCount"] and data["failedCount"] == len(data["problems"]):
        return 3
    if data["failedCount"]:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
#（注：内容由AI生成）
