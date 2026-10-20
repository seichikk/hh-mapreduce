#!/bin/bash
source "$(dirname "$0")/common.sh"
need_storage
need_results mapreduce

clear_screen
capture 06_salary runpy -m lab.salary || { note "ошибка"; exit 1; }
