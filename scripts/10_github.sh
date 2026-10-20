#!/bin/bash
source "$(dirname "$0")/common.sh"

if [ ! -s report/report.pdf ]; then
  note "нет report/report.pdf"
  exit 1
fi

PUB="$LAB/publish"
note "собираю папку для github: $PUB"
if [ -d "$PUB/.git" ]; then
  find "$PUB" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
else
  rm -rf "$PUB"
fi
mkdir -p "$PUB/report" "$PUB/results"
cp -R lab scripts docker README.md "$PUB/"
rm -rf "$PUB"/lab/__pycache__
cp report/report.tex report/report.pdf "$PUB/report/"
cp -R report/img report/plots report/out "$PUB/report/"
for t in mapreduce duckdb; do
  mkdir -p "$PUB/results/$t"
  cp results/$t/* "$PUB/results/$t/"
done
for t in mapreduce_naive mapreduce_failtest duckdb_parquet; do
  mkdir -p "$PUB/results/$t"
  cp results/$t/summary.json "$PUB/results/$t/" 2>/dev/null
done
cp -R results/salary results/regions "$PUB/results/" 2>/dev/null
mkdir -p "$PUB/results/profile"
cp results/profile/runs.csv results/profile/*.log "$PUB/results/profile/" 2>/dev/null
cp results/*.json "$PUB/results/" 2>/dev/null
printf 'dataset/\ndisks/\nlogs/\n__pycache__/\n*.pyc\n.DS_Store\n' > "$PUB/.gitignore"

note ""
note "файлов в папке: $(find "$PUB" -type f -not -path '*/.git/*' | wc -l | tr -d ' '), размер $(du -sh "$PUB" | cut -f1)"
[ "$(uname)" = Darwin ] && open "$PUB"
