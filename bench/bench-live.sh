#!/bin/zsh
# Имитация живого режима: режет запись на куски и по одному отдаёт локальному whisper-server,
# модель загружена один раз. Печатает задержку распознавания каждого куска.
# Запускать при открытом созвоне в Meet, чтобы проверить риск с 8 ГБ памяти.
#
#   bench/bench-live.sh [wav] [модель] [длина куска, с] [сколько кусков] [с какой секунды]
set -e
cd "$(dirname "$0")/.."

WAV=${1:-recordings/work/andrey-16k.wav}
MODEL=${2:-models/ggml-large-v3-turbo-q5_0.bin}
CHUNK=${3:-15}
COUNT=${4:-16}
START=${5:-600}
PORT=8178
TMP=$(mktemp -d)

whisper-server -m "$MODEL" -l ru -t 4 --host 127.0.0.1 --port $PORT >"$TMP/server.log" 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null; rm -rf "$TMP"' EXIT
until curl -s -o /dev/null "http://127.0.0.1:$PORT/"; do sleep 0.5; done

echo "модель: $MODEL, кусок: $CHUNK с"
echo "свободно памяти до: $(memory_pressure | tail -1 | grep -o '[0-9]*%')"
for i in $(seq 0 $((COUNT - 1))); do
  ffmpeg -v error -y -ss $((START + i * CHUNK)) -t "$CHUNK" -i "$WAV" "$TMP/c.wav"
  T0=$(python3 -c 'import time; print(time.time())')
  TEXT=$(curl -s "http://127.0.0.1:$PORT/inference" -F file=@"$TMP/c.wav" -F response_format=text -F language=ru)
  T1=$(python3 -c 'import time; print(time.time())')
  printf "%5.1f с | %s\n" $((T1 - T0)) "$(echo $TEXT | tr '\n' ' ' | cut -c1-110)"
done
echo "память сервера: $(($(ps -o rss= -p $SERVER) / 1024)) МБ"
echo "свободно памяти после: $(memory_pressure | tail -1 | grep -o '[0-9]*%')"
