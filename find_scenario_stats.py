#!/usr/bin/env python3
import json
import os
import math
import glob
import numpy as np


def load_jsonl(path):
    data = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return []
    return data


def summarize_file(path):
    rows = load_jsonl(path)
    if not rows:
        return None
    rows = [r for r in rows if isinstance(r, dict)]
    m = [r.get('metrics', {}) for r in rows]
    k = [r.get('kernel', {}) for r in rows]

    p99_app = np.array([mi.get('p99_ms', 0.0) for mi in m], dtype=float)
    p50_app = np.array([mi.get('p50_ms', 0.0) for mi in m], dtype=float)
    rtt_ms = np.array([ki.get('ewma_rtt_us', 0.0) / 1000.0 for ki in k], dtype=float)
    n = np.array([mi.get('n', 0.0) for mi in m], dtype=float)
    w = np.array([mi.get('window_sec', 30.0) or 0.0 for mi in m], dtype=float)
    thr = np.where(w > 0, n / w, 0.0)

    def safe_mean(x):
        return float(np.nanmean(x)) if x.size else float('nan')
    def safe_pct(x, q):
        return float(np.nanpercentile(x, q)) if x.size else float('nan')

    return {
        'file': path,
        'app_p99_mean': safe_mean(p99_app),
        'app_p99_p95': safe_pct(p99_app, 95),
        'app_p99_max': safe_pct(p99_app, 100),
        'kernel_rtt_p99': safe_pct(rtt_ms, 99),
        'kernel_rtt_mean': safe_mean(rtt_ms),
        'throughput_mean': safe_mean(thr),
        'throughput_max': safe_pct(thr, 99),
        'steps': len(rows),
    }


def scan_patterns():
    patterns = [
        'logs/**/*.jsonl',
    ]
    files = []
    for pat in patterns:
        files.extend(glob.glob(pat, recursive=True))
    files = [f for f in files if os.path.isfile(f)]
    return sorted(files)


def main():
    print('='*100)
    print('Scenario stats (kernel RTT p99, app p99 mean, throughput mean)')
    print('='*100)
    candidates = []
    for f in scan_patterns():
        s = summarize_file(f)
        if not s:
            continue
        candidates.append(s)
    # Sort by path for readability
    candidates.sort(key=lambda x: x['file'])

    print(f"{'file':<65} | {'ker p99(ms)':>11} | {'app p99(ms)':>11} | {'thr(msg/s)':>11} | steps")
    print('-'*100)
    for s in candidates:
        print(f"{s['file']:<65} | {s['kernel_rtt_p99']:>11.2f} | {s['app_p99_mean']:>11.2f} | {s['throughput_mean']:>11.2f} | {s['steps']}")

    # If user provided target triples, we could match nearest; here we just dump the table.

if __name__ == '__main__':
    main()
