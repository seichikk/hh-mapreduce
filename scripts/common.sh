#!/bin/bash

LAB="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$LAB" || exit 1

DISKS=4
IMAGE="${RUSTFS_IMAGE:-rustfs/rustfs:1.0.1}"
PYIMG="${PY_IMAGE_NAME:-hh-lab-py:1}"
NAME=rustfs
NET=hhnet
BUCKET=hh-lake
EXPECTED_SHA=303db922b541e4440906f5a7e8be32fb55e8808f950ffddb8c272f1548212a65
EXPECTED_SIZE=847619384
CONSOLE=http://localhost:9001/rustfs/console/
OUT="$LAB/report/out"
IMG="$LAB/report/img"
mkdir -p "$OUT" "$IMG" "$LAB/results" "$LAB/dataset" "$LAB/disks" "$LAB/logs" "$LAB/report/plots"

S3_ENDPOINT_IN="http://$NAME:9000"
if [ -n "$LOCAL_MODE" ]; then
  S3_ENDPOINT_IN="${S3_ENDPOINT:-http://127.0.0.1:9000}"
fi

py() {
  if [ -n "$LOCAL_MODE" ]; then
    (cd "$LAB" && S3_ENDPOINT="$S3_ENDPOINT_IN" python3 "$@")
  else
    docker run --rm --network "$NET" -e S3_ENDPOINT="$S3_ENDPOINT_IN" \
      -v "$LAB/lab:/app/lab:ro" -v "$LAB/results:/app/results" -v "$LAB/report:/app/report" \
      -w /app "$PYIMG" python "$@"
  fi
}

py_with_data() {
  if [ -n "$LOCAL_MODE" ]; then
    py "$@"
  else
    docker run --rm --network "$NET" -e S3_ENDPOINT="$S3_ENDPOINT_IN" \
      -v "$LAB/lab:/app/lab:ro" -v "$LAB/results:/app/results" -v "$LAB/report:/app/report" \
      -v "$LAB/dataset:/data:ro" -w /app "$PYIMG" python "$@"
  fi
}

run() {
  printf '\n$ %s\n' "$*"
  "$@"
}

runpy() {
  printf '\n$ python %s\n' "$*"
  py "$@"
}

runpyd() {
  printf '\n$ python %s\n' "$*"
  py_with_data "$@"
}

title() {
  printf '\n==== %s ====\n' "$*"
}

note() {
  printf '%s\n' "$*"
}

clear_screen() {
  clear 2>/dev/null || true
}

clean_out() {
  [ -f "$1" ] || return 0
  perl -CSD -i -pe 's/\e\[[0-9;?]*[A-Za-z]//g; s/\r//g; s/[^\x{09}\x{0A}\x{20}-\x{7E}\x{401}\x{410}-\x{44F}\x{451}\x{AB}\x{BB}\x{2013}\x{2014}\x{2116}\x{20BD}]/?/g' "$1" 2>/dev/null
  expand "$1" > "$1.tmp" && mv "$1.tmp" "$1"
}

capture() {
  local name="$1"
  shift
  "$@" 2>&1 | tee "$OUT/$name.txt"
  local rc=${PIPESTATUS[0]}
  clean_out "$OUT/$name.txt"
  return $rc
}

container_running() {
  [ -n "$LOCAL_MODE" ] && return 0
  [ "$(docker inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null)" = "true" ]
}

wait_up() {
  local i code
  for i in $(seq 1 90); do
    code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:9000/health/live" 2>/dev/null)
    [ "$code" = "200" ] && return 0
    sleep 1
  done
  return 1
}

need_storage() {
  if ! container_running; then
    note "хранилище rustfs не запущено (bash scripts/01_storage.sh или docker start rustfs)"
    exit 1
  fi
  if [ -z "$LOCAL_MODE" ] && ! docker image inspect "$PYIMG" >/dev/null 2>&1; then
    note "нет образа $PYIMG (bash scripts/00_check.sh)"
    exit 1
  fi
}

need_results() {
  for t in "$@"; do
    if [ ! -f "$LAB/results/$t/k3.csv" ]; then
      note "нет результатов results/$t"
      exit 1
    fi
  done
}

restart_storage() {
  if [ -n "$LOCAL_MODE" ]; then
    return 0
  fi
  docker restart "$NAME" >/dev/null
  wait_up || { note "rustfs не поднялся после перезапуска"; exit 1; }
  sleep 2
}
