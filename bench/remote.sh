# bench/remote.sh
#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/remote_hosts.env"

sshrun() {
  local host=$1; shift
  sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no "$USER@$host" "$@"
}
sshrun_bg() {
  local host=$1; shift
  # nohup 백그라운드 실행
  sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no "$USER@$host" "nohup bash -lc '$*' >/dev/null 2>&1 & echo \$!" 
}
push() { # $1 host, $2 local_path, $3 remote_path
  sshpass -p "$PASS" scp -o StrictHostKeyChecking=no -r "$2" "$USER@$1:$3"
}
pull() { # $1 host, $2 remote_path, $3 local_path
  sshpass -p "$PASS" scp -o StrictHostKeyChecking=no -r "$USER@$1:$2" "$3"
}
