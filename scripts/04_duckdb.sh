#!/bin/bash
source "$(dirname "$0")/common.sh"
need_storage

body() {
  title "этап 3б. тот же подсчёт sql-запросом duckdb прямо по объекту в s3"
  note "условие варианта в sql написано отдельно от python:"
  note "  where role = 'Программист, разработчик'"
  note "    and regexp_matches(lower(name), 'c#|с#|\\.net|dotnet|c sharp|csharp|си шарп')"
  runpy -m lab.duck --source csv || return 1
}

clear_screen
capture 04_duckdb body || { note "ошибка"; exit 1; }
