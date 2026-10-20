#!/bin/bash
source "$(dirname "$0")/common.sh"
need_storage

body() {
  title "этап 3а. свой mapreduce: читает объект из s3 чанками (range get) и считает навыки, пары и тройки"
  note "вариант: программист, разработчик на c# и .net"
  note "условие отбора: role = 'Программист, разработчик' и в названии вакансии есть c#, с#, .net, dotnet, c sharp, csharp или си шарп"
  if [ -z "$LOCAL_MODE" ]; then
    note ""
    note "доказательство, что вычисления не видят локальный файл: контейнер с python получает только код и папку для результатов"
    printf '\n$ (внутри контейнера) ls /app; ls /data\n'
    docker run --rm -v "$LAB/lab:/app/lab:ro" -v "$LAB/results:/app/results" -v "$LAB/report:/app/report" "$PYIMG" \
      sh -c 'ls /app; ls /data 2>&1 | sed "s/^/  /"; echo "  -> папки /data с датасетом в контейнере нет, данные можно взять только из s3"'
  fi
  runpy -m lab.mapreduce --mode opt --verbose || return 1
  title "та же задача наивной версией (без combiner, стандартный csv, один маппер) — для сверки и бонуса"
  runpy -m lab.mapreduce --mode naive --workers 1 --tag mapreduce_naive --compare-with mapreduce || return 1
}

clear_screen
capture 02_mapreduce body || { note "ошибка"; exit 1; }
