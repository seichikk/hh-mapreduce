import argparse
import csv
import io
import sys
import time

from botocore.exceptions import ClientError

from lab import common as c


def ensure_bucket(s3):
    try:
        s3.head_bucket(Bucket=c.BUCKET)
        print(f"бакет {c.BUCKET} уже существует")
    except ClientError:
        s3.create_bucket(Bucket=c.BUCKET)
        print(f"создан бакет {c.BUCKET}")


def header_from_s3(s3):
    head = s3.get_object(Bucket=c.BUCKET, Key=c.KEY, Range="bytes=0-1048575")["Body"].read()
    if head.startswith(b"\xef\xbb\xbf"):
        head = head[3:]
    text = head.decode("utf-8", "replace")
    reader = csv.reader(io.StringIO(text, newline=""))
    fields = next(reader)
    first = next(reader, [])
    return fields, dict(zip(fields, first))


def upload(path):
    s3 = c.client()
    ensure_bucket(s3)
    local_sha = c.sha256_file(path)
    size = path.stat().st_size
    print(f"локальный файл: {path.name}, {size} байт ({c.human_bytes(size)})")
    print(f"sha256 локального файла: {local_sha}")
    try:
        meta = s3.head_object(Bucket=c.BUCKET, Key=c.KEY)
        exists = meta["ContentLength"] == size
    except ClientError:
        exists = False
    if exists:
        print(f"объект s3://{c.BUCKET}/{c.KEY} уже загружен, размер совпадает, повторно не загружаю")
    else:
        t0 = time.perf_counter()
        s3.upload_file(str(path), c.BUCKET, c.KEY, Config=c.transfer_config())
        dt = time.perf_counter() - t0
        print(f"загружено в s3://{c.BUCKET}/{c.KEY} за {dt:.1f} с ({size / dt / 1048576:.1f} миб/с)")
    print("читаю объект обратно из хранилища и считаю sha256...")
    remote_sha, remote_size = c.sha256_s3(s3, c.KEY)
    print(f"sha256 объекта в s3:     {remote_sha}")
    print(f"размер объекта в s3: {remote_size} байт")
    ok = remote_sha == local_sha and remote_size == size
    print("файл в хранилище совпадает с исходным: " + ("да" if ok else "НЕТ"))
    c.save_json_local("storage.json", {"bucket": c.BUCKET, "key": c.KEY, "bytes": remote_size,
                                       "sha256": remote_sha, "match": ok})
    c.write_vars("storage", {"objBytes": c.tex_int(remote_size), "objHuman": c.tex_escape(c.human_bytes(remote_size)),
                             "objSha": "\\texttt{" + remote_sha[:32] + "\\dots}", "objMatch": "да" if ok else "нет"})
    return 0 if ok else 1


def inspect():
    s3 = c.client()
    fields, first = header_from_s3(s3)
    print(f"колонки датасета ({len(fields)}): " + ", ".join(fields))
    missing = [f for f in c.REQUIRED if f not in fields]
    if missing:
        print("НЕ ХВАТАЕТ нужных колонок: " + ", ".join(missing))
        return 1
    print("все нужные колонки на месте: " + ", ".join(c.REQUIRED))
    print("первая запись (обрезано):")
    for f in fields:
        if f in c.REQUIRED or f in ("vacancy_id", "employer", "schedule", "experience"):
            print(f"  {f}: {str(first.get(f, ''))[:90]!r}")
    c.write_out("fields.tex", c.tex_escape(", ".join(fields)) + "\n")
    return 0


def listing(prefix):
    s3 = c.client()
    paginator = s3.get_paginator("list_objects_v2")
    total = 0
    n = 0
    print(f"содержимое s3://{c.BUCKET}/{prefix}")
    for page in paginator.paginate(Bucket=c.BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            n += 1
            total += obj["Size"]
            stamp = obj["LastModified"].strftime("%Y-%m-%d %H:%M:%S")
            print(f"  {stamp}  {obj['Size']:>12}  {obj['Key']}")
    print(f"объектов: {n}, всего {c.human_bytes(total)}")
    return 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["upload", "inspect", "ls"])
    p.add_argument("--path")
    p.add_argument("--prefix", default="")
    a = p.parse_args()
    if a.action == "upload":
        from pathlib import Path
        return upload(Path(a.path))
    if a.action == "inspect":
        return inspect()
    return listing(a.prefix)


if __name__ == "__main__":
    sys.exit(main())
