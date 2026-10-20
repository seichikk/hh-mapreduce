#!/bin/bash
source "$(dirname "$0")/common.sh"
need_storage
need_results mapreduce

clear_screen
capture 07_regions runpy -m lab.regions "$@" || { note "ошибка"; exit 1; }
