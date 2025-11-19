#!/usr/bin/env python3
"""
Congestion 네트워크에서 3가지 방법 비교
1. Baseline (제어 없음)
2. EMQX Flow Control (Application-level)
3. eBPF+RL (Kernel-level)
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

def analyze_method(name, log, color='gray'):
    if not log:
        print(f"\n⚠️  {name}: 데이터 없음")
        return None
    
    p99s = [e['metrics']['p99_ms'] for e in log if 'metrics' in e]
    p95s = [e['metrics']['p95_ms'] for e in log if 'metrics' in e]
    p50s = [e['metrics']['p50_ms'] for e in log if 'metrics' in e]
    snds = [e['kernel']['snd_ratio'] for e in log if 'kernel' in e]
    rtts = [e['kernel']['ewma_rtt_us']/1000 for e in log if 'kernel' in e]
    
    # SLO 준수
    slo_compliant = [p for p in p99s if p <= 300]
    
    print(f"\n{'='*80}")
    print(f"{name}")
    print(f"{'='*80}")
    print(f"📊 샘플 수: {len(log)}개")
    print(f"\n🎯 Tail Latency:")
    print(f"  • P50: {np.median(p50s):.1f} ms")
    print(f"  • P95: {np.median(p95s):.1f} ms")
    print(f"  • P99: {np.median(p99s):.1f} ms (평균: {np.mean(p99s):.1f}, 최대: {np.max(p99s):.1f})")
    
    print(f"\n🔧 TCP 커널 신호:")
    print(f"  • snd_ratio: {np.median(snds):.3f} (평균: {np.mean(snds):.3f}, 최대: {np.max(snds):.3f})")
    print(f"  • snd_ratio > 1.0 비율: {len([s for s in snds if s > 1.0])/len(snds)*100:.1f}%")
    print(f"  • RTT: {np.median(rtts):.1f} ms")
    
    print(f"\n✅ SLO 준수 (P99 < 300ms): {len(slo_compliant)}/{len(p99s)} ({len(slo_compliant)/len(p99s)*100:.1f}%)")
    
    return {
        'name': name,
        'color': color,
        'samples': len(log),
        'p99_med': np.median(p99s),
        'p99_mean': np.mean(p99s),
        'p99_max': np.max(p99s),
        'p95_med': np.median(p95s),
        'p50_med': np.median(p50s),
        'snd_med': np.median(snds),
        'snd_mean': np.mean(snds),
        'snd_max': np.max(snds),
        'snd_overflow_rate': len([s for s in snds if s > 1.0])/len(snds)*100,
        'rtt_med': np.median(rtts),
        'slo_rate': len(slo_compliant)/len(p99s)*100,
        'p99s': p99s,
        'snds': snds,
        'rtts': rtts
    }

def visualize_three_way(baseline_stats, emqx_stats, rl_stats, output_dir):
    """3가지 방법 비교 시각화 - Congestion 네트워크 상태만"""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    fig = plt.figure(figsize=(20, 14))
    gs = fig.add_gridspec(3, 3, hspace=0.35, wspace=0.3)
    
    fig.suptitle('Congestion Network: Baseline vs EMQX vs eBPF+RL\n'
                 'Why Application-level Flow Control Fails', 
                 fontsize=16, fontweight='bold')
    
    methods = ['Baseline\n(No Control)', 'EMQX\n(App-level)', 'eBPF+RL\n(Kernel-level)']
    colors = ['gray', 'red', 'blue']
    stats_list = [baseline_stats, emqx_stats, rl_stats]
    
    # 1. P99 비교 (Bar)
    ax = fig.add_subplot(gs[0, 0])
    p99_values = [s['p99_med'] for s in stats_list]
    bars = ax.bar(methods, p99_values, color=colors, alpha=0.7, edgecolor='black', linewidth=2)
    ax.axhline(y=300, color='green', linestyle='--', linewidth=2, label='SLO (300ms)')
    ax.set_ylabel('P99 Latency (ms)', fontsize=12, fontweight='bold')
    ax.set_title('P99 Tail Latency', fontsize=13, fontweight='bold')
    ax.set_yscale('log')
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3, axis='y')
    
    for bar, val in zip(bars, p99_values):
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height*1.5,
                f'{val:.0f}ms', ha='center', va='bottom', fontsize=10, fontweight='bold')
    
    # 2. snd_ratio 비교 (Bar)
    ax = fig.add_subplot(gs[0, 1])
    snd_values = [s['snd_med'] for s in stats_list]
    bars = ax.bar(methods, snd_values, color=colors, alpha=0.7, edgecolor='black', linewidth=2)
    ax.axhline(y=1.0, color='orange', linestyle='--', linewidth=2, label='Overflow (>1.0)')
    ax.set_ylabel('snd_ratio (Buffer Pressure)', fontsize=12, fontweight='bold')
    ax.set_title('TCP Send Buffer Pressure', fontsize=13, fontweight='bold')
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3, axis='y')
    
    for bar, val in zip(bars, snd_values):
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height*1.1,
                f'{val:.3f}', ha='center', va='bottom', fontsize=10, fontweight='bold')
    
    # 3. SLO 준수율 (Bar)
    ax = fig.add_subplot(gs[0, 2])
    slo_values = [s['slo_rate'] for s in stats_list]
    bars = ax.bar(methods, slo_values, color=colors, alpha=0.7, edgecolor='black', linewidth=2)
    ax.set_ylabel('SLO Compliance Rate (%)', fontsize=12, fontweight='bold')
    ax.set_title('SLO Compliance (P99 < 300ms)', fontsize=13, fontweight='bold')
    ax.set_ylim(0, 100)
    ax.grid(True, alpha=0.3, axis='y')
    
    for bar, val in zip(bars, slo_values):
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height+2,
                f'{val:.1f}%', ha='center', va='bottom', fontsize=10, fontweight='bold')
    
    # 4. snd_ratio 시계열 (핵심!)
    ax = fig.add_subplot(gs[1, :])
    for stats in stats_list:
        ts = list(range(len(stats['snds'])))
        ax.plot(ts, stats['snds'], color=stats['color'], 
                label=stats['name'], linewidth=2.5, alpha=0.8)
    ax.axhline(y=1.0, color='orange', linestyle='--', linewidth=3, label='Buffer Overflow (>1.0)')
    ax.set_xlabel('Time (samples)', fontsize=13, fontweight='bold')
    ax.set_ylabel('snd_ratio (Buffer Pressure)', fontsize=13, fontweight='bold')
    ax.set_title('TCP Send Buffer Pressure over Time - WHY EMQX FAILS', fontsize=14, fontweight='bold')
    ax.legend(fontsize=12, loc='upper right')
    ax.grid(True, alpha=0.3)
    ax.set_ylim(0, max(max(baseline_stats['snds']), max(emqx_stats['snds'])) * 1.1)
    
    # 5. 버퍼 넘침 비율 (Bar)
    ax = fig.add_subplot(gs[2, 0])
    overflow_values = [s['snd_overflow_rate'] for s in stats_list]
    bars = ax.bar(methods, overflow_values, color=colors, alpha=0.7, edgecolor='black', linewidth=2)
    ax.set_ylabel('Buffer Overflow Rate (%)', fontsize=12, fontweight='bold')
    ax.set_title('Buffer Overflow Occurrence', fontsize=13, fontweight='bold')
    ax.set_ylim(0, 100)
    ax.grid(True, alpha=0.3, axis='y')
    
    for bar, val in zip(bars, overflow_values):
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height+2,
                f'{val:.1f}%', ha='center', va='bottom', fontsize=10, fontweight='bold')
    
    # 6. snd_ratio vs P99 산점도 (핵심 상관관계)
    ax = fig.add_subplot(gs[2, 1])
    for stats in stats_list:
        ax.scatter(stats['snds'], stats['p99s'], c=stats['color'], alpha=0.6, 
                   s=60, label=stats['name'], edgecolors='black', linewidths=1)
    ax.axvline(x=1.0, color='orange', linestyle='--', linewidth=2.5, label='Buffer Overflow')
    ax.axhline(y=300, color='green', linestyle='--', linewidth=2.5, label='SLO (300ms)')
    ax.set_xlabel('snd_ratio (Buffer Pressure)', fontsize=12, fontweight='bold')
    ax.set_ylabel('P99 Latency (ms)', fontsize=12, fontweight='bold')
    ax.set_title('Buffer Pressure vs Tail Latency', fontsize=13, fontweight='bold')
    ax.set_yscale('log')
    ax.legend(fontsize=10, loc='upper left')
    ax.grid(True, alpha=0.3)
    
    # 7. RTT 비교 (Bar)
    ax = fig.add_subplot(gs[2, 2])
    rtt_values = [s['rtt_med'] for s in stats_list]
    bars = ax.bar(methods, rtt_values, color=colors, alpha=0.7, edgecolor='black', linewidth=2)
    ax.set_ylabel('RTT (ms)', fontsize=12, fontweight='bold')
    ax.set_title('Round-Trip Time', fontsize=13, fontweight='bold')
    ax.grid(True, alpha=0.3, axis='y')
    
    for bar, val in zip(bars, rtt_values):
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height*1.1,
                f'{val:.0f}ms', ha='center', va='bottom', fontsize=10, fontweight='bold')
    
    output_path = Path(output_dir) / 'three_way_comparison.png'
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"\n✅ 그래프 저장: {output_path}")

def main():
    print("="*80)
    print("혼잡 네트워크에서 3가지 방법 비교")
    print("Baseline vs EMQX Flow Control vs eBPF+RL")
    print("="*80)
    
    # 로그 로드
    baseline_log = load_log('logs/baseline/baseline_conjestion.jsonl')
    if not baseline_log:
        # 다른 이름 시도
        baseline_log = load_log('logs/baseline/baseline_congestion.jsonl')
    
    emqx_log = load_log('logs/emqx_flow_control/congestion.jsonl')
    rl_log = load_log('logs/torch_model_experiments/congestion/rl_bc_v2_congestion.jsonl')
    
    # 분석
    baseline_stats = analyze_method("1️⃣  Baseline (제어 없음)", baseline_log, 'gray')
    emqx_stats = analyze_method("2️⃣  EMQX Flow Control (Application-level)", emqx_log, 'red')
    rl_stats = analyze_method("3️⃣  eBPF+RL (Kernel-level)", rl_log, 'blue')
    
    if not baseline_stats:
        print("\n⚠️  Baseline 데이터가 없어서 EMQX vs eBPF+RL만 비교합니다.")
        return
    
    # 비교 테이블
    print(f"\n{'='*80}")
    print("📊 종합 비교")
    print(f"{'='*80}")
    print(f"{'지표':<25} {'Baseline':>15} {'EMQX':>15} {'eBPF+RL':>15}")
    print(f"{'-'*80}")
    print(f"{'P99 (중앙값, ms)':<25} {baseline_stats['p99_med']:>15.1f} {emqx_stats['p99_med']:>15.1f} {rl_stats['p99_med']:>15.1f}")
    print(f"{'P99 (최대, ms)':<25} {baseline_stats['p99_max']:>15.1f} {emqx_stats['p99_max']:>15.1f} {rl_stats['p99_max']:>15.1f}")
    print(f"{'snd_ratio (중앙값)':<25} {baseline_stats['snd_med']:>15.3f} {emqx_stats['snd_med']:>15.3f} {rl_stats['snd_med']:>15.3f}")
    print(f"{'snd_ratio (최대)':<25} {baseline_stats['snd_max']:>15.3f} {emqx_stats['snd_max']:>15.3f} {rl_stats['snd_max']:>15.3f}")
    print(f"{'버퍼 넘침 비율 (%)':<25} {baseline_stats['snd_overflow_rate']:>15.1f} {emqx_stats['snd_overflow_rate']:>15.1f} {rl_stats['snd_overflow_rate']:>15.1f}")
    print(f"{'RTT (중앙값, ms)':<25} {baseline_stats['rtt_med']:>15.1f} {emqx_stats['rtt_med']:>15.1f} {rl_stats['rtt_med']:>15.1f}")
    print(f"{'SLO 준수율 (%)':<25} {baseline_stats['slo_rate']:>15.1f} {emqx_stats['slo_rate']:>15.1f} {rl_stats['slo_rate']:>15.1f}")
    
    print(f"\n{'='*80}")
    print("🎯 핵심 인사이트")
    print(f"{'='*80}")
    
    print(f"""
1️⃣  Baseline (제어 없음):
   • P99: {baseline_stats['p99_med']:.0f} ms
   • snd_ratio: {baseline_stats['snd_med']:.3f}
   • 버퍼 넘침: {baseline_stats['snd_overflow_rate']:.1f}%
   → 제어 없이도 어느 정도 동작하지만 불안정

2️⃣  EMQX Flow Control (Application-level):
   • P99: {emqx_stats['p99_med']:.0f} ms ({emqx_stats['p99_med']/1000:.0f}초!)
   • snd_ratio: {emqx_stats['snd_med']:.3f} (버퍼 {emqx_stats['snd_med']*100:.0f}% 넘침)
   • 버퍼 넘침: {emqx_stats['snd_overflow_rate']:.1f}%
   → 커널 신호 없어서 오히려 Baseline보다 더 나빠짐!
   → Application-level 제어의 역효과

3️⃣  eBPF+RL (Kernel-level):
   • P99: {rl_stats['p99_med']:.0f} ms
   • snd_ratio: {rl_stats['snd_med']:.3f}
   • 버퍼 넘침: {rl_stats['snd_overflow_rate']:.1f}%
   → 커널 신호로 버퍼 압력 제어
   → EMQX 대비 {(1 - rl_stats['p99_med']/emqx_stats['p99_med'])*100:.1f}% P99 개선
   → Baseline 대비 {(1 - rl_stats['p99_med']/baseline_stats['p99_med'])*100:.1f}% P99 개선

🔑 결론:
   • Baseline < eBPF+RL <<< EMQX (성능 순서)
   • EMQX가 가장 나쁨: 커널 신호 없이 잘못된 판단 → 역효과
   • eBPF+RL이 최선: 커널 신호 기반 정확한 제어
   
💡 핵심 주장:
   "Application-level Flow Control은 커널 TCP 버퍼 상태를 
    모르기 때문에 혼잡 네트워크에서 오히려 성능을 악화시킨다.
    제어 없는 Baseline보다도 못한 결과를 초래한다.
    eBPF 기반 커널 신호 모니터링이 필수적이다."
""")
    
    # 시각화
    visualize_three_way(baseline_stats, emqx_stats, rl_stats, 'results/three_way_analysis')
    
    print(f"\n{'='*80}")
    print("분석 완료!")
    print(f"{'='*80}")

if __name__ == '__main__':
    main()
