#!/usr/bin/env python3
"""生成 Hydro 题目目录骨架（problem.yaml / problem_zh.md / testdata 占位）。

用法：
    python3 scaffold.py --pid ABC478E --title-zh 小于与小于等于 --title-en "lt and le" \\
        --dir output/abc478_e --time 2s --memory 1024m --cases 12 --checker

生成后需人工填空：题面正文、std.cpp、gen.cpp、sol.md、a*.in。
"""
import argparse
import os

YAML = """title: {tz} / {te}
tag:
  - 待补标签
pid: {pid}
"""

ZH = """# {tz} / {te}

来源：[AtCoder {contest} - {letter}]({url})

## 题目描述

TODO：中文题意。

## 输入格式

```
TODO
```

## 输出格式

TODO

## 约束

- TODO

## 样例

```input1
TODO
```

```output1
TODO
```
"""

CONFIG_CK = """type: default
time: {time}
memory: {memory}
checker_type: testlib
checker: chk.cpp
subtasks:
  - score: 100
    type: sum
    cases:
{cases}
"""

CONFIG_PLAIN = """type: default
time: {time}
memory: {memory}
checker_type: default
subtasks:
  - score: 100
    type: sum
    cases:
{cases}
"""

SOL = """# 题解

## 思路

TODO

## 复杂度

- 时间：TODO
- 空间：TODO

## 参考代码

```cpp
TODO
```

## 数据说明

| 测试点 | 规模 | 内容 | 预期 |
|---|---|---|---|
| a1 | TODO | TODO | TODO |
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", required=True, help="如 ABC478E")
    ap.add_argument("--title-zh", required=True)
    ap.add_argument("--title-en", required=True)
    ap.add_argument("--dir", required=True, help="题目目录，如 output/abc478_e")
    ap.add_argument("--contest", default=None, help="如 abc478，默认从 pid 推")
    ap.add_argument("--letter", default=None, help="如 E，默认从 pid 推")
    ap.add_argument("--time", default="2s")
    ap.add_argument("--memory", default="1024m")
    ap.add_argument("--cases", type=int, default=10)
    ap.add_argument("--checker", action="store_true", help="config 使用 testlib checker")
    args = ap.parse_args()

    contest = args.contest or (args.pid[:-1].lower())
    letter = (args.letter or args.pid[-1]).upper()
    url = f"https://atcoder.jp/contests/{contest}/tasks/{contest}_{letter.lower()}"

    pdir = os.path.abspath(args.dir)
    tdir = os.path.join(pdir, "testdata")
    os.makedirs(tdir, exist_ok=True)

    def write(path, text):
        if os.path.exists(path):
            print(f"  skip（已存在）{path}")
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"  write {path}")

    write(os.path.join(pdir, "problem.yaml"),
          YAML.format(tz=args.title_zh, te=args.title_en, pid=args.pid))
    write(os.path.join(pdir, "problem_zh.md"),
          ZH.format(tz=args.title_zh, te=args.title_en, contest=contest, letter=letter, url=url))

    cases = "\n".join(
        f"      - input: a{i}.in\n        output: a{i}.out" for i in range(1, args.cases + 1)
    )
    tmpl = CONFIG_CK if args.checker else CONFIG_PLAIN
    write(os.path.join(tdir, "config.yaml"),
          tmpl.format(time=args.time, memory=args.memory, cases=cases))
    write(os.path.join(tdir, "sol.md"), SOL)
    print(f"\n骨架已生成：{pdir}（{args.cases} 个测试点占位）")


if __name__ == "__main__":
    main()
