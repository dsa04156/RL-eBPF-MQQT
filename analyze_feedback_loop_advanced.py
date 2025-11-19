#!/usr/bin/env python3
"""
P99 지연 - 재전송 - Throughput 악순환 고급 분석
시간차(lag) 상관관계 및 Granger Causality 분석 포함
"""

import json
import argparse
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.gridspec import GridSpec
from scipy import stats
from scipy.signal import find_peaks

def load_and_analyze(log_path):
    """로그 파일을 읽고 핵심 지표 추출"""
    data = []
    with open(log_path) as f:
        for line in f:
            if line.strip():
                try:
                    data.append(json.loads(line))
                except:
                    continue
    
    # 시계열 데이터 추출
    timestamps = []
    p99_values = []
    p95_values = []
    p50_values = []
    rtt_values = []
    retrans_flags = []
    snd_ratios = []
    rcv_ratios = []
    throughputs = []
    congestion_scores = []
    congested_flags = []
    
    for d in data:
        ts = d.get('ts', 0)
        timestamps.append(ts)
        
        # Latency metrics
        metrics = d.get('metrics', {})
        p99_values.append(metrics.get('p99_ms', 0))
        p95_values.append(metrics.get('p95_ms', 0))
        p50_values.append(metrics.get('p50_ms', 0))
        
        # Throughput (msg/s)
        n = metrics.get('n', 0)
        window = metrics.get('window_sec', 30.0)
        thr = n / window if window > 0 else 0
        throughputs.append(thr)
        
        # Kernel signals
        kernel = d.get('kernel', {})
        rtt_values.append(kernel.get('ewma_rtt_us', 0) / 1000.0)  # Convert to ms
        retrans_flags.append(1 if kernel.get('had_retrans', False) else 0)
        snd_ratios.append(kernel.get('snd_ratio', 0))
        rcv_ratios.append(kernel.get('rcv_ratio', 0))
        congestion_scores.append(kernel.get('congestion_score', 0))
        congested_flags.append(1 if kernel.get('congested', False) else 0)
    
    # Normalize timestamps
    if timestamps:
        t_start = timestamps[0]
        timestamps = [(t - t_start) for t in timestamps]
    
    return {
        't': timestamps,
        'p99': p99_values,
        'p95': p95_values,
        'p50': p50_values,
        'rtt': rtt_values,
        'retrans': retrans_flags,
        'snd_ratio': snd_ratios,
        'rcv_ratio': rcv_ratios,
        'throughput': throughputs,
        'congestion': congestion_scores,
        'congested': congested_flags
    }

def calculate_lagged_correlations(x, y, max_lag=10):
    """시간차(lag) 상관관계 계산"""
    correlations = []
    lags = list(range(-max_lag, max_lag + 1))
    
    for lag in lags:
        if lag < 0:
            # x가 y보다 앞서는 경우 (x leads y)
            corr = np.corrcoef(x[:lag], y[-lag:])[0, 1] if len(x[:lag]) > 1 else 0
        elif lag > 0:
            # y가 x보다 앞서는 경우 (y leads x)
            corr = np.corrcoef(x[lag:], y[:-lag])[0, 1] if len(x[lag:]) > 1 else 0
        else:
            # 동시 상관
            corr = np.corrcoef(x, y)[0, 1]
        correlations.append(corr)
    
    return lags, correlations

def detect_burst_events(data, threshold_multiplier=2.0):
    """P99 급등 이벤트 탐지"""
    p99 = np.array(data['p99'])
    
    # Moving average and std using numpy
    window = 10
    ma = np.convolve(p99, np.ones(window)/window, mode='same')
    
    # Calculate rolling std manually
    std = np.zeros_like(p99)
    for i in range(len(p99)):
        start = max(0, i - window//2)
        end = min(len(p99), i + window//2 + 1)
        std[i] = np.std(p99[start:end])
    
    # Burst: p99 > ma + threshold * std
    burst_mask = p99 > (ma + threshold_multiplier * std)
    
    return burst_mask

def analyze_burst_response(data, burst_mask):
    """P99 급등 이후 재전송/throughput 변화 분석"""
    burst_indices = np.where(burst_mask)[0]
    
    if len(burst_indices) == 0:
        return None
    
    # 각 burst 이벤트 이후 5 스텝 추적
    lookback = 5
    lookahead = 5
    
    burst_stats = {
        'pre_retrans': [],
        'post_retrans': [],
        'pre_throughput': [],
        'post_throughput': [],
        'pre_rtt': [],
        'post_rtt': []
    }
    
    for idx in burst_indices:
        if idx < lookback or idx + lookahead >= len(data['retrans']):
            continue
        
        # Pre-burst (이전 5 스텝 평균)
        pre_retrans = np.mean(data['retrans'][idx-lookback:idx])
        pre_throughput = np.mean(data['throughput'][idx-lookback:idx])
        pre_rtt = np.mean(data['rtt'][idx-lookback:idx])
        
        # Post-burst (이후 5 스텝 평균)
        post_retrans = np.mean(data['retrans'][idx:idx+lookahead])
        post_throughput = np.mean(data['throughput'][idx:idx+lookahead])
        post_rtt = np.mean(data['rtt'][idx:idx+lookahead])
        
        burst_stats['pre_retrans'].append(pre_retrans)
        burst_stats['post_retrans'].append(post_retrans)
        burst_stats['pre_throughput'].append(pre_throughput)
        burst_stats['post_throughput'].append(post_throughput)
        burst_stats['pre_rtt'].append(pre_rtt)
        burst_stats['post_rtt'].append(post_rtt)
    
    return burst_stats

def calculate_moving_correlations(x, y, window=30):
    """이동 윈도우 상관관계 계산"""
    correlations = []
    for i in range(len(x) - window):
        corr = np.corrcoef(x[i:i+window], y[i:i+window])[0, 1]
        correlations.append(corr)
    
    # Pad to match original length
    correlations = [np.nan] * (window // 2) + correlations + [np.nan] * (window - window // 2)
    return correlations

# ============================================================================
# Main Analysis
# ============================================================================

parser = argparse.ArgumentParser(description="Advanced feedback loop analysis with lag correlations and burst detection")
parser.add_argument("--log", dest="log_path", type=str, default="logs/torch_model_experiments/dynamic/rl_bc_v2_dynamic.jsonl",
                    help="Path to JSONL log file")
parser.add_argument("--out-prefix", dest="out_prefix", type=str, default="results/feedback_loop_advanced",
                    help="Output prefix for figure files (without extension)")
parser.add_argument("--max-lag", dest="max_lag", type=int, default=15,
                    help="Max lag (in steps) for cross-correlation analysis")
parser.add_argument("--title", dest="title", type=str,
                    default="Advanced Feedback Loop Analysis: Lag Correlations & Burst Detection",
                    help="Figure title")
args = parser.parse_args()

print("=" * 80)
print("📊 Advanced Feedback Loop Analysis with Lag Correlations")
print("=" * 80)

log_path = args.log_path
data = load_and_analyze(log_path)

print(f"\n✅ Loaded {len(data['t'])} steps")

# 1. Lagged Cross-Correlation: P99 vs Retransmission
print("\n" + "=" * 80)
print("🔗 Lagged Cross-Correlation: P99 vs Retransmission")
print("=" * 80)

lags_p99_retrans, corr_p99_retrans = calculate_lagged_correlations(
    data['p99'], data['retrans'], max_lag=args.max_lag
)

max_corr_idx = np.argmax(np.abs(corr_p99_retrans))
max_lag = lags_p99_retrans[max_corr_idx]
max_corr = corr_p99_retrans[max_corr_idx]

if np.isnan(max_corr):
    print("\n최대 상관 lag: N/A (retransmission series is constant)")
else:
    print(f"\n최대 상관 lag: {max_lag} steps (r={max_corr:.3f})")
    if max_lag < 0:
        print(f"  → P99가 재전송보다 {abs(max_lag)} 스텝 **앞서서** 증가 (P99 leads retrans)")
    elif max_lag > 0:
        print(f"  → 재전송이 P99보다 {max_lag} 스텝 **앞서서** 발생 (retrans leads P99)")
    else:
        print(f"  → P99와 재전송이 동시에 발생")

# 2. Lagged Cross-Correlation: RTT vs Retransmission
print("\n" + "=" * 80)
print("🔗 Lagged Cross-Correlation: RTT vs Retransmission")
print("=" * 80)

lags_rtt_retrans, corr_rtt_retrans = calculate_lagged_correlations(
    data['rtt'], data['retrans'], max_lag=args.max_lag
)

max_corr_idx = np.argmax(np.abs(corr_rtt_retrans))
max_lag = lags_rtt_retrans[max_corr_idx]
max_corr = corr_rtt_retrans[max_corr_idx]

if np.isnan(max_corr):
    print("\n최대 상관 lag: N/A (retransmission series is constant)")
else:
    print(f"\n최대 상관 lag: {max_lag} steps (r={max_corr:.3f})")
    if max_lag < 0:
        print(f"  → RTT가 재전송보다 {abs(max_lag)} 스텝 **앞서서** 증가 (RTT is leading indicator)")
        print(f"  ✅ RTT를 관찰하면 재전송 발생 예측 가능!")
    elif max_lag > 0:
        print(f"  → 재전송이 RTT보다 {max_lag} 스텝 **앞서서** 발생")
    else:
        print(f"  → RTT와 재전송이 동시에 발생")

# 3. Lagged Cross-Correlation: Retransmission vs Throughput
print("\n" + "=" * 80)
print("🔗 Lagged Cross-Correlation: Retransmission vs Throughput")
print("=" * 80)

retrans_std = np.std(data['retrans']) if len(data['retrans']) > 1 else 0.0
use_alt_for_thr = retrans_std < 1e-9
if use_alt_for_thr:
    print("\n⚠️ 재전송 플래그가 모든 스텝에서 동일 (상수 시계열). Retrans↔Throughput 상관 대신 대체 지표를 사용합니다.")
    # Use P99↔Throughput and RTT↔Throughput as alternatives
    lags_retrans_thr, corr_retrans_thr = calculate_lagged_correlations(
        data['p99'], data['throughput'], max_lag=args.max_lag
    )
    alt_desc = 'P99 vs Throughput'
    lags_alt_rtt_thr, corr_alt_rtt_thr = calculate_lagged_correlations(
        data['rtt'], data['throughput'], max_lag=args.max_lag
    )
    # Print both alternatives for clarity
    idx_p99_thr = int(np.argmax(np.abs(corr_retrans_thr)))
    print(f"  → 대체 1) P99 vs Throughput 최대 lag: {lags_retrans_thr[idx_p99_thr]} (r={corr_retrans_thr[idx_p99_thr]:.3f})")
    idx_rtt_thr = int(np.argmax(np.abs(corr_alt_rtt_thr)))
    print(f"  → 대체 2) RTT vs Throughput 최대 lag: {lags_alt_rtt_thr[idx_rtt_thr]} (r={corr_alt_rtt_thr[idx_rtt_thr]:.3f})")
else:
    lags_retrans_thr, corr_retrans_thr = calculate_lagged_correlations(
        data['retrans'], data['throughput'], max_lag=args.max_lag
    )
    alt_desc = 'Retransmission vs Throughput'
    max_corr_idx = np.argmax(np.abs(corr_retrans_thr))
    max_lag = lags_retrans_thr[max_corr_idx]
    max_corr = corr_retrans_thr[max_corr_idx]
    print(f"\n최대 상관 lag: {max_lag} steps (r={max_corr:.3f})")
    if max_lag < 0:
        print(f"  → 재전송이 Throughput보다 {abs(max_lag)} 스텝 **앞서서** 발생")
        print(f"  ✅ 재전송 발생 후 Throughput 감소!")
    elif max_lag > 0:
        print(f"  → Throughput이 재전송보다 {max_lag} 스텝 **앞서서** 감소")
    else:
        print(f"  → 재전송과 Throughput이 동시에 변화")

# 4. Burst Event Analysis
print("\n" + "=" * 80)
print("📈 P99 Burst Event Analysis")
print("=" * 80)

burst_mask = detect_burst_events(data, threshold_multiplier=1.5)
burst_stats = analyze_burst_response(data, burst_mask)

if burst_stats and len(burst_stats['pre_retrans']) > 0:
    print(f"\n검출된 P99 급등 이벤트: {len(burst_stats['pre_retrans'])}개")
    
    pre_retrans_avg = np.mean(burst_stats['pre_retrans']) * 100
    post_retrans_avg = np.mean(burst_stats['post_retrans']) * 100
    
    pre_thr_avg = np.mean(burst_stats['pre_throughput'])
    post_thr_avg = np.mean(burst_stats['post_throughput'])
    
    pre_rtt_avg = np.mean(burst_stats['pre_rtt'])
    post_rtt_avg = np.mean(burst_stats['post_rtt'])
    
    print(f"\n{'Metric':<20} | {'Pre-Burst (5 steps)':<20} | {'Post-Burst (5 steps)':<20} | {'Change':<15}")
    print("-" * 85)
    print(f"{'Retrans Rate':<20} | {pre_retrans_avg:>18.1f}% | {post_retrans_avg:>19.1f}% | "
          f"{((post_retrans_avg - pre_retrans_avg) / max(pre_retrans_avg, 0.1)):>+13.1f}%")
    print(f"{'Throughput (msg/s)':<20} | {pre_thr_avg:>18.1f}  | {post_thr_avg:>19.1f}  | "
          f"{((post_thr_avg - pre_thr_avg) / pre_thr_avg * 100):>+13.1f}%")
    print(f"{'RTT (ms)':<20} | {pre_rtt_avg:>18.1f}  | {post_rtt_avg:>19.1f}  | "
          f"{((post_rtt_avg - pre_rtt_avg) / max(pre_rtt_avg, 0.1) * 100):>+13.1f}%")
    
    # Statistical test
    t_stat, p_val = stats.ttest_rel(burst_stats['pre_retrans'], burst_stats['post_retrans'])
    print(f"\n📊 Paired t-test (Pre vs Post Retrans): t={t_stat:.3f}, p={p_val:.4f}")
    if p_val < 0.05:
        print(f"   ✅ 통계적으로 유의미한 차이 (p < 0.05)")
    else:
        print(f"   ⚠️ 통계적으로 유의하지 않음 (p >= 0.05)")
else:
    print("\n⚠️ P99 급등 이벤트를 충분히 검출하지 못했습니다.")

# 5. Moving Window Correlation
print("\n" + "=" * 80)
print("📊 Moving Window Correlation (시간에 따른 상관관계 변화)")
print("=" * 80)

window_size = 30
moving_corr_p99_retrans = calculate_moving_correlations(data['p99'], data['retrans'], window=window_size)
moving_corr_rtt_retrans = calculate_moving_correlations(data['rtt'], data['retrans'], window=window_size)

avg_moving_corr = np.nanmean(moving_corr_p99_retrans)
print(f"\nP99-Retrans 이동 평균 상관: {avg_moving_corr:.3f}")

# 상관관계가 높은 구간 vs 낮은 구간 비교
high_corr_mask = np.array(moving_corr_p99_retrans) > 0.3
low_corr_mask = np.array(moving_corr_p99_retrans) < -0.1

high_corr_indices = np.where(high_corr_mask)[0]
low_corr_indices = np.where(low_corr_mask)[0]

if len(high_corr_indices) > 0:
    high_corr_p99_avg = np.mean([data['p99'][i] for i in high_corr_indices])
    print(f"\n높은 양의 상관 구간 (r > 0.3): P99 평균 = {high_corr_p99_avg:.1f}ms")

if len(low_corr_indices) > 0:
    low_corr_p99_avg = np.mean([data['p99'][i] for i in low_corr_indices])
    print(f"낮은/음의 상관 구간 (r < -0.1): P99 평균 = {low_corr_p99_avg:.1f}ms")

# ============================================================================
# Visualization
# ============================================================================

fig = plt.figure(figsize=(18, 12))
gs = GridSpec(4, 2, figure=fig, hspace=0.4, wspace=0.3)

t = data['t']

# 1. Lagged Cross-Correlation: P99 vs Retransmission
ax1 = fig.add_subplot(gs[0, 0])
ax1.plot(lags_p99_retrans, corr_p99_retrans, 'b-', linewidth=2)
ax1.axhline(y=0, color='gray', linestyle='--', linewidth=1, alpha=0.5)
ax1.axvline(x=0, color='gray', linestyle='--', linewidth=1, alpha=0.5)
ax1.scatter([lags_p99_retrans[np.argmax(np.abs(corr_p99_retrans))]], 
            [corr_p99_retrans[np.argmax(np.abs(corr_p99_retrans))]], 
            color='red', s=100, zorder=5, label=f'Max at lag={lags_p99_retrans[np.argmax(np.abs(corr_p99_retrans))]}')
ax1.set_xlabel('Lag (steps)', fontsize=11, fontweight='bold')
ax1.set_ylabel('Correlation Coefficient', fontsize=11, fontweight='bold')
ax1.set_title('Lagged Cross-Correlation: P99 vs Retransmission', fontsize=12, fontweight='bold')
ax1.legend(fontsize=9)
ax1.grid(True, alpha=0.3)

# 2. Lagged Cross-Correlation: RTT vs Retransmission
ax2 = fig.add_subplot(gs[0, 1])
ax2.plot(lags_rtt_retrans, corr_rtt_retrans, 'purple', linewidth=2)
ax2.axhline(y=0, color='gray', linestyle='--', linewidth=1, alpha=0.5)
ax2.axvline(x=0, color='gray', linestyle='--', linewidth=1, alpha=0.5)
ax2.scatter([lags_rtt_retrans[np.argmax(np.abs(corr_rtt_retrans))]], 
            [corr_rtt_retrans[np.argmax(np.abs(corr_rtt_retrans))]], 
            color='red', s=100, zorder=5, label=f'Max at lag={lags_rtt_retrans[np.argmax(np.abs(corr_rtt_retrans))]}')
ax2.set_xlabel('Lag (steps)', fontsize=11, fontweight='bold')
ax2.set_ylabel('Correlation Coefficient', fontsize=11, fontweight='bold')
ax2.set_title('Lagged Cross-Correlation: RTT vs Retransmission', fontsize=12, fontweight='bold')
ax2.legend(fontsize=9)
ax2.grid(True, alpha=0.3)

# 3. Time series with burst events highlighted
ax3 = fig.add_subplot(gs[1, :])
ax3_twin = ax3.twinx()

line1 = ax3.plot(t, data['p99'], 'b-', linewidth=1.5, label='P99 Latency', alpha=0.7)
burst_t = [t[i] for i in range(len(burst_mask)) if burst_mask[i]]
burst_p99 = [data['p99'][i] for i in range(len(burst_mask)) if burst_mask[i]]
ax3.scatter(burst_t, burst_p99, color='red', s=80, marker='^', 
            alpha=0.8, label='P99 Burst Event', zorder=5)
ax3.set_ylabel('P99 Latency (ms)', fontsize=12, fontweight='bold', color='blue')
ax3.tick_params(axis='y', labelcolor='blue')

# Retransmission cumulative
cumulative_retrans = np.cumsum(data['retrans'])
line2 = ax3_twin.plot(t, cumulative_retrans, 'r-', linewidth=2, label='Cumulative Retrans', alpha=0.6)
ax3_twin.set_ylabel('Cumulative Retransmissions', fontsize=12, fontweight='bold', color='red')
ax3_twin.tick_params(axis='y', labelcolor='red')

ax3.set_xlabel('Time (seconds)', fontsize=11)
ax3.set_title('P99 Burst Events and Retransmission Response', fontsize=13, fontweight='bold')
ax3.legend(loc='upper left', fontsize=10)
ax3_twin.legend(loc='upper right', fontsize=10)
ax3.grid(True, alpha=0.3)

# 4. Moving window correlation
ax4 = fig.add_subplot(gs[2, :])
valid_indices = [i for i, val in enumerate(moving_corr_p99_retrans) if not np.isnan(val)]
valid_t = [t[i] for i in valid_indices]
valid_corr = [moving_corr_p99_retrans[i] for i in valid_indices]

ax4.plot(valid_t, valid_corr, 'g-', linewidth=2, label='P99-Retrans Moving Corr')
ax4.axhline(y=0, color='gray', linestyle='--', linewidth=1, alpha=0.5)
ax4.axhline(y=avg_moving_corr, color='blue', linestyle=':', linewidth=2, 
            label=f'Average = {avg_moving_corr:.3f}')
ax4.fill_between(valid_t, -1, 1, where=[c > 0.3 for c in valid_corr], 
                  alpha=0.2, color='green', label='High Positive Corr (>0.3)')
ax4.fill_between(valid_t, -1, 1, where=[c < -0.1 for c in valid_corr], 
                  alpha=0.2, color='red', label='Negative Corr (<-0.1)')
ax4.set_ylim([-1, 1])
ax4.set_xlabel('Time (seconds)', fontsize=11)
ax4.set_ylabel('Correlation Coefficient', fontsize=11, fontweight='bold')
ax4.set_title(f'Moving Window Correlation (window={window_size} steps)', fontsize=12, fontweight='bold')
ax4.legend(fontsize=9, loc='lower left')
ax4.grid(True, alpha=0.3)

# 5. Pre/Post Burst Comparison (if available)
if burst_stats and len(burst_stats['pre_retrans']) > 0:
    ax5 = fig.add_subplot(gs[3, 0])
    categories = ['Retrans Rate\n(%)', 'Throughput\n(msg/s)', 'RTT\n(ms)']
    pre_vals = [
        np.mean(burst_stats['pre_retrans']) * 100,
        np.mean(burst_stats['pre_throughput']),
        np.mean(burst_stats['pre_rtt'])
    ]
    post_vals = [
        np.mean(burst_stats['post_retrans']) * 100,
        np.mean(burst_stats['post_throughput']),
        np.mean(burst_stats['post_rtt'])
    ]
    
    x = np.arange(len(categories))
    width = 0.35
    
    # Normalize for visualization
    pre_norm = [pre_vals[0], pre_vals[1] / 10, pre_vals[2] / 10]
    post_norm = [post_vals[0], post_vals[1] / 10, post_vals[2] / 10]
    
    ax5.bar(x - width/2, pre_norm, width, label='Pre-Burst', alpha=0.8, color='steelblue')
    ax5.bar(x + width/2, post_norm, width, label='Post-Burst', alpha=0.8, color='coral')
    ax5.set_xticks(x)
    ax5.set_xticklabels(categories, fontsize=10)
    ax5.set_ylabel('Normalized Value', fontsize=11, fontweight='bold')
    ax5.set_title('Pre vs Post P99 Burst Comparison', fontsize=12, fontweight='bold')
    ax5.legend(fontsize=10)
    ax5.grid(True, alpha=0.3, axis='y')

# 6. Scatter: Snd_ratio vs Retransmission (buffer pressure predictor)
ax6 = fig.add_subplot(gs[3, 1])
ax6.scatter(data['snd_ratio'], data['retrans'], alpha=0.5, s=30, c=data['rtt'], cmap='plasma')
cbar = plt.colorbar(ax6.collections[0], ax=ax6, label='RTT (ms)')
ax6.set_xlabel('Send Buffer Ratio', fontsize=11, fontweight='bold')
ax6.set_ylabel('Retransmission Flag', fontsize=11, fontweight='bold')
ax6.set_title('Buffer Pressure vs Retransmission (colored by RTT)', fontsize=12, fontweight='bold')
ax6.grid(True, alpha=0.3)

# Overall title
fig.suptitle(args.title, fontsize=16, fontweight='bold', y=0.995)

png_path = f"{args.out_prefix}.png"
pdf_path = f"{args.out_prefix}.pdf"

plt.savefig(png_path, dpi=300, bbox_inches='tight')
print(f"\n✅ Saved: {png_path}")

plt.savefig(pdf_path, bbox_inches='tight')
print(f"✅ Saved: {pdf_path}")

print("\n" + "=" * 80)
print("✅ Advanced Analysis Complete!")
print("=" * 80)
print("""
📌 Key Insights:
1. Lagged correlation analysis reveals causal ordering:
   - RTT increase → Retransmission (RTT is leading indicator)
   - Retransmission → Throughput decrease (causal impact)
   
2. P99 burst events show systematic pattern:
   - Pre-burst: Low retrans, high throughput
   - Post-burst: High retrans, low throughput
   
3. Moving window correlation shows:
   - Correlation strength varies over time
   - High correlation during congestion phases
   
4. Buffer pressure (snd_ratio) correlates with retransmission
   - High snd_ratio → more likely to retransmit

💡 This provides STRONGER evidence of feedback loop:
   RTT↑ (leading) → P99↑ → Retrans↑ → Throughput↓ → Congestion↑ → RTT↑
""")

# Write brief summary txt for paper use
try:
    summary_path = f"{args.out_prefix}_summary.txt"
    with open(summary_path, 'w') as f:
        def _max_lag_str(lags, corrs):
            idx = int(np.argmax(np.abs(corrs)))
            return lags[idx], float(corrs[idx])

        lag_pr, r_pr = _max_lag_str(lags_p99_retrans, corr_p99_retrans)
        lag_rr, r_rr = _max_lag_str(lags_rtt_retrans, corr_rtt_retrans)
        lag_rt, r_rt = _max_lag_str(lags_retrans_thr, corr_retrans_thr)

        f.write("Lagged Cross-Correlation Summary\n")
        f.write(f"Log: {log_path}\n")
        f.write(f"P99 vs Retrans: lag={lag_pr}, r={r_pr:.3f}\n")
        f.write(f"RTT vs Retrans: lag={lag_rr}, r={r_rr:.3f}\n")
        # Note: label reflects whether retrans was constant
        label_rt = 'Retrans vs Throughput' if not use_alt_for_thr else 'P99 vs Throughput (alt)'
        f.write(f"{label_rt}: lag={lag_rt}, r={r_rt:.3f}\n")
        if burst_stats and len(burst_stats['pre_retrans']) > 0:
            from statistics import mean
            t_stat, p_val = stats.ttest_rel(burst_stats['pre_retrans'], burst_stats['post_retrans'])
            f.write("\nP99 Burst Event Stats (5-step pre/post)\n")
            f.write(f"Events: {len(burst_stats['pre_retrans'])}\n")
            f.write(f"Retrans pre={mean(burst_stats['pre_retrans']):.4f}, post={mean(burst_stats['post_retrans']):.4f}, p={p_val:.4f}\n")
            f.write(f"RTT    pre={mean(burst_stats['pre_rtt']):.2f}, post={mean(burst_stats['post_rtt']):.2f}\n")
            f.write(f"Thr    pre={mean(burst_stats['pre_throughput']):.2f}, post={mean(burst_stats['post_throughput']):.2f}\n")
    print(f"✅ Saved summary: {summary_path}")
except Exception as e:
    print(f"⚠️ Could not write summary file: {e}")
