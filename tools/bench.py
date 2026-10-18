#!/usr/bin/env python3
"""Runs a grid of N-body configurations and writes one CSV (standard library only).

Example (Stage 1, sequential only):
    python tools/bench.py --seq-binary build/nbody-seq --sizes 1000,2000,4000 --repeats 5 --steps 50

Example (later stages):
    python tools/bench.py --seq-binary build/nbody-seq --omp-binary build/nbody-omp \
        --sizes 2000,4000 --threads 1,2,4,8 --variants reduction,atomic,critical --repeats 5 --steps 50

Every row records the full configuration, so the CSV is the evidence for the report.
Do not draw conclusions from one run: use the medians this script prints."""
import argparse
import csv
import datetime
import os
import platform
import statistics
import subprocess
import sys

HEADER = "variant,grain,schedule,threads,n,steps,seed,repeat,seconds,pe_last,energy_drift".split(",")


def resolve(binary):
    path = os.path.abspath(binary)
    if platform.system() == "Windows" and not os.path.exists(path) and os.path.exists(path + ".exe"):
        path += ".exe"
    if not os.path.exists(path):
        sys.exit(f"binary not found: {binary} (run build.sh or build.ps1 first)")
    return path


def run(cmd):
    cmd = [resolve(cmd[0])] + cmd[1:]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode not in (0,):
        sys.exit(f"command failed ({out.returncode}): {' '.join(cmd)}\n{out.stderr or out.stdout}")
    return [l for l in out.stdout.splitlines() if l and not l.startswith("note:")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seq-binary", default="build/nbody-seq")
    ap.add_argument("--omp-binary", default=None, help="OpenMP build; needed for --threads and --variants")
    ap.add_argument("--sizes", default="1000,2000,4000")
    ap.add_argument("--steps", type=int, default=50)
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--threads", default="")
    ap.add_argument("--variants", default="reduction")
    ap.add_argument("--grains", default="body")
    ap.add_argument("--schedules", default="static")
    ap.add_argument("--out", default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    sizes = [int(x) for x in a.sizes.split(",") if x]
    threads = [int(x) for x in a.threads.split(",") if x]
    jobs = [("seq", "body", "static", 1, n, a.seq_binary) for n in sizes]
    if threads:
        if not a.omp_binary:
            sys.exit("--threads needs --omp-binary")
        for n in sizes:
            for v in a.variants.split(","):
                for g in a.grains.split(","):
                    for s in a.schedules.split(","):
                        for t in threads:
                            jobs.append((v, g, s, t, n, a.omp_binary))
    print(f"{len(jobs)} configurations x {a.repeats} repeats")
    if a.dry_run:
        return

    os.makedirs("results", exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = a.out or os.path.join("results", f"{platform.node()}_{stamp}.csv")
    rows = []
    for (v, g, s, t, n, binary) in jobs:
        cmd = [binary, "--csv", "--variant", v, "--grain", g, "--schedule", s, "--n", str(n), "--steps", str(a.steps),
               "--seed", str(a.seed), "--repeats", str(a.repeats)]
        if v != "seq":
            cmd += ["--threads", str(t)]
        for line in run(cmd):
            rows.append(dict(zip(HEADER, line.split(","))))
        print(f"  done: {v} grain={g} schedule={s} threads={t} n={n}")
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote {path}")

    # medians and speed-up against the sequential median for the same n
    med = {}
    for r in rows:
        med.setdefault((r["variant"], r["grain"], r["schedule"], r["threads"], r["n"]), []).append(float(r["seconds"]))
    seq = {k[4]: statistics.median(v) for k, v in med.items() if k[0] == "seq"}
    print(f"\n{'variant':10s} {'grain':5s} {'sched':8s} {'thr':>3s} {'n':>7s} {'median s':>10s} {'speed-up':>9s} {'eff.':>6s}")
    for k, v in med.items():
        m = statistics.median(v)
        sp = seq[k[4]] / m if k[4] in seq else float("nan")
        eff = sp / int(k[3]) if int(k[3]) else float("nan")
        print(f"{k[0]:10s} {k[1]:5s} {k[2]:8s} {k[3]:>3s} {k[4]:>7s} {m:10.4f} {sp:9.2f} {eff:6.2f}")


if __name__ == "__main__":
    main()
