# bench/common.sh
#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.."; pwd)

detect_if() {
  # lo 제외, 첫 번째 NIC
  ip -o link | awk -F': ' '$2!="lo"{print $2}' | head -n1
}
timestamp(){ date +"%F %T"; }
