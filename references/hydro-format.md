# Hydro 题目包格式细节

## 目录

```
<pid小写>/
├── problem.yaml
├── problem_zh.md
├── problem_en.md            # 可选，原文
├── testdata/
│   ├── config.yaml
│   ├── std.cpp
│   ├── gen.cpp
│   ├── chk.cpp              # 多解 / 构造题需要
│   ├── sol.md
│   └── a1.in / a1.out ...
└── additional_file/         # 图片、PDF（可选）
```

## problem.yaml

```yaml
title: 中文标题 / English Title
tag:
  - 图论
  - AtCoder ABC478
pid: ABC478E
```

- `title` 必须中英并列，用 ` / ` 分隔。
- `pid`：`ABC<场次><题号>`、`CF<场次><题号>`。

## testdata/config.yaml

最小可用：

```yaml
type: default
time: 2s
memory: 1024m
checker_type: default
subtasks:
  - score: 100
    type: sum
    cases:
      - input: a1.in
        output: a1.out
```

多子任务（推荐，便于部分分）：

```yaml
subtasks:
  - score: 30
    type: sum
    cases: [...]
  - score: 40
    type: sum
    cases: [...]
```

字段：

| 字段 | 说明 |
|---|---|
| `type` | `default` / `objective` / `interactive` |
| `time` / `memory` | 全局限制，如 `2s` / `1024m`；题面限制是多少就写多少，不要套用默认 1s/256m |
| `filename` | 文件 IO 名；标准 IO 题目省略 |
| `checker_type` | `default`（逐字符）或 `testlib` |
| `checker` | checker 路径，相对 `config.yaml` 所在目录 |
| `interactor` | 交互器，配合 `type: interactive` |
| `subtasks[].type` | `min` / `max` / `sum` |
| `subtasks[].if` | 依赖前置子任务通过才计分 |

注意：

- 同时写 `cases` 和 `subtasks` 时以 `cases` 优先；新题只用 `subtasks`。
- 单点可覆盖全局 `time` / `memory`。

## 题面样例语法

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

- 数字即测试点编号，Hydro 自动左右分栏；不要再写 `## 样例 N`。
- 行号分组：```` ```input1|2-3,6-7 ````。
- 附加文件：`![图](file://image.png)`、`@[pdf](file://a.pdf)`，文件放 `additional_file/`。

## Checker（多解题必备）

`chk.cpp` 用 testlib，标准框架：

```cpp
#include "testlib.h"
int main(int argc, char* argv[]) {
    registerTestlibCmd(argc, argv);
    int n = inf.readInt();
    // ... 读输入到本地数组
    string sans = ans.readWord();   // 标准答案只用来判 Yes/No 基线
    string jans = ouf.readWord();
    if (sans == "No") {
        if (jans == "No") quitf(_ok, "no solution, correct");
        quitf(_wa, "expected No, found %s", jans.c_str());
    }
    if (jans != "Yes") quitf(_wa, "expected Yes, found %s", jans.c_str());
    // 读选手输出、逐条校验条件
    for (...) if (!(a[u] <= a[v])) quitf(_wa, "condition %d violated", i + 1);
    quitf(_ok, "answer valid");
}
```

- `ouf.readInt(1, n, "A[i]")` 自带值域校验，越界直接 WA。
- 校验器的 argv 顺序是 `inf ouf ans`，退出码 0 为通过。

## 交互题

```yaml
type: interactive
interactor: interactor.cpp
```

题面必须写清交互协议、询问次数上限、刷新要求（C++ 用 `cout.flush()`）与非法输出处理。

## 数据命名

- 必须含数字：`a1.in`、`a1.out`；`sample.in` 不会被识别。
- 一组数据点权重相同时按 `a1..aN` 顺序排。
