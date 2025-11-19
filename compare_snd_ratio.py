#!/usr/bin/env python3
"""
EMQX Shadow vs RL Online 모드의 snd_ratio 비교
"""
import json
import numpy as np
import matplotlib.pyplot as plt

def load_snd_ratio(log_path):
    """로그에서 snd_ratio 추출"""
    snd_ratios = []
    with open(log_path) as f:
        for line in f:
            if not line.strip():
                continue
            data = json.loads(line)
            kernel = data.get('kernel', {})
            snd_ratio = kernel.get('snd_ratio', 0)
            snd_ratios.append(snd_ratio)
    return np.array(snd_ratios)

# 로그 로드
emqx_path = "logs/emqx_flow_control/congestion.jsonl"
rl_path = "logs/torch_model_experiments/congestion/rl_bc_v2_congestion.jsonl"

print("📊 EMQX vs RL: snd_ratio 비교 분석")
print("=" * 80)

emqx_snd = load_snd_ratio(emqx_path)
rl_snd = load_snd_ratio(rl_path)

print(f"\n📈 EMQX Flow Control (Shadow Mode)")
print(f"  Data points: {len(emqx_snd)}")
print(f"  Mean:   {np.mean(emqx_snd):.4f}")
print(f"  Median: {np.median(emqx_snd):.4f}")
print(f"  Std:    {np.std(emqx_snd):.4f}")
print(f"  Min:    {np.min(emqx_snd):.4f}")
print(f"  Max:    {np.max(emqx_snd):.4f}")
print(f"  P95:    {np.percentile(emqx_snd, 95):.4f}")
print(f"  P99:    {np.percentile(emqx_snd, 99):.4f}")

print(f"\n🎯 RL Online Control (Torch)")
print(f"  Data points: {len(rl_snd)}")
print(f"  Mean:   {np.mean(rl_snd):.4f}")
print(f"  Median: {np.median(rl_snd):.4f}")
print(f"  Std:    {np.std(rl_snd):.4f}")
print(f"  Min:    {np.min(rl_snd):.4f}")
print(f"  Max:    {np.max(rl_snd):.4f}")
print(f"  P95:    {np.percentile(rl_snd, 95):.4f}")
print(f"  P99:    {np.percentile(rl_snd, 99):.4f}")

# 개선율 계산
mean_improvement = (np.mean(emqx_snd) - np.mean(rl_snd)) / np.mean(emqx_snd) * 100
max_improvement = (np.max(emqx_snd) - np.max(rl_snd)) / np.max(emqx_snd) * 100
p99_improvement = (np.percentile(emqx_snd, 99) - np.percentile(rl_snd, 99)) / np.percentile(emqx_snd, 99) * 100

print(f"\n✨ 개선율")
print(f"  평균 snd_ratio: {mean_improvement:+.1f}%")
print(f"  최대 snd_ratio: {max_improvement:+.1f}%")
print(f"  P99 snd_ratio:  {p99_improvement:+.1f}%")

# 버퍼 압력 상태 분류
def classify_pressure(snd_ratios):
    low = np.sum(snd_ratios < 0.1) / len(snd_ratios) * 100
    medium = np.sum((snd_ratios >= 0.1) & (snd_ratios < 0.3)) / len(snd_ratios) * 100
    high = np.sum((snd_ratios >= 0.3) & (snd_ratios < 0.5)) / len(snd_ratios) * 100
    critical = np.sum(snd_ratios >= 0.5) / len(snd_ratios) * 100
    return low, medium, high, critical

print(f"\n🔍 버퍼 압력 분포 (EMQX)")
emqx_low, emqx_med, emqx_high, emqx_crit = classify_pressure(emqx_snd)
print(f"  낮음 (<0.1):     {emqx_low:5.1f}%  ✅")
print(f"  중간 (0.1~0.3):  {emqx_med:5.1f}%  ⚠️")
print(f"  높음 (0.3~0.5):  {emqx_high:5.1f}%  ⚠️⚠️")
print(f"  위험 (≥0.5):     {emqx_crit:5.1f}%  ❌")

print(f"\n🔍 버퍼 압력 분포 (RL)")
rl_low, rl_med, rl_high, rl_crit = classify_pressure(rl_snd)
print(f"  낮음 (<0.1):     {rl_low:5.1f}%  ✅")
print(f"  중간 (0.1~0.3):  {rl_med:5.1f}%  ⚠️")
print(f"  높음 (0.3~0.5):  {rl_high:5.1f}%  ⚠️⚠️")
print(f"  위험 (≥0.5):     {rl_crit:5.1f}%  ❌")

# 그래프 생성
fig, axes = plt.subplots(2, 2, figsize=(16, 12))
fig.suptitle('EMQX vs RL: snd_ratio (TCP Send Buffer Pressure) Comparison', 
             fontsize=16, fontweight='bold')

# 1. Time series
ax = axes[0, 0]
ax.plot(emqx_snd, label='EMQX (Shadow)', alpha=0.7, linewidth=1)
ax.plot(rl_snd, label='RL (Online)', alpha=0.7, linewidth=1)
ax.axhline(0.1, color='orange', linestyle='--', alpha=0.5, label='Caution')
ax.axhline(0.3, color='red', linestyle='--', alpha=0.5, label='Warning')
ax.set_xlabel('Time Window')
ax.set_ylabel('snd_ratio')
ax.set_title('snd_ratio Over Time')
ax.legend()
ax.grid(True, alpha=0.3)

# 2. Histogram
ax = axes[0, 1]
bins = np.linspace(0, max(np.max(emqx_snd), np.max(rl_snd)), 50)
ax.hist(emqx_snd, bins=bins, alpha=0.6, label='EMQX', edgecolor='black')
ax.hist(rl_snd, bins=bins, alpha=0.6, label='RL', edgecolor='black')
ax.axvline(0.1, color='orange', linestyle='--', alpha=0.5)
ax.axvline(0.3, color='red', linestyle='--', alpha=0.5)
ax.set_xlabel('snd_ratio')
ax.set_ylabel('Frequency')
ax.set_title('snd_ratio Distribution')
ax.legend()
ax.grid(True, alpha=0.3)

# 3. CDF
ax = axes[1, 0]
emqx_sorted = np.sort(emqx_snd)
rl_sorted = np.sort(rl_snd)
emqx_cdf = np.arange(1, len(emqx_sorted)+1) / len(emqx_sorted)
rl_cdf = np.arange(1, len(rl_sorted)+1) / len(rl_sorted)
ax.plot(emqx_sorted, emqx_cdf, label='EMQX', linewidth=2)
ax.plot(rl_sorted, rl_cdf, label='RL', linewidth=2)
ax.axvline(0.1, color='orange', linestyle='--', alpha=0.5)
ax.axvline(0.3, color='red', linestyle='--', alpha=0.5)
ax.set_xlabel('snd_ratio')
ax.set_ylabel('CDF')
ax.set_title('Cumulative Distribution Function')
ax.legend()
ax.grid(True, alpha=0.3)

# 4. Box plot
ax = axes[1, 1]
ax.boxplot([emqx_snd, rl_snd], labels=['EMQX', 'RL'])
ax.axhline(0.1, color='orange', linestyle='--', alpha=0.5)
ax.axhline(0.3, color='red', linestyle='--', alpha=0.5)
ax.set_ylabel('snd_ratio')
ax.set_title('Box Plot Comparison')
ax.grid(True, alpha=0.3, axis='y')

plt.tight_layout()
plt.savefig('results/snd_ratio_comparison.png', dpi=300, bbox_inches='tight')
print(f"\n✅ Saved: results/snd_ratio_comparison.png")

print("\n" + "=" * 80)
print("💡 해석:")
print("  - snd_ratio = TCP 송신 버퍼 사용률 (0~1)")
print("  - 낮을수록 좋음 (버퍼 압력 낮음)")
print("  - EMQX보다 RL이 낮으면 → 버퍼 관리 우수 → Latency 안정")
