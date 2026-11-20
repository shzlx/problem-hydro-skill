# 通用库目录

本目录放置造题、评测和题目整理过程中复用的通用库。

## 当前内容

| 文件 | 说明 |
|---|---|
| `testlib.h` | 竞赛编程标准库，用于编写 checker、validator、generator 和 interactor |

## 使用方式

```cpp
#include "testlib.h"
```

编译：`g++ -O2 -std=c++14 your_file.cpp -o your_program`

## 维护要求

- 第三方库应保留原始许可、版本和来源说明。
- 对第三方库做本地修改时，应在提交或文档中说明修改原因。
- 不把一次性题目代码放入本目录。
