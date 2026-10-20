import csv
import hashlib
import io
import json
import math
import os
import statistics
from pathlib import Path

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
OUT = ROOT / "report" / "out"
PLOTS = ROOT / "report" / "plots"

ENDPOINT = os.environ.get("S3_ENDPOINT", "http://rustfs:9000")
ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "rustfsadmin")
SECRET_KEY = os.environ.get("S3_SECRET_KEY", "rustfsadmin")
BUCKET = os.environ.get("S3_BUCKET", "hh-lake")
KEY = os.environ.get("S3_KEY", "raw/it_vacancies_2024.csv")
PARQUET_KEY = os.environ.get("S3_PARQUET_KEY", "raw/it_vacancies_2024.parquet")

VARIANT_TITLE = "вариант 4: программист, разработчик на C# и .NET"
VARIANT_ROLE = "Программист, разработчик"
VARIANT_TOKENS = ("c#", "с#", ".net", "dotnet", "c sharp", "csharp", "си шарп")
SKILL_STRIP = " \t\r\n"
REQUIRED = ("name", "role", "key_skills", "area", "salary_from", "salary_to", "currency", "gross")
KS = (1, 2, 3)

SALARY_MIN = 10_000
SALARY_MAX = 1_000_000
NDFL = 0.87


def client():
    return boto3.client(
        "s3",
        endpoint_url=ENDPOINT,
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
        region_name="us-east-1",
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            retries={"max_attempts": 3, "mode": "standard"},
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )


def transfer_config():
    return TransferConfig(multipart_threshold=64 << 20, multipart_chunksize=64 << 20, max_concurrency=4)


def is_variant(row):
    if (row.get("role") or "") != VARIANT_ROLE:
        return False
    name = (row.get("name") or "").lower()
    return any(token in name for token in VARIANT_TOKENS)


def parse_skills(text):
    found = set()
    for part in (text or "").split(";"):
        skill = part.strip(SKILL_STRIP).lower()
        if skill:
            found.add(skill)
    return sorted(found)


def to_number(text):
    if text is None:
        return None
    text = str(text).strip().replace(",", ".")
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    return value


def is_true(text):
    return str(text or "").strip().lower() in ("true", "t", "1", "yes", "да")


def salary_net(row):
    if str(row.get("currency") or "").strip().upper() not in ("RUR", "RUB"):
        return None
    low = to_number(row.get("salary_from"))
    high = to_number(row.get("salary_to"))
    if low is None and high is None:
        return None
    if low is not None and high is not None:
        if low > high:
            low, high = high, low
        value = (low + high) / 2
    else:
        value = low if low is not None else high
    if is_true(row.get("gross")):
        value *= NDFL
    if value < SALARY_MIN or value > SALARY_MAX:
        return None
    return round(value, 2)


def first_of(row, names):
    for name in names:
        value = row.get(name)
        if value:
            return value
    return ""


def vacancy_record(row, skills):
    return {
        "vacancy_id": row.get("vacancy_id") or row.get("id") or "",
        "name": row.get("name") or "",
        "area": (row.get("area") or "").strip() or "не указан",
        "employer": first_of(row, ("employer", "employer_name", "company", "employer_id")),
        "experience": row.get("experience") or "",
        "schedule": row.get("schedule") or "",
        "salary": salary_net(row),
        "skills": skills,
    }


def get_bytes(s3, key):
    return s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()


def put_bytes(s3, key, data, content_type="text/csv"):
    s3.put_object(Bucket=BUCKET, Key=key, Body=data, ContentType=content_type)


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_s3(s3, key):
    h = hashlib.sha256()
    size = 0
    body = s3.get_object(Bucket=BUCKET, Key=key)["Body"]
    for chunk in iter(lambda: body.read(8 << 20), b""):
        h.update(chunk)
        size += len(chunk)
    return h.hexdigest(), size


def counts_to_csv(counter, k):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow([f"skill_{i}" for i in range(1, k + 1)] + ["count"])
    for combo, n in sorted(counter.items(), key=lambda item: (-item[1], item[0])):
        w.writerow(list(combo) + [n])
    return buf.getvalue().encode("utf-8")


def csv_to_counts(data):
    reader = csv.reader(io.StringIO(data.decode("utf-8")))
    next(reader, None)
    return {tuple(row[:-1]): int(row[-1]) for row in reader if row}


def vacancies_to_jsonl(rows):
    return "".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in rows).encode("utf-8")


def jsonl_to_vacancies(data):
    return [json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]


def load_vacancies(s3, tag="mapreduce"):
    return jsonl_to_vacancies(get_bytes(s3, f"results/{tag}/vacancies.jsonl"))


def load_counts(s3, tag="mapreduce"):
    return {k: csv_to_counts(get_bytes(s3, f"results/{tag}/k{k}.csv")) for k in KS}


def save_local(rel, data):
    path = RESULTS / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def save_json_local(rel, obj):
    return save_local(rel, (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def median(values):
    return statistics.median(values) if values else None


def quantile(values, q):
    if not values:
        return None
    s = sorted(values)
    pos = (len(s) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def human_bytes(n):
    n = float(n)
    for unit in ("байт", "киб", "миб", "гиб"):
        if n < 1024 or unit == "гиб":
            return f"{int(n)} {unit}" if unit == "байт" else f"{n:.2f} {unit}"
        n /= 1024


def tex_escape(s):
    rep = {"\\": "\\textbackslash{}", "_": "\\_", "&": "\\&", "%": "\\%", "$": "\\$", "#": "\\#",
           "{": "\\{", "}": "\\}", "~": "\\textasciitilde{}", "^": "\\textasciicircum{}"}
    return "".join(rep.get(ch, ch) for ch in str(s))


def tex_skill(s, width=38):
    s = str(s)
    if len(s) > width:
        s = s[: width - 1] + "…"
    return tex_escape(s).replace("…", "\\dots{}")


def tex_int(n):
    if n is None:
        return "---"
    return f"{int(round(n)):,}".replace(",", "\\,")


def tex_dec(x, digits=2):
    if x is None:
        return "---"
    return f"{x:.{digits}f}".replace(".", "{,}")


def tex_signed(n):
    if n is None:
        return "---"
    sign = "+" if n > 0 else ("$-$" if n < 0 else "")
    return sign + tex_int(abs(n))


def write_out(name, text):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(text, encoding="utf-8")


def write_vars(name, values):
    lines = [f"\\renewcommand{{\\{k}}}{{{v}}}" for k, v in values.items()]
    write_out(f"vars-{name}.tex", "\n".join(lines) + "\n")


def table_rows(rows):
    return "\n".join(" & ".join(str(c) for c in r) + " \\\\" for r in rows) + "\n"
