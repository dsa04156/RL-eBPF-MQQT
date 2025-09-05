#!/usr/bin/env python3
import sys, json, math, statistics as st
from collections import defaultdict

if len(sys.argv) < 2:
    print("usage: analyze_eda.py <eda.jsonl>", file=sys.stderr); sys.exit(1)

path = sys.argv[1]
# interval 단위 집계: 같은 ts 구간(대략 INTERVAL_S) 내 여러 flow를 합산/요약
per_slot = {}                 # slot_key -> dict
slot_rtts = defaultdict(list) # slot_key -> [rtt_ms...]
slot_retx = defaultdict(int)  # slot_key -> sum(retrans_delta)
slot_snd = defaultdict(int)   # slot_key -> max sndbuf
slot_rcv = defaultdict(int)   # slot_key -> max rcvbuf
interval_s = None

def slot(ts, s):
    if s is None or s <= 0: return int(ts)  # fallback
    return int(ts // s)

with open(path) as f:
    for line in f:
        line=line.strip()
        if not line or line[0] != '{': continue
        try:
            o=json.loads(line)
        except: 
            continue
        ts=o.get("ts")
        if ts is None: continue
        interval_s = interval_s or o.get("interval_s", 2.0)
        k = slot(ts, interval_s)
        rtt = o.get("rtt_ms")
        if isinstance(rtt,(int,float)):
            slot_rtts[k].append(float(rtt))
        slot_retx[k]+= int(o.get("retrans_delta",0))
        slot_snd[k] = max(slot_snd[k], int(o.get("sndbuf",0)))
        slot_rcv[k] = max(slot_rcv[k], int(o.get("rcvbuf",0)))

# slot별 대표값 만들기 (flow 평균 RTT, 합산 재전송)
slots = sorted(slot_rtts.keys() | slot_retx.keys())
avg_rtts = []
max_rtts = []
retx_any = 0
sum_retx = 0
max_snd = 0
max_rcv = 0
for k in slots:
    if slot_rtts[k]:
        avg_rtts.append(st.mean(slot_rtts[k]))
        max_rtts.append(max(slot_rtts[k]))
    if slot_retx[k] > 0:
        retx_any += 1
    sum_retx += slot_retx[k]
    max_snd = max(max_snd, slot_snd[k])
    max_rcv = max(max_rcv, slot_rcv[k])

def pct(a,p):
    if not a: return float('nan')
    a=sorted(a); idx=max(0,min(len(a)-1,int(round((p/100.0)*(len(a)-1)))))
    return a[idx]

def fmt(x):
    return "nan" if isinstance(x,float) and math.isnan(x) else (f"{x:.2f}" if isinstance(x,float) else str(x))

print("# EDA summary")
print(f"samples_slots={len(slots)}  interval_s={interval_s}")
print(f"rtt_avg_ms:   p50={fmt(pct(avg_rtts,50))}  p95={fmt(pct(avg_rtts,95))}  p99={fmt(pct(avg_rtts,99))}  mean={fmt(st.mean(avg_rtts) if avg_rtts else float('nan'))}")
print(f"rtt_max_ms:   p50={fmt(pct(max_rtts,50))}  p95={fmt(pct(max_rtts,95))}  p99={fmt(pct(max_rtts,99))}")
print(f"retrans:      sum={sum_retx}  slots_with_retx={retx_any}/{len(slots)}")
print(f"max_sndbuf_B: {max_snd}   max_rcvbuf_B: {max_rcv}")
