#!/usr/bin/env python3
"""按仓库 doc/hydro-problem.md 规范校验题目包，可选打包 zip。

用法：
    python3 check_package.py output/abc478_e
    python3 check_package.py output/abc478_e --zip output/ABC478E_lt_and_le.zip

退出码：0 全部通过（允许 warning）；1 存在 FAIL。
"""
import argparse
import glob
import os
import re
import subprocess
import sys

OK, WARN, FAIL = "PASS", "WARN", "FAIL"


def load_yaml(path):
    try:
        import yaml
    except ImportError:
        sys.exit("需要 PyYAML：pip3 install pyyaml")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


class Report:
    def __init__(self):
        self.fails = 0
        self.rows = []

    def add(self, level, msg):
        self.rows.append((level, msg))
        if level == FAIL:
            self.fails += 1

    def dump(self):
        for level, msg in self.rows:
            print(f"  [{level}] {msg}")


def sample_blocks(md_text):
    """提取 ```inputN ... ``` 代码块，返回 {N: 内容}。"""
    out = {}
    for m in re.finditer(r"```input(\d+)\s*\n(.*?)```", md_text, re.S):
        out[int(m.group(1))] = m.group(2).strip()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("problem_dir")
    ap.add_argument("--zip", default=None, help="校验通过后打包到该路径")
    args = ap.parse_args()

    pdir = os.path.abspath(args.problem_dir)
    tdir = os.path.join(pdir, "testdata")
    r = Report()

    # 1. problem.yaml
    py_path = os.path.join(pdir, "problem.yaml")
    meta = {}
    if not os.path.isfile(py_path):
        r.add(FAIL, "缺少 problem.yaml")
    else:
        meta = load_yaml(py_path) or {}
        title = str(meta.get("title", ""))
        if "/" not in title:
            r.add(FAIL, f"title 未中英并列（应形如「中文 / English」）：{title}")
        elif not re.search(r"[\u4e00-\u9fff]", title.split("/")[0]):
            r.add(FAIL, f"title 前半段应为中文：{title}")
        else:
            r.add(OK, f"title = {title}")
        if not meta.get("pid"):
            r.add(FAIL, "缺少 pid")
        else:
            r.add(OK, f"pid = {meta['pid']}")
        if not meta.get("tag"):
            r.add(WARN, "tag 为空，建议补教学标签")
        else:
            r.add(OK, f"tag = {', '.join(map(str, meta['tag']))}")

    # 2. 题面文件
    langs = [os.path.basename(p) for p in glob.glob(os.path.join(pdir, "problem_*.md"))]
    if not langs:
        r.add(FAIL, "缺少 problem_*.md")
    else:
        r.add(OK, f"题面：{', '.join(sorted(langs))}")
    if "problem_zh.md" not in langs:
        r.add(WARN, "缺少 problem_zh.md（中文题面）")

    # 3. config.yaml
    cfg_path = os.path.join(tdir, "config.yaml")
    cfg = {}
    if not os.path.isfile(cfg_path):
        r.add(FAIL, "缺少 testdata/config.yaml")
    else:
        cfg = load_yaml(cfg_path) or {}
        cases = []
        for st in cfg.get("subtasks") or []:
            cases += [(c["input"], c["output"]) for c in st.get("cases") or []]
        cases += [(c["input"], c["output"]) for c in cfg.get("cases") or []]
        if not cases:
            r.add(FAIL, "config.yaml 未配置任何测试点")
        else:
            r.add(OK, f"{len(cases)} 个测试点，time={cfg.get('time')}, memory={cfg.get('memory')}")

        if cfg.get("subtasks"):
            total = sum(int(st.get("score", 0)) for st in cfg["subtasks"])
            if total != 100:
                r.add(FAIL, f"子任务总分 {total} ≠ 100")
            else:
                r.add(OK, f"子任务总分 100（{len(cfg['subtasks'])} 个子任务）")

        missing = [f"{i}->{o}" for i, o in cases
                   if not os.path.isfile(os.path.join(tdir, i))
                   or not os.path.isfile(os.path.join(tdir, o))]
        if missing:
            r.add(FAIL, f"测试点文件缺失：{missing[:5]}")
        else:
            r.add(OK, "所有 case 的 .in/.out 均存在")

        if cfg.get("checker_type") == "testlib":
            chk = cfg.get("checker")
            if not chk:
                r.add(FAIL, "checker_type=testlib 但未指定 checker 文件")
            else:
                chk_path = chk if os.path.isabs(chk) else os.path.join(tdir, chk)
                if os.path.isfile(chk_path):
                    r.add(OK, f"checker 存在：{chk}")
                else:
                    r.add(FAIL, f"checker 不存在：{chk_path}")
                src = os.path.join(tdir, "std.cpp")
                if os.path.isfile(src) and not chk_path.endswith(".cpp"):
                    r.add(WARN, "checker 应为 .cpp 源码")

        # 4. 题面样例与 a1.in 一致性
        zh = os.path.join(pdir, "problem_zh.md")
        if os.path.isfile(zh):
            with open(zh, encoding="utf-8") as f:
                blocks = sample_blocks(f.read())
            a1 = os.path.join(tdir, "a1.in")
            if blocks and os.path.isfile(a1):
                with open(a1, encoding="utf-8") as f:
                    a1_text = f.read().strip()
                same = blocks[1].split() if 1 in blocks else []
                if same == a1_text.split():
                    r.add(OK, "样例 1 与 a1.in 一致")
                else:
                    r.add(WARN, "样例 1 与 a1.in 内容不一致（若 a1 非样例可忽略）")
            if "## 样例" in open(zh, encoding="utf-8").read() and "```input1" not in open(zh, encoding="utf-8").read():
                r.add(FAIL, "题面有样例章节但没有 ```input1``` 代码块")

    # 5. testdata 目录卫生
    if os.path.isdir(tdir):
        extra = [f for f in os.listdir(tdir) if f in ("testlib.h",)]
        if extra:
            r.add(WARN, f"testdata 内有编译依赖残留：{extra}，建议移出")
        ins = {f[:-3] for f in os.listdir(tdir) if f.endswith(".in")}
        outs = {f[:-4] for f in os.listdir(tdir) if f.endswith(".out")}
        if ins - outs:
            r.add(FAIL, f"有 .in 缺少 .out：{sorted(ins - outs)}")
        if outs - ins:
            r.add(FAIL, f"有 .out 缺少 .in：{sorted(outs - ins)}")
        if ins and not (ins - outs or outs - ins):
            r.add(OK, f"{len(ins)} 组 .in/.out 配对完整")

    # 6. 打包
    if args.zip:
        if os.path.exists(args.zip):
            os.remove(args.zip)
        target = os.path.dirname(os.path.abspath(args.zip))
        os.makedirs(target, exist_ok=True)
        r_cmd = subprocess.run(
            ["zip", "-rq", "-9", os.path.abspath(args.zip), os.path.basename(pdir),
             "-x", "*.DS_Store", "-x", "__MACOSX/*"],
            cwd=os.path.dirname(pdir),
        )
        if r_cmd.returncode != 0:
            r.add(FAIL, "zip 打包失败")
        else:
            t = subprocess.run(["unzip", "-t", args.zip], capture_output=True, text=True)
            if t.returncode == 0:
                size = os.path.getsize(args.zip) / 1024 / 1024
                r.add(OK, f"打包完成：{args.zip}（{size:.1f} MB，unzip -t 通过）")
            else:
                r.add(FAIL, "zip 完整性校验失败")

    r.dump()
    print(f"\n{'FAIL' if r.fails else 'ALL PASS'}（{r.fails} 个问题）")
    return 1 if r.fails else 0


if __name__ == "__main__":
    sys.exit(main())
