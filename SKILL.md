---
name: problem-hydro-skill
description: 把 AtCoder / Codeforces 等平台的竞赛题目整理成可直接导入 Hydro OJ 的题目包（problem.yaml + problem_zh.md + testdata 中的 config.yaml / std.cpp / gen.cpp / checker / 测试数据），并完成本地评测、对拍与打包校验。当用户说「抓题打包」「把 abcXXX 某题做成题目包」「AtCoder 题目转 Hydro」「导入 Hydro」「继续打包 B/C/D 题」「重新打包/校验已有题目包」时使用。This skill should be used when a user asks to fetch an online judge problem and package it as a Hydro OJ problem package, or to verify, rebuild and repackage an existing one.
---

# Codeforces / AtCoder → Hydro 题目包

## 用途

竞赛造题工具集：抓取 Codeforces / AtCoder 题目,打包为 Hydro OJ 标准题目包。覆盖：抓题 → 中文题面 → 标程与数据 → 校验 → 打包。

## 工作约定

工作规范文件：

| 文件 | 内容 |
|---|---|
| `doc/hydro-problem.md` | 目录结构、`problem.yaml`、`config.yaml`、特殊评测 |
| `doc/cpp-code-style.md` | C++ 风格：`-O2 -std=c++14`、`bits/stdc++.h`、`ios::sync_with_stdio(false)` |
| `userscripts/atcoder/atcoder-contest-export.py` | AtCoder 抓题脚本 |
| `userscripts/codeforces/cf-contest-export.py` | Codeforces 抓题脚本（由同目录 userscript 改写的命令行版） |

目录：题目包 `output/<pid小写>/`，临时文件 `work/`，脚本 `scripts/`。
本 skill 的脚本在 `scripts/`（下称 `$SK`）。

## 工作流

### 1. 抓题

```bash
# AtCoder
python3 userscripts/atcoder/atcoder-contest-export.py abc478 --task E --format markdown

# Codeforces（2285 / 2285A / 2285/A / 题目 URL 都能当目标，gym 加 --gym）
python3 userscripts/codeforces/cf-contest-export.py 2285 --task A --format markdown
```

- `--task A` 只取单题；省略抓整场；`--lang ja`（AtCoder 日文）/ `--lang ru`（CF 俄文）；`--refresh` 跳过缓存。
- 输出到 stdout，日志到 stderr。退出码 2=参数错，3=全失败，4=部分失败。
- CF 脚本输出的 JSON 已带 `suggestedPid`（`CF2285A`）、`timeLimitMs`、`memoryLimitMiB`，可直接填进 `scaffold.py` 的 `--pid/--time/--memory`。
- 拿到英文原题后：**逐段翻译成中文**，公式、变量名、样例数值保持原样；`problem_en.md` 存原文。

### 2. 建骨架

```bash
python3 $SK/scaffold.py --pid ABC478E --title-zh 小于与小于等于 --title-en "lt and le" \
    --dir output/abc478_e --time 2s --memory 1024m --cases 12 --checker
```

生成 `problem.yaml`、`problem_zh.md`、`testdata/{config.yaml,sol.md}` 占位。已存在的文件不会被覆盖。

`--checker` 表示这题多解，需要 testlib checker。

### 3. 写题面

`problem_zh.md` 必含：题目描述、输入格式、输出格式、约束、样例。首行放来源链接。

样例用代码块，**不要**写 `## 样例 1` 这种标题：

````markdown
```input1
3 5
```

```output1
2
2
1
```
````

约定 `a1.in` 与题面样例 1 内容一致（`check_package.py` 会核对）。题解**只**写进 `testdata/sol.md`。

数学记号一律不翻译，原样保留：$a_i \neq t_j$、$1 \le N \le 100$、$\dots$、\vdots、$\sum$、$2\times10^5$ 等照抄，不要改成「不等于」「省略号」「竖省略号」这类中文说法，也不要增删 $ 或 \。

### 4. 标程、生成器、评测器

- `testdata/std.cpp`：标程。优先官方题解代码；无官方代码时，按可行解法自写并明确告知用户，用对拍证明正确。
- `testdata/gen.cpp`：testlib 生成器，参数化（seed + 规模 + 模式），支持「保证有解 / 保证无解 / 纯随机」几档。
- `testdata/chk.cpp`：**多解、构造、输出方案类题目必须写** testlib checker，只校验合法性不比较具体取值。
- 测试数据：`a1..aN.in/out`，文件名必须含数字（`sample.in` 不会被识别）。

数据点至少要覆盖：题面样例、最小规模、最大规模、退化情形（全相等 / 全部无解 / 链状 / 星形）、极端值域、能卡掉错解的构造点。

### 5. 校验

```bash
# 用标程重算 .out，并逐点用 checker 校验
python3 $SK/run_cases.py output/abc478_e --write

# 对拍（小数据，比较 Yes/No 或第一行）
python3 $SK/fuzz.py --gen "/tmp/gen {seed} 4 30 60" --std /tmp/std --alt /tmp/brute --cmp token

# 规范校验 + 打包 + unzip -t
python3 $SK/check_package.py output/abc478_e --zip output/ABC478E_lt_and_le.zip
```

用 `run_cases.py` 前先把 `std.cpp`、`chk.cpp`、`gen.cpp` 编译好；脚本会自动处理 macOS 缺 `bits/stdc++.h`、自动从 `libs/testlib.h` 找 testlib。

**必须**做的三件事：

1. 标程与另一实现（暴力 / 另一解法）对拍一致；
2. 每个点用 checker 自检通过；
3. `check_package.py` 全 PASS，且 `unzip -t` 通过。

### 6. 交付

`present_files` 给出 zip + `problem_zh.md` + `sol.md`。回复里说明：题号标题、分值/时空限制、测试点覆盖表、校验结果（对拍组数、checker 自检、耗时最慢点）、以及标程来源（官方 or 自写）。

## 关键规则

| 规则 | 说明 |
|---|---|
| `title` 中英并列 | `中文标题 / English Title`，缺斜杠直接判不合规 |
| `pid` 格式 | `ABC478E`、`CF2232A` |
| 总分 100 | `subtasks` 的 `score` 求和必须等于 100 |
| 多解必用 checker | 否则非样例解会被默认比较器判错；`ans` 文件只用于判 `Yes/No` 基线 |
| 题解位置 | `testdata/sol.md`，不写进 `problem_zh.md` |
| zip 命名 | `<PID>_<标题>.zip`，内含题目目录一层; 多题时打包成一个ZIP，`<PID>_<A-E>.zip`,每个题目一个目录。 |
| 压缩 | `zip -rq -9`，输出目录 `output/` |
| 数学记号不翻译 | $a_i \neq t_j$、$\dots$、\vdots、$1 \le N \le 100$ 原样照抄，只译自然语言 |

## 脚本

| 脚本 | 作用 |
|---|---|
| `scaffold.py` | 生成题目目录骨架 |
| `run_cases.py` | 编译 std/checker，跑全部测试点，`--write` 重算 `.out` |
| `check_package.py` | 规范校验（title/pid/总分/文件配对/样例一致性），`--zip` 打包 |
| `fuzz.py` | 对拍，`--cmp first\|token\|full`，`--dump-fail` 存失败用例 |

## 参考

- `references/hydro-format.md`：`config.yaml` 字段、特殊评测、数据命名细节
- `references/pitfalls.md`：踩过的坑与对应处理
