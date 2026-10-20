#!/bin/bash
source "$(dirname "$0")/common.sh"

DATA=$(ls -S dataset/*.csv 2>/dev/null | head -n 1)
if [ -z "$DATA" ]; then
  note "в папке dataset нет csv. положи туда it_vacancies_2024.csv и запусти снова"
  exit 1
fi

start_rustfs() {
  if docker ps -a --format '{{.Names}}' | grep -qx "$NAME"; then
    note "нашёл старый контейнер $NAME (например, из дз-2), удаляю его. данные дз-2 в ~/hdfs-lab не трогаются"
    docker rm -f "$NAME" >/dev/null
  fi
  docker network inspect "$NET" >/dev/null 2>&1 || docker network create "$NET" >/dev/null
  local vols=() i
  for i in $(seq 1 "$DISKS"); do
    mkdir -p "disks/disk$i"
    vols+=(-v "$LAB/disks/disk$i:/data/rustfs$i")
  done
  run docker run -d --name "$NAME" --network "$NET" --user 0:0 --restart unless-stopped \
    -p 127.0.0.1:9000:9000 -p 127.0.0.1:9001:9001 "${vols[@]}" -v "$LAB/logs:/logs" \
    -e "RUSTFS_VOLUMES=/data/rustfs{1...$DISKS}" \
    -e RUSTFS_ACCESS_KEY=rustfsadmin -e RUSTFS_SECRET_KEY=rustfsadmin \
    -e RUSTFS_ADDRESS=0.0.0.0:9000 -e RUSTFS_CONSOLE_ENABLE=true -e RUSTFS_CONSOLE_ADDRESS=0.0.0.0:9001 \
    -e RUSTFS_UNSAFE_BYPASS_DISK_CHECK=true -e RUSTFS_OBS_LOG_DIRECTORY=/logs -e RUSTFS_OBS_LOGGER_LEVEL=warn \
    "$IMAGE"
  note "жду, пока rustfs поднимется..."
  if wait_up; then
    note "rustfs отвечает: http://localhost:9000/health/live -> 200"
  else
    note "rustfs не поднялся за 90 секунд:"
    docker logs --tail 20 "$NAME" 2>&1
    exit 1
  fi
  run docker ps --filter "name=^${NAME}\$" --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
}

body() {
  title "этап 1. объектное хранилище rustfs: $DISKS папки-диска, erasure coding"
  if [ -z "$LOCAL_MODE" ]; then
    if container_running && [ -d disks/disk1/"$BUCKET" ]; then
      note "rustfs уже запущен и бакет $BUCKET есть — использую его"
      run docker ps --filter "name=^${NAME}\$" --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
    else
      start_rustfs
    fi
  fi
  title "этап 2. загрузка датасета в бакет $BUCKET"
  if [ -n "$LOCAL_MODE" ]; then
    runpyd -m lab.storage upload --path "$DATA" || return 1
  else
    runpyd -m lab.storage upload --path "/data/$(basename "$DATA")" || return 1
  fi
  runpy -m lab.storage inspect || return 1
  runpy -m lab.storage ls --prefix raw/
  [ -z "$LOCAL_MODE" ] && run du -sh disks/disk*
  return 0
}

clear_screen
capture 01_storage body
rc=$?
[ $rc -eq 0 ] || { note "ошибка"; exit 1; }


