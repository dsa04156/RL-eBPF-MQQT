# bench/run_ours_remote.sh  (baseline과 동일 흐름 + eda 추가, 확정본)
#!/usr/bin/env bash
set -euo pipefail
# set -x  # 필요 시 디버그

source "$(dirname "$0")/common.sh"
source "$(dirname "$0")/remote_hosts.env"
source "$(dirname "$0")/remote.sh"

OUT=~/mqtt-ebpf-edge/results/ours
mkdir -p "$OUT"
IF=$(detect_if)

# 정리 루틴: 어떤 경로로 끝나도 네트워크/원격 프로세스/EDA 정리
cleanup() {
  echo "[$(timestamp)] [!] cleanup"
  bench/netem_off.sh "$IF" || true
  sshrun "$SUB_HOST" "pkill -f subscriber.py || true"
  sshrun "$PUB_HOST" "pkill -f publisher.py || true"
  [ -n "${SUB_JOB-}" ] && kill "$SUB_JOB" 2>/dev/null || true
  [ -n "${EDA_PID-}" ] && kill "$EDA_PID" 2>/dev/null || true
}
trap cleanup EXIT

echo "[$(timestamp)] [*] Start eda.py on broker"
# eda.py 경로 자동탐색 (~/bpf/eda.py → ~/mqtt-ebpf-edge/bpf/eda.py → ~/eda.py)
# EDA는 로컬에서 백그라운드로 실행하고, 로그는 브로커 로컬 파일에 저장
timeout 200s bash -lc '
  set -euo pipefail
  if   [ -f ~/bpf/eda.py ]; then cd ~/bpf; TGT=~/bpf/eda.py
  elif [ -f ~/mqtt-ebpf-edge/bpf/eda.py ]; then cd ~/mqtt-ebpf-edge/bpf; TGT=~/mqtt-ebpf-edge/bpf/eda.py
  elif [ -f ~/eda.py ]; then cd ~; TGT=~/eda.py
  else echo "[ERR] eda.py not found"; exit 2; fi
  echo "[EDA] using $TGT" | tee -a ~/mqtt-ebpf-edge/results/ours/eda_log.jsonl
  stdbuf -oL -eL sudo -E PYTHONUNBUFFERED=1 python3 -u "$TGT" 2>&1 | tee -a ~/mqtt-ebpf-edge/results/ours/eda_log.jsonl
' & EDA_PID=$!
sleep 3

# 1) 네트워크 조건 주입 (브로커 NIC)
bench/netem_on.sh "$IF" 500kbit 50ms 2%

# 2) 서브스크라이버 원격 실행 (원격 파일에 기록, timeout 190s)
echo "[$(timestamp)] [*] Start subscriber on $SUB_HOST"
sshrun "$SUB_HOST" "bash -lc '
  set -euo pipefail
  : > ~/subscriber_raw.log
  : > ~/latency_log.csv
  cd $SUB_DIR || exit 1
  timeout 190s bash -lc \"stdbuf -oL -eL python3 -u subscriber.py 2>&1 \
    | tee -a ~/subscriber_raw.log \
    | grep -E '^[0-9]+\.[0-9]+,latency_s,[0-9.]+' >> ~/latency_log.csv\"
'" & SUB_JOB=$!

sleep 3

# 3) 퍼블리셔 원격 실행 (원격 파일에 기록, timeout 180s)
echo "[$(timestamp)] [*] Start publisher on $PUB_HOST"
sshrun "$PUB_HOST" "bash -lc '
  set -euo pipefail
  : > ~/publisher_raw.log
  cd $PUB_DIR || exit 1
  echo \"[PUB] start \$(date +%F_%T)\" >> ~/publisher_raw.log
  timeout 180s bash -lc \"PYTHONUNBUFFERED=1 stdbuf -oL -eL python3 -u publisher.py >> ~/publisher_raw.log 2>&1\" || true
  echo \"[PUB] end \$(date +%F_%T)\" >> ~/publisher_raw.log
'"

# 4) 서브스크라이버 세션 종료 대기(퍼블리셔 종료 후 최대 10초 더), 남아있으면 정리
for _ in $(seq 1 10); do
  if ! kill -0 "$SUB_JOB" 2>/dev/null; then break; fi
  sleep 1
done
kill "$SUB_JOB" 2>/dev/null || true

sleep 3

# 5) 로그 회수 (baseline과 동일 형식)
echo "[$(timestamp)] [*] Pull logs"
pull "$SUB_HOST" "~/subscriber_raw.log" "$OUT/subscriber_raw.log" || echo "[WARN] subscriber_raw.log 회수 실패"
pull "$SUB_HOST" "~/latency_log.csv"   "$OUT/latency_log.csv"   || echo "[WARN] latency_log.csv 회수 실패"
pull "$PUB_HOST" "~/publisher_raw.log" "$OUT/publisher_raw_remote.log" || echo "[WARN] publisher_raw_remote.log 회수 실패"

echo "[*] File sizes:"; ls -l "$OUT" || true

# 6) 혼잡 해제 + EDA 종료 (cleanup에서도 보장되지만 정상 경로에서도 수행)
bench/netem_off.sh "$IF"
kill "$EDA_PID" 2>/dev/null || true
echo "[$(timestamp)] [*] Ours done → $OUT"

# 7) 간단 진단
[ ! -s "$OUT/subscriber_raw.log" ]       && echo "[DIAG] subscriber_raw.log 비어있음 (SUB_HOST 실행/경로/BROKER 확인)"
[ ! -s "$OUT/latency_log.csv" ]          && echo "[DIAG] latency_log.csv 비어있음 (subscriber 출력 패턴 확인)"
[ ! -s "$OUT/publisher_raw_remote.log" ] && echo "[DIAG] publisher_raw_remote.log 비어있음 (퍼블리셔 실행/출력 확인)"
