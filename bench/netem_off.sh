# bench/netem_off.sh
#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"
IF=${1:-enp0s8}
echo "[$(timestamp)] [*] Clear qdisc on $IF"
sudo tc qdisc del dev "$IF" root 2>/dev/null || true
tc qdisc show dev "$IF" | sed 's/^/  /'
