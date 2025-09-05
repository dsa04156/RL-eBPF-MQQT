#!/usr/bin/env bash
set -euo pipefail
# set -x  # 필요 시 디버그

source "$(dirname "$0")/common.sh"
source "$(dirname "$0")/remote_hosts.env"
source "$(dirname "$0")/remote.sh"

OUT=~/mqtt-ebpf-edge/results/baseline
mkdir -p "$OUT"
IF=$(detect_if)

pgrep -x mosquitto >/dev/null || echo "[WARN] mosquitto가 보이지 않습니다. 브로커(1883) 확인 요망."

# 백그라운드 잡을 확실히 정리
cleanup() {
  echo "[$(timestamp)] [!] cleanup"
  bench/netem_off.sh "$IF" || true
  # 원격 프로세스 종료
  sshrun "$SUB_HOST" "pkill -f subscriber.py || true"
  sshrun "$PUB_HOST" "pkill -f publisher.py || true"
  # 남아있을 수 있는 SSH 백그라운드 세션 종료
  [ -n "${SUB_JOB-}" ] && kill "$SUB_JOB" 2>/dev/null || true
}
trap cleanup EXIT

# 1) 네트워크 조건 주입
bench/netem_on.sh "$IF" 500kbit 50ms 2%

# 2) 서브스크라이버 원격 실행 (원격 파일에 기록, **timeout 190s**)
echo "[$(timestamp)] [*] Start subscriber on $SUB_HOST"
sshrun "$SUB_HOST" "bash -lc '
  set -euo pipefail
  : > ~/subscriber_raw.log
  : > ~/latency_log.csv
  cd $SUB_DIR || exit 1
  # 190초 후 종료되도록 명시적 타임아웃
  timeout 190s bash -lc \"stdbuf -oL -eL python3 -u subscriber.py 2>&1 \
    | tee -a ~/subscriber_raw.log \
    | grep -E '^[0-9]+\.[0-9]+,latency_s,[0-9.]+' >> ~/latency_log.csv\"
'" & SUB_JOB=$!

sleep 3

# 3) 퍼블리셔 원격 실행 (원격 파일에 기록, **timeout 180s**)
echo "[$(timestamp)] [*] Start publisher on $PUB_HOST"
sshrun "$PUB_HOST" "bash -lc '
  set -euo pipefail
  : > ~/publisher_raw.log
  cd $PUB_DIR || exit 1
  echo \"[PUB] start \$(date +%F_%T)\" >> ~/publisher_raw.log
  timeout 180s bash -lc \"PYTHONUNBUFFERED=1 stdbuf -oL -eL python3 -u publisher.py >> ~/publisher_raw.log 2>&1\" || true
  echo \"[PUB] end \$(date +%F_%T)\" >> ~/publisher_raw.log
'"

# 4) 서브스크라이버 세션 종료 대기(퍼블리셔 종료 후 최대 10초 더)
#   → 남아있으면 강제 종료
for _ in $(seq 1 10); do
  if ! kill -0 "$SUB_JOB" 2>/dev/null; then break; fi
  sleep 1
done
kill "$SUB_JOB" 2>/dev/null || true

sleep 3

# 5) 로그 회수
echo "[$(timestamp)] [*] Pull logs"
pull "$SUB_HOST" "~/subscriber_raw.log" "$OUT/subscriber_raw.log" || echo "[WARN] subscriber_raw.log 회수 실패"
pull "$SUB_HOST" "~/latency_log.csv"   "$OUT/latency_log.csv"   || echo "[WARN] latency_log.csv 회수 실패"
pull "$PUB_HOST" "~/publisher_raw.log" "$OUT/publisher_raw.log" || echo "[WARN] publisher_raw.log 회수 실패"

echo "[*] File sizes:"; ls -l "$OUT" || true

# 6) 혼잡 해제 (cleanup에서도 보장되지만 정상 경로에서도 수행)
bench/netem_off.sh "$IF"

# 7) 간단 진단
[ ! -s "$OUT/subscriber_raw.log" ] && echo "[DIAG] subscriber_raw.log 비어있음 → SUB_HOST 실행/경로/BROKER 확인"
[ ! -s "$OUT/latency_log.csv" ]   && echo "[DIAG] latency_log.csv 비어있음 → subscriber 출력 패턴 확인"
[ ! -s "$OUT/publisher_raw.log" ] && echo "[DIAG] publisher_raw.log 비어있음 → 퍼블리셔 실행/출력 확인"

echo "[$(timestamp)] [*] Baseline done → $OUT"
