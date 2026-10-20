#!/bin/bash
source "$(dirname "$0")/common.sh"
need_storage
need_results mapreduce

body() {
  title "проверка отказоустойчивости: процесс-маппер задачи 5 умирает (os._exit(137)) на первой попытке"
  note "мастер должен заметить падение, пересоздать пул процессов, перезапустить потерянные задачи"
  note "и получить ровно тот же результат, что и без сбоя (сравниваем sha256 файлов k1..k3)"
  runpy -m lab.mapreduce --mode opt --fail-task 5 --verbose --tag mapreduce_failtest --compare-with mapreduce
}

clear_screen
capture 03_failure body || { note "результат после сбоя не совпал"; exit 1; }
