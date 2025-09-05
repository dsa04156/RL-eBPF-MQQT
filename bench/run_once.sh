#!/usr/bin/env bash
set -euo pipefail

# ======= 환경값 (필요시 수정) =======
MODE=${MODE:-baseline}                     # baseline | ours
RUN_ID=${RUN_ID:-$(date +%Y%m%d_%H%M%S)}   # ex) base_run1, ours_run1 식으로 넘겨도 됨

# 브로커/원격 호스트
BROKER_HOST=${BROKER_HOST:-192.168.0.1}
BROKER_PORT=${BROKER_PORT:-23232}
PUB_HOST=${PUB_HOST:-192.168.0.2}
SUB_HOST=${SUB_HOST:-192.168.0.3}
USER=${USER_NAME:-sslab}

# 원격 경로(각 호스트에서 compose 있는 디렉토리)
PUB_DIR=${PUB_DIR:-~/jinuk/clients}        # publisher-compose.yml 있는 곳
SUB_DIR=${SUB_DIR:-~/jinuk/clients}        # subscriber-compose.yml 있는 곳

# 부하 프로파일
PUB_N=${PUB_N:-20}
SUB_N=${SUB_N:-10}
RATE=${RATE:-50}
BATCH=${BATCH:-1}
QOS=${QOS:-1}
PAYLOAD_BYTES=${PAYLOAD_BYTES:-512}

# 러닝 시간(초)
DUR=${DUR:-180}
SUB_EXTRA_WAIT=${SUB_EXTRA_WAIT:-10}

# 결과 저장 루트(브로커 PC)
BASE=~/mqtt-ebpf-edge/results
OUT_DIR=$BASE/$MODE
SUB_OUT=$OUT_DIR/subs/$RUN_ID
PUB_OUT=$OUT_DIR/pubs/$RUN_ID
EDA_LOG_PATH=$OUT_DIR/eda_log_${RUN_ID}.jsonl

mkdir -p "$SUB_OUT" "$PUB_OUT"

echo "[*] RUN start: mode=$MODE run_id=$RUN_ID"
echo "[*] load: PUB_N=$PUB_N, SUB_N=$SUB_N, RATE=$RATE, BATCH=$BATCH, QOS=$QOS, PAYLOAD_BYTES=$PAYLOAD_BYTES"

# ======= ours 모드면 eBPF 에이전트 시작 =======
EDA_PID_FILE=/tmp/eda_${RUN_ID}.pid
if [ "$MODE" = "ours" ]; then
  echo "[*] start eBPF eda.py on broker (background)"
  # eda.py 위치: ~/mqtt-ebpf-edge/eda.py (필요시 경로 조정)
  ( cd ~/mqtt-ebpf-edge
    sudo -E MQTT_HOST="$BROKER_HOST" MQTT_PORT="$BROKER_PORT" EDA_OBSERVE=0 \
      TH_RTT_US=60000 TH_RETRANS=1 TH_SNDBUF=$((256*1024)) TH_RCVBUF=$((256*1024)) \
      CONTROL_MIN_SEC=2 CTRL_RATE=5 CTRL_BATCH=5 \
      python3 -u eda.py | tee "$EDA_LOG_PATH"
  ) > /dev/null 2>&1 &
  echo $! > "$EDA_PID_FILE"
  sleep 1
fi

# ======= 원격: 퍼블리셔/서브스크 올리기 =======
echo "[*] start publishers on $PUB_HOST"
ssh -o StrictHostKeyChecking=no ${USER}@${PUB_HOST} "
  set -euo pipefail
  cd $PUB_DIR
  RATE=$RATE BATCH=$BATCH QOS=$QOS PAYLOAD_BYTES=$PAYLOAD_BYTES \
  docker compose -f publisher-compose.yml up -d --build --scale publisher=$PUB_N
"

echo "[*] start subscribers on $SUB_HOST"
ssh -o StrictHostKeyChecking=no ${USER}@${SUB_HOST} "
  set -euo pipefail
  cd $SUB_DIR
  mkdir -p ./results
  docker compose -f subscriber-compose.yml up -d --build --scale subscriber=$SUB_N
"

# ======= 러닝 =======
echo "[*] running for $DUR sec ..."
sleep "$DUR"

# ======= 종료(퍼브 → 섭) =======
echo "[*] stop publishers"
ssh -o StrictHostKeyChecking=no ${USER}@${PUB_HOST} "
  cd $PUB_DIR && docker compose -f publisher-compose.yml down
"

echo "[*] stop subscribers (wait ${SUB_EXTRA_WAIT}s)"
sleep "$SUB_EXTRA_WAIT"
ssh -o StrictHostKeyChecking=no ${USER}@${SUB_HOST} "
  cd $SUB_DIR && docker compose -f subscriber-compose.yml down
"

# ======= ours 모드면 eBPF 종료 =======
if [ "$MODE" = "ours" ] && [ -f "$EDA_PID_FILE" ]; then
  echo "[*] stop eda.py"
  sudo kill $(cat "$EDA_PID_FILE") 2>/dev/null || true
  rm -f "$EDA_PID_FILE"
fi

# ======= 원격에서 tar 묶기 =======
echo "[*] pack logs on subscriber host"
ssh -o StrictHostKeyChecking=no ${USER}@${SUB_HOST} "
  cd $SUB_DIR
  RUN_ID=$RUN_ID ./collect_subscriber_logs.sh
"

echo "[*] pack logs on publisher host"
ssh -o StrictHostKeyChecking=no ${USER}@${PUB_HOST} "
  cd $PUB_DIR
  RUN_ID=$RUN_ID SERVICE_LABEL=publisher ./collect_publisher_logs.sh
"

# ======= 브로커로 회수 =======
echo "[*] pull subscriber tar"
scp -o StrictHostKeyChecking=no ${USER}@${SUB_HOST}:$SUB_DIR/subscriber_logs_${RUN_ID}.tar.gz "$SUB_OUT"/
tar -C "$SUB_OUT" -xzf "$SUB_OUT/subscriber_logs_${RUN_ID}.tar.gz"
rm -f "$SUB_OUT/subscriber_logs_${RUN_ID}.tar.gz"

echo "[*] pull publisher tar"
if scp -o StrictHostKeyChecking=no ${USER}@${PUB_HOST}:$PUB_DIR/publisher_logs_${RUN_ID}.tar.gz "$PUB_OUT"/; then
  tar -C "$PUB_OUT" -xzf "$PUB_OUT/publisher_logs_${RUN_ID}.tar.gz"
  rm -f "$PUB_OUT/publisher_logs_${RUN_ID}.tar.gz"
else
  echo "[WARN] publisher tar not found (optional)"
fi

# ======= 요약 안내 =======
echo "[OK] gathered → $OUT_DIR (run_id=$RUN_ID)"
echo "[*] subscriber CSV files: $(find "$SUB_OUT" -name "*_lat.csv" | wc -l)"
echo "[*] total lines (lat.csv): $(cat "$SUB_OUT"/*_lat.csv 2>/dev/null | wc -l || true)"

# ======= 단일 요약 CSV 생성(선택) =======
if [ -f ~/mqtt-ebpf-edge/bench/analyze.py ]; then
  echo "[*] generate single summary CSV"
  cd ~/mqtt-ebpf-edge
  python3 bench/analyze.py --mode single \
    --glob "$OUT_DIR/subs/$RUN_ID/*_lat.csv" \
    --out  "$OUT_DIR/summary_${RUN_ID}.csv" \
    --per-host-out "$OUT_DIR/summary_${RUN_ID}_per_host.csv" || true
fi

echo "[DONE] run_once: $MODE / $RUN_ID"
