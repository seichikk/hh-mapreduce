import json
import math
import sys
from collections import Counter

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from lab import common as c


def main():
    s3 = c.client()
    vac = c.load_vacancies(s3)
    counts = c.load_counts(s3)
    summary = json.loads(c.get_bytes(s3, "results/mapreduce/summary.json"))
    sizes = Counter(len(v["skills"]) for v in vac)
    total = len(vac)
    print(f"вакансий варианта: {total}")
    print("сколько навыков в одной вакансии и сколько сочетаний она даёт:")
    print(f"  {'n':>3} {'вакансий':>9} {'доля':>7} {'C(n,1)':>8} {'C(n,2)':>8} {'C(n,3)':>8}   вклад в пары / тройки")
    rows = []
    acc = [0, 0, 0]
    for n in sorted(sizes):
        m = sizes[n]
        part = [m * math.comb(n, k) for k in c.KS]
        for i in range(3):
            acc[i] += part[i]
        rows.append((n, m, part))
    sums = [sum(counts[k].values()) for k in c.KS]
    for n, m, part in rows:
        if m * 1000 >= total or n <= 15:
            print(f"  {n:>3} {m:>9} {100 * m / total:>6.1f}% {math.comb(n, 1):>8} {math.comb(n, 2):>8} {math.comb(n, 3):>8}"
                  f"   {100 * part[1] / max(sums[1], 1):5.1f}% / {100 * part[2] / max(sums[2], 1):5.1f}%")
    big = [r for r in rows if r[0] > 15]
    if big:
        print(f"  ... ещё {len(big)} значений n > 15: {sum(r[1] for r in big)} вакансий, "
              f"но {100 * sum(r[2][2] for r in big) / max(sums[2], 1):.1f}% всех троек")
    print()
    print("рост по размеру сочетания k:")
    print(f"  {'k':>2} {'уникальных':>11} {'сумма частот':>13} {'sum C(n,k)':>11} {'в shuffle (opt)':>16}")
    for k in c.KS:
        print(f"  {k:>2} {len(counts[k]):>11} {sums[k - 1]:>13} {acc[k - 1]:>11} {'':>16}")
    print(f"всего записей в shuffle после combiner: {summary['shuffled']}, без combiner: {sum(summary['emitted'])}")
    avg = sum(len(v["skills"]) for v in vac) / max(total, 1)
    nmax = max(sizes) if sizes else 0
    print(f"в среднем {avg:.2f} навыка на вакансию, максимум {nmax}")
    print(f"вакансия с {nmax} навыками одна даёт {math.comb(nmax, 2)} пар и {math.comb(nmax, 3)} троек")

    tex_rows = []
    for n, m, part in rows:
        if n <= 12:
            tex_rows.append([n, c.tex_int(m), c.tex_dec(100 * m / total, 1), c.tex_int(math.comb(n, 2)),
                             c.tex_int(math.comb(n, 3)), c.tex_int(part[1]), c.tex_int(part[2])])
    if any(r[0] > 12 for r in rows):
        tail = [r for r in rows if r[0] > 12]
        tex_rows.append([f"$>12$", c.tex_int(sum(r[1] for r in tail)), c.tex_dec(100 * sum(r[1] for r in tail) / total, 1),
                         "", "", c.tex_int(sum(r[2][1] for r in tail)), c.tex_int(sum(r[2][2] for r in tail))])
    c.write_out("growth_table.tex", c.table_rows(tex_rows))
    k_rows = [[k, c.tex_int(len(counts[k])), c.tex_int(sums[k - 1]), c.tex_int(acc[k - 1])] for k in c.KS]
    c.write_out("growth_k.tex", c.table_rows(k_rows))
    heavy = sum(r[2][2] for r in rows if r[0] >= 10)
    c.write_vars("growth", {
        "avgSkills": c.tex_dec(avg, 2), "maxSkills": str(nmax),
        "maxPairs": c.tex_int(math.comb(nmax, 2)), "maxTriples": c.tex_int(math.comb(nmax, 3)),
        "uniqOne": c.tex_int(len(counts[1])), "uniqTwo": c.tex_int(len(counts[2])), "uniqThree": c.tex_int(len(counts[3])),
        "sumOne": c.tex_int(sums[0]), "sumTwo": c.tex_int(sums[1]), "sumThree": c.tex_int(sums[2]),
        "heavyShare": c.tex_dec(100 * heavy / max(sums[2], 1), 1),
        "heavyVacShare": c.tex_dec(100 * sum(r[1] for r in rows if r[0] >= 10) / max(total, 1), 1),
        "shuffledOpt": c.tex_int(summary["shuffled"]), "emittedAll": c.tex_int(sum(summary["emitted"])),
    })

    c.PLOTS.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(1, 2, figsize=(11, 4))
    ns = sorted(sizes)
    ax[0].bar(ns, [sizes[n] for n in ns], color="#4c78a8")
    ax[0].set_xlabel("число навыков в вакансии, n")
    ax[0].set_ylabel("вакансий")
    ax[0].set_title("распределение числа навыков")
    ax[1].plot(list(c.KS), [len(counts[k]) for k in c.KS], "o-", label="уникальных сочетаний")
    ax[1].plot(list(c.KS), sums, "s-", label="сумма частот = Σ C(n, k)")
    ax[1].set_yscale("log")
    ax[1].set_xticks(list(c.KS))
    ax[1].set_xlabel("размер сочетания k")
    ax[1].set_ylabel("штук (логарифмическая шкала)")
    ax[1].set_title("рост числа сочетаний")
    ax[1].legend()
    for a_ in ax:
        a_.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(c.PLOTS / "growth.png", dpi=150)
    print("график сохранён: report/plots/growth.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
