#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"
IF=${1:-enp0s8}
RATE=2Mbit
DELAY=${3:-50ms}
LOSS=${4:-2%}

echo "[$(timestamp)] [*] Apply netem on $IF rate=$RATE delay=$DELAY loss=$LOSS"
sudo tc qdisc del dev "$IF" root 2>/dev/null || true
sudo tc qdisc add dev "$IF" root handle 1: htb default 10
sudo tc class add dev "$IF" parent 1: classid 1:10 htb rate "$RATE" ceil "$RATE"
sudo tc qdisc add dev "$IF" parent 1:10 handle 10: netem delay "$DELAY" loss "$LOSS"
tc -s qdisc show dev "$IF" | sed 's/^/  /'