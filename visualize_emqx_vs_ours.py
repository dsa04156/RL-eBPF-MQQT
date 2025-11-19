#!/usr/bin/env python3
"""
EMQX vs eBPF+RL 비교 (Congestion Network)
깔끔한 2x2 레이아웃
"""
import json
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

def load_log(path):
    data = []
    try:
        with open(path) as f:
            for line in f:
                try:
                    data.append(json.loads(line))
                except:
                    continue
    except FileNotFoundError:
        print(f"⚠️  파일 없음: {path}")
        return []
    return data

def extract_timeseries(log):
    if not log:
        return None
    
    p99s = [e['metrics']['p99_ms'] for e in log if 'metrics' in e]
    snds = [e['kernel']['snd_ratio'] for e in log if 'kernel' in e]
    
    return {
        'p99': np.array(p99s),
        'snd': np.array(snds),
        'time': np.arange(len(p99s)) * 2.0  # 2초 간격
    }

# 로그 로드
print("="*80)
print("EMQX vs eBPF+RL Comparison (Congestion Network)")
print("="*80)

emqx_log = load_log('logs/emqx_flow_control/conjestion.jsonl')
rl_log = load_log('logs/torch_model_experiments/congestion/rl_bc_v2_congestion.jsonl')

emqx_data = extract_timeseries(emqx_log)
rl_data = extract_timeseries(rl_log)

if not emqx_data or not rl_data:
    print("⚠️  데이터 로드 실패")
    exit(1)

print(f"\n📊 EMQX: {len(emqx_data['p99'])} samples")
print(f"   P99: {np.median(emqx_data['p99']):.1f}ms")
print(f"   snd_ratio: {np.median(emqx_data['snd']):.3f}")

print(f"\n📊 eBPF+RL: {len(rl_data['p99'])} samples")
print(f"   P99: {np.median(rl_data['p99']):.1f}ms")
print(f"   snd_ratio: {np.median(rl_data['snd']):.3f}")

# 그래프 생성: 2x2 레이아웃
fig, axes = plt.subplots(2, 2, figsize=(16, 10))

colors = {
    'EMQX': '#e74c3c',
    'eBPF+RL': '#3498db'
}

# ==================== (0,0): P99 Latency 비교 ====================
ax = axes[0, 0]
ax.plot(emqx_data['time'], emqx_data['p99'], 
        color=colors['EMQX'], label='EMQX (Application-level)',
        linewidth=3, alpha=0.85)
ax.plot(rl_data['time'], rl_data['p99'], 
        color=colors['eBPF+RL'], label='eBPF+RL (Kernel-level)',
        linewidth=3, alpha=0.85)

ax.axhline(y=300, color='green', linestyle='--', linewidth=2.5, 
           label='SLO (300ms)', alpha=0.7)
ax.set_xlabel('Time (seconds)', fontsize=13, fontweight='bold')
ax.set_ylabel('P99 Latency (ms)', fontsize=13, fontweight='bold')
ax.set_title('P99 Tail Latency', fontsize=15, fontweight='bold')
ax.legend(loc='upper right', fontsize=11, framealpha=0.95)
ax.grid(True, alpha=0.3)
ax.set_yscale('log')
ax.set_ylim(1, max(np.max(emqx_data['p99']), np.max(rl_data['p99'])) * 1.2)

# ==================== (0,1): snd_ratio 비교 ====================
ax = axes[0, 1]
ax.plot(emqx_data['time'], emqx_data['snd'], 
        color=colors['EMQX'], label='EMQX',
        linewidth=3, alpha=0.85)
ax.plot(rl_data['time'], rl_data['snd'], 
        color=colors['eBPF+RL'], label='eBPF+RL',
        linewidth=3, alpha=0.85)

ax.axhline(y=1.0, color='orange', linestyle='--', linewidth=2.5, 
           label='Overflow (1.0)', alpha=0.7)
ax.set_xlabel('Time (seconds)', fontsize=13, fontweight='bold')
ax.set_ylabel('snd_ratio (Buffer Pressure)', fontsize=13, fontweight='bold')
ax.set_title('TCP Send Buffer Pressure', fontsize=15, fontweight='bold')
ax.legend(loc='upper right', fontsize=11, framealpha=0.95)
ax.grid(True, alpha=0.3)

# ==================== (1,0): P99 Distribution ====================
ax = axes[1, 0]

emqx_p99_bins = np.logspace(0, 5, 50)
rl_p99_bins = np.logspace(0, 5, 50)

ax.hist(emqx_data['p99'], bins=emqx_p99_bins, 
        color=colors['EMQX'], alpha=0.6, label='EMQX', edgecolor='black')
ax.hist(rl_data['p99'], bins=rl_p99_bins, 
        color=colors['eBPF+RL'], alpha=0.6, label='eBPF+RL', edgecolor='black')

ax.axvline(x=300, color='green', linestyle='--', linewidth=2.5, 
           label='SLO (300ms)', alpha=0.7)
ax.set_xlabel('P99 Latency (ms)', fontsize=13, fontweight='bold')
ax.set_ylabel('Frequency', fontsize=13, fontweight='bold')
ax.set_title('P99 Distribution', fontsize=15, fontweight='bold')
ax.legend(loc='upper right', fontsize=11, framealpha=0.95)
ax.grid(True, alpha=0.3, axis='y')
ax.set_xscale('log')

# ==================== (1,1): 통계 비교 ====================
ax = axes[1, 1]

metrics = ['P99\n(ms)', 'snd_ratio', 'Buffer\nOverflow (%)']
emqx_vals = [
    np.median(emqx_data['p99']),
    np.median(emqx_data['snd']) * 100,  # 스케일 조정
    len(emqx_data['snd'][emqx_data['snd'] > 1.0]) / len(emqx_data['snd']) * 100
]
rl_vals = [
    np.median(rl_data['p99']),
    np.median(rl_data['snd']) * 100,  # 스케일 조정
    len(rl_data['snd'][rl_data['snd'] > 1.0]) / len(rl_data['snd']) * 100
]

x = np.arange(len(metrics))
width = 0.35

bars1 = ax.bar(x - width/2, emqx_vals, width, label='EMQX',
               color=colors['EMQX'], alpha=0.8, edgecolor='black', linewidth=2)
bars2 = ax.bar(x + width/2, rl_vals, width, label='eBPF+RL',
               color=colors['eBPF+RL'], alpha=0.8, edgecolor='black', linewidth=2)

ax.set_ylabel('Value (scaled)', fontsize=13, fontweight='bold')
ax.set_title('Performance Comparison', fontsize=15, fontweight='bold')
ax.set_xticks(x)
ax.set_xticklabels(metrics, fontsize=12, fontweight='bold')
ax.legend(loc='upper left', fontsize=11, framealpha=0.95)
ax.grid(True, alpha=0.3, axis='y')
ax.set_yscale('log')

# 값 표시
for bar, val, metric_idx in zip(bars1, emqx_vals, range(len(metrics))):
    height = bar.get_height()
    if metric_idx == 0:  # P99
        label = f'{val:.0f}'
    elif metric_idx == 1:  # snd_ratio (원래 값으로)
        label = f'{val/100:.2f}'
    else:  # overflow
        label = f'{val:.1f}%'
    ax.text(bar.get_x() + bar.get_width()/2., height*1.2,
           label, ha='center', va='bottom', fontsize=10, fontweight='bold',
           color=colors['EMQX'])

for bar, val, metric_idx in zip(bars2, rl_vals, range(len(metrics))):
    height = bar.get_height()
    if metric_idx == 0:  # P99
        label = f'{val:.0f}'
    elif metric_idx == 1:  # snd_ratio (원래 값으로)
        label = f'{val/100:.3f}'
    else:  # overflow
        label = f'{val:.1f}%'
    ax.text(bar.get_x() + bar.get_width()/2., height*1.2,
           label, ha='center', va='bottom', fontsize=10, fontweight='bold',
           color=colors['eBPF+RL'])

plt.tight_layout()

# 저장
output_dir = Path('results/final_comparison')
output_dir.mkdir(parents=True, exist_ok=True)
output_path = output_dir / 'congestion_timeseries.png'
plt.savefig(output_path, dpi=150, facecolor='white')
print(f"\n✅ 그래프 저장: {output_path}")

# 통계 출력
print(f"\n{'='*80}")
print("📊 성능 비교 통계")
print(f"{'='*80}")

emqx_p99_med = np.median(emqx_data['p99'])
rl_p99_med = np.median(rl_data['p99'])
emqx_snd_med = np.median(emqx_data['snd'])
rl_snd_med = np.median(rl_data['snd'])

emqx_overflow = len(emqx_data['snd'][emqx_data['snd'] > 1.0]) / len(emqx_data['snd']) * 100
rl_overflow = len(rl_data['snd'][rl_data['snd'] > 1.0]) / len(rl_data['snd']) * 100

emqx_slo = len([p for p in emqx_data['p99'] if p <= 300]) / len(emqx_data['p99']) * 100
rl_slo = len([p for p in rl_data['p99'] if p <= 300]) / len(rl_data['p99']) * 100

improvement_p99 = (emqx_p99_med - rl_p99_med) / emqx_p99_med * 100
improvement_snd = (emqx_snd_med - rl_snd_med) / emqx_snd_med * 100

print(f"\n{'지표':<20} {'EMQX':>15} {'eBPF+RL':>15} {'개선율':>15}")
print(f"{'-'*80}")
print(f"{'P99 Latency (ms)':<20} {emqx_p99_med:>15.1f} {rl_p99_med:>15.1f} {improvement_p99:>14.1f}%")
print(f"{'snd_ratio':<20} {emqx_snd_med:>15.3f} {rl_snd_med:>15.3f} {improvement_snd:>14.1f}%")
print(f"{'Buffer Overflow (%)':<20} {emqx_overflow:>15.1f} {rl_overflow:>15.1f} {emqx_overflow-rl_overflow:>14.1f}%p")
print(f"{'SLO Compliance (%)':<20} {emqx_slo:>15.1f} {rl_slo:>15.1f} {rl_slo-emqx_slo:>14.1f}%p")

print(f"\n{'='*80}")
print("💡 핵심 발견")
print(f"{'='*80}")
print(f"""
1️⃣  P99 Latency:
   • EMQX: {emqx_p99_med:.1f}ms ({emqx_p99_med/1000:.1f}초)
   • eBPF+RL: {rl_p99_med:.1f}ms
   • 개선: {improvement_p99:.1f}% ({emqx_p99_med/rl_p99_med:.0f}배)

2️⃣  Buffer Control:
   • EMQX: snd_ratio={emqx_snd_med:.3f}, 넘침={emqx_overflow:.1f}%
   • eBPF+RL: snd_ratio={rl_snd_med:.3f}, 넘침={rl_overflow:.1f}%
   • 차이: 커널 신호 모니터링 유무

3️⃣  SLO Compliance:
   • EMQX: {emqx_slo:.1f}% (거의 불가능)
   • eBPF+RL: {rl_slo:.1f}% (부분 달성)
   
🔑 결론:
"Application-level Flow Control (EMQX)로는 P99=20초를 0.3초로 낮출 수 없다.
 eBPF 기반 커널 신호 모니터링이 SLO 수준 제어에 필수적이다."
""")
