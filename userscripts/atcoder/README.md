# AtCoder Contest Problem Exporter —— 面向 AI / Agent 调用的题目抓取器

参考 Codeforces Contest Problem Exporter 的数据结构重写，适配 AtCoder 页面。
仅用标准库，无需浏览器、无需第三方依赖。

用法示例
--------
    # 抓整场比赛，JSON 打到 stdout（默认）
    python3 atcoder-contest-export.py https://atcoder.jp/contests/abc478

    # 存文件 + 压缩输出（给 LLM 省 token）
    python3 atcoder-contest-export.py abc478 --compact --out abc478.json

    # 导出 Hydro / Markdown 友好的整场题面
    python3 atcoder-contest-export.py abc478 --format markdown --out abc478.md

    # 只要某几题（按字母或 task id）
    python3 atcoder-contest-export.py abc478 --task A --task abc478_c

    # 日文题面
    python3 atcoder-contest-export.py abc478 --lang ja

    # 逐题一行 JSON（流式喂给模型 / 分批处理）
    python3 atcoder-contest-export.py abc478 --format jsonl

命令行约定（方便 Agent 使用）
----------------------------
* stdout 只输出正文数据（json / jsonl / markdown），日志一律写 stderr；
* 退出码：0 全成功；2 参数错误；3 全部失败；4 部分题目失败；
* 失败题目不会中断整场导出，会以 {"...","error":"..."} 形式留在结果里；
* 支持缓存，重复调用不再打 AtCoder（默认 1 小时内有效，--refresh 强制重抓）。

也可以在 Python 里直接调用
--------------------------
文件名带连字符，需先复制 / 软链成 `atcoder_contest_export.py` 再导入：

    from atcoder_contest_export import fetch_contest
    data = fetch_contest("abc478", lang="en")


# AtCoder Editorial Exporter —— 面向 AI / Agent 调用的题解抓取器

`atcoder-editorial-export.py`，数据结构对齐 `codeforces/cf-editorial-export.py`，
适配 AtCoder 的「单篇题解页」与「比赛题解索引页」。仅用标准库
（urllib + html.parser），无需浏览器、无需第三方依赖。

用法示例
--------
    # 单篇题解
    python3 atcoder-editorial-export.py https://atcoder.jp/contests/abc248/editorial/3797

    # 整场比赛的题解（索引页里每道题选一篇，默认英文，缺英文回落日文）
    python3 atcoder-editorial-export.py abc248 --compact --out work/abc248-editorials.json

    # 按题筛选 / 导出 Markdown
    python3 atcoder-editorial-export.py abc248 --task B --task Ex --format markdown --out work/abc248.md

    # 已知 task id 或 task 页面，自动去索引里找对应题解
    python3 atcoder-editorial-export.py abc248_b

    # 同一题的所有题解版本（官方 / 用户）
    python3 atcoder-editorial-export.py abc248 --task B --variants all

    # 接到题目包：英文原文落 work/，中文成稿再写进 solution/sol.md
    python3 atcoder-editorial-export.py abc248 --task B --format markdown --out work/abc248_b_sol.md

参数
----
| 参数 | 说明 |
|---|---|
| `target` | 题解 URL、题解索引 URL、比赛 ID（`abc248`）、task id（`abc248_b`）或 task URL |
| `--lang {en,ja}` | 题解语言，默认 `en`；索引里缺英文时自动回落日文 |
| `--task A` | 只导出指定题，可重复（`--task B --task Ex --task abc248_c`） |
| `--editorial ID` | 只导出指定 editorial id（如 `3797`） |
| `--variants {first,all}` | 每题取第一篇（默认）或全部可用题解 |
| `--format` | `json`（默认）/ `jsonl` / `markdown` |
| `--out` | 输出文件，`-` 表示 stdout（默认） |
| `--compact` | JSON 单行紧凑输出 |
| `--lean` | 去掉 `text` / `introMarkdown` / `sections` / `codeBlocks` / `html` |
| `--html` | 额外输出题解正文 HTML |
| `--cache-dir` | HTML 缓存目录，默认 `~/.cache/atcoder-editorial-export` |
| `--cache-ttl` / `--refresh` | 缓存有效期（默认 3600s）/ 忽略缓存强制重抓 |
| `--delay` / `--timeout` | 请求间隔（默认 0.6s）/ 单次超时（默认 25s） |
| `--quiet` | 不打印 stderr 进度日志 |

输出结构
--------
单篇（`type: "editorial"`）：

    contestId, contestTitle, contestUrl, editorialId, url, lang,
    title, label(官方/用户题解), author, postedAt, updatedAt,
    problem{index, taskId, title, name, url},
    introMarkdown, sections[], codeBlocks[]{language, code},
    markdown, text, scriptVersion

整场（`type: "editorial-collection"`）：外层带 `contestTitle`、`editorialIndexUrl`、
`grabbedAt`、`editorialCount`、`failedCount`，`editorials[]` 内是上面的单篇结构。

* 标程代码取 `codeBlocks[].code`（`language` 为 `cpp` 时直接可用）；
* `markdown` 顶部带题解链接 / 作者 / 发布时间，写成 `solution/sol.md` 时只留正文，
  元信息压成一行来源链接。

命令行约定（方便 Agent 使用）
----------------------------
* stdout 只输出正文数据（json / jsonl / markdown），日志一律写 stderr；
* 退出码：0 全成功；2 参数错误；3 全部失败；4 部分失败；
* 失败条目不会中断整场，会以 {"...","error":"..."} 形式留在结果里；
* 支持 HTML 缓存，重复调用不再打 AtCoder（默认 1 小时，--refresh 强制重抓）。

Python 调用
-----------
文件名带连字符，需先复制 / 软链成 `atcoder_editorial_export.py` 再导入：

    from atcoder_editorial_export import fetch_editorial
    data = fetch_editorial("https://atcoder.jp/contests/abc248/editorial/3797",
                           lang="en", tasks=["B"], variants="all")

已知限制
--------
- 索引页里被隐藏（`hidden`，未公开 / 未翻译）的题解默认跳过，只有该题没有可见题解时才回退使用；
- 题解正文里的数学公式原样保留为 `\(...\)` / `\[...\]`，转 Hydro 题面时按原样贴，不要改写成中文描述；
- 单场题解逐个请求，`--delay` 默认 0.6s，整场几十篇时请耐心或调大 `--timeout`。
