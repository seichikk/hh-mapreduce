#!/bin/bash
source "$(dirname "$0")/common.sh"

if [ -z "$LOCAL_MODE" ] && ! docker image inspect "$PYIMG" >/dev/null 2>&1; then
  note "нет образа $PYIMG. запусти: bash scripts/00_check.sh"
  exit 1
fi
note "вырезаю фрагменты кода для отчёта..."
py -m lab.snippets >/dev/null || exit 1

missing=0
for s in 01_storage 01_console 02_mapreduce 03_failure 04_duckdb 05_verify 06_salary 07_regions 08_profile 08_console_results; do
  if [ ! -s "report/img/$s.png" ]; then
    note "нет скриншота report/img/$s.png"
    missing=$((missing + 1))
  fi
done
[ $missing -eq 0 ] && note "все 10 скриншотов на месте"

PDFLATEX=""
for p in pdflatex /Library/TeX/texbin/pdflatex; do
  if type -P "$p" >/dev/null 2>&1 || [ -x "$p" ]; then PDFLATEX="$p"; break; fi
done
if [ -z "$PDFLATEX" ]; then
  note "pdflatex не найден"
  exit 0
fi
cd report || exit 1
for i in 1 2; do
  "$PDFLATEX" -interaction=nonstopmode -halt-on-error report.tex > ../logs/latex.log 2>&1 || {
    note "latex упал, последние строки лога:"
    grep -A5 '^!' ../logs/latex.log | head -20
    exit 1
  }
done
note "готово: report/report.pdf ($(ls -lh report.pdf | awk '{print $5}'))"
[ "$(uname)" = Darwin ] && open report.pdf
