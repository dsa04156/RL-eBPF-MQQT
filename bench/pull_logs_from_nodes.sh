#!/usr/bin/env bash
set -euo pipefail

SSH_PASS="1231"
SSH_CMD="sshpass -p $SSH_PASS scp -o StrictHostKeyChecking=no"

MODE=${MODE:-baseline}     # baseline | ours
RUN_ID=${RUN_ID:-$(date +%Y%m%d_%H%M%S)}
SUB_HOST=${SUB_HOST:-192.168.0.3}
PUB_HOST=${PUB_HOST:-192.168.0.2}
USER=${USER_NAME:-sslab}
SUB_TAR=${SUB_TAR:-jinuk/clients/subscriber_logs_${RUN_ID}.tar.gz}
PUB_TAR=${PUB_TAR:-jinuk/clients/publisher_logs_${RUN_ID}.tar.gz}
SUB_DOWN_TAR=${SUB_DOWN_TAR:-subscriber_logs_${RUN_ID}.tar.gz}
PUB_DOWN_TAR=${PUB_DOWN_TAR:-publisher_logs_${RUN_ID}.tar.gz}
BASE=~/mqtt-ebpf-edge/results
OUT_DIR=$BASE/$MODE
SUB_OUT=$OUT_DIR/subs/$RUN_ID
PUB_OUT=$OUT_DIR/pubs/$RUN_ID
EDA_OUT=$OUT_DIR
mkdir -p "$SUB_OUT" "$PUB_OUT"

echo "[*] pull subscriber logs"
$SSH_CMD ${USER}@${SUB_HOST}:~/${SUB_TAR} "$SUB_OUT"/
tar -C "$SUB_OUT" -xzf "$SUB_OUT/$SUB_DOWN_TAR"; rm -f "$SUB_OUT/$SUB_DOWN_TAR"

echo "[*] pull publisher logs"
if $SSH_CMD ${USER}@${PUB_HOST}:~/${PUB_TAR} "$PUB_OUT"/; then
  tar -C "$PUB_OUT" -xzf "$PUB_OUT/$PUB_DOWN_TAR"; rm -f "$PUB_OUT/$PUB_DOWN_TAR"
else
  echo "[WARN] publisher logs not found (optional)"
fi

# ours 또는 generated 모드일 때 eda_log 보관
if [ "$MODE" = "ours" ] && [ -f "$EDA_OUT/eda_log.jsonl" ]; then
  cp "$EDA_OUT/eda_log.jsonl" "$OUT_DIR/eda_log_${RUN_ID}.jsonl"
elif [ "$MODE" = "generated" ] && [ -f "$EDA_OUT/eda_${RUN_ID}.jsonl" ]; then
  echo "[*] eBPF log already in correct location: eda_${RUN_ID}.jsonl"
fi

echo "[OK] gathered → $OUT_DIR (run_id=$RUN_ID)"
echo "[*] subscriber CSV counts:"; find "$SUB_OUT" -name "*_lat.csv" | wc -l
echo "[*] total lines (lat.csv):"; cat "$SUB_OUT"/*_lat.csv 2>/dev/null | wc -l || true
echo "[hint] analyze: bench/analyze.py"
