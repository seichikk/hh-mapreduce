import argparse
import json
import sys
from collections import defaultdict
from itertools import combinations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from lab import common as c

CAPITALS = ("москва", "санкт-петербург")


def is_junior(exp):
    e = (exp or "").lower().replace(" ", "")
    return "нетопыта" in e or "noexperience" in e or "от1годадо3" in e or "between1and3" in e


def is_capital(area):
    return (area or "").strip().lower() in CAPITALS


def pick_base(combo, counts_prev):
    subs = list(combinations(combo, len(combo) - 1))
    return min(subs, key=lambda s: (-counts_prev.get(s, 0), s))


def analyse(vac, counts, min_pair, min_triple, min_base, min_emp):
    pay = defaultdict(list)
    emp = defaultdict(set)
    jun = defaultdict(int)
    cap = defaultdict(int)
    paid = [v for v in vac if v["salary"] is not None]
    for v in paid:
        for k in c.KS:
            for combo in combinations(v["skills"], k):
                pay[combo].append(v["salary"])
                if v["employer"]:
                    emp[combo].add(v["employer"])
                jun[combo] += is_junior(v["experience"])
                cap[combo] += is_capital(v["area"])
    has_emp = any(v["employer"] for v in paid)
    effects = {2: [], 3: []}
    for k, need in ((2, min_pair), (3, min_triple)):
        for combo, values in pay.items():
            if len(combo) != k or len(values) < need:
                continue
            if has_emp and len(emp[combo]) < min_emp:
                continue
            base = pick_base(combo, counts[k - 1])
            base_values = pay.get(base, [])
            if len(base_values) < min_base:
                continue
            single = min(combo, key=lambda s: (-counts[1].get((s,), 0), s))
            m = c.median(values)
            bm = c.median(base_values)
            sm = c.median(pay.get((single,), []))
            effects[k].append({
                "combo": combo, "base": base, "demand": counts[k].get(combo, 0),
                "base_demand": counts[k - 1].get(base, 0), "n": len(values), "base_n": len(base_values),
                "median": m, "base_median": bm, "delta": m - bm, "pct": 100 * (m / bm - 1),
                "single": single, "single_median": sm, "delta_single": m - sm if sm else None,
                "employers": len(emp[combo]) if has_emp else None,
                "junior": 100 * jun[combo] / len(values), "capital": 100 * cap[combo] / len(values),
                "base_junior": 100 * jun[base] / len(base_values), "base_capital": 100 * cap[base] / len(base_values),
            })
    return paid, effects, has_emp


def fmt(x):
    return f"{x:,.0f}".replace(",", " ")


def print_block(title, items, k):
    print(f"\n{title}")
    print(f"  {'сочетание':<38} {'с з/п':>5} {'база (более частая часть)':<24} {'мед. базы':>9} {'медиана':>9} {'прибавка':>8} {'%':>6} {'джун':>5}")
    for e in items:
        print(f"  {' + '.join(e['combo'])[:38]:<38} {e['n']:>5} {' + '.join(e['base'])[:24]:<24} "
              f"{fmt(e['base_median']):>9} {fmt(e['median']):>9} {fmt_signed(e['delta']):>8} {e['pct']:>+6.1f} {e['junior']:>4.0f}%")


def fmt_signed(x):
    return ("+" if x > 0 else "") + fmt(x)


def tex_rows(items):
    rows = []
    for e in items:
        rows.append([c.tex_skill(" + ".join(e["combo"]), 44), c.tex_int(e["n"]), c.tex_skill(" + ".join(e["base"]), 28),
                     c.tex_int(e["base_median"]), c.tex_int(e["median"]), c.tex_signed(e["delta"]),
                     c.tex_dec(e["pct"], 1), c.tex_dec(e["junior"], 0) + "/" + c.tex_dec(e["base_junior"], 0)])
    return c.table_rows(rows) if rows else "\\multicolumn{8}{c}{нет сочетаний, прошедших порог} \\\\\n"


def plot(effects, top):
    c.PLOTS.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))
    for ax, k, title in ((axes[0], 2, "пары навыков"), (axes[1], 3, "тройки навыков")):
        items = sorted(effects[k], key=lambda e: e["delta"])
        sel = items[:top] + items[-top:] if len(items) > 2 * top else items
        labels = [" + ".join(e["combo"])[:42] for e in sel]
        vals = [e["delta"] / 1000 for e in sel]
        ax.barh(range(len(sel)), vals, color=["#d62728" if v < 0 else "#2ca02c" for v in vals])
        ax.set_yticks(range(len(sel)))
        ax.set_yticklabels(labels, fontsize=7)
        ax.axvline(0, color="black", lw=0.8)
        ax.set_xlabel("разница медиан с базой, тыс. руб. на руки")
        ax.set_title(title)
        ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    fig.savefig(c.PLOTS / "salary.png", dpi=150)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--min-pair", type=int, default=30)
    p.add_argument("--min-triple", type=int, default=20)
    p.add_argument("--min-base", type=int, default=30)
    p.add_argument("--min-employers", type=int, default=5)
    p.add_argument("--top", type=int, default=10)
    a = p.parse_args()
    s3 = c.client()
    vac = c.load_vacancies(s3)
    counts = c.load_counts(s3)
    min_pair, min_triple = a.min_pair, a.min_triple
    paid, effects, has_emp = analyse(vac, counts, min_pair, min_triple, a.min_base, a.min_employers)
    while (len(effects[2]) < 2 * a.top or len(effects[3]) < 2 * a.top) and min_triple > 10:
        min_pair = max(15, min_pair - 5)
        min_triple = max(10, min_triple - 5)
        paid, effects, has_emp = analyse(vac, counts, min_pair, min_triple, a.min_base, a.min_employers)
    all_pay = [v["salary"] for v in paid]
    overall = c.median(all_pay)
    print(f"вакансий варианта: {len(vac)}, из них с зарплатой в рублях: {len(paid)} ({100 * len(paid) / max(len(vac), 1):.1f}%)")
    print(f"зарплата: середина вилки или одна известная граница, только RUR, gross переведён в «на руки» (x{c.NDFL}), "
          f"оставлены значения {fmt(c.SALARY_MIN)}..{fmt(c.SALARY_MAX)} руб.")
    print(f"медиана по варианту: {fmt(overall)} руб., квартили {fmt(c.quantile(all_pay, .25))} и {fmt(c.quantile(all_pay, .75))} руб.")
    print(f"прибавка пары = медиана(пара) - медиана(более частый навык пары); тройки = медиана(тройка) - медиана(самая частая пара внутри)")
    print(f"пороги: пара >= {min_pair} вакансий с з/п, тройка >= {min_triple}, база >= {a.min_base}"
          + (f", работодателей >= {a.min_employers}" if has_emp else ""))
    print(f"прошли порог: пар {len(effects[2])}, троек {len(effects[3])}")
    res = {}
    for k, name in ((2, "пары"), (3, "тройки")):
        items = sorted(effects[k], key=lambda e: (-e["delta"], e["combo"]))
        up = [e for e in items if e["delta"] > 0][: a.top]
        down = [e for e in reversed(items) if e["delta"] < 0][: a.top]
        res[k] = (up, down)
        print_block(f"{name}, которые сильнее всего ПОВЫШАЮТ медиану относительно базы:", up, k)
        print_block(f"{name}, которые сильнее всего ПОНИЖАЮТ медиану относительно базы:", down, k)
    singles = []
    for (skill,), n in sorted(counts[1].items(), key=lambda it: -it[1])[:15]:
        values = [v["salary"] for v in paid if skill in v["skills"]]
        if values:
            singles.append([c.tex_skill(skill, 30), c.tex_int(n), c.tex_int(len(values)), c.tex_int(c.median(values)),
                            c.tex_signed(c.median(values) - overall)])
    c.write_out("salary_singles.tex", c.table_rows(singles))
    c.write_out("salary_pairs_up.tex", tex_rows(res[2][0]))
    c.write_out("salary_pairs_down.tex", tex_rows(res[2][1]))
    c.write_out("salary_triples_up.tex", tex_rows(res[3][0]))
    c.write_out("salary_triples_down.tex", tex_rows(res[3][1]))

    def name_of(lst, i=0):
        return c.tex_skill(" + ".join(lst[i]["combo"]), 60) if len(lst) > i else "---"

    def val(lst, key, i=0):
        return lst[i][key] if len(lst) > i else None

    def avg(lst, key):
        return sum(e[key] for e in lst) / len(lst) if lst else None

    c.write_vars("salary", {
        "salN": c.tex_int(len(paid)), "salShare": c.tex_dec(100 * len(paid) / max(len(vac), 1), 1),
        "salMedian": c.tex_int(overall), "salQone": c.tex_int(c.quantile(all_pay, .25)),
        "salQthree": c.tex_int(c.quantile(all_pay, .75)),
        "minPair": str(min_pair), "minTriple": str(min_triple), "minBase": str(a.min_base),
        "minEmp": str(a.min_employers) if has_emp else "---",
        "nPairEff": c.tex_int(len(effects[2])), "nTripleEff": c.tex_int(len(effects[3])),
        "pairUpName": name_of(res[2][0]), "pairUpDelta": c.tex_signed(val(res[2][0], "delta")),
        "pairUpBase": c.tex_skill(" + ".join(res[2][0][0]["base"])) if res[2][0] else "---",
        "pairDownName": name_of(res[2][1]), "pairDownDelta": c.tex_signed(val(res[2][1], "delta")),
        "pairDownBase": c.tex_skill(" + ".join(res[2][1][0]["base"])) if res[2][1] else "---",
        "tripleUpName": name_of(res[3][0]), "tripleUpDelta": c.tex_signed(val(res[3][0], "delta")),
        "tripleDownName": name_of(res[3][1]), "tripleDownDelta": c.tex_signed(val(res[3][1], "delta")),
        "upJunior": c.tex_dec(avg(res[2][0] + res[3][0], "junior"), 0),
        "downJunior": c.tex_dec(avg(res[2][1] + res[3][1], "junior"), 0),
        "upCapital": c.tex_dec(avg(res[2][0] + res[3][0], "capital"), 0),
        "downCapital": c.tex_dec(avg(res[2][1] + res[3][1], "capital"), 0),
    })
    up_j = avg(res[2][0] + res[3][0], "junior")
    down_j = avg(res[2][1] + res[3][1], "junior")
    up_c = avg(res[2][0] + res[3][0], "capital")
    down_c = avg(res[2][1] + res[3][1], "capital")
    print()
    if up_j is not None and down_j is not None:
        print(f"наблюдение: в повышающих сочетаниях вакансий с опытом до 3 лет в среднем {up_j:.0f}%, в понижающих {down_j:.0f}%")
    if up_c is not None and down_c is not None:
        print(f"наблюдение: доля москвы и петербурга в повышающих сочетаниях {up_c:.0f}%, в понижающих {down_c:.0f}%")
    plot(effects, a.top)
    print("график сохранён: report/plots/salary.png")
    out = {k: [{**e, "combo": list(e["combo"]), "base": list(e["base"])} for e in effects[k]] for k in (2, 3)}
    data = (json.dumps({"overall_median": overall, "n": len(paid), "effects": out}, ensure_ascii=False, indent=1) + "\n").encode()
    c.save_local("salary/effects.json", data)
    c.put_bytes(s3, "results/salary/effects.json", data, "application/json")
    print(f"все сочетания с прибавками: s3://{c.BUCKET}/results/salary/effects.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
