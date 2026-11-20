# Hydro 题目文件夹规范

Hydro 官方题目传输格式是基于 zip 的标准格式：压缩包内可包含多个题目文件夹，每个文件夹内放置题目元信息、题面、测试数据和附加文件。

## 标准目录结构

```text
problem-package.zip
├── some-problem/
│   ├── problem.yaml
│   ├── problem_zh.md
│   ├── problem_en.md          # 可选，国外题目可放原文
|   ├── solution/
│   │   ├── sol.md             # 题解（不放 problem_zh.md）
│   ├── testdata/
│   │   ├── config.yaml
│   │   ├── std.cpp
│   │   ├── gen.cpp            # 数据生成器
│   │   ├── a1.in
│   │   ├── a1.out
│   │   ├── a2.in
│   │   └── a2.out
│   └── additional_file/
│       ├── image.png
│       └── statement.pdf
└── another-problem/
    └── ...
```

约定：

- 一个题目一个目录；目录名应稳定、简短、可排序。
- 题目目录必须包含 `problem.yaml` 和至少一个 `problem_*.md`。
- 测试数据、标程、数据生成器放入 `testdata/`。
- 图片、PDF 等题面附加资源放入 `additional_file/`。

## problem.yaml

最小示例：

```yaml
title: 题目名
tag:
  - 标签1
  - 标签2
pid: P1001
```

字段说明：

- `title`：题目显示名称，**必须中英并列**，格式 `中文标题 / English Title`。
- `tag`：标签列表；抓取后可先保留原平台标签，再人工整理教学标签。
- `pid`：题号，建议字母+数字。Codeforces / AtCoder 题目按 `CF2232A`、`ABC458B` 格式命名。

## 题面文件

题面文件使用 `problem_*.md` 命名，例如 `problem_zh.md`、`problem_en.md`。

规范：

- 使用 Markdown 编写，语言代号可用短形式 `zh` 或完整形式 `zh_CN`。
- 多语言题面可同时存在，Hydro 自动识别并提供切换。
- 题面应包含：题目描述、输入格式、输出格式、约束、样例和说明。
- 其他平台题目应包含来源（如 Codeforces 原题链接）。
- **题解不要写进 `problem_zh.md`**，放到 `testdata/sol.md`。

### 样例写法

Hydro 支持用代码块声明样例输入输出：

````markdown
```input1
1 2
```

```output1
3
```
````

后接数字表示测试点编号，Hydro 自动合并并左右分栏显示。**不要**再写 `## 样例 N` 标题。

行号分组标注：

````markdown
```input1|2-3,6-7,10-11
7
3
1 2 1
2
7 7
6
1 2 3 1 2 3
```
````

### 附加文件引用

`additional_file/` 中的文件可在题面中用 `file://` 引用：

```markdown
[下载数据](file://input.in)
![示意图](file://image.png)
@[pdf](file://statement.pdf)
@[doc](file://statement.docx)
```

注意：

- 图片、PDF 等资源应放在 `additional_file/`，不要放入 `testdata/`。
- 外部平台抓取到的图片要记录原始链接；下载到本地后更新题面为 `file://` 路径。
- PDF 预览异常时，可尝试 `@[pdf](file://statement.pdf?noDisposition=1)`。

## 题解与标程

- **题解文件**：写入 `solution/sol.md`。`problem_zh.md` 只放题面，**不放题解**。
- **标程来源**：优先从官方题解逐字复制 C++ 代码。若未提供标程代码，**直接向用户索要，不要自行实现**。

## 测试数据目录

`testdata/` 存放正式测试数据和评测配置。文件名必须包含数字（`sample.in` 不会被自动识别）。

推荐命名：

```text
testdata/
├── config.yaml
├── a1.in
├── a1.out
├── a2.in
├── a2.out
├── a3.in
└── a3.out
```

Hydro 自动识别时默认使用 `1s`、`256MB` 限制。

## testdata/config.yaml

复杂题目应显式提供 `testdata/config.yaml`。最小常用配置：

```yaml
type: default
time: 1s
memory: 256m
checker_type: default
subtasks:
  - score: 100
    type: sum
    cases:
      - input: a1.in
        output: a1.out
      - input: a2.in
        output: a2.out
```

常用字段：

| 字段 | 说明 |
|---|---|
| `type` | 题目类型：`default`、`objective`、`interactive` |
| `time` | 全局时间限制，如 `1s` |
| `memory` | 全局空间限制，如 `256m` |
| `filename` | 文件 IO 名称；标准输入输出题目删除此项 |
| `checker_type` | 比较器类型：`default` 或 `testlib` |
| `checker` | 自定义 checker 文件路径 |
| `interactor` | 交互器文件路径 |
| `user_extra_files` | 复制到用户程序工作目录的额外文件 |
| `judge_extra_files` | 复制到评测端工作目录的额外文件 |
| `subtasks` | 测试点和子任务配置 |
| `langs` | 允许提交的语言 ID 列表 |
| `time_limit_rate` / `memory_limit_rate` | 按语言设置时空倍率 |

说明：

- 同时配置 `cases` 和 `subtasks` 时优先使用 `cases`；但 `cases` 已被官方标注为旧方式，新题优先使用 `subtasks`。
- `subtasks[].type` 可使用 `min`、`max`、`sum`。
- 可用 `subtasks[].if` 表示依赖前置子任务通过后才计分。
- 单个测试点可覆盖全局 `time` 和 `memory`。

## 特殊评测与交互题

### Checker

使用 testlib checker 时：

```yaml
type: default
checker_type: testlib
checker: chk.cpp
```

要求：

- checker 文件放在题目目录或 `testdata/` 可引用的位置，路径必须与 `config.yaml` 一致。
- C++ checker 扩展名使用 `.cpp`。
- 不需要写 `seekeof`。

### Interactor

交互题配置：

```yaml
type: interactive
interactor: interactor.cpp
```

要求：

- 题面必须清楚写出交互协议、询问限制、刷新要求和非法输出处理。
- C++ 交互程序需要刷新缓冲区时使用 `cout.flush()`。

### 客观题

客观题只需配置 `config.yaml`，不需要上传测试数据文件：

```yaml
type: objective
answers:
  '1': ['2', 50]
  '2':
    'A': 30
    'B': 10
  '3': [['A', 'B'], 20]
```
