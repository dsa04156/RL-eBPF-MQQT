#!/usr/bin/env bash
# One-touch runner with foreground logging for EDA + remote pub/sub
# usage: ./run_eda_shadow.sh {start|start-fg|stop|status|logs}

set -u

### ==== CONFIG ====
BROKER="192.168.0.1"
PORT="23232"

PUB_HOST="192.168.0.2"
SUB_HOST="192.168.0.3"
SSH_USER="sslab"
SSH_PASS="1231"

PUBLISHERS=5
PUB_RATE=2000
TOPIC_PREFIX="bench/foo"
PUB_QOS=1
SUB_COUNT=1
SUB_QOS=1

INTERVAL_S=0.25
CONTROL_MIN_SEC=0.75
TAIL_USE_P=99
TARGET_P_MS=80
RL_EPSILON=0.6

# Paths (absolute!)
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # /home/sslab/mqtt-ebpf-edge/bench
ROOT_DIR="$(cd "$BASE_DIR/.." && pwd)"                     # /home/sslab/mqtt-ebpf-edge
PY_FILE="$ROOT_DIR/bpf/eda_rl.py"                          # <-- 핵심!
LOG_DIR="$HOME/mqtt-ebpf-edge/results"
OUT_FILE="$LOG_DIR/eda_shadow_fast.jsonl"
ERR_FILE="${OUT_FILE%.jsonl}.err"
RL_LOG="$LOG_DIR/rl/eda_rl_shadow.jsonl"

### ==== HELPERS ====
say() { printf '%s\n' "$*" >&2; }
sshdo() {
  local host="$1"; shift
  sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no -o BatchMode=no \
    "${SSH_USER}@${host}" "bash -lc '$*'"
}

check_deps() {
  local missing=0
  command -v sshpass >/dev/null || { say "[MISS] sshpass"; missing=1; }
  command -v mosquitto_pub >/dev/null || { say "[MISS] mosquitto_pub"; missing=1; }
  command -v mosquitto_sub >/dev/null || { say "[MISS] mosquitto_sub"; missing=1; }
  command -v python3 >/dev/null || { say "[MISS] python3"; missing=1; }
  command -v sudo >/dev/null || { say "[MISS] sudo"; missing=1; }
  [ -f "$PY_FILE" ] || { say "[MISS] $PY_FILE"; missing=1; }
  [ $missing -eq 0 ] || { say "[ERR] dependency missing. abort."; exit 1; }
}

mklogdirs() { mkdir -p "$LOG_DIR" "$LOG_DIR/rl"; }

start_agent_bg() {
  mklogdirs
  # background + quiet (기존 방식)
  sudo -E nohup env \
    MQTT_HOST="$BROKER" MQTT_PORT="$PORT" CONTROL_TOPIC="control/room1" \
    TELEMETRY_TOPIC="eda/latency" TAIL_USE_P="$TAIL_USE_P" TARGET_P_MS="$TARGET_P_MS" \
    EDA_OBSERVE=0 INTERVAL_S="$INTERVAL_S" CONTROL_MIN_SEC="$CONTROL_MIN_SEC" \
    RL_MODE=shadow RL_EPSILON="$RL_EPSILON" RL_LOG_PATH="$RL_LOG" \
    CTRL_RATE=5 CTRL_BATCH=5 \
    python3 -u "$PY_FILE" >> "$OUT_FILE" 2>> "$ERR_FILE" < /dev/null &
  echo "[LOCAL] EDA shadow started (bg pid=$!)"
}

start_agent_fg() {
  mklogdirs
  # foreground + live console logs
  say "[LOCAL] starting EDA shadow in FOREGROUND (Ctrl+C to stop only the agent)"
  set -o pipefail
  sudo -E env \
    MQTT_HOST="$BROKER" MQTT_PORT="$PORT" CONTROL_TOPIC="control/room1" \
    TELEMETRY_TOPIC="eda/latency" TAIL_USE_P="$TAIL_USE_P" TARGET_P_MS="$TARGET_P_MS" \
    EDA_OBSERVE=0 INTERVAL_S="$INTERVAL_S" CONTROL_MIN_SEC="$CONTROL_MIN_SEC" \
    RL_MODE=shadow RL_EPSILON="$RL_EPSILON" RL_LOG_PATH="$RL_LOG" \
    CTRL_RATE=5 CTRL_BATCH=5 \
    python3 -u "$PY_FILE" 2>&1 | tee -a "$OUT_FILE"
}

stop_agent() { sudo pkill -f "$PY_FILE" || true; echo "[LOCAL] EDA shadow stopped"; }

start_publishers() {
  local cmd="
mkdir -p /tmp/pub_logs
for t in \$(seq 1 $PUBLISHERS); do
  nohup setsid bash -c \
   \"seq 1000000000 | pv -q -l -L $PUB_RATE 2>/dev/null \
     | mosquitto_pub -h $BROKER -p $PORT -t ${TOPIC_PREFIX}\$t -q $PUB_QOS -l\" \
   >/tmp/pub_logs/pub_\$t.log 2>&1 &
done
pgrep -af 'mosquitto_pub.*${TOPIC_PREFIX}' || true
"
  sshdo "$PUB_HOST" "$cmd" || { say "[ERR] publisher start failed"; exit 1; }
  echo "[PUB@$PUB_HOST] started"
}

stop_publishers() {
  local cmd="
pkill -f 'mosquitto_pub.*${TOPIC_PREFIX}' || true
pkill -f 'pv -q -l -L' || true
pkill -f '^seq 1000000000$' || true
"
  sshdo "$PUB_HOST" "$cmd" || true
  echo "[PUB@$PUB_HOST] stopped"
}

start_subscribers() {
  local cmd="
mkdir -p /tmp/sub_logs
for i in \$(seq 1 $SUB_COUNT); do
  nohup setsid mosquitto_sub -h $BROKER -p $PORT -t 'bench/#' -q $SUB_QOS \
    >/tmp/sub_logs/sub_\$i.log 2>&1 &
done
pgrep -af \"mosquitto_sub -h $BROKER -p $PORT -t bench/#\" || true
"
  sshdo "$SUB_HOST" "$cmd" || { say "[ERR] subscriber start failed"; exit 1; }
  echo "[SUB@$SUB_HOST] started"
}

stop_subscribers() {
  local cmd="pkill -f \"mosquitto_sub -h $BROKER -p $PORT -t bench/#\" || true"
  sshdo "$SUB_HOST" "$cmd" || true
  echo "[SUB@$SUB_HOST] stopped"
}

status_all() {
  echo "=== STATUS ==="
  echo "[LOCAL] EDA:"
  pgrep -af "$PY_FILE" || echo "  (no process)"
  echo "[PUB@$PUB_HOST]:"
  sshdo "$PUB_HOST" "pgrep -af 'mosquitto_pub|pv -q -l -L|^seq 1000000000$' || echo '  (no process)'" || true
  echo "[SUB@$SUB_HOST]:"
  sshdo "$SUB_HOST" "pgrep -af \"mosquitto_sub -h $BROKER -p $PORT -t bench/#\" || echo '  (no process)'" || true
  echo "[FILES] OUT=$OUT_FILE  ERR=$ERR_FILE  RL=$RL_LOG"
}

logs_tail() {
  echo "---- LOCAL OUT ----"; tail -n 50 "$OUT_FILE" 2>/dev/null || true
  echo "---- LOCAL ERR ----"; tail -n 50 "$ERR_FILE" 2>/dev/null || true
  echo "---- RL LOG    ----"; tail -n 50 "$RL_LOG" 2>/dev/null || true
  echo "---- PUB logs@${PUB_HOST} ----"
  sshdo "$PUB_HOST" "tail -n 20 /tmp/pub_logs/pub_*.log 2>/dev/null || true" || true
  echo "---- SUB logs@${SUB_HOST} ----"
  sshdo "$SUB_HOST" "tail -n 20 /tmp/sub_logs/sub_*.log 2>/dev/null || true" || true
}

usage() {
  cat <<EOF
Usage: $0 {start|start-fg|stop|status|logs}
  start     : agent(bg) + remote pub/sub
  start-fg  : agent(FOREGROUND, console logs) + remote pub/sub
  stop      : stop pub/sub + agent
  status    : show processes
  logs      : tail last logs (local & remote)
EOF
}

### ==== MAIN ====
cmd="${1:-}"; check_deps
case "$cmd" in
  start)     start_agent_bg; start_publishers; start_subscribers ;;
  start-fg)  start_publishers; start_subscribers; start_agent_fg ;;
  stop)      stop_publishers; stop_subscribers; stop_agent ;;
  status)    status_all ;;
  logs)      logs_tail ;;
  *)         usage; exit 1 ;;
esac
