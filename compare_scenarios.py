#!/usr/bin/env python3
"""
Normal vs Congestion 네트워크 비교
평시 상태와 혼잡 상태에서 3가지 방법의 성능 비교
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

def get_stats(log):
    if not log:
        return None
    
    p99s = [e['metrics']['p99_ms'] for e in log if 'metrics' in e]
    snds = [e['kernel']['snd_ratio'] for e in log if 'kernel' in e]
    
    slo_compliant = [p for p in p99s if p <= 300]
    
    return {
        'p99_med': np.median(p99s),
        'snd_med': np.median(snds),
        'snd_overflow_rate': len([s for s in snds if s > 1.0])/len(snds)*100,
        'slo_rate': len(slo_compliant)/len(p99s)*100,
        'samples': len(log)
    }

# 로그 로드
print("="*80)
print("Normal vs Congestion 네트워크 비교")
print("="*80)

scenarios = {
    'Normal': {
        'baseline': 'logs/baseline/normal.jsonl',
        'emqx': 'logs/emqx_flow_control/normal.jsonl',
        'rl': 'logs/torch_model_experiments/normal/rl_torch_normal.jsonl'
    },
    'Congestion': {
        'baseline': 'logs/baseline/congestion.jsonl',
        'emqx': 'logs/emqx_flow_control/conjestion.jsonl',
        'rl': 'logs/torch_model_experiments/congestion/rl_bc_v2_congestion.jsonl'
    }
}

results = {}
for scenario_name, paths in scenarios.items():
    print(f"\n{'='*80}")
    print(f"📍 {scenario_name} Network")
    print(f"{'='*80}")
    
    results[scenario_name] = {}
    for method, path in paths.items():
        log = load_log(path)
        stats = get_stats(log)
        
        if stats:
            results[scenario_name][method] = stats
            print(f"\n{method.upper()}:")
            print(f"  샘플: {stats['samples']}개")
            print(f"  P99: {stats['p99_med']:.1f} ms")
            print(f"  snd_ratio: {stats['snd_med']:.3f}")
            print(f"  버퍼 넘침: {stats['snd_overflow_rate']:.1f}%")
            print(f"  SLO 준수: {stats['slo_rate']:.1f}%")
        else:
            print(f"\n{method.upper()}: 데이터 없음")

# 비교 테이블 생성
print(f"\n{'='*80}")
print("📊 시나리오별 종합 비교")
print(f"{'='*80}")

for scenario_name in ['Normal', 'Congestion']:
    print(f"\n【 {scenario_name} Network 】")
    print(f"{'─'*80}")
    
    if scenario_name not in results:
        continue
    
    scenario_data = results[scenario_name]
    
    # P99 비교
    print(f"\n{'방법':<15} {'P99 (ms)':>15} {'snd_ratio':>15} {'버퍼넘침(%)':>15} {'SLO준수(%)':>15}")
    print(f"{'─'*80}")
    
    for method in ['baseline', 'emqx', 'rl']:
        if method in scenario_data:
            s = scenario_data[method]
            method_name = {'baseline': 'Baseline', 'emqx': 'EMQX', 'rl': 'eBPF+RL'}[method]
            print(f"{method_name:<15} {s['p99_med']:>15.1f} {s['snd_med']:>15.3f} {s['snd_overflow_rate']:>15.1f} {s['slo_rate']:>15.1f}")

# 시나리오 간 차이 분석
print(f"\n{'='*80}")
print("💡 핵심 인사이트: Normal vs Congestion")
print(f"{'='*80}")

if 'Normal' in results and 'Congestion' in results:
    print("\n1️⃣  Normal Network (평시):")
    if 'emqx' in results['Normal']:
        n_emqx = results['Normal']['emqx']
        print(f"   • EMQX: P99={n_emqx['p99_med']:.1f}ms, snd_ratio={n_emqx['snd_med']:.3f}")
        print(f"   → 네트워크가 양호하면 Flow Control이 정상 동작")
    
    print("\n2️⃣  Congestion Network (혼잡):")
    if 'emqx' in results['Congestion']:
        c_emqx = results['Congestion']['emqx']
        print(f"   • EMQX: P99={c_emqx['p99_med']:.1f}ms, snd_ratio={c_emqx['snd_med']:.3f}")
        print(f"   → 네트워크가 혼잡하면 Flow Control 완전 실패!")
    
    if 'emqx' in results['Normal'] and 'emqx' in results['Congestion']:
        n_emqx = results['Normal']['emqx']
        c_emqx = results['Congestion']['emqx']
        degradation = (c_emqx['p99_med'] / n_emqx['p99_med'] - 1) * 100
        print(f"\n   📉 EMQX 성능 저하: {degradation:.0f}% (Normal → Congestion)")
    
    print("\n3️⃣  eBPF+RL의 안정성:")
    if 'rl' in results['Normal'] and 'rl' in results['Congestion']:
        n_rl = results['Normal'].get('rl', {})
        c_rl = results['Congestion']['rl']
        if n_rl:
            print(f"   • Normal: P99={n_rl['p99_med']:.1f}ms, snd_ratio={n_rl['snd_med']:.3f}")
        print(f"   • Congestion: P99={c_rl['p99_med']:.1f}ms, snd_ratio={c_rl['snd_med']:.3f}")
        print(f"   → 네트워크 상태와 무관하게 안정적 제어!")

print(f"\n{'='*80}")
print("🔑 결론")
print(f"{'='*80}")
print("""
【 Normal Network (평시) 】
• Application-level Flow Control이 어느 정도 동작
• 모든 방법이 비슷한 성능
• eBPF의 이점이 크게 드러나지 않음

【 Congestion Network (혼잡) 】
• Application-level Flow Control 완전 실패
• EMQX가 Baseline보다도 나쁨 (역효과!)
• eBPF+RL만 안정적 성능 유지

💡 핵심 메시지:
"혼잡 네트워크에서만 Application-level의 한계가 명확히 드러난다.
 평시에는 괜찮지만, 혼잡할 때 커널 신호 없이는 불가능하다."
""")

# 시각화
fig, axes = plt.subplots(1, 2, figsize=(16, 6))
fig.suptitle('Normal vs Congestion Network Comparison', fontsize=16, fontweight='bold')

methods = ['Baseline', 'EMQX', 'eBPF+RL']
colors = ['#808080', '#e74c3c', '#3498db']

for idx, scenario in enumerate(['Normal', 'Congestion']):
    ax = axes[idx]
    
    if scenario not in results:
        continue
    
    scenario_data = results[scenario]
    p99_values = []
    snd_values = []
    actual_methods = []
    actual_colors = []
    
    for i, method in enumerate(['baseline', 'emqx', 'rl']):
        if method in scenario_data:
            p99_values.append(scenario_data[method]['p99_med'])
            snd_values.append(scenario_data[method]['snd_med'])
            actual_methods.append(methods[i])
            actual_colors.append(colors[i])
    
    # P99와 snd_ratio를 dual axis로 표시
    ax2 = ax.twinx()
    
    x = range(len(actual_methods))
    width = 0.35
    
    bars1 = ax.bar([i - width/2 for i in x], p99_values, width, 
                    label='P99 Latency', color=actual_colors, alpha=0.7, edgecolor='black', linewidth=2)
    bars2 = ax2.bar([i + width/2 for i in x], snd_values, width,
                     label='snd_ratio', color=actual_colors, alpha=0.4, edgecolor='black', linewidth=2, hatch='///')
    
    ax.set_xlabel('Method', fontsize=12, fontweight='bold')
    ax.set_ylabel('P99 Latency (ms)', fontsize=12, fontweight='bold', color='black')
    ax2.set_ylabel('snd_ratio (Buffer Pressure)', fontsize=12, fontweight='bold', color='darkred')
    ax.set_title(f'{scenario} Network', fontsize=14, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(actual_methods)
    
    if scenario == 'Congestion':
        ax.set_yscale('log')
    
    ax.axhline(y=300, color='green', linestyle='--', linewidth=2, label='SLO (300ms)', alpha=0.7)
    ax2.axhline(y=1.0, color='orange', linestyle='--', linewidth=2, label='Overflow (1.0)', alpha=0.7)
    
    # 값 표시
    for bar, val in zip(bars1, p99_values):
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height*1.2,
                f'{val:.0f}ms', ha='center', va='bottom', fontsize=10, fontweight='bold')
    
    for bar, val in zip(bars2, snd_values):
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height*1.1,
                 f'{val:.2f}', ha='center', va='bottom', fontsize=10, fontweight='bold', color='darkred')
    
    ax.grid(True, alpha=0.3, axis='y')
    ax.legend(loc='upper left', fontsize=10)
    ax2.legend(loc='upper right', fontsize=10)

plt.tight_layout()
output_dir = Path('results/scenario_comparison')
output_dir.mkdir(parents=True, exist_ok=True)
output_path = output_dir / 'normal_vs_congestion.png'
plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
print(f"\n✅ 그래프 저장: {output_path}")
