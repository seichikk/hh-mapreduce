import argparse
import json
import sys
from collections import Counter

from botocore.exceptions import ClientError

from lab import common as c

NAMES = {
    "mapreduce": "mapreduce (основной)",
    "duckdb": "duckdb, csv",
    "mapreduce_naive": "mapreduce, наивный",
    "mapreduce_failtest": "mapreduce с отказом маппера",
    "duckdb_parquet": "duckdb, parquet",
}


def exists(s3, key):
    try:
        s3.head_object(Bucket=c.BUCKET, Key=key)
        return True
    except ClientError:
        return False


def top1(counts):
    if not counts:
        return None
    return min(counts.items(), key=lambda item: (-item[1], item[0]))


def ids_of(s3, tag):
    if tag.startswith("duckdb"):
        return Counter(line for line in c.get_bytes(s3, f"results/{tag}/vacancy_ids.txt").decode("utf-8").splitlines())
    return Counter(v["vacancy_id"] for v in c.load_vacancies(s3, tag))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ref", default="mapreduce")
    a = p.parse_args()
    s3 = c.client()
    ref = c.load_counts(s3, a.ref)
    ref_ids = ids_of(s3, a.ref)
    others = [t for t in NAMES if t != a.ref and exists(s3, f"results/{t}/k3.csv")]
    print(f"эталон: results/{a.ref}/ ; сравниваю с: " + ", ".join(f"results/{t}/" for t in others))
    rows_tex = []
    all_ok = True
    report = {}
    for k in c.KS:
        t = top1(ref[k])
        rows_tex.append([f"k={k}", NAMES[a.ref], c.tex_int(len(ref[k])), c.tex_int(sum(ref[k].values())),
                         c.tex_skill(" + ".join(t[0]), 46) if t else "---", c.tex_int(t[1]) if t else "---", "эталон"])
    for tag in others:
        other = c.load_counts(s3, tag)
        other_ids = ids_of(s3, tag)
        same_ids = other_ids == ref_ids
        print()
        print(f"--- {NAMES[tag]} (results/{tag}/) против {NAMES[a.ref]}")
        print(f"отобранные вакансии: {sum(ref_ids.values())} и {sum(other_ids.values())}, "
              f"набор id совпадает: {'да' if same_ids else 'НЕТ'}")
        if not same_ids:
            only_ref = ref_ids - other_ids
            only_other = other_ids - ref_ids
            print(f"  только в эталоне: {sum(only_ref.values())}, например {list(only_ref)[:5]}")
            print(f"  только в {tag}: {sum(only_other.values())}, например {list(only_other)[:5]}")
        tag_ok = same_ids
        rep = {}
        for k in c.KS:
            a_keys = set(ref[k])
            b_keys = set(other[k])
            only_a = a_keys - b_keys
            only_b = b_keys - a_keys
            diff = [key for key in a_keys & b_keys if ref[k][key] != other[k][key]]
            ok = not only_a and not only_b and not diff
            tag_ok = tag_ok and ok
            print(f"k={k}: ключей {len(a_keys)}/{len(b_keys)}, сумма частот {sum(ref[k].values())}/{sum(other[k].values())}, "
                  f"только в эталоне {len(only_a)}, только во втором {len(only_b)}, разные частоты {len(diff)} -> "
                  + ("совпадает" if ok else "РАСХОЖДЕНИЕ"))
            for key in sorted(diff)[:5]:
                print(f"    {' + '.join(key)}: {ref[k][key]} против {other[k][key]}")
            for key in sorted(only_a)[:3]:
                print(f"    только в эталоне: {' + '.join(key)} = {ref[k][key]}")
            for key in sorted(only_b)[:3]:
                print(f"    только во втором: {' + '.join(key)} = {other[k][key]}")
            t = top1(other[k])
            rows_tex.append([f"k={k}", NAMES[tag], c.tex_int(len(other[k])), c.tex_int(sum(other[k].values())),
                             c.tex_skill(" + ".join(t[0]), 46) if t else "---", c.tex_int(t[1]) if t else "---",
                             "совпало" if ok else "\\textbf{расхождение}"])
            rep[k] = {"only_ref": len(only_a), "only_other": len(only_b), "diff": len(diff)}
        print(f"итог для {NAMES[tag]}: " + ("ВСЕ ЧИСЛА СОВПАЛИ" if tag_ok else "ЕСТЬ РАСХОЖДЕНИЯ"))
        all_ok = all_ok and tag_ok
        report[tag] = {"ok": tag_ok, "same_ids": same_ids, "per_k": rep}
    rows_tex.sort(key=lambda r: r[0])
    c.write_out("verify_table.tex", c.table_rows(rows_tex))
    c.save_json_local("verify.json", {"ref": a.ref, "ok": all_ok, "tags": report})
    summary = json.loads(c.get_bytes(s3, f"results/{a.ref}/summary.json"))
    c.write_vars("verify", {
        "verifyOk": "полностью совпали" if all_ok else "\\textbf{не совпали}",
        "verifyTags": str(len(others) + 1),
        "nVacancies": c.tex_int(summary["vacancies"]),
        "nWithSkills": c.tex_int(summary["with_skills"]),
        "nWithSalary": c.tex_int(summary["with_salary"]),
        "nRows": c.tex_int(summary["rows_scanned"]),
    })
    print()
    print("ИТОГ: " + ("результаты всех способов совпали полностью" if all_ok else "есть расхождения, смотри выше"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
