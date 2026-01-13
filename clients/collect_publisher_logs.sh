#!/usr/bin/env bash
set -euo pipefail
RUN_ID=${RUN_ID:-$(date +%Y%m%d_%H%M%S)}
SERVICE_LABEL=${SERVICE_LABEL:-publisher}    # compose 서비스명
DST_DIR=${DST_DIR:-./pub_logs}
OUT=${OUT:-publisher_logs_${RUN_ID}.tar.gz}
mkdir -p "$DST_DIR"

CONTS=$(docker ps -q -f "label=com.docker.compose.service=${SERVICE_LABEL}" || true)
if [ -z "$CONTS" ]; then
  echo "[WARN] no containers with service label: ${SERVICE_LABEL}"
else
  for id in $CONTS; do
    name=$(docker inspect --format '{{.Name}}' "$id" | sed 's#^/##')
    started=$(docker inspect --format '{{.State.StartedAt}}' "$id")
    echo "[*] docker logs → $DST_DIR/${name}.log"
    docker logs --since "$started" --timestamps "$id" > "$DST_DIR/${name}.log" 2>&1 || true
  done
fi

tar -C "$DST_DIR" -czf "$OUT" .
echo "[OK] packed → $OUT"
echo "[*] tar content:"; tar -tzf "$OUT" | head -n 20

