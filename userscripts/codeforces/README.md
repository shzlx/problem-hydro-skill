# Codeforces 抓题工具

本目录有两组工具：抓题（题面）与题解（editorial），每组都是「浏览器篡改猴 + 命令行 Python」两份实现。

| 文件 | 形态 | 用途 |
|---|---|---|
| `cf-contest-problem-export.user.js` | 浏览器篡改猴脚本 | 在比赛页/题目页点按钮，下载 JSON 或 Markdown |
| `cf-contest-export.py` | 命令行脚本 | 无浏览器环境下抓题，供 Agent / 批处理流水线调用 |
| `cf-editorial-export.user.js` | 浏览器篡改猴脚本 | 在 `/blog/entry/*` 页面导出题解 |
| `cf-editorial-export.py` | 命令行脚本 | 抓 Codeforces 题解（blog entry），输出 JSON / Markdown |

同组内命令行版由 userscript 改写而来，仅用 Python 标准库（urllib + html.parser），无需 bs4 / requests。

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


## 题解导出（`cf-editorial-export.py`）

把 `cf-editorial-export.user.js` 的浏览器能力搬到命令行：给一个 blog entry
（题解通常是 `/blog/entry/<id>`），输出结构化 JSON 或 Markdown，供 AI / Agent 直接读取。
依赖 Python 3.9+，仅标准库。

特点：

- 优先走 Codeforces 的 `blogEntry.view` 接口，稳定、免登录、不受 Cloudflare 影响；
- 接口失败回落到网页抓取，并支持本地 HTML / API JSON 离线解析（`--input-file`）；
- 保留 spoiler（折叠块）的标题与内容 —— CF 题解大量使用折叠块；
- 按题目标题自动分段（A/B/C/…），给出 `problemUrl`、`markdown`、纯文本；
- stdout 只输出数据，进度写 stderr；退出码可区分「参数错 / 抓取错」。

```bash
E=userscripts/codeforces/cf-editorial-export.py

python3 $E 135181
python3 $E https://codeforces.com/blog/entry/135181 --compact
python3 $E 135181 --format markdown --out work/cf135181_sol.md
python3 $E 135181 --lean --compact
python3 $E --input-file page.html --entry 135181
```

### 参数

| 参数 | 说明 |
|---|---|
| `target` | blog entry URL 或数字 entry id |
| `--entry ID` | 直接指定 entry id（与 `target` 二选一） |
| `--format json\|jsonl\|markdown` | 输出格式，默认 `json` |
| `--out FILE` | 输出文件，`-` 表示 stdout（默认） |
| `--source auto\|api\|web` | 抓取来源，默认 `auto`（先 api，失败再 web） |
| `--input-file FILE` | 离线解析本地 HTML 或 API JSON |
| `--cookie STR` | 网页抓取时附加的 Cookie |
| `--timeout` | 单请求超时，默认 20s |
| `--cache-dir` / `--cache-ttl` / `--refresh` | 响应缓存目录（默认 `~/.cache/cf-editorial-export`）、有效期（默认 3600s）、强制重抓 |
| `--lean` | 去掉 `text` / `introText` / `introMarkdown` / `codeBlocks` / `html`，保留 `sections` |
| `--compact` / `--html` | 单行 JSON / 额外输出原始正文 HTML |
| `--quiet` | 不打印进度日志 |

### 输出字段

| 字段 | 说明 |
|---|---|
| `entryId` / `title` / `sourceUrl` / `author` | 题解元信息 |
| `publishedAt` / `publishedAtRaw` / `grabbedAt` | ISO 时间 / 原始时间 / 抓取时间 |
| `locale` / `originalLocale` / `tags` | 语言与标签 |
| `introMarkdown` / `introText` | 第一篇题解之前的正文（前言、比赛链接等） |
| `sections[]` | 按题分段：`seq`、`index`、`contestId`、`problemKey`（如 `1351A`）、`title`、`problemUrl`、`markdown`、`text`、`codeBlocks[]` |
| `markdown` / `text` | 整篇合并的 Markdown / 纯文本 |

- `problemKey`（`contestId + index`）可与抓题脚本的 `suggestedPid` 对齐（加 `CF` 前缀即成 `CF1351A`）；
- 标程代码取 `sections[].codeBlocks[].code`；`markdown` 顶部带题解链接 / 作者 / 发布时间，
  写成 `solution/sol.md` 时只留正文，元信息压成一行来源链接。

### 已知限制

- 题解正文若整段没有 `A. / B. / C.` 这类题目标题，`sections` 为空，内容全在 `markdown` / `introMarkdown` 里；
- `blogEntry.view` 只对公开 entry 有效，私密 / 草稿 entry 需 `--source web --cookie`；
- 网页抓取受 Cloudflare 影响时可能返回 `403`，优先用默认的 api 通道。