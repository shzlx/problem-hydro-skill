# C++ 代码规范

## 编译

- 编译选项：`-O2 -std=c++14`
- 使用万能头文件：`#include<bits/stdc++.h>`

## 命名

| 类型 | 规则 | 示例 |
|---|---|---|
| 常量 | 全大写 | `MAXN`、`MOD`、`INF` |
| 变量 | 全小写 | `n`、`ans`、`cnt`、`from`、`to` |
| 结构体 | 首字母大写 | `Node`、`Edge`、`Op` |
| 函数 | 小写优先 | `work`、`dfs`、`h` |

## I/O

- 使用输入输出加速：`ios::sync_with_stdio(false); cin.tie(0);`
- 仅使用 `cin` / `cout`，用 `'\n'` 换行
- 交互题刷新缓冲区：`cout.flush()`

## 代码风格

- 数组下标可按题目习惯使用 `1` 起始；若使用 `0` 起始，同一份代码内保持一致。
- `if`、`for`、`while` 单语句分支可以不加大括号；多语句分支必须加大括号。
- 尽量用全局静态数组，常用存图方式：`vector<pair<int,int>> e[MAXN+5];`
