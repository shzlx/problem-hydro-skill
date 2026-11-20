# 踩过的坑

## 编译环境

**macOS 没有 `bits/stdc++.h`**
Apple clang / Xcode 工具链不带 GCC 的万能头，`#include <bits/stdc++.h>` 会 `fatal error: file not found`。仓库本身没有 GCC 时：

- 交付代码保留 `bits/stdc++.h`（Hydro 的 GNU 环境需要）；
- 本地验证由 `run_cases.py` 自动生成临时 shim（`/tmp/gccshim/bits/stdc++.h` 里 include 常用标准头）并用 `-I` 注入；
- 手工验证时自己建一份 shim 目录，别改交付文件。

## testlib

**老版本没有带默认值的 `opt<T>`**
`opt<int>(1, default)` 在仓库附带的 `libs/testlib.h` 里不存在（只有 `opt(int index)` 等重载），会报一屏「no matching function」。生成器改用 argc/argv 解析：

```cpp
registerGen(argc, argv, 1);
int n = (argc >= 3) ? atoi(argv[2]) : rnd.next(1, 100);
```

**checker 参数顺序**
`chk inf ouf ans`，不是 `chk inf ans ouf`。退出码 0 为通过。

**checker 的路径**
`config.yaml` 在 `testdata/` 内，`checker: chk.cpp` 就是同目录。放 `testdata/` 最省事。

## 多解题

- 用默认比较器（逐字符）判多解题必然错判：样例答案只是其中一个合法解。
- `ans` 文件仍有作用：给 checker 提供 `Yes/No` 基线。没有它，checker 无法判断「本题到底该不该有解」。
- checker 只校验合法性（值域 + 每条约束），不比具体取值。

## 数据

**大文件体积**
N=2e5 的 `.out` 里每个值可能多字节，单点能到 1MB+，12 个点整包 7 MB 左右。用 `zip -9` 能压到 6~7 MB，Hydro 导入正常。想更小就减少同规模大点数量，而不是砍掉大点。

**名字必须含数字**
`sample.in` / `in1.txt` 之外的命名要确认被识别；统一 `a1.in`。

**大点必须验耗时**
`run_cases.py` 会标出超过限制 50% 的点。递归实现的 DFS（20 万点链）会爆栈，要么改迭代、要么加大栈。

## 题面

- 样例用 ```` ```input1```` 代码块，不要写 `## 样例 1` 标题，Hydro 会自动分栏。
- `title` 少了 ` / ` 分隔符，Hydro 里会显示成一个怪名字，`check_package.py` 会直接判 FAIL。
- 时限/空间按原题写（AtCoder 常见 2s / 1024 MiB），不要套 Hydro 默认的 1s / 256MB。

## 流程

- 规范要求标程优先取官方题解代码；没有官方标程时**先问用户**，确认后再自写，并说明后续可替换。
- 抓题脚本有缓存（默认 1 小时），改题面信息后用 `--refresh`。
- `work/` 放暴力、备选实现、临时二进制，`testdata/` 只留交付文件（`testlib.h` 不要留在里面）。
