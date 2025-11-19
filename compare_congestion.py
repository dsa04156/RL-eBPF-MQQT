#!/usr/bin/env python3
import json
import argparse
import numpy as np


def load_log(path):
    data = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data.append(json.loads(line))
            except Exception:
                continue
    return data


def summarize(data):
    if not data:
        return None

    cnt = len(data)
    # Metrics
    p50 = [d.get('metrics', {}).get('p50_ms', 0) for d in data if 'metrics' in d]
    p95 = [d.get('metrics', {}).get('p95_ms', 0) for d in data if 'metrics' in d]
    p99 = [d.get('metrics', {}).get('p99_ms', 0) for d in data if 'metrics' in d]

    thr = []
    n_list = []
    w_list = []
    for d in data:
        m = d.get('metrics', {})
        n = m.get('n', 0)
        w = m.get('window_sec', 30.0) or 0.0
        thr.append(n / w if w > 0 else 0.0)
        n_list.append(n)
        w_list.append(w)

    rtt = [d.get('kernel', {}).get('ewma_rtt_us', 0) / 1000.0 for d in data if 'kernel' in d]
    retrans_flags = [1 if d.get('kernel', {}).get('had_retrans', False) else 0 for d in data]
    cong_score = [d.get('kernel', {}).get('congestion_score', 0) for d in data if 'kernel' in d]
    congested = [1 if d.get('kernel', {}).get('congested', False) else 0 for d in data]

    applied = [1 if d.get('applied', False) else 0 for d in data]
    actions = [d.get('a', {}) or d.get('a_raw', {}) for d in data]
    nonzero_actions = sum(1 for a in actions if abs(a.get('d_rate', 0.0)) > 1e-9)

    def safe_mean(arr):
        return float(np.mean(arr)) if arr else float('nan')

    def safe_std(arr):
        return float(np.std(arr)) if arr else float('nan')

    def safe_percentile(arr, q):
        return float(np.percentile(arr, q)) if arr else float('nan')

    return {
        'steps': cnt,
        'arr_p50': p50,
        'arr_p95': p95,
        'arr_p99': p99,
        'arr_n': n_list,
        'arr_w': w_list,
        'p50_mean': safe_mean(p50),
        'p95_mean': safe_mean(p95),
        'p99_mean': safe_mean(p99),
        'p99_p95': safe_percentile(p99, 95),
        'p99_max': max(p99) if p99 else float('nan'),
        'rtt_mean': safe_mean(rtt),
        'rtt_std': safe_std(rtt),
        'retrans_rate_pct': safe_mean(retrans_flags) * 100.0,
        'retrans_const': len(set(retrans_flags)) == 1,
        'throughput_mean': safe_mean(thr),
        'throughput_std': safe_std(thr),
        'cong_mean': safe_mean(cong_score),
        'congested_pct': safe_mean(congested) * 100.0,
        'applied_pct': safe_mean(applied) * 100.0,
        'nonzero_actions_pct': (nonzero_actions * 100.0 / cnt) if cnt else 0.0,
    }


def on_time_bounds_summary(s, threshold_ms=200.0):
    p50 = s['arr_p50']
    p95 = s['arr_p95']
    p99 = s['arr_p99']
    n_list = s['arr_n']
    w_list = s['arr_w']

    total_msgs = 0
    total_time = 0.0
    on_lb = 0.0
    on_ub = 0.0

    for p50_i, p95_i, p99_i, n_i, w_i in zip(p50, p95, p99, n_list, w_list):
        total_msgs += n_i
        total_time += (w_i or 0.0)
        # Bounds from quantiles
        if threshold_ms < p50_i:
            lb, ub = 0.0, 0.5
        elif threshold_ms < p95_i:
            lb, ub = 0.5, 0.95
        elif threshold_ms < p99_i:
            lb, ub = 0.95, 0.99
        else:
            lb, ub = 0.99, 1.0
        on_lb += n_i * lb
        on_ub += n_i * ub

    ratio_lb = (on_lb / total_msgs) if total_msgs else float('nan')
    ratio_ub = (on_ub / total_msgs) if total_msgs else float('nan')
    thr_lb = (on_lb / total_time) if total_time else float('nan')
    thr_ub = (on_ub / total_time) if total_time else float('nan')

    return {
        'ratio_lb': ratio_lb,
        'ratio_ub': ratio_ub,
        'thr_lb': thr_lb,
        'thr_ub': thr_ub,
        'msgs_total': total_msgs,
        'time_total': total_time,
    }


def main():
    ap = argparse.ArgumentParser(description='Compare congestion logs: EMQX flow control vs Torch model experiments')
    ap.add_argument('--emqx', default='logs/emqx_flow_control/congestion.jsonl', help='EMQX congestion log path')
    ap.add_argument('--torch', default='logs/torch_model_experiments/congestion/rl_bc_v2_congestion.jsonl', help='Torch model congestion log path')
    args = ap.parse_args()

    emqx = load_log(args.emqx)
    torch = load_log(args.torch)

    s1 = summarize(emqx)
    s2 = summarize(torch)

    if not s1 or not s2:
        print('❌ Failed to read logs or logs are empty')
        return 1

    def fmt(x, unit=''):
        if x != x:  # NaN
            return 'N/A'
        if unit == '%':
            return f"{x:.1f}%"
        if unit == 'ms':
            return f"{x:.1f}ms"
        if unit == 'msg/s':
            return f"{x:.1f}"
        return f"{x:.1f}"

    print('='*100)
    print('📊 CONGESTION LOG COMPARISON: EMQX Flow Control vs Torch Model')
    print('='*100)

    print(f"Steps                           | EMQX: {s1['steps']} | Torch: {s2['steps']}")

    print('\nLatency (ms)')
    print('-'*100)
    print(f"P50 mean                        | {fmt(s1['p50_mean'],'ms'):>12} | {fmt(s2['p50_mean'],'ms'):>12}")
    print(f"P95 mean                        | {fmt(s1['p95_mean'],'ms'):>12} | {fmt(s2['p95_mean'],'ms'):>12}")
    print(f"P99 mean                        | {fmt(s1['p99_mean'],'ms'):>12} | {fmt(s2['p99_mean'],'ms'):>12}")
    print(f"P99 95th perc                   | {fmt(s1['p99_p95'],'ms'):>12} | {fmt(s2['p99_p95'],'ms'):>12}")
    print(f"P99 max                         | {fmt(s1['p99_max'],'ms'):>12} | {fmt(s2['p99_max'],'ms'):>12}")

    print('\nRTT (ms)')
    print('-'*100)
    print(f"RTT mean                        | {fmt(s1['rtt_mean'],'ms'):>12} | {fmt(s2['rtt_mean'],'ms'):>12}")
    print(f"RTT std                         | {fmt(s1['rtt_std'],'ms'):>12} | {fmt(s2['rtt_std'],'ms'):>12}")

    print('\nRetransmission & Congestion')
    print('-'*100)
    print(f"Retrans rate (had_retrans=true) | {fmt(s1['retrans_rate_pct'],'%'):>12} | {fmt(s2['retrans_rate_pct'],'%'):>12}  (Torch const={s2['retrans_const']})")
    print(f"Congestion score mean           | {fmt(s1['cong_mean']):>12} | {fmt(s2['cong_mean']):>12}")
    print(f"Constricted steps (%)           | {fmt(s1['congested_pct'],'%'):>12} | {fmt(s2['congested_pct'],'%'):>12}")

    print('\nThroughput (msg/s)')
    print('-'*100)
    print(f"Throughput mean                 | {fmt(s1['throughput_mean'],'msg/s'):>12} | {fmt(s2['throughput_mean'],'msg/s'):>12}")
    print(f"Throughput std                  | {fmt(s1['throughput_std'],'msg/s'):>12} | {fmt(s2['throughput_std'],'msg/s'):>12}")

    print('\nControl Actions (if present)')
    print('-'*100)
    print(f"Applied steps (%)               | {fmt(s1['applied_pct'],'%'):>12} | {fmt(s2['applied_pct'],'%'):>12}")
    print(f"Non-zero actions (%)            | {fmt(s1['nonzero_actions_pct'],'%'):>12} | {fmt(s2['nonzero_actions_pct'],'%'):>12}")

    # On-time throughput comparisons
    for T in (200.0, 1000.0):
        b1 = on_time_bounds_summary(s1, threshold_ms=T)
        b2 = on_time_bounds_summary(s2, threshold_ms=T)
        print(f"\nOn-time (<= {int(T)} ms) — lower/upper bounds")
        print('-'*100)
        print(f"On-time ratio                    | {fmt(b1['ratio_lb'],'%'):>12}–{fmt(b1['ratio_ub'],'%'):>12} | {fmt(b2['ratio_lb'],'%'):>12}–{fmt(b2['ratio_ub'],'%'):>12}")
        print(f"On-time throughput (msg/s)       | {fmt(b1['thr_lb'],'msg/s'):>12}–{fmt(b1['thr_ub'],'msg/s'):>12} | {fmt(b2['thr_lb'],'msg/s'):>12}–{fmt(b2['thr_ub'],'msg/s'):>12}")

    print('\nKey Notes')
    print('-'*100)
    if s2['retrans_const']:
        print('• Torch congestion log has retrans flag saturated at 100%; use P99/RTT vs Throughput for causality instead of retrans.')
    if s1['throughput_mean'] and s2['throughput_mean']:
        delta_thr = (s2['throughput_mean'] - s1['throughput_mean']) / s1['throughput_mean'] * 100.0
        print(f"• Torch throughput vs EMQX: {delta_thr:+.1f}%")
    if s1['p99_mean'] and s2['p99_mean']:
        delta_p99 = (s2['p99_mean'] - s1['p99_mean']) / s1['p99_mean'] * 100.0
        print(f"• Torch P99 vs EMQX: {delta_p99:+.1f}%")


if __name__ == '__main__':
    raise SystemExit(main())
