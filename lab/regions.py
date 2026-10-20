import argparse
import csv
import io
import sys
from collections import Counter
from itertools import combinations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from lab import common as c
from lab.salary import is_junior

TOP = {1: 7, 2: 5, 3: 5}


def is_remote(schedule):
    s = (schedule or "").lower()
    return "удал" in s or "remote" in s


def pick_regions(vac, given):
    if given:
        return given
    cnt = Counter(v["area"] for v in vac)
    chosen = [r for r in ("Москва", "Санкт-Петербург") if cnt[r] > 0]
    for r, _ in cnt.most_common():
        if len(chosen) >= 3:
            break
        if r not in chosen and r != "не указан":
            chosen.append(r)
    return chosen


def fmt(x):
    return "---" if x is None else f"{x:,.0f}".replace(",", " ")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--regions", nargs="*", default=[])
    p.add_argument("--min-salary-n", type=int, default=5)
    a = p.parse_args()
    s3 = c.client()
    vac = c.load_vacancies(s3)
    regions = pick_regions(vac, a.regions)
    area_counts = Counter(v["area"] for v in vac)
    print("топ-8 регионов по числу вакансий варианта:")
    for r, n in area_counts.most_common(8):
        print(f"  {r:<28} {n:>6}  ({100 * n / len(vac):.1f}%)")
    print("для сравнения беру: " + ", ".join(regions) + " (две столицы и самый крупный регион после них)")
    profile = []
    combos = {}
    for r in regions:
        rv = [v for v in vac if v["area"] == r]
        pays = [v["salary"] for v in rv if v["salary"] is not None]
        ws = [v for v in rv if v["skills"]]
        profile.append({
            "region": r, "vacancies": len(rv), "share": 100 * len(rv) / len(vac), "salary_n": len(pays),
            "median": c.median(pays), "q1": c.quantile(pays, .25), "q3": c.quantile(pays, .75),
            "with_skills": 100 * len(ws) / max(len(rv), 1),
            "avg_skills": sum(len(v["skills"]) for v in rv) / max(len(rv), 1),
            "remote": 100 * sum(is_remote(v["schedule"]) for v in rv) / max(len(rv), 1),
            "junior": 100 * sum(is_junior(v["experience"]) for v in rv) / max(len(rv), 1),
            "employers": len({v["employer"] for v in rv if v["employer"]}),
        })
        cnt = {k: Counter() for k in c.KS}
        pay = {k: {} for k in c.KS}
        for v in rv:
            for k in c.KS:
                for combo in combinations(v["skills"], k):
                    cnt[k][combo] += 1
                    if v["salary"] is not None:
                        pay[k].setdefault(combo, []).append(v["salary"])
        combos[r] = (cnt, pay, len(ws))
    print()
    print("таблица 1. профиль регионов")
    head = f"  {'регион':<18} {'вакансий':>8} {'доля':>6} {'с з/п':>6} {'медиана':>9} {'q1':>9} {'q3':>9} {'с навыками':>10} {'навыков':>8} {'удалёнка':>8} {'опыт<3л':>8} {'работод.':>8}"
    print(head)
    for pr in profile:
        print(f"  {pr['region'][:18]:<18} {pr['vacancies']:>8} {pr['share']:>5.1f}% {pr['salary_n']:>6} {fmt(pr['median']):>9} "
              f"{fmt(pr['q1']):>9} {fmt(pr['q3']):>9} {pr['with_skills']:>9.1f}% {pr['avg_skills']:>8.2f} {pr['remote']:>7.1f}% "
              f"{pr['junior']:>7.1f}% {pr['employers']:>8}")
    print()
    print("таблица 2. самые частые навыки, пары и тройки в каждом регионе")
    print("  (доля — от вакансий региона с навыками; медиана — по вакансиям сочетания с зарплатой, если их >= "
          f"{a.min_salary_n})")
    rows2 = []
    csv_buf = io.StringIO()
    w = csv.writer(csv_buf, lineterminator="\n")
    w.writerow(["region", "k", "rank", "skills", "vacancies", "share_pct", "salary_n", "median"])
    for r in regions:
        cnt, pay, nws = combos[r]
        print(f"  {r}:")
        for k in c.KS:
            items = sorted(cnt[k].items(), key=lambda it: (-it[1], it[0]))[: TOP[k]]
            for rank, (combo, n) in enumerate(items, 1):
                vals = pay[k].get(combo, [])
                med = c.median(vals) if len(vals) >= a.min_salary_n else None
                share = 100 * n / max(nws, 1)
                print(f"    k={k} #{rank}: {' + '.join(combo)[:60]:<60} {n:>5} {share:>5.1f}%  медиана {fmt(med)} (n={len(vals)})")
                w.writerow([r, k, rank, " + ".join(combo), n, round(share, 2), len(vals), med if med is not None else ""])
                rows2.append([c.tex_escape(r) if rank == 1 and k == 1 else "", k, c.tex_skill(" + ".join(combo), 44),
                              c.tex_int(n), c.tex_dec(share, 1), c.tex_int(med) if med is not None else "---"])
        rows2.append(["\\midrule"])
    rows2 = rows2[:-1]
    print()
    print("что отличает регионы: навыки, доля которых в регионе заметно выше, чем в двух других вместе")
    lifts = {}
    for r in regions:
        cnt_r, _, nws_r = combos[r]
        others = [o for o in regions if o != r]
        cnt_o = Counter()
        nws_o = 0
        for o in others:
            cnt_o.update(combos[o][0][1])
            nws_o += combos[o][2]
        cand = []
        for combo, n in cnt_r[1].items():
            if n < 15:
                continue
            sr = n / max(nws_r, 1)
            so = cnt_o.get(combo, 0) / max(nws_o, 1)
            if so > 0:
                cand.append((sr / so, combo[0], 100 * sr, 100 * so))
        cand.sort(reverse=True)
        lifts[r] = cand[:3]
        txt = "; ".join(f"{s} {a_:.1f}% против {b:.1f}% (x{l:.2f})" for l, s, a_, b in cand[:3]) or "нет навыков с >= 15 упоминаниями"
        print(f"  {r}: {txt}")
    profile_rows = [[c.tex_escape(pr["region"]), c.tex_int(pr["vacancies"]), c.tex_dec(pr["share"], 1), c.tex_int(pr["salary_n"]),
                     c.tex_int(pr["median"]), c.tex_int(pr["q1"]) + "--" + c.tex_int(pr["q3"]),
                     c.tex_dec(pr["with_skills"], 0), c.tex_dec(pr["avg_skills"], 1), c.tex_dec(pr["remote"], 0),
                     c.tex_dec(pr["junior"], 0)] for pr in profile]
    c.write_out("regions_profile.tex", c.table_rows(profile_rows))
    c.write_out("regions_combos.tex", "\n".join(" & ".join(str(x) for x in r) + ("" if r == ["\\midrule"] else " \\\\") for r in rows2) + "\n")
    lift_rows = []
    for r in regions:
        for l, s, a_, b in lifts[r]:
            lift_rows.append([c.tex_escape(r), c.tex_skill(s, 34), c.tex_dec(a_, 1), c.tex_dec(b, 1), c.tex_dec(l, 2)])
    c.write_out("regions_lift.tex", c.table_rows(lift_rows) if lift_rows else "\\multicolumn{5}{c}{---} \\\\\n")
    best = max(profile, key=lambda pr: pr["median"] or 0)
    worst = min(profile, key=lambda pr: pr["median"] or 10 ** 9)
    remote = max(profile, key=lambda pr: pr["remote"])
    vars_ = {"regionsList": c.tex_escape(", ".join(regions)),
             "regBest": c.tex_escape(best["region"]), "regBestMed": c.tex_int(best["median"]),
             "regWorst": c.tex_escape(worst["region"]), "regWorstMed": c.tex_int(worst["median"]),
             "regGapPct": c.tex_dec(100 * (best["median"] / worst["median"] - 1), 0) if best["median"] and worst["median"] else "---",
             "regRemote": c.tex_escape(remote["region"]), "regRemotePct": c.tex_dec(remote["remote"], 0)}
    for i, pr in enumerate(profile):
        tag = "ABC"[i]
        vars_[f"reg{tag}"] = c.tex_escape(pr["region"])
        vars_[f"reg{tag}N"] = c.tex_int(pr["vacancies"])
        vars_[f"reg{tag}Med"] = c.tex_int(pr["median"])
        vars_[f"reg{tag}Remote"] = c.tex_dec(pr["remote"], 0)
        vars_[f"reg{tag}Junior"] = c.tex_dec(pr["junior"], 0)
        vars_[f"reg{tag}Lift"] = c.tex_skill(lifts[pr["region"]][0][1]) if lifts[pr["region"]] else "---"
    c.write_vars("regions", vars_)
    data = csv_buf.getvalue().encode("utf-8")
    c.save_local("regions/top_combos.csv", data)
    c.put_bytes(s3, "results/regions/top_combos.csv", data)
    pbuf = io.StringIO()
    pw = csv.DictWriter(pbuf, fieldnames=list(profile[0]), lineterminator="\n")
    pw.writeheader()
    pw.writerows(profile)
    c.save_local("regions/profile.csv", pbuf.getvalue().encode("utf-8"))
    c.put_bytes(s3, "results/regions/profile.csv", pbuf.getvalue().encode("utf-8"))
    print(f"\nтаблицы сохранены: s3://{c.BUCKET}/results/regions/profile.csv и top_combos.csv")

    c.PLOTS.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.2))
    names = [pr["region"] for pr in profile]
    med = [(pr["median"] or 0) / 1000 for pr in profile]
    lo = [((pr["median"] or 0) - (pr["q1"] or 0)) / 1000 for pr in profile]
    hi = [((pr["q3"] or 0) - (pr["median"] or 0)) / 1000 for pr in profile]
    ax[0].bar(names, med, yerr=[lo, hi], capsize=6, color=["#4c78a8", "#f58518", "#54a24b"])
    ax[0].set_ylabel("тыс. руб. на руки")
    ax[0].set_title("медиана зарплаты и межквартильный размах")
    ax[0].grid(axis="y", alpha=0.3)
    top_sk = [s for (s,), _ in sorted(Counter({k: n for r in regions for k, n in combos[r][0][1].items()}).items(),
                                      key=lambda it: -it[1])[:12]]
    width = 0.27
    for i, r in enumerate(regions):
        cnt, _, nws = combos[r]
        ax[1].barh([j + i * width for j in range(len(top_sk))], [100 * cnt[1].get((s,), 0) / max(nws, 1) for s in top_sk],
                   height=width, label=r)
    ax[1].set_yticks([j + width for j in range(len(top_sk))])
    ax[1].set_yticklabels(top_sk, fontsize=8)
    ax[1].invert_yaxis()
    ax[1].set_xlabel("доля вакансий региона с навыками, %")
    ax[1].set_title("востребованность навыков")
    ax[1].legend(fontsize=8)
    ax[1].grid(axis="x", alpha=0.3)
    fig.tight_layout()
    fig.savefig(c.PLOTS / "regions.png", dpi=150)
    print("график сохранён: report/plots/regions.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
