#!/usr/bin/env python3
"""对拍：用生成器批量造数据，比较两份实现的输出。

用法：
    python3 fuzz.py --gen "python3 gen.py {seed} 1 100" --std ./std --alt ./brute --iters 300
    python3 fuzz.py --gen "python3 gen.py {seed}" --std ./a --alt ./b --cmp token --dump-fail /tmp/fail

--cmp 可选：
    first  比较第一行整行（默认，适合 Yes/No 判定题）
    token  比较第一行第一个 token
    full   比较完整输出

多解题不要用 first/full 直接比序列，改用 run_cases.py + testlib checker 校验合法性。
"""
import argparse
import os
import subprocess
import sys


def gen_input(cmd_tpl, seed):
    cmd = cmd_tpl.format(seed=seed)
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit(f"生成器失败（seed={seed}）：{cmd}\n{p.stderr}")
    return p.stdout


def run(bin_path, data, timeout=30):
    p = subprocess.run([bin_path], input=data, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout


def pick(out, mode):
    lines = out.strip().splitlines()
    if not lines:
        return ""
    if mode == "first":
        return lines[0].strip()
    if mode == "token":
        return lines[0].split()[0] if lines[0].split() else ""
    return out.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", required=True, help="生成器命令模板，用 {seed} 占位")
    ap.add_argument("--std", required=True)
    ap.add_argument("--alt", required=True, help="第二个实现，如暴力或另一解法")
    ap.add_argument("--iters", type=int, default=200)
    ap.add_argument("--cmp", choices=["first", "token", "full"], default="first")
    ap.add_argument("--dump-fail", default=None, help="失败用例保存目录")
    ap.add_argument("--start-seed", type=int, default=1)
    args = ap.parse_args()

    for i in range(args.iters):
        seed = args.start_seed + i
        data = gen_input(args.gen, seed)
        rc1, out1 = run(args.std, data)
        rc2, out2 = run(args.alt, data)
        if rc1 != 0 or rc2 != 0:
            print(f"[RE] seed={seed} std_rc={rc1} alt_rc={rc2}")
            bad = True
        else:
            bad = pick(out1, args.cmp) != pick(out2, args.cmp)
        if bad:
            print(f"[MISMATCH] seed={seed}")
            print("--- input ---")
            print(data[:2000])
            print("--- std ---")
            print(out1[:2000])
            print("--- alt ---")
            print(out2[:2000])
            if args.dump_fail:
                os.makedirs(args.dump_fail, exist_ok=True)
                with open(os.path.join(args.dump_fail, f"fail_{seed}.in"), "w") as f:
                    f.write(data)
            return 1
    print(f"OK: {args.iters} 组数据全部一致（cmp={args.cmp}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
