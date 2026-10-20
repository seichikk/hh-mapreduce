#!/bin/bash
source "$(dirname "$0")/common.sh"

if [ -z "$LOCAL_MODE" ]; then
  if ! type -P docker >/dev/null 2>&1; then
    note "docker не найден. установи docker desktop"
    exit 1
  fi
  if ! docker info >/dev/null 2>&1; then
    note "docker установлен, но не запущен. открой docker desktop, дождись engine running и запусти снова"
    exit 1
  fi
  note "собираю образ с python, duckdb и pyarrow..."
  docker build -t "$PYIMG" docker/ || { note "образ не собрался"; exit 1; }
  docker image inspect "$IMAGE" >/dev/null 2>&1 || docker pull "$IMAGE" || { note "не скачался $IMAGE"; exit 1; }
fi

DATA=$(ls -S dataset/*.csv 2>/dev/null | head -n 1)

V="$OUT/vars-host.tex"
: > "$V"
clear_screen
{
  title "стенд"
  if [ "$(uname)" = Darwin ]; then
    model=$(sysctl -n hw.model)
    cpu=$(sysctl -n machdep.cpu.brand_string)
    cores=$(sysctl -n hw.physicalcpu)
    ram=$(( $(sysctl -n hw.memsize) / 1073741824 ))
    os="macOS $(sw_vers -productVersion)"
  else
    model=$(hostname)
    cpu=$(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2 | sed 's/^ *//')
    cores=$(nproc)
    ram=$(( $(awk '/MemTotal/ {print $2}' /proc/meminfo) / 1048576 ))
    os="$(uname -sr)"
  fi
  note "модель: $model"
  note "процессор: $cpu, физических ядер: $cores"
  note "оперативная память: $ram гб"
  note "система: $os"
  if [ -z "$LOCAL_MODE" ]; then
    dmem=$(( $(docker info --format '{{.MemTotal}}') / 1048576 ))
    dcpu=$(docker info --format '{{.NCPU}}')
    note "docker engine $(docker version --format '{{.Server.Version}}'), выделено docker: $dcpu cpu, $dmem миб памяти"
    if [ "$dmem" -lt 3500 ]; then
      note "предупреждение: docker выделено меньше 4 гб памяти"
    fi
    docker run --rm "$PYIMG" python -c "import duckdb, pyarrow, boto3, psutil, sys; print('python', sys.version.split()[0], '| duckdb', duckdb.__version__, '| pyarrow', pyarrow.__version__, '| boto3', boto3.__version__)"
  else
    dmem=0
    dcpu=$cores
  fi
  printf '\\renewcommand{\\hostModel}{%s}\n\\renewcommand{\\hostCpu}{%s}\n\\renewcommand{\\hostCores}{%s}\n\\renewcommand{\\hostRam}{%s}\n\\renewcommand{\\hostOs}{%s}\n\\renewcommand{\\dockerMem}{%s}\n\\renewcommand{\\dockerCpu}{%s}\n' \
    "$model" "$cpu" "$cores" "$ram" "$os" "$dmem" "$dcpu" > "$V"

  title "датасет"
  if [ -z "$DATA" ]; then
    note "в папке dataset нет csv-файла."
    exit 1
  fi
  size=$(wc -c < "$DATA" | tr -d ' ')
  note "файл: $DATA, $size байт"
  note "считаю sha256 (секунд 10)..."
  sha=$(shasum -a 256 "$DATA" | cut -d' ' -f1)
  note "sha256: $sha"
  if [ "$sha" = "$EXPECTED_SHA" ]; then
    note "это тот самый курсовой файл it_vacancies_2024.csv (sha256 совпал с эталоном курса)"
  else
    note "sha256 НЕ совпал с известным курсовым файлом ($EXPECTED_SIZE байт, $EXPECTED_SHA)."
  fi
  head -c 600 "$DATA" | head -n 2 | cut -c1-300
} 2>&1 | tee "$OUT/00_check.txt"
rc=${PIPESTATUS[0]}
clean_out "$OUT/00_check.txt"
[ "$rc" -eq 0 ] || exit "$rc"

note ""
