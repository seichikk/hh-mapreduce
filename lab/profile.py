import argparse
import csv
import io
import json
import os
import resource
import statistics
import subprocess
import sys
import time

import psutil

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from lab import common as c

M = [sys.executable, "-m"]
METHODS = {
    "mr_naive": ("mapreduce, наивный (до)", M + ["lab.mapreduce", "--mode", "naive", "--workers", "1"]),
    "mr_opt_w1": ("mapreduce, arrow + combiner, 1 маппер", M + ["lab.mapreduce", "--mode", "opt", "--workers", "1"]),
    "mr_opt": ("mapreduce, оптимизированный (после)", M + ["lab.mapreduce", "--mode", "opt"]),
    "mr_opt_c8": ("mapreduce opt, чанк 8 миб", M + ["lab.mapreduce", "--mode", "opt", "--chunk-mib", "8"]),
    "mr_opt_c128": ("mapreduce opt, чанк 128 миб", M + ["lab.mapreduce", "--mode", "opt", "--chunk-mib", "128"]),
    "duck_csv": ("duckdb по csv", M + ["lab.duck", "--source", "csv"]),
    "duck_parquet": ("duckdb по parquet (после)", M + ["lab.duck", "--source", "parquet"]),
}
TEXKEY = {"mr_naive": "MrNaive", "mr_opt_w1": "MrOptOne", "mr_opt": "MrOpt", "mr_opt_c8": "MrOptSmall",
          "mr_opt_c128": "MrOptBig", "duck_csv": "DuckCsv", "duck_parquet": "DuckParquet"}
RUNS = c.RESULTS / "profile" / "runs.jsonl"


def tree_rss(proc):
    total = 0
    try:
        procs = [proc] + proc.children(recursive=True)
    except psutil.NoSuchProcess:
        return 0
    for p in procs:
        try:
            total += p.memory_info().rss
        except psutil.NoSuchProcess:
            pass
    return total


def run_one(method, attempt):
    title, cmd = METHODS[method]
    tag = f"profile/{method}"
    cmd = cmd + ["--tag", tag, "--no-upload"]
    log_path = c.RESULTS / "profile" / f"{method}_{attempt}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    t0 = time.perf_counter()
    peak = 0
    samples = 0
    with open(log_path, "w") as log:
        proc = subprocess.Popen(cmd, cwd=c.ROOT, stdout=log, stderr=subprocess.STDOUT)
        ps = psutil.Process(proc.pid)
        while proc.poll() is None:
            peak = max(peak, tree_rss(ps))
            samples += 1
            time.sleep(0.02)
    wall = time.perf_counter() - t0
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu = (after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime)
    if proc.returncode != 0:
        print(open(log_path).read()[-3000:])
        raise SystemExit(f"{method}: процесс завершился с кодом {proc.returncode}")
    same = True
    for k in c.KS:
        mine = (c.RESULTS / tag / f"k{k}.csv").read_bytes()
        ref = (c.RESULTS / "mapreduce" / f"k{k}.csv").read_bytes()
        same = same and c.sha256_bytes(mine) == c.sha256_bytes(ref)
    rec = {"method": method, "title": title, "attempt": attempt, "seconds": round(wall, 3), "cpu_seconds": round(cpu, 3),
           "peak_rss_mib": round(peak / 1048576, 1), "samples": samples, "same_as_reference": same}
    with open(RUNS, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"{title:<38} #{attempt}: время {wall:6.2f} с, cpu {cpu:6.2f} с, пик {peak / 1048576:6.0f} миб, "
          f"совпало с эталоном: {'да' if same else 'НЕТ'}")
    return 0 if same else 1


def summary():
    recs = [json.loads(line) for line in open(RUNS) if line.strip()]
    order = [m for m in METHODS if any(r["method"] == m for r in recs)]
    rows = []
    print(f"{'способ':<38} {'n':>2} {'время, с (ср +- ск)':>19} {'мин':>6} {'cpu, с':>7} {'пик, миб':>13} {'совпало':>7}")
    stats = {}
    for m in order:
        rs = [r for r in recs if r["method"] == m]
        t = [r["seconds"] for r in rs]
        mem = [r["peak_rss_mib"] for r in rs]
        cpu = [r["cpu_seconds"] for r in rs]
        sd = statistics.stdev(t) if len(t) > 1 else 0.0
        msd = statistics.stdev(mem) if len(mem) > 1 else 0.0
        ok = all(r["same_as_reference"] for r in rs)
        st = {"title": rs[0]["title"], "n": len(rs), "mean": statistics.mean(t), "sd": sd, "min": min(t),
              "cpu": statistics.mean(cpu), "mem": statistics.mean(mem), "mem_sd": msd, "mem_max": max(mem), "ok": ok}
        stats[m] = st
        print(f"{st['title']:<38} {st['n']:>2} {st['mean']:>11.2f} +- {sd:<5.2f} {st['min']:>6.2f} {st['cpu']:>7.2f} "
              f"{st['mem']:>6.0f} +- {msd:<4.0f} {'да' if ok else 'НЕТ':>7}")
        rows.append([c.tex_escape(st["title"]), st["n"], c.tex_dec(st["mean"]) + " $\\pm$ " + c.tex_dec(sd),
                     c.tex_dec(st["min"]), c.tex_dec(st["cpu"], 1), c.tex_dec(st["mem"], 0) + " $\\pm$ " + c.tex_dec(msd, 0),
                     "да" if ok else "\\textbf{нет}"])
    c.write_out("profile_table.tex", c.table_rows(rows))
    run_rows = [[c.tex_escape(r["title"]), r["attempt"], c.tex_dec(r["seconds"]), c.tex_dec(r["cpu_seconds"], 1),
                 c.tex_dec(r["peak_rss_mib"], 0)] for m in order for r in recs if r["method"] == m]
    c.write_out("profile_runs.tex", c.table_rows(run_rows))

    def ratio(a, b, key):
        if a in stats and b in stats and stats[b][key]:
            return stats[a][key] / stats[b][key]
        return None

    v = {"profAttempts": str(min(s["n"] for s in stats.values())), "profOk": "да" if all(s["ok"] for s in stats.values()) else "нет"}
    for m, s in stats.items():
        key = TEXKEY[m]
        v[f"t{key}"] = c.tex_dec(s["mean"])
        v[f"m{key}"] = c.tex_dec(s["mem"], 0)
    for name, a_, b_ in (("MrSpeed", "mr_naive", "mr_opt"), ("ParSpeed", "duck_csv", "duck_parquet"),
                         ("DuckVsMr", "mr_opt", "duck_csv"), ("WorkersSpeed", "mr_opt_w1", "mr_opt"),
                         ("ParserSpeed", "mr_naive", "mr_opt_w1")):
        r = ratio(a_, b_, "mean")
        v[f"ratio{name}"] = c.tex_dec(r, 1) if r else "---"
    for name, a_, b_ in (("MrMem", "mr_naive", "mr_opt"), ("ParMem", "duck_csv", "duck_parquet")):
        r = ratio(a_, b_, "mem")
        v[f"ratio{name}"] = c.tex_dec(r, 1) if r else "---"
    c.write_vars("profile", v)

    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(recs[0]), lineterminator="\n")
    w.writeheader()
    w.writerows(recs)
    data = buf.getvalue().encode("utf-8")
    c.save_local("profile/runs.csv", data)
    s3 = c.client()
    c.put_bytes(s3, "results/profile/runs.csv", data)
    print(f"\nвсе запуски: s3://{c.BUCKET}/results/profile/runs.csv")

    c.PLOTS.mkdir(parents=True, exist_ok=True)
    titles = [stats[m]["title"] for m in order]
    fig, ax = plt.subplots(1, 2, figsize=(13, 4.8))
    colors = ["#d62728" if "naive" in m else ("#ff7f0e" if m.startswith("duck") else "#1f77b4") for m in order]
    ax[0].barh(titles, [stats[m]["mean"] for m in order], xerr=[stats[m]["sd"] for m in order], color=colors, capsize=4)
    for m in order:
        rs = [r["seconds"] for r in recs if r["method"] == m]
        ax[0].scatter(rs, [stats[m]["title"]] * len(rs), color="black", s=10, zorder=3)
    ax[0].set_xlabel("время, с (столбик — среднее, точки — отдельные запуски)")
    ax[0].set_title("время выполнения")
    ax[0].invert_yaxis()
    ax[0].grid(axis="x", alpha=0.3)
    ax[1].barh(titles, [stats[m]["mem"] for m in order], xerr=[stats[m]["mem_sd"] for m in order], color=colors, capsize=4)
    ax[1].set_xlabel("пик памяти дерева процессов, миб")
    ax[1].set_title("память")
    ax[1].invert_yaxis()
    ax[1].set_yticklabels([])
    ax[1].grid(axis="x", alpha=0.3)
    fig.tight_layout()
    fig.savefig(c.PLOTS / "profile.png", dpi=150)
    print("график сохранён: report/plots/profile.png")
    return 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["run", "summary", "list", "reset"])
    p.add_argument("--method")
    p.add_argument("--attempt", type=int, default=1)
    a = p.parse_args()
    if a.action == "list":
        print(" ".join(METHODS))
        return 0
    if a.action == "reset":
        RUNS.parent.mkdir(parents=True, exist_ok=True)
        RUNS.write_text("")
        return 0
    if a.action == "run":
        return run_one(a.method, a.attempt)
    return summary()


if __name__ == "__main__":
    sys.exit(main())
