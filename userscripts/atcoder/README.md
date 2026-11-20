AtCoder Contest Problem Exporter —— 面向 AI / Agent 调用的题目抓取器

参考 Codeforces Contest Problem Exporter 的数据结构重写，适配 AtCoder 页面。
仅用标准库，无需浏览器、无需第三方依赖。

用法示例
--------
    # 抓整场比赛，JSON 打到 stdout（默认）
    python3 atcoder-contest-export.py https://atcoder.jp/contests/abc478

    # 存文件 + 压缩输出（给 LLM 省 token）
    python3 atcoder-contest-export.py abc478 --compact --out abc478.json

    # 导出 Hydro / Markdown 友好的整场题面
    python3 atcoder-contest-export.py abc478 --format markdown --out abc478.md

    # 只要某几题（按字母或 task id）
    python3 atcoder-contest-export.py abc478 --task A --task abc478_c

    # 日文题面
    python3 atcoder-contest-export.py abc478 --lang ja

    # 逐题一行 JSON（流式喂给模型 / 分批处理）
    python3 atcoder-contest-export.py abc478 --format jsonl

命令行约定（方便 Agent 使用）
----------------------------
* stdout 只输出正文数据（json / jsonl / markdown），日志一律写 stderr；
* 退出码：0 全成功；2 参数错误；3 全部失败；4 部分题目失败；
* 失败题目不会中断整场导出，会以 {"...","error":"..."} 形式留在结果里；
* 支持缓存，重复调用不再打 AtCoder（默认 1 小时内有效，--refresh 强制重抓）。

也可以在 Python 里直接调用
--------------------------
    from atcoder_contest_export import fetch_contest
    data = fetch_contest("abc478", lang="en")