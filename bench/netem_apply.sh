#!/usr/bin/env bash
# netem_apply.sh — HTB + netem 혼잡 주입/표시/해제 유틸
# 사용법:
#   ./netem_apply.sh on  [IF] [RATE] [DELAY] [JITTER] [LOSS] [LOSS_CORR] [DUP] [REORDER] [LIMIT]
#   ./netem_apply.sh off [IF]
#   ./netem_apply.sh show [IF]
#
# 예시:
#   ./netem_apply.sh on  enp0s8 500kbit 50ms 5ms 2% 25% 0.1% 0.2% 1000
#   ./netem_apply.sh off enp0s8
#   ./netem_apply.sh show enp0s8
#
# 기본값:
#   IF=enp0s8 RATE=500kbit DELAY=50ms JITTER=0ms LOSS=2% LOSS_CORR=0% DUP=0% REORDER=0% LIMIT=1000

set -euo pipefail

# --- 공통 유틸 (common.sh이 있으면 timestamp 사용) ---
if [[ -f "$(dirname "$0")/common.sh" ]]; then
  # shellcheck source=/dev/null
  source "$(dirname "$0")/common.sh"
  if ! declare -F timestamp >/dev/null; then
    timestamp() { date -Iseconds; }
  fi
else
  timestamp() { date -Iseconds; }
fi

cmd="${1:-}"
IF="${2:-enp0s8}"

# on 모드 인자 (순서 주의)
RATE="${3:-500kbit}"
DELAY="${4:-50ms}"
JITTER="${5:-0ms}"
LOSS="${6:-2%}"
LOSS_CORR="${7:-0%}"
DUP="${8:-0%}"
REORDER="${9:-0%}"
LIMIT="${10:-1000}"     # netem queue limit (# of packets)

usage() {
  cat <<EOF
Usage:
  $0 on  [IF] [RATE] [DELAY] [JITTER] [LOSS] [LOSS_CORR] [DUP] [REORDER] [LIMIT]
  $0 off [IF]
  $0 show [IF]

Defaults:
  IF=enp0s8 RATE=500kbit DELAY=50ms JITTER=0ms LOSS=2% LOSS_CORR=0% DUP=0% REORDER=0% LIMIT=1000

Examples:
  $0 on  enp0s8 300kbit 70ms 10ms 3% 20% 0.1% 0.2% 2000
  $0 off enp0s8
  $0 show enp0s8
EOF
}

show_qdisc() {
  local ifc="$1"
  tc -s qdisc show dev "$ifc" | sed 's/^/  /'
  tc class show dev "$ifc" | sed 's/^/  /' || true
}

apply_on() {
  local ifc="$1"
  local rate="$2" delay="$3" jitter="$4" loss="$5" lc="$6" dup="$7" reorder="$8" limit="$9"

  echo "[$(timestamp)] [*] Apply netem on ${ifc}"
  echo "              rate=${rate}, delay=${delay} ± ${jitter}, loss=${loss} (corr ${lc}), dup=${dup}, reorder=${reorder}, limit=${limit}"

  # 기존 qdisc 제거
  sudo tc qdisc del dev "$ifc" root 2>/dev/null || true

  # HTB 루트 + 클래스로 대역폭 제한
  sudo tc qdisc add dev "$ifc" root handle 1: htb default 10
  sudo tc class add dev "$ifc" parent 1: classid 1:10 htb rate "$rate" ceil "$rate"

  # netem 인자 조합
  # delay [jitter] [distribution]  loss [p% [correlation]]  duplicate [p%]  reorder [p% [correlation]]  limit [packets]
  # 지터가 0이면 생략
  local delay_args=()
  if [[ "$jitter" != "0ms" && "$jitter" != "0" ]]; then
    delay_args=(delay "$delay" "$jitter")
  else
    delay_args=(delay "$delay")
  fi

  local loss_args=()
  if [[ "$LOSS_CORR" != "0%" && "$LOSS_CORR" != "0" ]]; then
    loss_args=(loss "$loss" "$lc")
  else
    loss_args=(loss "$loss")
  fi

  local dup_args=()
  if [[ "$dup" != "0%" && "$dup" != "0" ]]; then
    dup_args=(duplicate "$dup")
  fi

  local reord_args=()
  if [[ "$reorder" != "0%" && "$reorder" != "0" ]]; then
    reord_args=(reorder "$reorder")
  fi

  sudo tc qdisc add dev "$ifc" parent 1:10 handle 10: netem \
    "${delay_args[@]}" \
    "${loss_args[@]}" \
    "${dup_args[@]}" \
    "${reord_args[@]}" \
    limit "$limit"

  echo "[$(timestamp)] [*] qdisc status:"
  show_qdisc "$ifc"
}

apply_off() {
  local ifc="$1"
  echo "[$(timestamp)] [*] Delete qdisc on ${ifc}"
  sudo tc qdisc del dev "$ifc" root 2>/dev/null || true
  echo "[$(timestamp)] [*] qdisc status:"
  show_qdisc "$ifc" || true
}

case "$cmd" in
  on)
    apply_on "$IF" "$RATE" "$DELAY" "$JITTER" "$LOSS" "$LOSS_CORR" "$DUP" "$REORDER" "$LIMIT"
    ;;
  off)
    apply_off "$IF"
    ;;
  show)
    echo "[$(timestamp)] [*] qdisc status on ${IF}"
    show_qdisc "$IF"
    ;;
  -h|--help|"")
    usage
    ;;
  *)
    echo "Unknown command: $cmd"; usage; exit 1 ;;
esac
