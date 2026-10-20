#!/bin/bash
source "$(dirname "$0")/common.sh"
need_storage
need_results mapreduce duckdb

clear_screen
capture 05_verify runpy -m lab.verify
rc=$?
capture 05_growth runpy -m lab.growth
if [ $rc -ne 0 ]; then
  note "есть расхождения, см. report/out/05_verify.txt"
  exit 1
fi
