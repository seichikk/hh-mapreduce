#!/bin/bash
source "$(dirname "$0")/common.sh"
need_storage
need_results mapreduce duckdb

ATTEMPTS="${ATTEMPTS:-3}"

bonus() {
  title "бонус: колоночная копия датасета в parquet (duckdb пишет её прямо в s3)"
  runpy -m lab.duck --to-parquet || return 1
  runpy -m lab.duck --source parquet --tag duckdb_parquet || return 1
  runpy -m lab.verify || return 1
}

profile() {
  title "профилирование: каждый способ запускается $ATTEMPTS раза, перед каждым запуском rustfs перезапускается"
  note "время — от старта процесса до записи результатов; память — пик суммарного rss дерева процессов (опрос каждые 20 мс)"
  note "после каждого запуска результат сверяется с эталоном results/mapreduce по sha256"
  py -m lab.profile reset
  local methods
  methods=($(py -m lab.profile list))
  local n=${#methods[@]} a i m
  for a in $(seq 1 "$ATTEMPTS"); do
    note ""
    note "--- попытка $a из $ATTEMPTS"
    for i in $(seq 0 $((n - 1))); do
      m=${methods[$(((i + a - 1) % n))]}
      restart_storage
      py -m lab.profile run --method "$m" --attempt "$a" || return 1
    done
  done
  title "итог профилирования"
  py -m lab.profile summary
}

clear_screen
capture 08_bonus bonus || { note "ошибка"; exit 1; }
capture 08_profile profile || { note "ошибка"; exit 1; }
