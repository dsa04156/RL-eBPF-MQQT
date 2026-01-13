#!/usr/bin/env bash
set -euo pipefail
RUN_ID=${RUN_ID:-$(date +%Y%m%d_%H%M%S)}
SRC_DIR=${SRC_DIR:-./results}
OUT=${OUT:-subscriber_logs_${RUN_ID}.tar.gz}

[ -d "$SRC_DIR" ] || { echo "[ERR] not found: $SRC_DIR"; exit 1; }

echo "[*] preview files:"; ls -l "$SRC_DIR" | head -n 20 || true
echo "[*] csv line counts (top 5):"
for f in $(ls "$SRC_DIR"/*_lat.csv 2>/dev/null | head -n 5); do wc -l "$f"; done || true

tar -C "$SRC_DIR" -czf "$OUT" .
echo "[OK] packed → $OUT"
echo "[*] tar content:"; tar -tzf "$OUT" | head -n 20

