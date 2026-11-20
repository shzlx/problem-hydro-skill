# Codeforces 抓题工具

本目录有两个入口，数据结构和抓取逻辑一致（都以 `.problem-statement` 为解析目标）：

| 文件 | 形态 | 用途 |
|---|---|---|
| `cf-contest-problem-export.user.js` | 浏览器篡改猴脚本 | 在比赛页/题目页点按钮，下载 JSON 或 Markdown |
| `cf-contest-export.py` | 命令行脚本 | 无浏览器环境下抓取，供 Agent / 批处理流水线调用 |

命令行版由 userscript 改写而来，仅用 Python 标准库（urllib + html.parser），无需 bs4 / requests。

## 用法

```bash
S=userscripts/codeforces/cf-contest-export.py

# 整场比赛，JSON 到 stdout（默认）
python3 $S 2285

# 只抓 A 题，输出 Hydro 友好 Markdown
python3 $S 2285 --task A --format markdown

# 单题 URL / 简写都可以
python3 $S https://codeforces.com/contest/2285/problem/A
python3 $S 2285A

# 压缩 JSON 存文件（给 LLM 省 token）
python3 $S 2285 --compact --lean --out work/cf2285.json

# Gym 比赛
python3 $S 100002 --gym --format markdown

# 逐题一行 JSON（流式处理）
python3 $S 2285 --format jsonl
```

## 目标写法

| 写法 | 解释 |
|---|---|
| `2285` | contest 2285 整场 |
| `2285A` / `2285/A` | contest 2285 的 A 题 |
| `https://codeforces.com/contest/2285[/problem/A]` | URL，带不带 `problem/A` 都行 |
| `100002` + `--gym` | gym 100002 整场 |
| `https://codeforces.com/gym/100002/problem/A` | gym 单题（自动识别） |

## 参数

| 参数 | 说明 |
|---|---|
| `--format json\|jsonl\|markdown` | 输出格式，默认 `json` |
| `--out FILE` | 输出文件，`-` 表示 stdout（默认） |
| `--task INDEX` | 只导出指定题，可重复（`--task A --task c`，大小写不敏感） |
| `--lean` | 精简 JSON：去掉 `sections` / `markdown` / `lineGroups` |
| `--compact` | JSON 单行输出 |
| `--html` | 附带 `statementHtml`（题面原始 HTML） |
| `--lang en\|ru` | 题面语言，默认 `en`（走 `?locale=`） |
| `--gym` | 纯数字 ID 按 gym 处理 |
| `--delay` / `--timeout` | 请求间隔（默认 0.8s）/ 单请求超时（默认 30s） |
| `--cache-dir` / `--cache-ttl` / `--refresh` | HTML 缓存目录（默认 `~/.cache/codeforces-export`）、有效期（默认 3600s）、强制重抓 |
| `--hydro-groups` | 样例代码块带 CF 分组行号（`input1\|2,4`），与 userscript 一致；默认输出 `input1` |
| `--quiet` | 不打印进度日志 |

## 命令行约定

- stdout 只有正文数据（json / jsonl / markdown），进度日志全部走 stderr；
- 退出码：`0` 全成功、`2` 参数/目标错误、`3` 全部失败、`4` 部分题目失败；
- 单题失败不中断整场，失败项以 `{"index": ..., "error": "..."}` 留在结果里；
- 默认给每道题补 `suggestedPid`（如 `CF2285A`）、`timeLimitMs`、`memoryLimitMiB`，方便直接对接 Hydro 打包流程。

## 输出字段

| 字段 | 说明 |
|---|---|
| `contestTitle` / `contestKind` / `contestId` / `contestUrl` | 比赛元信息 |
| `problems[].title` / `index` / `name` | 题号与标题（`A. Composite Permutation` → `A` + `Composite Permutation`） |
| `problems[].timeLimit` / `memoryLimit` | 原始文本，如 `1 second` / `256 megabytes` |
| `problems[].timeLimitMs` / `memoryLimitMiB` | 数值化限制 |
| `problems[].sections` | `statementMarkdown` / `inputMarkdown` / `outputMarkdown` / `noteMarkdown` |
| `problems[].samples[]` | `input` / `output` 文本、按 `test-example-line-N` 解析的行分组、Hydro fence 名 |
| `problems[].markdown` | 单题完整 Markdown（含 `input1` 样例块） |

## 与 userscript 的差异

| 项目 | userscript | 命令行版 |
|---|---|---|
| 运行环境 | 浏览器页面，带登录态 Cookie | 无状态 HTTP 请求 |
| 题目发现 | 当前页链接，失败再读 `/problems` | 先读比赛页，无链接时读 `/problems` |
| 公式 | 原样保留 `$$$…$$$` | 转 Markdown：`$…$` 行内、`$$…$$` 行间（`tex-span` / `tex-graphics` 一并处理） |
| 样例 fence | 总是带分组行号 | 默认不带，`--hydro-groups` 还原 |
| 输出 | 下载文件 | stdout / `--out`，可 `jsonl`、可 `--lean` |

## 已知限制

- **只有 PDF 题面的 gym**（页标题为 `Attachments - …`，例如 gym 100001）抓不到题面，会明确报错；
- Codeforces 有反爬，连续大量请求可能返回 `403`/`429`；脚本内建 3 次重试与默认 0.8s 间隔，仍失败请调大 `--delay`；
- 题面语言只做了 `en` / `ru`（`?locale=`）。
