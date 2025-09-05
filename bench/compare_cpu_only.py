#!/usr/bin/env python3
# compare_cpu_only.py — OFF/ON 두 폴더의 summary.csv 비교
import sys, os, csv

def read_sum(d):
    p=os.path.join(d,"summary.csv")
    if not os.path.exists(p): return None
    with open(p) as f:
        r=list(csv.DictReader(f))
        return r[0] if r else None

def f(x):
    try: return float(x)
    except: return None

def main():
    if len(sys.argv)<3:
        print("Usage: compare_cpu_only.py OFF_DIR ON_DIR [OUT_CSV]")
        sys.exit(2)
    off, on = sys.argv[1], sys.argv[2]
    out_csv = sys.argv[3] if len(sys.argv)>3 else os.path.join(os.path.dirname(on) or ".", "CPU_ONLY_AB.csv")

    a=read_sum(off); b=read_sum(on)
    if not a or not b:
        print("ERROR: summary.csv not found in one of the dirs")
        sys.exit(1)

    off_sys=f(a['system_cpu_pct_avg']); on_sys=f(b['system_cpu_pct_avg'])
    off_eda=f(a.get('eda_cpu_pct_avg') or ""); on_eda=f(b.get('eda_cpu_pct_avg') or "")

    d_sys = (on_sys - off_sys) if (off_sys is not None and on_sys is not None) else None
    d_eda = (on_eda - off_eda) if (off_eda is not None and on_eda is not None) else None

    print("label,system_cpu_pct_avg,eda_cpu_pct_avg")
    print(f"OFF,{a['system_cpu_pct_avg']},{a.get('eda_cpu_pct_avg','')}")
    print(f"ON,{b['system_cpu_pct_avg']},{b.get('eda_cpu_pct_avg','')}")
    print("\nΔ(ON-OFF):")
    print(f"system_cpu_pct_delta,{'' if d_sys is None else round(d_sys,2)}")
    if d_eda is not None:
        print(f"eda_cpu_pct_delta,{round(d_eda,2)}")

    with open(out_csv,"w",newline="") as fcsv:
        w=csv.writer(fcsv)
        w.writerow(["phase","system_cpu_pct_avg","eda_cpu_pct_avg"])
        w.writerow(["OFF", a['system_cpu_pct_avg'], a.get('eda_cpu_pct_avg','')])
        w.writerow(["ON",  b['system_cpu_pct_avg'], b.get('eda_cpu_pct_avg','')])
        w.writerow([])
        w.writerow(["system_cpu_pct_delta(ON-OFF)", "" if d_sys is None else round(d_sys,2)])
        if d_eda is not None:
            w.writerow(["eda_cpu_pct_delta(ON-OFF)", round(d_eda,2)])
    print("[WROTE]", out_csv)

if __name__ == "__main__":
    main()
