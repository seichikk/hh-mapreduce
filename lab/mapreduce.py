import argparse
import csv
import io
import json
import math
import multiprocessing as mp
import os
import sys
import time
import zlib
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from itertools import combinations

from lab import common as c

BOM = b"\xef\xbb\xbf"
NEED = ("vacancy_id", "id", "name", "role", "area", "key_skills", "salary_from", "salary_to", "currency",
        "gross", "employer", "employer_name", "company", "employer_id", "experience", "schedule")
MAX_ATTEMPTS = 3


def record_boundary(buf):
    total = buf.count(b'"')
    pos = len(buf)
    while True:
        pos = buf.rfind(b"\n", 0, pos)
        if pos < 0:
            return -1
        if (total - buf.count(b'"', pos)) % 2 == 0:
            return pos + 1


def rows_csv(data, fields):
    reader = csv.reader(io.StringIO(data.decode("utf-8"), newline=""))
    for values in reader:
        if values:
            yield dict(zip(fields, values))


def rows_arrow(data, fields):
    import pyarrow as pa
    import pyarrow.csv as pcsv
    need = [f for f in NEED if f in fields]
    table = pcsv.read_csv(
        pa.py_buffer(data),
        read_options=pcsv.ReadOptions(column_names=fields, use_threads=False, block_size=64 << 20),
        parse_options=pcsv.ParseOptions(newlines_in_values=True),
        convert_options=pcsv.ConvertOptions(include_columns=need,
                                            column_types={f: pa.string() for f in need},
                                            strings_can_be_null=False, quoted_strings_can_be_null=False),
    )
    cols = {f: table.column(f).to_pylist() for f in need}
    roles = cols["role"]
    for i in range(table.num_rows):
        if roles[i] == c.VARIANT_ROLE:
            yield {f: cols[f][i] for f in need}
        else:
            yield None


def partition_of(combo, reducers):
    return zlib.crc32("\x1f".join(combo).encode("utf-8")) % reducers


def map_task(task_id, attempt, data, fields, mode, fail_task, reducers):
    if task_id == fail_task and attempt == 1:
        print(f"  [маппер задачи {task_id}] имитирую падение процесса: os._exit(137)\n", end="", flush=True)
        os._exit(137)
    t0 = time.perf_counter()
    parser = "csv"
    if mode == "opt":
        try:
            rows = list(rows_arrow(data, fields))
            parser = "arrow"
        except Exception:
            rows = list(rows_csv(data, fields))
            parser = "csv (запасной)"
    else:
        rows = rows_csv(data, fields)
    if mode == "naive":
        parts = [[[] for _ in c.KS] for _ in range(reducers)]
    else:
        parts = [[Counter() for _ in c.KS] for _ in range(reducers)]
    scanned = 0
    vacancies = []
    emitted = [0, 0, 0]
    for row in rows:
        scanned += 1
        if row is None or not c.is_variant(row):
            continue
        skills = c.parse_skills(row.get("key_skills"))
        vacancies.append(c.vacancy_record(row, skills))
        for k in c.KS:
            for combo in combinations(skills, k):
                emitted[k - 1] += 1
                target = parts[partition_of(combo, reducers)][k - 1]
                if mode == "naive":
                    target.append((combo, 1))
                else:
                    target[combo] += 1
    shuffled = sum(len(parts[r][k - 1]) for r in range(reducers) for k in c.KS)
    return {"task": task_id, "attempt": attempt, "pid": os.getpid(), "parser": parser, "scanned": scanned,
            "vacancies": vacancies, "emitted": emitted, "shuffled": shuffled, "parts": parts,
            "seconds": time.perf_counter() - t0, "bytes": len(data)}


def reduce_task(r, k, pieces, mode):
    if mode == "naive":
        pairs = [p for piece in pieces for p in piece]
        pairs.sort()
        total = {}
        prev = None
        acc = 0
        for combo, one in pairs:
            if combo != prev:
                if prev is not None:
                    total[prev] = acc
                prev, acc = combo, 0
            acc += one
        if prev is not None:
            total[prev] = acc
        return r, k, total
    total = Counter()
    for piece in pieces:
        total.update(piece)
    return r, k, dict(total)


class Master:
    def __init__(self, mode, workers, reducers, fail_task, verbose):
        self.mode = mode
        self.workers = workers
        self.reducers = reducers
        self.fail_task = fail_task
        self.verbose = verbose
        self.ctx = mp.get_context("spawn")
        self.pool = ProcessPoolExecutor(max_workers=workers, mp_context=self.ctx)
        self.futures = {}
        self.tasks = {}
        self.done = {}
        self.fields = None
        self.restarts = 0
        self.retried = []

    def submit(self, tid):
        data, attempt = self.tasks[tid]
        try:
            f = self.pool.submit(map_task, tid, attempt, data, self.fields, self.mode, self.fail_task, self.reducers)
        except BrokenProcessPool:
            self.recover("пул процессов сломан, один из мапперов аварийно завершился", extra=(tid,))
            return
        self.futures[f] = tid

    def recover(self, reason, extra=()):
        lost = sorted(set(self.futures.values()) | set(extra))
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.futures.clear()
        self.restarts += 1
        print(f"  мастер: {reason}. пул процессов пересоздан, задачи перезапускаются: {lost}", flush=True)
        self.pool = ProcessPoolExecutor(max_workers=self.workers, mp_context=self.ctx)
        for tid in lost:
            self.tasks[tid][1] += 1
            if self.tasks[tid][1] > MAX_ATTEMPTS:
                raise RuntimeError(f"задача {tid} упала {MAX_ATTEMPTS} раза подряд")
            self.retried.append((tid, self.tasks[tid][1]))
            self.submit(tid)

    def collect(self, limit):
        while len(self.futures) > limit:
            finished, _ = wait(list(self.futures), return_when=FIRST_COMPLETED)
            for f in finished:
                if f not in self.futures:
                    continue
                tid = self.futures[f]
                try:
                    res = f.result()
                except BrokenProcessPool:
                    self.recover(f"процесс-маппер аварийно завершился во время задачи {tid}")
                    break
                except Exception as e:
                    del self.futures[f]
                    self.tasks[tid][1] += 1
                    if self.tasks[tid][1] > MAX_ATTEMPTS:
                        raise
                    print(f"  мастер: задача {tid} упала с ошибкой {e!r}, повторяю", flush=True)
                    self.retried.append((tid, self.tasks[tid][1]))
                    self.submit(tid)
                    continue
                del self.futures[f]
                del self.tasks[tid]
                self.done[tid] = res
                if self.verbose:
                    print(f"  map {tid:>3}: попытка {res['attempt']}, процесс {res['pid']}, {c.human_bytes(res['bytes'])}, "
                          f"строк {res['scanned']}, вакансий варианта {len(res['vacancies'])}, "
                          f"парсер {res['parser']}, {res['seconds']:.2f} с\n", end="", flush=True)


def run(mode, chunk_mib, workers, reducers, fail_task, verbose):
    s3 = c.client()
    size = s3.head_object(Bucket=c.BUCKET, Key=c.KEY)["ContentLength"]
    chunk = chunk_mib << 20
    print(f"объект s3://{c.BUCKET}/{c.KEY}: {size} байт ({c.human_bytes(size)})")
    print(f"режим {mode}: чанк {chunk_mib} миб (около {math.ceil(size / chunk)} range get), "
          f"мапперов {workers}, редьюсеров {reducers}" + (f", сбой маппера задачи {fail_task}" if fail_task >= 0 else ""))
    m = Master(mode, workers, reducers, fail_task, verbose)
    t0 = time.perf_counter()
    offset = 0
    carry = b""
    tid = 0
    gets = 0
    read_bytes = 0
    t_read = 0.0
    while offset < size:
        end = min(offset + chunk, size) - 1
        tr = time.perf_counter()
        data = s3.get_object(Bucket=c.BUCKET, Key=c.KEY, Range=f"bytes={offset}-{end}")["Body"].read()
        t_read += time.perf_counter() - tr
        gets += 1
        read_bytes += len(data)
        offset = end + 1
        buf = carry + data
        carry = b""
        if m.fields is None:
            if buf.startswith(BOM):
                buf = buf[3:]
            nl = buf.find(b"\n")
            m.fields = next(csv.reader([buf[:nl].decode("utf-8").rstrip("\r")]))
            buf = buf[nl + 1:]
            missing = [f for f in c.REQUIRED if f not in m.fields]
            if missing:
                raise SystemExit("в датасете нет колонок: " + ", ".join(missing))
        cut = len(buf) if offset >= size else record_boundary(buf)
        if cut <= 0:
            carry = buf
            continue
        m.tasks[tid] = [buf[:cut], 1]
        carry = buf[cut:]
        m.submit(tid)
        tid += 1
        m.collect(workers * 2)
    if carry:
        m.tasks[tid] = [carry, 1]
        m.submit(tid)
        tid += 1
    m.collect(0)
    t_map = time.perf_counter() - t0
    shuffle = [[[] for _ in c.KS] for _ in range(reducers)]
    vacancies = []
    stats = {"scanned": 0, "emitted": [0, 0, 0], "shuffled": 0}
    for t in sorted(m.done):
        res = m.done[t]
        stats["scanned"] += res["scanned"]
        stats["shuffled"] += res["shuffled"]
        for i in range(3):
            stats["emitted"][i] += res["emitted"][i]
        vacancies.extend(res["vacancies"])
        for r in range(reducers):
            for k in c.KS:
                shuffle[r][k - 1].append(res["parts"][r][k - 1])
    m.done.clear()
    t1 = time.perf_counter()
    counts = {k: {} for k in c.KS}
    futs = [m.pool.submit(reduce_task, r, k, shuffle[r][k - 1], mode) for r in range(reducers) for k in c.KS]
    shuffle = None
    for f in futs:
        r, k, part = f.result()
        counts[k].update(part)
    m.pool.shutdown()
    t_reduce = time.perf_counter() - t1
    total = time.perf_counter() - t0
    combos = [sum(math.comb(len(v["skills"]), k) for v in vacancies) for k in c.KS]
    sums = [sum(counts[k].values()) for k in c.KS]
    summary = {
        "mode": mode, "chunk_mib": chunk_mib, "workers": workers, "reducers": reducers, "fail_task": fail_task,
        "object_bytes": size, "range_gets": gets, "read_bytes": read_bytes, "map_tasks": tid,
        "rows_scanned": stats["scanned"], "vacancies": len(vacancies),
        "with_skills": sum(1 for v in vacancies if v["skills"]),
        "with_salary": sum(1 for v in vacancies if v["salary"] is not None),
        "emitted": stats["emitted"], "shuffled": stats["shuffled"],
        "unique": [len(counts[k]) for k in c.KS], "sums": sums, "combinations": combos,
        "restarts": m.restarts, "retried": m.retried,
        "seconds_total": round(total, 3), "seconds_map": round(t_map, 3), "seconds_reduce": round(t_reduce, 3),
        "seconds_s3_read": round(t_read, 3),
    }
    print(f"прочитано из s3: {read_bytes} байт за {gets} range get, это весь объект: {'да' if read_bytes == size else 'НЕТ'}")
    print(f"map-задач: {tid}, просмотрено записей: {stats['scanned']}, вакансий варианта: {len(vacancies)} "
          f"(с навыками {summary['with_skills']}, с зарплатой {summary['with_salary']})")
    print(f"записей ушло в shuffle: {stats['shuffled']} (до combiner было бы {sum(stats['emitted'])})")
    for k in c.KS:
        top = min(counts[k].items(), key=lambda item: (-item[1], item[0]), default=None)
        top_s = " + ".join(top[0]) + f" = {top[1]}" if top else "---"
        print(f"k={k}: уникальных сочетаний {len(counts[k])}, сумма частот {sums[k - 1]}, "
              f"сумма C(n,{k}) по вакансиям {combos[k - 1]}, совпадает: {'да' if sums[k - 1] == combos[k - 1] else 'НЕТ'}; топ: {top_s}")
    if m.restarts or m.retried:
        print(f"перезапусков пула: {m.restarts}, повторных попыток задач: {len(m.retried)} {m.retried}")
    print(f"время: всего {total:.2f} с, map {t_map:.2f} с (из них чтение s3 {t_read:.2f} с), reduce {t_reduce:.2f} с")
    if sums != combos:
        raise SystemExit("сумма частот не совпала с числом сочетаний")
    return counts, vacancies, summary


def save(tag, counts, vacancies, summary, upload):
    s3 = c.client() if upload else None
    files = {f"k{k}.csv": c.counts_to_csv(counts[k], k) for k in c.KS}
    files["vacancies.jsonl"] = c.vacancies_to_jsonl(vacancies)
    files["summary.json"] = (json.dumps(summary, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    for name, data in files.items():
        c.save_local(f"{tag}/{name}", data)
        if upload:
            key = f"results/{tag}/{name}"
            c.put_bytes(s3, key, data)
            back = c.get_bytes(s3, key)
            ok = c.sha256_bytes(back) == c.sha256_bytes(data)
            print(f"  сохранено s3://{c.BUCKET}/{key} ({len(data)} байт), sha256 после чтения обратно совпал: {'да' if ok else 'НЕТ'}")
    return {name: c.sha256_bytes(data) for name, data in files.items() if name.startswith("k")}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["naive", "opt"], default="opt")
    p.add_argument("--chunk-mib", type=int, default=32)
    p.add_argument("--workers", type=int, default=max(1, min(4, os.cpu_count() or 1)))
    p.add_argument("--reducers", type=int, default=4)
    p.add_argument("--fail-task", type=int, default=-1)
    p.add_argument("--tag", default="mapreduce")
    p.add_argument("--no-upload", action="store_true")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--compare-with", default="")
    a = p.parse_args()
    counts, vacancies, summary = run(a.mode, a.chunk_mib, a.workers, a.reducers, a.fail_task, a.verbose)
    hashes = save(a.tag, counts, vacancies, summary, not a.no_upload)
    same = None
    if a.compare_with:
        s3 = c.client()
        same = True
        for k in c.KS:
            ref = c.sha256_bytes(c.get_bytes(s3, f"results/{a.compare_with}/k{k}.csv"))
            eq = ref == hashes[f"k{k}.csv"]
            same = same and eq
            print(f"k{k}.csv: sha256 {hashes[f'k{k}.csv'][:16]}..., эталон results/{a.compare_with}: {ref[:16]}..., совпадает: {'да' if eq else 'НЕТ'}")
        print("результат совпал с эталонным прогоном: " + ("да" if same else "НЕТ"))
    if a.tag == "mapreduce":
        c.write_vars("mapreduce", {
            "mrTasks": str(summary["map_tasks"]), "mrGets": str(summary["range_gets"]), "mrChunk": str(a.chunk_mib),
            "mrWorkers": str(a.workers), "mrReducers": str(a.reducers), "mrSeconds": c.tex_dec(summary["seconds_total"]),
            "mrShuffled": c.tex_int(summary["shuffled"]), "mrEmitted": c.tex_int(sum(summary["emitted"])),
            "mrCombinerPct": c.tex_dec(100 * (1 - summary["shuffled"] / max(sum(summary["emitted"]), 1)), 1),
            "mrReadS": c.tex_dec(summary["seconds_s3_read"]),
        })
    if a.tag == "mapreduce_failtest":
        c.write_vars("failtest", {
            "failTask": str(a.fail_task), "failRestarts": str(summary["restarts"]),
            "failRetried": ", ".join(f"{t} (попытка {n})" for t, n in summary["retried"]) or "---",
            "failSame": "совпали" if same else "\\textbf{не совпали}",
        })
    return 0 if same in (None, True) else 1


if __name__ == "__main__":
    sys.exit(main())
