#!/usr/bin/env bash
# Heavy IoT-style dynamic netem profile
# Usage:
#   sudo IF=enp0s8 bash bench/netem_iot_heavy.sh

set -euo pipefail

IF=${IF:-enp0s8}

log() { echo "[netem-iot-heavy] $(date +%T) $*" >&2; }

cleanup() {
  log "cleanup: tc qdisc del dev $IF root"
  tc qdisc del dev "$IF" root 2>/dev/null || true
}
trap cleanup EXIT

apply_clear() {
  log "phase=$1 (clear, no shaping)"
  tc qdisc del dev "$IF" root 2>/dev/null || true
}

apply_netem() {
  local name=$1
  local rate=$2   # 예: 10mbit or "none"
  local delay=$3  # ms
  local jitter=$4 # ms
  local loss=$5   # %
  if [[ "$rate" == "none" ]]; then
    log "phase=$name delay=${delay}ms jitter=${jitter}ms loss=${loss}%"
    tc qdisc replace dev "$IF" root netem delay ${delay}ms ${jitter}ms distribution normal loss ${loss}%
  else
    log "phase=$name rate=${rate} delay=${delay}ms jitter=${jitter}ms loss=${loss}%"
    tc qdisc replace dev "$IF" root netem rate ${rate} delay ${delay}ms ${jitter}ms distribution normal loss ${loss}%
  fi
}

log "interface=$IF — start HEAVY IoT-ish profile"

# 1) Warm-up normal-ish (이미 살짝 나쁨) — 120s
#    8mbit, 50ms, 0.5% loss
apply_netem "WARMUP_NORMAL" "8mbit" 50 10 0.5
sleep 120

# 2) Short heavy spike 1 — 45s
#    2mbit, 150ms, 3% loss
apply_netem "BURST_HEAVY_1" "2mbit" 150 40 3.0
sleep 45

# 3) 정상으로 약간 회복 — 90s
apply_netem "NORMAL_1" "8mbit" 60 10 0.5
sleep 90

# 4) Short heavy spike 2 — 45s
#    1mbit, 200ms, 5% loss
apply_netem "BURST_HEAVY_2" "1mbit" 200 60 5.0
sleep 45

# 5) Long moderate (센서 steady) — 180s
#    5mbit, 70ms, 1% loss
apply_netem "MODERATE_LONG" "5mbit" 70 15 1.0
sleep 180

# 6) Backhaul degradation (길게 나쁜 상태) — 180s
#    1mbit, 220ms, 4% loss
apply_netem "BACKHAUL_BAD" "1mbit" 220 80 4.0
sleep 180

# 7) Near-blackout (진짜 개판 구간) — 60s
#    512kbit, 400ms, 10% loss
apply_netem "BLACKOUT_LIKE" "512kbit" 400 100 10.0
sleep 60

# 8) Recovery (천천히 회복) — 240s
#    4mbit, 120ms, 1% loss
apply_netem "RECOVERY" "4mbit" 120 30 1.0
sleep 240

# 9) 마지막 정상 — 120s
apply_netem "FINAL_NORMAL" "8mbit" 60 10 0.5
sleep 120

apply_clear "END_CLEAR"
log "done"
