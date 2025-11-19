#!/usr/bin/env python3
"""
Dynamic scenario comparison visualization
동적 네트워크 환경에서 EMQX vs BC v2 모델 비교 시각화
"""

import json
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.gridspec import GridSpec

# 한글 폰트 설정
plt.rcParams['font.family'] = 'DejaVu Sans'
plt.rcParams['axes.unicode_minus'] = False

def load_log(path):
    data = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data.append(json.loads(line))
            except:
                continue
    return data

print("Loading logs...")
log1 = load_log("logs/emqx_flow_control/dynamic.jsonl")
log2 = load_log("logs/torch_model_experiments/dynamic/rl_bc_v2_dynamic.jsonl")

print(f"EMQX: {len(log1)} steps")
print(f"BC v2: {len(log2)} steps")

# Extract time series
def extract_series(data):
    timestamps = [d['ts'] for d in data]
    # Normalize to start from 0
    if timestamps:
        t_start = timestamps[0]
        timestamps = [(t - t_start) for t in timestamps]
    
    p99s = [d.get('metrics', {}).get('p99_ms', 0) for d in data]
    p95s = [d.get('metrics', {}).get('p95_ms', 0) for d in data]
    p50s = [d.get('metrics', {}).get('p50_ms', 0) for d in data]
    rewards = [d.get('r', 0) for d in data]
    
    actions = [d.get('a', {}).get('d_rate', 0) for d in data]
    applied = [1 if d.get('applied', False) else 0 for d in data]
    
    congestion = [d.get('kernel', {}).get('congestion_score', 0) for d in data]
    
    return {
        't': timestamps,
        'p99': p99s,
        'p95': p95s,
        'p50': p50s,
        'reward': rewards,
        'action': actions,
        'applied': applied,
        'congestion': congestion
    }

s1 = extract_series(log1)
s2 = extract_series(log2)

# Create comprehensive visualization
fig = plt.figure(figsize=(16, 12))
gs = GridSpec(4, 2, figure=fig, hspace=0.3, wspace=0.3)

# 1. P99 Latency Comparison
ax1 = fig.add_subplot(gs[0, :])
ax1.plot(s1['t'], s1['p99'], 'b-', alpha=0.7, linewidth=2, label='EMQX Flow Control (Shadow)')
ax1.plot(s2['t'], s2['p99'], 'r-', alpha=0.7, linewidth=2, label='BC v2 Model (Online)')
ax1.axhline(y=200, color='gray', linestyle='--', linewidth=1, alpha=0.5, label='SLO Target (200ms)')
ax1.set_ylabel('P99 Latency (ms)', fontsize=12, fontweight='bold')
ax1.set_xlabel('Time (seconds)', fontsize=11)
ax1.set_title('P99 Latency Over Time - Dynamic Network Scenario', fontsize=14, fontweight='bold')
ax1.legend(loc='upper right', fontsize=10)
ax1.grid(True, alpha=0.3)
ax1.set_ylim(bottom=0)

# 2. P95 Latency
ax2 = fig.add_subplot(gs[1, 0])
ax2.plot(s1['t'], s1['p95'], 'b-', alpha=0.6, linewidth=1.5, label='EMQX')
ax2.plot(s2['t'], s2['p95'], 'r-', alpha=0.6, linewidth=1.5, label='BC v2')
ax2.set_ylabel('P95 Latency (ms)', fontsize=11, fontweight='bold')
ax2.set_xlabel('Time (seconds)', fontsize=10)
ax2.set_title('P95 Latency', fontsize=12, fontweight='bold')
ax2.legend(loc='upper right', fontsize=9)
ax2.grid(True, alpha=0.3)

# 3. P50 Latency
ax3 = fig.add_subplot(gs[1, 1])
ax3.plot(s1['t'], s1['p50'], 'b-', alpha=0.6, linewidth=1.5, label='EMQX')
ax3.plot(s2['t'], s2['p50'], 'r-', alpha=0.6, linewidth=1.5, label='BC v2')
ax3.set_ylabel('P50 Latency (ms)', fontsize=11, fontweight='bold')
ax3.set_xlabel('Time (seconds)', fontsize=10)
ax3.set_title('P50 Latency', fontsize=12, fontweight='bold')
ax3.legend(loc='upper right', fontsize=9)
ax3.grid(True, alpha=0.3)

# 4. Rewards
ax4 = fig.add_subplot(gs[2, 0])
ax4.plot(s1['t'], s1['reward'], 'b-', alpha=0.6, linewidth=1.5, label='EMQX')
ax4.plot(s2['t'], s2['reward'], 'r-', alpha=0.6, linewidth=1.5, label='BC v2')
ax4.axhline(y=0, color='black', linestyle='-', linewidth=0.5, alpha=0.3)
ax4.set_ylabel('Reward', fontsize=11, fontweight='bold')
ax4.set_xlabel('Time (seconds)', fontsize=10)
ax4.set_title('Reward Signal', fontsize=12, fontweight='bold')
ax4.legend(loc='lower right', fontsize=9)
ax4.grid(True, alpha=0.3)

# 5. Actions with Applied markers
ax5 = fig.add_subplot(gs[2, 1])
ax5.plot(s1['t'], s1['action'], 'b-', alpha=0.4, linewidth=1, label='EMQX Action')
ax5.plot(s2['t'], s2['action'], 'r-', alpha=0.4, linewidth=1, label='BC v2 Action')

# Mark applied actions
applied_t2 = [s2['t'][i] for i in range(len(s2['applied'])) if s2['applied'][i] == 1]
applied_a2 = [s2['action'][i] for i in range(len(s2['applied'])) if s2['applied'][i] == 1]
if applied_t2:
    ax5.scatter(applied_t2, applied_a2, color='red', s=100, marker='o', 
                edgecolors='black', linewidths=2, zorder=5, label='BC v2 Applied')

ax5.axhline(y=0, color='black', linestyle='-', linewidth=0.5, alpha=0.3)
ax5.set_ylabel('Action (d_rate)', fontsize=11, fontweight='bold')
ax5.set_xlabel('Time (seconds)', fontsize=10)
ax5.set_title('Control Actions (Applied Actions Marked)', fontsize=12, fontweight='bold')
ax5.legend(loc='upper right', fontsize=9)
ax5.grid(True, alpha=0.3)

# 6. Congestion Score
ax6 = fig.add_subplot(gs[3, :])
ax6.plot(s1['t'], s1['congestion'], 'b-', alpha=0.5, linewidth=1.5, label='EMQX Congestion')
ax6.plot(s2['t'], s2['congestion'], 'r-', alpha=0.5, linewidth=1.5, label='BC v2 Congestion')
ax6.fill_between(s1['t'], s1['congestion'], alpha=0.2, color='blue')
ax6.fill_between(s2['t'], s2['congestion'], alpha=0.2, color='red')
ax6.set_ylabel('Congestion Score', fontsize=11, fontweight='bold')
ax6.set_xlabel('Time (seconds)', fontsize=10)
ax6.set_title('Network Congestion (Dynamic Phases)', fontsize=12, fontweight='bold')
ax6.legend(loc='upper right', fontsize=9)
ax6.grid(True, alpha=0.3)
ax6.set_ylim(bottom=0)

# Add annotations for key insights
fig.text(0.5, 0.98, 'Dynamic Network Scenario: EMQX Flow Control vs BC v2 Model', 
         ha='center', va='top', fontsize=16, fontweight='bold')

# Summary statistics box
summary_text = f"""Summary Statistics:
EMQX: {len(log1)} steps, P99 mean={np.mean(s1['p99']):.1f}ms, Applied={sum(s1['applied'])}/{len(s1['applied'])}
BC v2: {len(log2)} steps, P99 mean={np.mean(s2['p99']):.1f}ms, Applied={sum(s2['applied'])}/{len(s2['applied'])} ⚡
"""
fig.text(0.02, 0.02, summary_text, ha='left', va='bottom', 
         fontsize=9, family='monospace', 
         bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.3))

plt.savefig('results/dynamic_comparison.png', dpi=300, bbox_inches='tight')
print("\n✅ Saved: results/dynamic_comparison.png")

plt.savefig('results/dynamic_comparison.pdf', bbox_inches='tight')
print("✅ Saved: results/dynamic_comparison.pdf")

plt.show()

print("\n" + "="*80)
print("📊 Visualization Complete!")
print("="*80)
print(f"""
Key Findings:
1. BC v2 applied only {sum(s2['applied'])} action(s) but achieved {np.mean(s2['p99']):.1f}ms avg P99
2. EMQX had {sum(s1['applied'])} applied (shadow mode) with {np.mean(s1['p99']):.1f}ms avg P99
3. Dynamic network phases visible in congestion score fluctuations
4. Single control action from BC v2 had lasting impact on tail latency
""")
