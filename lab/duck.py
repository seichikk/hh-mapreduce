import argparse
import json
import sys
import time
from urllib.parse import urlparse

import duckdb

from lab import common as c

VARIANT_SQL = r"""
    role = 'Программист, разработчик'
    AND regexp_matches(lower(name), 'c#|с#|\.net|dotnet|c sharp|csharp|си шарп')
"""

SKILLS_SQL = r"""
    list_sort(list_distinct(list_filter(
        list_transform(string_split(coalesce(key_skills, ''), ';'),
                       s -> lower(trim(s, ' ' || chr(9) || chr(13) || chr(10)))),
        s -> s <> '')))
"""


def connect(threads, memory):
    con = duckdb.connect(config={"threads": threads, "memory_limit": memory})
    host = urlparse(c.ENDPOINT).netloc
    try:
        try:
            con.execute("LOAD httpfs")
        except duckdb.Error:
            con.execute("INSTALL httpfs")
            con.execute("LOAD httpfs")
        con.execute(f"""
            CREATE SECRET rustfs (TYPE s3, KEY_ID '{c.ACCESS_KEY}', SECRET '{c.SECRET_KEY}',
                                  ENDPOINT '{host}', URL_STYLE 'path', USE_SSL false, REGION 'us-east-1')
        """)
        how = "httpfs"
    except duckdb.Error:
        import s3fs
        fs = s3fs.S3FileSystem(key=c.ACCESS_KEY, secret=c.SECRET_KEY, client_kwargs={"endpoint_url": c.ENDPOINT})
        con.register_filesystem(fs)
        how = "fsspec"
    return con, how


def csv_source(strict=True):
    opts = "header=true, all_varchar=true, delim=',', quote='\"', escape='\"', max_line_size=67108864"
    if not strict:
        opts += ", strict_mode=false"
    return f"read_csv('s3://{c.BUCKET}/{c.KEY}', {opts})"


def parquet_source():
    return f"read_parquet('s3://{c.BUCKET}/{c.PARQUET_KEY}')"


def load_variant(con, source):
    def build(src):
        con.execute("DROP TABLE IF EXISTS vac")
        con.execute(f"""
            CREATE TABLE vac AS
            SELECT row_number() OVER () AS rid,
                   coalesce(vacancy_id, '') AS vacancy_id,
                   {SKILLS_SQL} AS skills
            FROM {src}
            WHERE {VARIANT_SQL}
        """)
    if source == "parquet":
        build(parquet_source())
        return "parquet"
    try:
        build(csv_source(True))
        return "csv"
    except duckdb.InvalidInputException as e:
        print("строгий разбор csv не прошёл: " + str(e).splitlines()[0])
        print("повторяю с strict_mode=false")
        build(csv_source(False))
        return "csv (strict_mode=false)"


KEEP = ("vacancy_id", "id", "name", "role", "area", "key_skills", "salary_from", "salary_to", "currency", "gross",
        "employer", "employer_name", "company", "employer_id", "experience", "schedule", "published_at")

COUNT_SQL = {
    1: """SELECT skill AS skill_1, count(*) AS cnt FROM s GROUP BY ALL""",
    2: """SELECT a.skill AS skill_1, b.skill AS skill_2, count(*) AS cnt
          FROM s a JOIN s b ON a.rid = b.rid AND a.skill < b.skill GROUP BY ALL""",
    3: """SELECT a.skill AS skill_1, b.skill AS skill_2, c.skill AS skill_3, count(*) AS cnt
          FROM s a JOIN s b ON a.rid = b.rid AND a.skill < b.skill
                   JOIN s c ON a.rid = c.rid AND b.skill < c.skill GROUP BY ALL""",
}


def run(source, threads, memory):
    t0 = time.perf_counter()
    con, how = connect(threads, memory)
    parsed = load_variant(con, source)
    t_load = time.perf_counter() - t0
    con.execute("CREATE TABLE s AS SELECT rid, unnest(skills) AS skill FROM vac")
    counts = {}
    for k in c.KS:
        rows = con.execute(COUNT_SQL[k]).fetchall()
        counts[k] = {tuple(r[:-1]): r[-1] for r in rows}
    n, with_skills = con.execute("SELECT count(*), count(*) FILTER (WHERE len(skills) > 0) FROM vac").fetchone()
    combos = [con.execute(f"SELECT coalesce(sum(CASE WHEN len(skills) >= {k} THEN {comb_sql(k)} ELSE 0 END), 0)::BIGINT "
                          f"FROM vac").fetchone()[0] for k in c.KS]
    ids = [r[0] for r in con.execute("SELECT vacancy_id FROM vac ORDER BY rid").fetchall()]
    total = time.perf_counter() - t0
    sums = [sum(counts[k].values()) for k in c.KS]
    summary = {"source": parsed, "access": how, "threads": threads, "memory_limit": memory,
               "vacancies": n, "with_skills": with_skills, "unique": [len(counts[k]) for k in c.KS],
               "sums": sums, "combinations": [int(x) for x in combos],
               "seconds_total": round(total, 3), "seconds_load": round(t_load, 3)}
    print(f"доступ к s3 из duckdb: {how}, источник: {parsed}, потоков {threads}, лимит памяти {memory}")
    print(f"вакансий варианта: {n} (с навыками {with_skills})")
    for k in c.KS:
        top = min(counts[k].items(), key=lambda item: (-item[1], item[0]), default=None)
        top_s = " + ".join(top[0]) + f" = {top[1]}" if top else "---"
        print(f"k={k}: уникальных сочетаний {len(counts[k])}, сумма частот {sums[k - 1]}; топ: {top_s}")
    print(f"время: всего {total:.2f} с, из них чтение и фильтр {t_load:.2f} с")
    con.close()
    return counts, ids, summary


def comb_sql(k):
    n = "len(skills)"
    if k == 1:
        return n
    if k == 2:
        return f"{n} * ({n} - 1) // 2"
    return f"{n} * ({n} - 1) * ({n} - 2) // 6"


def save(tag, counts, ids, summary, upload):
    s3 = c.client() if upload else None
    files = {f"k{k}.csv": c.counts_to_csv(counts[k], k) for k in c.KS}
    files["vacancy_ids.txt"] = ("\n".join(ids) + "\n").encode("utf-8")
    files["summary.json"] = (json.dumps(summary, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    for name, data in files.items():
        c.save_local(f"{tag}/{name}", data)
        if upload:
            key = f"results/{tag}/{name}"
            c.put_bytes(s3, key, data)
            ok = c.sha256_bytes(c.get_bytes(s3, key)) == c.sha256_bytes(data)
            print(f"  сохранено s3://{c.BUCKET}/{key} ({len(data)} байт), sha256 после чтения обратно совпал: {'да' if ok else 'НЕТ'}")


def to_parquet(threads, memory):
    from lab.storage import header_from_s3
    s3 = c.client()
    fields, _ = header_from_s3(s3)
    keep = [f for f in fields if f in KEEP]
    dropped = [f for f in fields if f not in KEEP]
    print("в parquet беру колонки: " + ", ".join(keep))
    print("отбрасываю (анализу не нужны): " + (", ".join(dropped) if dropped else "ничего"))
    con, how = connect(threads, memory)
    con.execute("SET preserve_insertion_order = false")
    cols = ", ".join(f'"{f}"' for f in keep)
    t0 = time.perf_counter()
    for strict in (True, False):
        try:
            con.execute(f"COPY (SELECT {cols} FROM {csv_source(strict)}) TO 's3://{c.BUCKET}/{c.PARQUET_KEY}' "
                        f"(FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 100000)")
            break
        except duckdb.InvalidInputException:
            if not strict:
                raise
    dt = time.perf_counter() - t0
    size = s3.head_object(Bucket=c.BUCKET, Key=c.PARQUET_KEY)["ContentLength"]
    csv_size = s3.head_object(Bucket=c.BUCKET, Key=c.KEY)["ContentLength"]
    print(f"csv -> parquet через duckdb ({how}) за {dt:.1f} с")
    print(f"s3://{c.BUCKET}/{c.KEY}: {csv_size} байт ({c.human_bytes(csv_size)})")
    print(f"s3://{c.BUCKET}/{c.PARQUET_KEY}: {size} байт ({c.human_bytes(size)}), в {csv_size / size:.1f} раза меньше")
    c.save_json_local("parquet.json", {"csv_bytes": csv_size, "parquet_bytes": size, "seconds": round(dt, 2)})
    c.write_vars("parquet", {"parquetHuman": c.tex_escape(c.human_bytes(size)), "csvHuman": c.tex_escape(c.human_bytes(csv_size)),
                             "parquetRatio": c.tex_dec(csv_size / size, 1), "parquetSeconds": c.tex_dec(dt, 1),
                             "parquetCols": c.tex_escape(", ".join(keep))})
    con.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", choices=["csv", "parquet"], default="csv")
    p.add_argument("--threads", type=int, default=4)
    p.add_argument("--memory", default="1500MB")
    p.add_argument("--tag", default="duckdb")
    p.add_argument("--no-upload", action="store_true")
    p.add_argument("--to-parquet", action="store_true")
    p.add_argument("--explain", action="store_true")
    a = p.parse_args()
    if a.to_parquet:
        to_parquet(a.threads, a.memory)
        return 0
    if a.explain:
        con, how = connect(a.threads, a.memory)
        src = csv_source(True) if a.source == "csv" else parquet_source()
        plan = con.execute(f"EXPLAIN ANALYZE SELECT count(*) FROM {src} WHERE {VARIANT_SQL}").fetchall()
        print(plan[0][1])
        return 0
    counts, ids, summary = run(a.source, a.threads, a.memory)
    if summary["sums"] != summary["combinations"]:
        print("сумма частот не совпала с числом сочетаний")
        return 1
    save(a.tag, counts, ids, summary, not a.no_upload)
    if a.tag == "duckdb":
        c.write_vars("duckdb", {"duckSeconds": c.tex_dec(summary["seconds_total"]), "duckAccess": summary["access"],
                                "duckThreads": str(a.threads), "duckMemory": c.tex_escape(a.memory)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
