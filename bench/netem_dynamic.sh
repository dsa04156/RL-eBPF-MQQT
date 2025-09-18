#!/usr/bin/env bash
# Dynamic netem profile runner
# Usage:
#   sudo IF=eth0 PHASE_DUR=30 CYCLES=1 bash bench/netem_dynamic.sh
# Env:
#   IF           - network interface (default: eth0)
#   PHASE_DUR    - seconds per phase (default: 30)
#   CYCLES       - how many times to run all phases (default: 1)
#   RATE         - rate used in rate-limited phases (default varies per phase)
#   LOSS_PCT     - loss percent (default varies per phase)
#   DELAY_MS     - delay baseline in ms (default varies per phase)
#   JITTER_MS    - jitter in ms (default varies per phase)

set -euo pipefail

IF=${IF:-enp0s8}
PHASE_DUR=${PHASE_DUR:-30}
CYCLES=${CYCLES:-1}

log() { echo "[netem-dyn] $(date +%T) $*" >&2; }

cleanup() {
  log "cleanup: tc qdisc del dev $IF root"
  tc qdisc del dev "$IF" root 2>/dev/null || true
}
trap cleanup EXIT

apply_none() {
  log "phase=NONE (no shaping)"
  tc qdisc del dev "$IF" root 2>/dev/null || true
}

apply_delay_loss() {
  local delay=${DELAY_MS:-80}
  local jitter=${JITTER_MS:-20}
  local loss=${LOSS_PCT:-1}
  log "phase=DELAY_LOSS delay=${delay}ms jitter=${jitter}ms loss=${loss}%"
  tc qdisc replace dev "$IF" root netem delay ${delay}ms ${jitter}ms distribution normal loss ${loss}%
}

apply_rate_limit() {
  local rate=${RATE:-5mbit}
  local delay=${DELAY_MS:-60}
  local loss=${LOSS_PCT:-0.5}
  log "phase=RATE_LIMIT rate=${rate} delay=${delay}ms loss=${loss}%"
  # Modern netem supports 'rate'
  tc qdisc replace dev "$IF" root netem rate ${rate} delay ${delay}ms loss ${loss}%
}

apply_severe() {
  local rate=${RATE:-2mbit}
  local delay=${DELAY_MS:-120}
  local jitter=${JITTER_MS:-50}
  local loss=${LOSS_PCT:-2}
  log "phase=SEVERE rate=${rate} delay=${delay}ms jitter=${jitter}ms loss=${loss}%"
  tc qdisc replace dev "$IF" root netem rate ${rate} delay ${delay}ms ${jitter}ms distribution normal loss ${loss}%
}

run_phase() {
  local fn=$1
  $fn
  sleep "$PHASE_DUR"
}

log "interface=$IF phase_dur=${PHASE_DUR}s cycles=$CYCLES"

for ((i=1;i<=CYCLES;i++)); do
  log "cycle $i/${CYCLES} — start"
  run_phase apply_none
  run_phase apply_delay_loss
  run_phase apply_rate_limit
  run_phase apply_severe
  run_phase apply_none
  log "cycle $i/${CYCLES} — end"
done

log "done"
