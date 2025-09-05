#!/usr/bin/env bash
# collect_cpu_only.sh — 시스템/EDA CPU만 수집 (ON/OFF 각각 1회)
set -euo pipefail
export LC_ALL=C

LABEL="${LABEL:-run}"                                   # 예: OFF / ON
OUT="${OUT:-$HOME/results/cpu_${LABEL}_$(date +%Y%m%d_%H%M%S)}"
DURATION="${DURATION:-120}"                             # 권장 120~300초
EDA_PID="${EDA_PID:-}"                                  # 예: $(pgrep -f 'bpf/eda.py' | head -n1)

mkdir -p "$OUT"
echo "OUT=$OUT  LABEL=$LABEL  DURATION=$DURATION  EDA_PID=${EDA_PID:-<none>}"

need() { command -v "$1" >/dev/null 2>&1 || { echo "ERROR: $1 not found"; exit 1; }; }
need mpstat
need ps || true

# 종료 시 백그라운드 정리
cleanup_bg() {
  shopt -s nullglob
  for f in "$OUT"/pid_*; do
    [ -f "$f" ] || continue
    kill "$(cat "$f")" >/dev/null 2>&1 || true
  done
  shopt -u nullglob
}
trap cleanup_bg EXIT

# 1) 시스템 CPU: mpstat (마지막 Average: all의 idle% 사용)
mpstat -P ALL 1 "$DURATION" > "$OUT/mpstat.txt" & echo $! > "$OUT/pid_mpstat"

# 2) (옵션) EDA PID: 1Hz로 %CPU 샘플
if [ -n "$EDA_PID" ] && ps -p "$EDA_PID" >/dev/null 2>&1; then
  (
    i=0
    while [ "$i" -lt "$DURATION" ]; do
      # 첫 줄 헤더가 나오지 않게 %cpu= 형식 사용
      ps -p "$EDA_PID" -o %cpu= >> "$OUT/ps_cpu.txt" || true
      sleep 1
      i=$((i+1))
    done
  ) & echo $! > "$OUT/pid_ps"
else
  echo "INFO: skip EDA PID sampling" > "$OUT/ps_cpu.txt"
fi

# 대기
sleep "$DURATION"

# 3) 요약
python3 - <<'PY'
import os,statistics
out=os.environ["OUT"]; dur=int(os.environ.get("DURATION","0")); label=os.environ.get("LABEL","run")

def parse_mpstat_idle(p):
    try:
        lines=open(p,errors='ignore').read().splitlines()
    except:
        return None
    idle=None
    # 가장 마지막 "Average: all" 라인 탐색
    for ln in reversed(lines):
        s=ln.strip()
        if s.startswith("Average:") and (" all" in s or s.endswith("all")):
            parts=ln.split()
            try:
                idle=float(parts[-1])
                break
            except:
                pass
    return idle

def parse_ps_avg(p):
    if not os.path.exists(p): return None
    xs=[]
    for ln in open(p,errors='ignore'):
        ln=ln.strip()
        if not ln or ln.startswith("INFO:"): 
            continue
        try:
            xs.append(float(ln))
        except:
            pass
    return round(sum(xs)/len(xs),2) if xs else None

idle=parse_mpstat_idle(os.path.join(out,"mpstat.txt"))
sys_cpu = round(100.0 - idle, 2) if idle is not None else None
eda_cpu = parse_ps_avg(os.path.join(out,"ps_cpu.txt"))

with open(os.path.join(out,"summary.csv"),"w") as f:
    f.write("label,duration_s,system_cpu_pct_avg,eda_cpu_pct_avg\n")
    f.write(f"{label},{dur},{'' if sys_cpu is None else sys_cpu},{'' if eda_cpu is None else eda_cpu}\n")

print({"label":label,"system_cpu_pct_avg":sys_cpu,"eda_cpu_pct_avg":eda_cpu})
PY

echo "Wrote $OUT/summary.csv"
