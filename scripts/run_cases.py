#!/usr/bin/env python3
"""本地评测 Hydro 题目包：编译 std / checker，跑全部测试点并校验。

用法：
    python3 run_cases.py output/abc478_e              # 只校验现有 a*.out
    python3 run_cases.py output/abc478_e --write      # 用 std 重新生成 a*.out 后再校验
    python3 run_cases.py output/abc478_e --std testdata/std.cpp --no-checker

行为：
* 自动处理 macOS clang 缺少 bits/stdc++.h 的问题（生成临时 shim 头文件）；
* checker_type 为 testlib 时自动编译 checker，并从仓库 libs/ 复制 testlib.h；
* 有 checker 走 checker 判定，无 checker 做逐字节对比；
* 逐点报告 PASS/FAIL 与耗时，全部通过返回 0。
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

SHIM_HEADERS = [
    "cstdio", "cstdlib", "cstring", "cmath", "cassert", "string", "vector",
    "algorithm", "iostream", "iomanip", "map", "set", "queue", "stack", "deque",
    "utility", "numeric", "functional", "limits", "bitset", "array", "tuple",
    "unordered_map", "unordered_set", "sstream", "fstream", "random", "chrono",
]


def find_repo_root(start):
    """向上查找带 doc/hydro-problem.md 的仓库根目录。"""
    cur = os.path.abspath(start)
    while True:
        if os.path.isfile(os.path.join(cur, "doc", "hydro-problem.md")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def load_yaml(path):
    try:
        import yaml
    except ImportError:
        sys.exit("需要 PyYAML：pip3 install pyyaml")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def compile_cpp(src, out, repo_root, need_testlib=False, extra_incs=()):
    """编译 C++，遇到 bits/stdc++.h 缺失时自动加 shim。返回 True/False。"""
    incs = list(extra_incs)
    tmpdirs = []
    if need_testlib and repo_root:
        lib = os.path.join(repo_root, "libs", "testlib.h")
        if os.path.isfile(lib):
            incs.append(os.path.dirname(lib))

    def build():
        cmd = ["g++", "-O2", "-std=c++14", src, "-o", out]
        cmd += [f"-I{i}" for i in incs]
        return subprocess.run(cmd, capture_output=True, text=True)

    r = build()
    if r.returncode != 0 and "bits/stdc++.h" in r.stderr:
        shim = tempfile.mkdtemp(prefix="gccshim.")
        tmpdirs.append(shim)
        os.makedirs(os.path.join(shim, "bits"), exist_ok=True)
        with open(os.path.join(shim, "bits", "stdc++.h"), "w", encoding="utf-8") as f:
            f.write("".join(f"#include <{h}>\n" for h in SHIM_HEADERS))
        incs.append(shim)
        r = build()
    if r.returncode != 0:
        sys.stderr.write(f"[compile] {src} 失败：\n{r.stderr}\n")
        return False
    return True


def parse_cases(cfg):
    """兼容 subtasks 与 cases 两种写法，返回 [(name_in, name_out), ...]。"""
    cases = []
    for st in cfg.get("subtasks") or []:
        for c in st.get("cases") or []:
            cases.append((c["input"], c["output"]))
    for c in cfg.get("cases") or []:
        cases.append((c["input"], c["output"]))
    return cases


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("problem_dir", help="题目目录，如 output/abc478_e")
    ap.add_argument("--std", default=None, help="标程路径，默认 testdata/std.cpp")
    ap.add_argument("--write", action="store_true", help="用标程重新生成 .out")
    ap.add_argument("--no-checker", action="store_true", help="忽略 checker，逐字节对比")
    args = ap.parse_args()

    pdir = os.path.abspath(args.problem_dir)
    tdir = os.path.join(pdir, "testdata")
    cfg_path = os.path.join(tdir, "config.yaml")
    if not os.path.isfile(cfg_path):
        sys.exit(f"找不到 {cfg_path}")
    cfg = load_yaml(cfg_path)
    repo_root = find_repo_root(pdir)

    cases = parse_cases(cfg)
    if not cases:
        sys.exit("config.yaml 里没有 case")

    work = tempfile.mkdtemp(prefix="hydrocheck.")
    std_src = os.path.join(pdir, args.std) if args.std and not os.path.isabs(args.std) \
        else (args.std or os.path.join(tdir, "std.cpp"))
    std_bin = os.path.join(work, "std")
    if not compile_cpp(std_src, std_bin, repo_root):
        sys.exit("标程编译失败")

    chk_bin = None
    chk_name = cfg.get("checker")
    if not args.no_checker and cfg.get("checker_type") == "testlib" and chk_name:
        chk_src = chk_name if os.path.isabs(chk_name) else os.path.join(tdir, chk_name)
        if not os.path.isfile(chk_src):
            sys.exit(f"找不到 checker：{chk_src}")
        chk_bin = os.path.join(work, "chk")
        if not compile_cpp(chk_src, chk_bin, repo_root, need_testlib=True):
            sys.exit("checker 编译失败")

    time_limit = str(cfg.get("time", "2s"))
    m = re.match(r"([\d.]+)", time_limit)
    limit = float(m.group(1)) if m else 2.0

    fails = 0
    for cin, cout in cases:
        ip = os.path.join(tdir, cin)
        op = os.path.join(tdir, cout)
        if not os.path.isfile(ip):
            print(f"  [MISS] {cin} 不存在")
            fails += 1
            continue
        t0 = time.time()
        with open(ip, "rb") as f:
            run = subprocess.run([std_bin], stdin=f, capture_output=True)
        elapsed = time.time() - t0
        if run.returncode != 0:
            print(f"  [RE]   {cin} 标程非零退出 {run.returncode}")
            fails += 1
            continue
        if args.write:
            with open(op, "wb") as f:
                f.write(run.stdout)
        if not os.path.isfile(op):
            print(f"  [MISS] {cout} 不存在（可加 --write 生成）")
            fails += 1
            continue

        if chk_bin:
            with tempfile.NamedTemporaryFile(delete=False) as tf:
                tf.write(run.stdout)
                out_path = tf.name
            r = subprocess.run([chk_bin, ip, out_path, op], capture_output=True, text=True)
            os.unlink(out_path)
            msg = (r.stdout + r.stderr).strip().splitlines()
            verdict = msg[-1] if msg else ""
            ok = r.returncode == 0
        else:
            with open(op, "rb") as f:
                expected = f.read()
            ok = expected.strip() == run.stdout.strip()
            verdict = "byte match" if ok else "byte mismatch"

        slow = "  <<< 超时风险" if elapsed > limit * 0.5 else ""
        print(f"  [{'PASS' if ok else 'FAIL'}] {cin:12s} {elapsed:5.2f}s  {verdict}{slow}")
        if not ok:
            fails += 1

    shutil.rmtree(work, ignore_errors=True)
    total = len(cases)
    print(f"\n{total - fails}/{total} 通过" + ("" if fails == 0 else f"，{fails} 个失败"))
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
