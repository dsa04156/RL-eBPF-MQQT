#!/usr/bin/env python3
"""
재전송 압력 지수(RPI) 시각화
 - EMQX vs Torch 혼잡 로그 비교
 - RPI = 가중합(RTT_norm, dRTT_norm(+), snd_ratio_norm, congestion_score_norm)
 - 산점도/타임라인/처리량 오버레이 + 랙 상관 출력
"""

import argparse
import json
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec


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


def extract_series(data):
    t = [d.get('ts', 0.0) for d in data]
    if t:
        t0 = t[0]
        t = [ti - t0 for ti in t]

    metrics = [d.get('metrics', {}) for d in data]
    p99 = [m.get('p99_ms', 0.0) for m in metrics]
    p95 = [m.get('p95_ms', 0.0) for m in metrics]
    p50 = [m.get('p50_ms', 0.0) for m in metrics]
    n = [m.get('n', 0.0) for m in metrics]
    w = [m.get('window_sec', 30.0) or 0.0 for m in metrics]
    thr = [(ni / wi) if wi > 0 else 0.0 for ni, wi in zip(n, w)]

    k = [d.get('kernel', {}) for d in data]
    rtt = [ki.get('ewma_rtt_us', 0.0) / 1000.0 for ki in k]  # ms
    snd_ratio = [ki.get('snd_ratio', 0.0) for ki in k]
    cong = [ki.get('congestion_score', 0.0) for ki in k]
    had_retrans = [1 if ki.get('had_retrans', False) else 0 for ki in k]

    return {
        't': np.asarray(t, dtype=float),
        'p99': np.asarray(p99, dtype=float),
        'p95': np.asarray(p95, dtype=float),
        'p50': np.asarray(p50, dtype=float),
        'thr': np.asarray(thr, dtype=float),
        'rtt': np.asarray(rtt, dtype=float),
        'snd_ratio': np.asarray(snd_ratio, dtype=float),
        'cong': np.asarray(cong, dtype=float),
        'retrans': np.asarray(had_retrans, dtype=float),
    }


def robust_norm(x, p_low=5, p_high=95):
    x = np.asarray(x, dtype=float)
    if len(x) == 0:
        return x
    lo = np.nanpercentile(x, p_low)
    hi = np.nanpercentile(x, p_high)
    if not np.isfinite(lo) or not np.isfinite(hi) or hi - lo == 0:
        mean = np.nanmean(x)
        std = np.nanstd(x)
        if std == 0:
            return np.zeros_like(x)
        z = (x - mean) / (std + 1e-12)
        z = (z - np.nanmin(z)) / max(np.nanmax(z) - np.nanmin(z), 1e-12)
        return np.clip(z, 0, 1)
    z = (x - lo) / (hi - lo)
    return np.clip(z, 0, 1)


def central_diff_positive(x, t):
    x = np.asarray(x, dtype=float)
    t = np.asarray(t, dtype=float)
    if len(x) < 3:
        return np.zeros_like(x)
    dt = np.gradient(t)
    dx = np.gradient(x, t)
    dx = np.maximum(dx, 0.0)
    # Normalize derivative scale via percentile
    return robust_norm(dx)


def moving_avg(x, window=5):
    if window <= 1:
        return x
    x = np.asarray(x, dtype=float)
    k = np.ones(window) / window
    return np.convolve(x, k, mode='same')


def build_rpi(series, weights, smooth_window=5):
    rtt_n = robust_norm(series['rtt'])
    drtt_n = central_diff_positive(series['rtt'], series['t'])
    snd_n = robust_norm(series['snd_ratio'])
    cong_n = robust_norm(series['cong'])

    wrtt, wdrtt, wsnd, wcong = weights
    rpi = wrtt * rtt_n + wdrtt * drtt_n + wsnd * snd_n + wcong * cong_n
    if smooth_window and smooth_window > 1:
        rpi = moving_avg(rpi, smooth_window)
    rpi = np.clip(rpi, 0, 1)
    return rpi, {
        'rtt_n': rtt_n,
        'drtt_n': drtt_n,
        'snd_n': snd_n,
        'cong_n': cong_n,
    }


def lagged_corr(x, y, max_lag=15):
    lags = range(-max_lag, max_lag + 1)
    corrs = []
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    for lag in lags:
        if lag < 0:
            a = x[:lag]
            b = y[-lag:]
        elif lag > 0:
            a = x[lag:]
            b = y[:-lag]
        else:
            a = x
            b = y
        if len(a) > 2 and np.nanstd(a) > 0 and np.nanstd(b) > 0:
            corrs.append(float(np.corrcoef(a, b)[0, 1]))
        else:
            corrs.append(np.nan)
    return list(lags), corrs


def main():
    ap = argparse.ArgumentParser(description='Retransmission Pressure Index (RPI) visualization: EMQX vs Torch')
    ap.add_argument('--emqx', default='logs/emqx_flow_control/congestion.jsonl', help='EMQX congestion log path')
    ap.add_argument('--torch', default='logs/torch_model_experiments/congestion/rl_bc_v2_congestion.jsonl', help='Torch congestion log path')
    ap.add_argument('--weights', default='0.35,0.25,0.25,0.15', help='Weights for RTT, dRTT, snd_ratio, congestion_score')
    ap.add_argument('--smooth', type=int, default=7, help='Smoothing window for RPI')
    ap.add_argument('--lags', type=int, default=15, help='Max lag for cross-correlation')
    ap.add_argument('--out', default='results/retrans_index_comparison', help='Output prefix (no extension)')
    args = ap.parse_args()

    w = tuple(float(x) for x in args.weights.split(','))
    if len(w) != 4:
        raise SystemExit('weights must be four comma-separated floats: rtt,drtt,snd,cong')

    emqx = extract_series(load_log(args.emqx))
    torch = extract_series(load_log(args.torch))

    rpi_e, parts_e = build_rpi(emqx, w, smooth_window=args.smooth)
    rpi_t, parts_t = build_rpi(torch, w, smooth_window=args.smooth)

    # Lag correlation: RPI vs Throughput
    lags_e, corr_e = lagged_corr(rpi_e, emqx['thr'], max_lag=args.lags)
    lags_t, corr_t = lagged_corr(rpi_t, torch['thr'], max_lag=args.lags)

    def best_lag(lags, corrs):
        arr = np.asarray(corrs, dtype=float)
        if np.all(np.isnan(arr)):
            return None
        idx = int(np.nanargmax(np.abs(arr)))
        return lags[idx], float(arr[idx])

    bl_e = best_lag(lags_e, corr_e)
    bl_t = best_lag(lags_t, corr_t)

    print('=' * 80)
    print('📊 Retransmission Pressure Index (RPI) — Lag correlation vs Throughput')
    print('=' * 80)
    if bl_e:
        print(f"EMQX: best lag={bl_e[0]} steps, r={bl_e[1]:+.3f}")
    else:
        print("EMQX: correlation not defined (constant series or too short)")
    if bl_t:
        print(f"Torch: best lag={bl_t[0]} steps, r={bl_t[1]:+.3f}")
    else:
        print("Torch: correlation not defined (constant series or too short)")

    # Visualization
    fig = plt.figure(figsize=(18, 12))
    gs = GridSpec(3, 2, figure=fig, hspace=0.35, wspace=0.3)

    # 1) Time series P99 + RPI
    ax1 = fig.add_subplot(gs[0, 0])
    ax1_t = ax1.twinx()
    ax1.plot(emqx['t'], emqx['p99'], 'tab:blue', lw=1.5, alpha=0.7, label='P99 (ms)')
    ax1_t.plot(emqx['t'], rpi_e, 'tab:red', lw=2.0, alpha=0.8, label='RPI')
    ax1.set_title('EMQX: P99 & RPI', fontsize=12, fontweight='bold')
    ax1.set_xlabel('Time (s)')
    ax1.set_ylabel('P99 (ms)', color='tab:blue')
    ax1_t.set_ylabel('RPI (0–1)', color='tab:red')
    ax1.grid(True, alpha=0.3)

    ax2 = fig.add_subplot(gs[0, 1])
    ax2_t = ax2.twinx()
    ax2.plot(torch['t'], torch['p99'], 'tab:blue', lw=1.5, alpha=0.7, label='P99 (ms)')
    ax2_t.plot(torch['t'], rpi_t, 'tab:red', lw=2.0, alpha=0.8, label='RPI')
    ax2.set_title('Torch: P99 & RPI', fontsize=12, fontweight='bold')
    ax2.set_xlabel('Time (s)')
    ax2.set_ylabel('P99 (ms)', color='tab:blue')
    ax2_t.set_ylabel('RPI (0–1)', color='tab:red')
    ax2.grid(True, alpha=0.3)

    # 2) Throughput + RPI overlay
    ax3 = fig.add_subplot(gs[1, 0])
    ax3_t = ax3.twinx()
    ax3.plot(emqx['t'], emqx['thr'], 'tab:green', lw=1.8, alpha=0.7, label='Throughput (msg/s)')
    ax3_t.plot(emqx['t'], rpi_e, 'tab:red', lw=2.0, alpha=0.7, label='RPI')
    ax3.set_title('EMQX: Throughput & RPI', fontsize=12, fontweight='bold')
    ax3.set_xlabel('Time (s)')
    ax3.set_ylabel('Throughput (msg/s)', color='tab:green')
    ax3_t.set_ylabel('RPI (0–1)', color='tab:red')
    ax3.grid(True, alpha=0.3)

    ax4 = fig.add_subplot(gs[1, 1])
    ax4_t = ax4.twinx()
    ax4.plot(torch['t'], torch['thr'], 'tab:green', lw=1.8, alpha=0.7, label='Throughput (msg/s)')
    ax4_t.plot(torch['t'], rpi_t, 'tab:red', lw=2.0, alpha=0.7, label='RPI')
    ax4.set_title('Torch: Throughput & RPI', fontsize=12, fontweight='bold')
    ax4.set_xlabel('Time (s)')
    ax4.set_ylabel('Throughput (msg/s)', color='tab:green')
    ax4_t.set_ylabel('RPI (0–1)', color='tab:red')
    ax4.grid(True, alpha=0.3)

    # 3) Scatter: RPI vs Throughput (color=RTT)
    ax5 = fig.add_subplot(gs[2, 0])
    sc1 = ax5.scatter(rpi_e, emqx['thr'], c=emqx['rtt'], cmap='plasma', s=25, alpha=0.7)
    cbar1 = plt.colorbar(sc1, ax=ax5, label='RTT (ms)')
    ax5.set_title('EMQX: RPI vs Throughput (color=RTT)', fontsize=12, fontweight='bold')
    ax5.set_xlabel('RPI (0–1)')
    ax5.set_ylabel('Throughput (msg/s)')
    ax5.grid(True, alpha=0.3)

    ax6 = fig.add_subplot(gs[2, 1])
    sc2 = ax6.scatter(rpi_t, torch['thr'], c=torch['rtt'], cmap='plasma', s=25, alpha=0.7)
    cbar2 = plt.colorbar(sc2, ax=ax6, label='RTT (ms)')
    ax6.set_title('Torch: RPI vs Throughput (color=RTT)', fontsize=12, fontweight='bold')
    ax6.set_xlabel('RPI (0–1)')
    ax6.set_ylabel('Throughput (msg/s)')
    ax6.grid(True, alpha=0.3)

    fig.suptitle('Retransmission Pressure Index (RPI): EMQX vs Torch (Congestion)', fontsize=16, fontweight='bold')

    png = f"{args.out}.png"
    pdf = f"{args.out}.pdf"
    plt.savefig(png, dpi=300, bbox_inches='tight')
    plt.savefig(pdf, bbox_inches='tight')
    print(f"\n✅ Saved: {png}")
    print(f"✅ Saved: {pdf}")


if __name__ == '__main__':
    main()

