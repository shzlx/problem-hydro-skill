#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Codeforces Contest Problem Exporter

由 userscripts/codeforces/cf-contest-problem-export.user.js 改写而来：
浏览器脚本在页面里点按钮下载；本脚本用标准库直接请求页面，输出到 stdout / 文件，
方便 Agent 与批处理流水线调用。仅依赖 Python 标准库（无 bs4 / requests）。

用法示例
--------
    # 抓整场比赛，JSON 打到 stdout（默认）
    python3 cf-contest-export.py 2285

    # 只抓 A 题，输出 Hydro 友好的 Markdown
    python3 cf-contest-export.py 2285 --task A --format markdown

    # 单题 URL 也可以
    python3 cf-contest-export.py https://codeforces.com/contest/2285/problem/A

    # 压缩 JSON 存文件（给 LLM 省 token）
    python3 cf-contest-export.py 2285 --compact --lean --out work/cf2285.json

    # Gym / 逐题一行 JSON
    python3 cf-contest-export.py 100001 --gym --format jsonl

命令行约定
----------
* stdout 只输出正文数据（json / jsonl / markdown），进度日志一律走 stderr；
* 退出码：0 全成功；2 参数错误；3 全部失败；4 部分题目失败；
* 单题失败不中断整场，以 {"...", "error": "..."} 形式留在结果里；
* HTML 页面带缓存（默认 1 小时），--refresh 强制重抓。
"""

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
BASE = "https://codeforces.com"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 "
    "cf-contest-export/0.1.0"
)
DEFAULT_DELAY = 0.8
DEFAULT_TIMEOUT = 30.0

# ---------------------------------------------------------------------------
# 极简 DOM：Codeforces 题面结构固定，够用即可，避免引入 bs4 / lxml
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


def children_of(node: Node, tag: str | None = None, cls: str | None = None) -> list[Node]:
    """只取直接子元素，样例区要用：.input / .output 必须成对且不嵌套。"""
    out = []
    for child in node.children:
        if not isinstance(child, Node):
            continue
        if tag and child.tag != tag:
            continue
        if cls and not child.has_class(cls):
            continue
        out.append(child)
    return out


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
        elif child.tag == "img":
            # Codeforces 把较复杂的公式渲染成图片，alt 里是 LaTeX
            alt = child.get("alt") or ""
            if "tex-graphics" in child.classes and alt:
                parts.append(f" {alt} ")
        else:
            parts.append(node_text(child))
    return collapse("".join(parts))


def pre_text(node: Node) -> str:
    """样例 / 输入格式代码块：保留换行与缩进，<br> 转 \n。"""
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


# ---------------------------------------------------------------------------
# HTML -> Markdown（针对 Codeforces 的 tex-span / tex-font-style 做了适配）
# ---------------------------------------------------------------------------

MATH_CLASSES = ("tex-span", "tex-font-style-it", "tex-font-style-bf", "tex-font-style-tt")


def is_math(node: Node) -> bool:
    classes = node.classes
    return "tex-span" in classes


def math_text(node: Node | str) -> str:
    """数学节点转 LaTeX 片段：sup -> ^{}，sub -> _{}，其余拍平。"""
    if isinstance(node, str):
        return collapse(node)
    tag = node.tag
    if tag in ("script", "style"):
        return ""
    if tag == "br":
        return " "
    if tag == "sup":
        return "^{" + math_text_children(node) + "}"
    if tag == "sub":
        return "_{" + math_text_children(node) + "}"
    if tag == "img":
        alt = node.get("alt") or ""
        return alt
    return math_text_children(node)


def math_text_children(node: Node) -> str:
    return "".join(math_text(c) for c in node.children)


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
        return "\n\n```\n" + pre_text(node) + "\n```\n\n"
    if tag == "code":
        return "`" + collapse(node_text(node)) + "`"
    if is_math(node):
        body = math_text(node).strip()
        return f"${body}$" if body else ""
    if tag == "img":
        if "tex-graphics" in node.classes:
            alt = (node.get("alt") or "").strip()
            return f"${alt}$" if alt else ""
        src = abs_url(node.get("src"), base_url)
        if not src:
            return ""
        return f"![{node.get('alt')}]({src})"
    if tag in ("b", "strong"):
        return "**" + md_children(node, base_url, in_pre).strip() + "**"
    if tag in ("i", "em"):
        return "*" + md_children(node, base_url, in_pre).strip() + "*"
    if tag == "a":
        text = md_children(node, base_url, in_pre).strip() or collapse(node_text(node))
        href = abs_url(node.get("href"), base_url)
        return f"[{text}]({href})" if href else text
    if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
        level = min(int(tag[1]) + 2, 4)
        return "\n" + "#" * level + " " + md_children(node, base_url, in_pre).strip() + "\n\n"
    if node.has_class("section-title"):
        return "\n**" + md_children(node, base_url, in_pre).strip() + "**\n\n"
    if tag == "li":
        return "- " + md_children(node, base_url, in_pre).strip() + "\n"
    if tag in ("ul", "ol"):
        return "\n" + md_children(node, base_url, in_pre).rstrip() + "\n\n"
    if tag == "hr":
        return "\n---\n\n"
    if tag == "table":
        return "\n" + table_md(node, base_url) + "\n\n"
    if tag in ("p", "div", "section", "blockquote", "center"):
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


def normalize_latex(text: str) -> str:
    """Codeforces 用 $$$…$$$ 作行内公式、$$$$$$…$$$$$$ 作行间公式定界符，
    这里转成 Markdown 的 $…$ / $$…$$。代码块内保持原样。"""
    parts = re.split(r"(?ms)^(```.*?^```)", text)
    for i in range(0, len(parts), 2):
        seg = parts[i]
        seg = re.sub(r"\${6}(.+?)\${6}", _latex_span("$$"), seg, flags=re.S)
        seg = re.sub(r"\${3}(.+?)\${3}", _latex_span("$"), seg, flags=re.S)
        parts[i] = seg.replace("$$$", "")
    return "".join(parts)


def _latex_span(delim: str):
    def repl(m: re.Match) -> str:
        body = re.sub(r"[ \t]*\n[ \t]*", " ", m.group(1))
        return delim + body + delim

    return repl


def tidy_markdown(text: str) -> str:
    text = normalize_latex(text)
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


def md_section_body(node: Node, base_url: str) -> str:
    """取一个 section 的正文：去掉内部 .section-title（标题已由外层字段表达）。"""
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, Node) and child.has_class("section-title"):
            continue
        parts.append(md(child, base_url))
    return tidy_markdown("".join(parts))


# ---------------------------------------------------------------------------
# 网络
# ---------------------------------------------------------------------------

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
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept-Encoding": "gzip",
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
# 样例：拆行 + Hydro 行号分组
# ---------------------------------------------------------------------------

def build_ranges(lines: list[int]) -> str:
    if not lines:
        return ""
    ranges: list[str] = []
    left = right = lines[0]
    for value in lines[1:]:
        if value == right + 1:
            right = value
        else:
            ranges.append(str(left) if left == right else f"{left}-{right}")
            left = right = value
    ranges.append(str(left) if left == right else f"{left}-{right}")
    return ",".join(ranges)


def sample_line_group(node: Node) -> tuple[int | None, str]:
    classes = node.classes
    number = None
    for name in classes:
        m = re.fullmatch(r"test-example-line-(\d+)", name)
        if m:
            number = int(m.group(1))
            break
    parity = ""
    if "test-example-line-odd" in classes:
        parity = "odd"
    if "test-example-line-even" in classes:
        parity = "even"
    return number, parity


def empty_pre_block() -> dict[str, Any]:
    return {"text": "", "lines": [], "oddLineRanges": "", "evenLineRanges": "", "lineGroups": []}


def extract_pre_block(pre: Node) -> dict[str, Any]:
    line_nodes = find_all(pre, "div", cls="test-example-line")
    line_nodes = [n for n in line_nodes if any(
        re.fullmatch(r"test-example-line-\d+", c) for c in n.classes)]
    if not line_nodes:
        text = pre_text(pre).replace("\r\n", "\n").rstrip()
        lines = text.split("\n") if text else []
        return {
            "text": text,
            "lines": lines,
            "oddLineRanges": "",
            "evenLineRanges": "",
            "lineGroups": [],
        }

    lines: list[str] = []
    line_groups: list[dict[str, Any]] = []
    for i, line_node in enumerate(line_nodes, 1):
        group, parity = sample_line_group(line_node)
        lines.append(collapse_preserve(line_node))
        line_groups.append({"line": i, "group": group, "parity": parity})

    odd = [g["line"] for g in line_groups if g["parity"] == "odd"]
    even = [g["line"] for g in line_groups if g["parity"] == "even" and g["group"] != 0]
    return {
        "text": "\n".join(lines),
        "lines": lines,
        "oddLineRanges": build_ranges(odd),
        "evenLineRanges": build_ranges(even),
        "lineGroups": line_groups,
    }


def collapse_preserve(node: Node) -> str:
    """单行样例文本：只把 nbsp 换空格，行尾去空白，不压缩中间空格。"""
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
        elif child.tag == "br":
            parts.append("\n")
        elif child.tag in ("script", "style"):
            continue
        else:
            parts.append(collapse_preserve(child))
    return "".join(parts).replace("\u00a0", " ").rstrip()


def extract_samples(statement: Node) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    sample_root = find_first(statement, "div", cls="sample-tests")
    if sample_root is None:
        return samples

    inputs = [p for box in find_all(sample_root, "div", cls="input")
              for p in find_all(box, "pre")[:1]]
    outputs = [p for box in find_all(sample_root, "div", cls="output")
               for p in find_all(box, "pre")[:1]]

    if not inputs and not outputs:
        # 兜底：.sample-test 里两个 pre 依次是输入、输出
        for box in find_all(sample_root, "div", cls="sample-test"):
            pres = find_all(box, "pre")
            if len(pres) >= 2:
                inputs.append(pres[0])
                outputs.append(pres[1])

    for i in range(max(len(inputs), len(outputs))):
        inp = extract_pre_block(inputs[i]) if i < len(inputs) else empty_pre_block()
        out = extract_pre_block(outputs[i]) if i < len(outputs) else empty_pre_block()
        samples.append({
            "index": i + 1,
            "input": inp["text"],
            "output": out["text"],
            "inputLines": inp["lines"],
            "outputLines": out["lines"],
            "inputOddLineRanges": inp["oddLineRanges"],
            "inputEvenLineRanges": inp["evenLineRanges"],
            "outputOddLineRanges": out["oddLineRanges"],
            "outputEvenLineRanges": out["evenLineRanges"],
            "hydroInputFence": f"input{i + 1}" + (f"|{inp['oddLineRanges']}" if inp["oddLineRanges"] else ""),
            "hydroOutputFence": f"output{i + 1}" + (f"|{out['oddLineRanges']}" if out["oddLineRanges"] else ""),
        })
    return samples


# ---------------------------------------------------------------------------
# 题面解析
# ---------------------------------------------------------------------------

INDEX_RE = re.compile(r"^([A-Z][0-9A-Z]*)\.\s*")
TIME_RE = re.compile(r"([0-9.]+)\s*(?:second|seconds|sec)\b", re.I)
MEM_RE = re.compile(r"([0-9.]+)\s*(megabytes?|MB|MiB|gigabytes?|GB)\b", re.I)


def clean_limit(text: str, prefix: str) -> str:
    return collapse(re.sub(rf"^{re.escape(prefix)}", "", collapse(text), flags=re.I))


def parse_ms(limit: str) -> int | None:
    m = TIME_RE.search(limit or "")
    if not m:
        return None
    try:
        return int(round(float(m.group(1)) * 1000))
    except ValueError:
        return None


def parse_mib(limit: str) -> int | None:
    m = MEM_RE.search(limit or "")
    if not m:
        return None
    try:
        value = float(m.group(1))
    except ValueError:
        return None
    unit = m.group(2).lower()
    return int(value * (1024 if unit.startswith("gig") or unit == "gb" else 1))


def extract_sections(statement: Node, base_url: str) -> dict[str, str]:
    """对应 userscript 的 extractProblemSections：statement 内除 header /
    input-specification / output-specification / sample-tests / note 外的内容。"""
    parts: list[str] = []
    for child in statement.children:
        if not isinstance(child, Node):
            continue
        if (child.has_class("header") or child.has_class("input-specification")
                or child.has_class("output-specification")
                or child.has_class("sample-tests") or child.has_class("note")):
            continue
        parts.append(md(child, base_url))

    input_node = find_first(statement, "div", cls="input-specification")
    output_node = find_first(statement, "div", cls="output-specification")
    note_node = find_first(statement, "div", cls="note")

    return {
        "statementMarkdown": tidy_markdown("".join(parts)),
        "inputMarkdown": md_section_body(input_node, base_url) if input_node else "",
        "outputMarkdown": md_section_body(output_node, base_url) if output_node else "",
        "noteMarkdown": md_section_body(note_node, base_url) if note_node else "",
    }


def extract_problem(html: str, source_url: str, fallback_index: str = "",
                    hydro_groups: bool = False) -> dict[str, Any]:
    doc = parse_html(html)
    statement = find_first(doc, "div", cls="problem-statement")
    if statement is None:
        title_node = find_first(doc, "title")
        page_title = collapse(node_text(title_node)) if title_node is not None else ""
        if page_title.lower().startswith("attachments") or "attachments" in page_title.lower():
            raise RuntimeError("该比赛只提供 PDF 附件题面（attachments），页面里没有 HTML 题面")
        raise RuntimeError("未找到 .problem-statement，可能题目不存在、被反爬拦截或页面改版")

    header = find_first(statement, "div", cls="header")
    title = ""
    time_limit = memory_limit = input_file = output_file = ""
    if header is not None:
        title_node = find_first(header, "div", cls="title")
        title = collapse(node_text(title_node)) if title_node else ""
        time_node = find_first(header, "div", cls="time-limit")
        if time_node:
            time_limit = clean_limit(node_text(time_node), "time limit per test")
        mem_node = find_first(header, "div", cls="memory-limit")
        if mem_node:
            memory_limit = clean_limit(node_text(mem_node), "memory limit per test")
        in_node = find_first(header, "div", cls="input-file")
        if in_node:
            input_file = clean_limit(node_text(in_node), "input")
        out_node = find_first(header, "div", cls="output-file")
        if out_node:
            output_file = clean_limit(node_text(out_node), "output")

    if not title:
        title_node = find_first(doc, "div", cls="title")
        title = collapse(node_text(title_node)) if title_node else ""
    m = INDEX_RE.match(title)
    index = m.group(1) if m else (fallback_index or "")
    name = title[m.end():].strip() if m else title.strip()

    sections = extract_sections(statement, source_url)
    samples = extract_samples(statement)
    interactive = bool(re.search(r"interactive problem|This is an interactive",
                                 collapse(node_text(statement)), re.I))

    if not sections["statementMarkdown"] and not samples:
        raise RuntimeError("题面为空，可能被反爬或页面改版")

    problem = {
        "index": index,
        "title": title or index,
        "name": name,
        "sourceUrl": source_url,
        "timeLimit": time_limit,
        "timeLimitMs": parse_ms(time_limit),
        "memoryLimit": memory_limit,
        "memoryLimitMiB": parse_mib(memory_limit),
        "inputFile": input_file,
        "outputFile": output_file,
        "interactive": interactive,
        "statementHtml": serialize_html(statement, source_url),
        "sections": sections,
        "samples": samples,
        "hydroGroups": hydro_groups,
    }
    problem["markdown"] = problem_markdown(problem)
    return problem


def problem_markdown(problem: dict[str, Any]) -> str:
    lines: list[str] = [f"## {problem['title']}", ""]
    lines.append(f"- 原题链接：{problem['sourceUrl']}")
    if problem.get("timeLimit"):
        lines.append(f"- 时间限制：{problem['timeLimit']}")
    if problem.get("memoryLimit"):
        lines.append(f"- 空间限制：{problem['memoryLimit']}")
    if problem.get("inputFile"):
        lines.append(f"- 输入：{problem['inputFile']}")
    if problem.get("outputFile"):
        lines.append(f"- 输出：{problem['outputFile']}")
    if problem.get("interactive"):
        lines.append("- 类型：交互题")
    lines.append("")

    def section(title: str, body: str):
        if body:
            lines.extend([f"### {title}", "", body, ""])

    sections = problem.get("sections") or {}
    section("题目描述", sections.get("statementMarkdown", ""))
    section("输入格式", sections.get("inputMarkdown", ""))
    section("输出格式", sections.get("outputMarkdown", ""))

    samples = problem.get("samples") or []
    if samples:
        use_groups = bool(problem.get("hydroGroups"))
        lines.extend(["### 样例", ""])
        for sample in samples:
            in_fence = sample["hydroInputFence"] if use_groups else f"input{sample['index']}"
            out_fence = sample["hydroOutputFence"] if use_groups else f"output{sample['index']}"
            lines.extend([
                f"#### 样例 {sample['index']} 输入", "",
                f"```{in_fence}",
                sample["input"],
                "```", "",
                f"#### 样例 {sample['index']} 输出", "",
                f"```{out_fence}",
                sample["output"],
                "```", "",
            ])

    section("说明", sections.get("noteMarkdown", ""))
    return tidy_markdown("\n".join(lines))


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
# 比赛级导出
# ---------------------------------------------------------------------------

def normalize_target(target: str, *, gym: bool = False) -> tuple[str, str, str | None]:
    """返回 (kind, contest_id, single_problem_index 或 None)。"""
    target = target.strip()

    m = re.match(
        r"^(?:https?://)?(?:[A-Za-z0-9.-]*codeforces\.[A-Za-z]+)"
        r"/(contest|gym)/(\d+)(?:/problem/([^/?#]+))?",
        target,
    )
    if m:
        return m.group(1), m.group(2), m.group(3)

    m = re.match(r"^(\d+)/problem/([^/?#]+)$", target)
    if m:
        return ("gym" if gym else "contest"), m.group(1), m.group(2)

    m = re.match(r"^(\d+)[/:]([A-Za-z][0-9A-Za-z]*)$", target)
    if m:
        return ("gym" if gym else "contest"), m.group(1), m.group(2)

    m = re.match(r"^(\d+)([A-Za-z][0-9A-Za-z]*)?$", target)
    if m:
        return ("gym" if gym else "contest"), m.group(1), m.group(2)

    raise ValueError(
        f"无法识别的目标：{target}（可用 2285 / 2285A / 2285/A / "
        f"https://codeforces.com/contest/2285[/problem/A]）"
    )


def clean_title(raw: str) -> str:
    text = collapse(raw)
    text = re.sub(r"\s*-\s*Codeforces\s*$", "", text, flags=re.I)
    text = re.sub(r"^Dashboard\s*-\s*", "", text, flags=re.I)
    text = re.sub(r"^Status\s*-\s*", "", text, flags=re.I)
    return text


def problem_links(doc: Node, kind: str, contest_id: str) -> list[dict[str, str]]:
    pattern = re.compile(rf"^/{kind}/{re.escape(contest_id)}/problem/([^/?#]+)$")
    found: dict[str, dict[str, str]] = {}
    for anchor in find_all(doc, "a"):
        href = anchor.get("href")
        m = pattern.match(href)
        if not m:
            continue
        index = m.group(1)
        found.setdefault(index, {
            "index": index,
            "url": BASE + f"/{kind}/{contest_id}/problem/{index}",
            "text": collapse(node_text(anchor)),
        })
    return sort_by_index(list(found.values()))


def sort_by_index(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(item: dict[str, Any]):
        index = item.get("index") or ""
        m = re.match(r"([A-Za-z]*)(\d*)", index)
        letter, number = (m.group(1), m.group(2)) if m else (index, "")
        return (letter.lower(), int(number) if number else 0, index)

    return sorted(items, key=key)


def fetch_contest(target: str, *, gym: bool = False, lang: str = "en",
                  delay: float = DEFAULT_DELAY, timeout: float = DEFAULT_TIMEOUT,
                  cache_dir: str | None = None, cache_ttl: float = 3600.0,
                  refresh: bool = False, tasks: list[str] | None = None,
                  include_html: bool = False, hydro_groups: bool = False,
                  log: Any = None) -> dict[str, Any]:
    kind, contest_id, single = normalize_target(target, gym=gym)
    note = log or (lambda msg: print(msg, file=sys.stderr))
    fetcher = Fetcher(lang=lang, delay=delay, timeout=timeout, cache_dir=cache_dir,
                      cache_ttl=cache_ttl, refresh=refresh, log=note)

    locale = f"?locale={lang}" if lang else ""
    contest_url = f"{BASE}/{kind}/{contest_id}"
    listing_url = f"{contest_url}{locale}"

    links: list[dict[str, str]] = []
    contest_title = ""
    try:
        doc = parse_html(fetcher.get_html(listing_url))
        title_node = find_first(doc, "title")
        if title_node is not None:
            contest_title = clean_title(node_text(title_node))
        links = problem_links(doc, kind, contest_id)
        if not links and kind == "contest":
            # 对应 userscript 的兜底：比赛主页没链接时改读 /problems
            note(f"{listing_url} 未发现题目链接，改读 {contest_url}/problems")
            doc = parse_html(fetcher.get_html(f"{contest_url}/problems{locale}"))
            links = problem_links(doc, kind, contest_id)
            if not contest_title:
                title_node = find_first(doc, "title")
                if title_node is not None:
                    contest_title = clean_title(node_text(title_node))
    except RuntimeError as exc:
        if not single:
            raise
        note(f"比赛页读取失败，仅抓单题：{exc}")

    if not contest_title:
        contest_title = f"{'Gym' if kind == 'gym' else 'Contest'} {contest_id}"

    if single:
        wanted = [single]
    elif tasks:
        named = {t.strip() for t in tasks if t.strip()}
        wanted = [l["index"] for l in links
                  if l["index"] in named or l["index"].upper() in {n.upper() for n in named}
                  or f"https://codeforces.com/{kind}/{contest_id}/problem/{l['index']}" in named]
        if not wanted:
            raise ValueError(f"没有匹配的题目：{', '.join(sorted(named))}")
    else:
        wanted = [l["index"] for l in links]

    if not wanted:
        raise ValueError(f"未在 {listing_url} 解析到题目链接，请确认比赛 ID 或改用单题 URL")

    problems: list[dict[str, Any]] = []
    failed = 0
    for i, index in enumerate(wanted, 1):
        url = f"{BASE}/{kind}/{contest_id}/problem/{index}{locale}"
        note(f"[{i}/{len(wanted)}] {index} {url}")
        try:
            html = fetcher.get_html(url)
            problem = extract_problem(html, url, index, hydro_groups=hydro_groups)
            problem["contestKind"] = kind
            problem["contestId"] = contest_id
            problem["suggestedPid"] = f"CF{contest_id}{problem['index']}".upper()
            if not include_html:
                problem.pop("statementHtml", None)
            problems.append(problem)
        except Exception as exc:  # noqa: BLE001 —— 单题失败不影响整场
            failed += 1
            problems.append({
                "index": index,
                "title": index,
                "sourceUrl": url,
                "error": str(exc),
            })

    return {
        "platform": "Codeforces",
        "type": "contest-problems",
        "scriptVersion": SCRIPT_VERSION,
        "lang": lang,
        "contestKind": kind,
        "contestId": contest_id,
        "contestTitle": contest_title,
        "contestUrl": contest_url,
        "grabbedAt": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "problemCount": len(problems),
        "failedCount": failed,
        "problems": problems,
    }


def contest_markdown(data: dict[str, Any]) -> str:
    kind = data.get("contestKind", "contest")
    header_title = data.get("contestTitle") or f"Codeforces {kind} {data['contestId']}"
    lines = [
        f"# {header_title}",
        "",
        "- 平台：Codeforces",
        f"- 比赛链接：{data['contestUrl']}",
        f"- 抓取时间：{data['grabbedAt']}",
        f"- 脚本版本：{data['scriptVersion']}",
        f"- 题面语言：{data['lang']}",
        "",
    ]
    for problem in data["problems"]:
        if problem.get("error"):
            lines.extend([f"## {problem['index']}", "", f"抓取失败：{problem['error']}", ""])
            continue
        lines.extend([problem["markdown"], ""])
    return tidy_markdown("\n".join(lines)) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def default_cache_dir() -> str:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return str(Path(base) / "codeforces-export")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cf-contest-export",
        description="抓取 Codeforces 比赛题面，输出适合 Agent / Hydro 打包使用的 JSON 或 Markdown。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python3 cf-contest-export.py 2285 --format markdown --task A\n"
            "  python3 cf-contest-export.py https://codeforces.com/contest/2285/problem/A\n"
            "  python3 cf-contest-export.py 2285 --compact --out work/cf2285.json\n"
            "  python3 cf-contest-export.py 100001 --gym --format jsonl\n"
        ),
    )
    p.add_argument("target",
                   help="比赛 ID（2285）、单题（2285A / 2285/A）或 URL（/contest/… 、/gym/…）")
    p.add_argument("--gym", action="store_true", help="把纯数字 ID 当作 gym 比赛")
    p.add_argument("--lang", default="en", choices=["en", "ru"], help="题面语言，默认 en")
    p.add_argument("--format", choices=["json", "jsonl", "markdown"], default="json",
                   help="输出格式：json(默认)、jsonl(每题一行)、markdown")
    p.add_argument("--out", default="-", help="输出文件；- 表示 stdout（默认）")
    p.add_argument("--task", action="append", metavar="INDEX",
                   help="只导出指定题，可重复：--task A --task C")
    p.add_argument("--delay", type=float, default=DEFAULT_DELAY, help=f"请求间隔秒数，默认 {DEFAULT_DELAY}")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="单请求超时秒数")
    p.add_argument("--cache-dir", default=default_cache_dir(),
                   help="HTML 缓存目录，默认 ~/.cache/codeforces-export")
    p.add_argument("--cache-ttl", type=float, default=3600.0, help="缓存有效期秒数，默认 3600")
    p.add_argument("--refresh", action="store_true", help="忽略缓存强制重新抓取")
    p.add_argument("--compact", action="store_true", help="JSON 单行紧凑输出（省 token）")
    p.add_argument("--lean", action="store_true", help="精简 JSON：去掉 sections / markdown / lineGroups")
    p.add_argument("--html", action="store_true", help="额外输出 statementHtml（整段题面原始 HTML）")
    p.add_argument("--hydro-groups", action="store_true",
                   help="样例代码块带上 Codeforces 的分组行号（```input1|2,4），与浏览器脚本行为一致；"
                        "默认输出不带行号的 ```input1")
    p.add_argument("--quiet", action="store_true", help="不打印进度日志到 stderr")
    p.add_argument("--version", action="version", version=f"%(prog)s {SCRIPT_VERSION}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    log = (lambda m: None) if args.quiet else (lambda m: print(m, file=sys.stderr))

    try:
        data = fetch_contest(
            args.target,
            gym=args.gym,
            lang=args.lang,
            delay=args.delay,
            timeout=args.timeout,
            cache_dir=None if args.cache_dir in ("", "-") else args.cache_dir,
            cache_ttl=args.cache_ttl,
            refresh=args.refresh,
            tasks=args.task,
            include_html=args.html,
            hydro_groups=args.hydro_groups,
            log=log,
        )
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2 if isinstance(exc, ValueError) else 3

    if args.lean and args.format != "markdown":
        for problem in data["problems"]:
            problem.pop("sections", None)
            problem.pop("markdown", None)
            problem.pop("statementHtml", None)
            problem.pop("hydroGroups", None)
            for sample in problem.get("samples") or []:
                for key in ("lineGroups", "inputLines", "outputLines",
                            "inputEvenLineRanges", "outputEvenLineRanges"):
                    sample.pop(key, None)

    if args.format == "json":
        text = json.dumps(data, ensure_ascii=False, indent=None if args.compact else 2) + "\n"
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
