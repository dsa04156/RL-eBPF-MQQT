#!/usr/bin/env bash
set -euo pipefail
cat <<'EOF'
BROKER=${BROKER:-192.168.0.1}
RAW=~/subscriber_raw.log
CSV=~/latency_log.csv
: > "$RAW"
: > "$CSV"

cd ~/jinuk/clients || { echo "[ERR] clients 디렉토리 없음"; exit 1; }

# 무버퍼링으로 즉시 흘려보내기
stdbuf -oL -eL python3 -u subscriber.py 2>&1 | tee -a "$RAW" | \
awk '
  # 0) 이미 CSV 포맷(ts,latency_s,value)이면 그대로 통과
  /^[0-9]+\.[0-9]+,latency_s,[0-9.]+$/ { print; fflush(stdout); next }

  # 1) 이하 예비 규칙: 문자열에서 latency_s= / latency_ms= / latency=..s / JSON 키 등
  #   (필요 시 살려 사용. 지금은 CSV가 바로 들어오므로 보조 수단)
  match($0, /latency_s=([0-9.]+)/, m)   { printf("%.6f,latency_s,%.6f\n", systime()+0, m[1]); fflush(stdout); next }
  match($0, /latency_ms=([0-9.]+)/, m)  { printf("%.6f,latency_s,%.6f\n", systime()+0, m[1]/1000.0); fflush(stdout); next }
  match($0, /latency=([0-9.]+)s/, m)    { printf("%.6f,latency_s,%.6f\n", systime()+0, m[1]); fflush(stdout); next }
  match($0, /"latency_ms"\s*:\s*([0-9.]+)/, m) { printf("%.6f,latency_s,%.6f\n", systime()+0, m[1]/1000.0); fflush(stdout); next }
  match($0, /"latency_s"\s*:\s*([0-9.]+)/, m)  { printf("%.6f,latency_s,%.6f\n", systime()+0, m[1]); fflush(stdout); next }

  # 매칭 안 되면 버림(로그는 RAW에 남음)
' | tee -a "$CSV"

EOF
