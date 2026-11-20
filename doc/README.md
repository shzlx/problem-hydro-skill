# 文档索引

本目录保存仓库维护规范。`AGENT.md` 必须遵循本目录中的规则；当不同文档出现冲突时，优先级如下：

1. 用户本次明确提出的要求。
2. `doc/cpp-code-style.md` 中的代码风格要求。
3. `doc/hydro-problem.md` 中的 Hydro 题目包格式要求。
4. `AGENT.md` 中的协作说明。

## 文档列表

| 文件 | 说明 |
|---|---|
| `cpp-code-style.md` | C++ 工具和脚本的编译选项、命名、I/O 等风格约定 |
| `hydro-problem.md` | Hydro 题目包的目录结构、`problem.yaml`、题面、测试数据、特殊评测等规范 |

## 目录约定

| 目录 | 说明 |
|---|---|
| `libs/` | 通用库，如 `testlib.h` |
| `userscripts/` | 抓题 / 题解脚本，按平台分子目录（浏览器篡改猴 + 命令行 Python 两种形态） |
| `doc/` | 仓库规范和维护文档 |
| `work/` | 工作目录（gitignored） |
| `output/` | 输出目录（gitignored） |

## 发版

`.github/workflows/release.yml` 在 push 到 `main` 后自动发版：

| 触发 | 效果 |
|---|---|
| commit message 含 `#minor` / `#major` | 按 minor / major 自增版本号 |
| 普通 commit | patch 自增（`v1.0.2` → `v1.0.3`） |
| commit message 含 `[skip release]` | 跳过本次发版 |
| 手动 dispatch | 可指定版本号，或只选 bump |

产物为 `problem-hydro-skill-<tag>.zip`（`git archive`，排除 `.github/`、`work/`、`output/`），
附在 Release 上，直接解压到 skills 目录即可使用。

## 文档维护原则

- 文档用中文编写，命令、文件名、API 名称保持原文。
- 新增规则应具体、可执行，避免空泛口号。
- 当规范与实际代码长期不一致时，应优先修正文档或明确例外。
