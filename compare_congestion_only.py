#!/usr/bin/env python3
"""
혼잡 네트워크에서 EMQX Flow Control vs eBPF+RL 비교
핵심 주장: Application-level Flow Control은 커널 신호를 못 봐서 실패한다
"""
import json
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

def load_log(path):
    data = []
    with open(path) as f:
        for line in f:
            try:
                data.append(json.loads(line))
            except:
                continue
    return data

def analyze_method(name, log):
    p99s = [e['metrics']['p99_ms'] for e in log if 'metrics' in e]
    p95s = [e['metrics']['p95_ms'] for e in log if 'metrics' in e]
    p50s = [e['metrics']['p50_ms'] for e in log if 'metrics' in e]
    snds = [e['kernel']['snd_ratio'] for e in log if 'kernel' in e]
    rtts = [e['kernel']['ewma_rtt_us']/1000 for e in log if 'kernel' in e]
    
    # SLO 준수 (P99 < 300ms)
    slo_compliant = [p for p in p99s if p <= 300]
    
    print(f"\n{'='*80}")
    print(f"{name}")
    print(f"{'='*80}")
    print(f"📊 샘플 수: {len(log)}개")
    print(f"\n🎯 Tail Latency:")
    print(f"  • P50 (중앙값): {np.median(p50s):.1f} ms")
    print(f"  • P95 (중앙값): {np.median(p95s):.1f} ms")
    print(f"  • P99 (중앙값): {np.median(p99s):.1f} ms")
    print(f"  • P99 (평균): {np.mean(p99s):.1f} ms")
    print(f"  • P99 (최대): {np.max(p99s):.1f} ms")
    
    print(f"\n🔧 TCP 커널 신호:")
    print(f"  • snd_ratio (중앙값): {np.median(snds):.3f}")
    print(f"  • snd_ratio (평균): {np.mean(snds):.3f}")
    print(f"  • snd_ratio (최대): {np.max(snds):.3f}")
    print(f"  • snd_ratio > 1.0 비율: {len([s for s in snds if s > 1.0])/len(snds)*100:.1f}%")
    print(f"  • RTT (중앙값): {np.median(rtts):.1f} ms")
    print(f"  • RTT (평균): {np.mean(rtts):.1f} ms")
    
    print(f"\n✅ SLO 준수 (P99 < 300ms):")
    print(f"  • 준수 샘플: {len(slo_compliant)}/{len(p99s)} ({len(slo_compliant)/len(p99s)*100:.1f}%)")
    print(f"  • 위반 샘플: {len(p99s)-len(slo_compliant)}/{len(p99s)} ({(len(p99s)-len(slo_compliant))/len(p99s)*100:.1f}%)")
    
    return {
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
        'slo_compliant_rate': len(slo_compliant)/len(p99s)*100,
        'p99s': p99s,
        'snds': snds
    }

def visualize_comparison(emqx_stats, rl_stats, output_dir):
    """EMQX vs eBPF+RL 비교 시각화"""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    fig, axes = plt.subplots(2, 3, figsize=(18, 12))
    fig.suptitle('Congestion Network: EMQX Flow Control vs eBPF+RL\n'
                 'Application-level vs Kernel-level Signal Monitoring', 
                 fontsize=16, fontweight='bold')
    
    # 1. P99 비교 (Bar)
    ax = axes[0, 0]
    methods = ['EMQX\nFlow Control', 'eBPF+RL']
    p99_values = [emqx_stats['p99_med'], rl_stats['p99_med']]
    colors = ['red', 'blue']
    bars = ax.bar(methods, p99_values, color=colors, alpha=0.7, edgecolor='black', linewidth=2)
    ax.axhline(y=300, color='green', linestyle='--', linewidth=2, label='SLO (300ms)')
    ax.set_ylabel('P99 Latency (ms)', fontsize=12, fontweight='bold')
    ax.set_title('P99 Tail Latency Comparison', fontsize=13, fontweight='bold')
    ax.set_yscale('log')
    ax.legend()
    ax.grid(True, alpha=0.3, axis='y')
    
    # 값 표시
    for bar, val in zip(bars, p99_values):
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height*1.5,
                f'{val:.0f} ms', ha='center', va='bottom', fontsize=11, fontweight='bold')
    
    # 2. snd_ratio 비교 (Bar)
    ax = axes[0, 1]
    snd_values = [emqx_stats['snd_med'], rl_stats['snd_med']]
    bars = ax.bar(methods, snd_values, color=colors, alpha=0.7, edgecolor='black', linewidth=2)
    ax.axhline(y=1.0, color='orange', linestyle='--', linewidth=2, label='Buffer Overflow (>1.0)')
    ax.set_ylabel('snd_ratio (Buffer Pressure)', fontsize=12, fontweight='bold')
    ax.set_title('TCP Send Buffer Pressure', fontsize=13, fontweight='bold')
    ax.legend()
    ax.grid(True, alpha=0.3, axis='y')
    
    # 값 표시
    for bar, val in zip(bars, snd_values):
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height*1.1,
                f'{val:.3f}', ha='center', va='bottom', fontsize=11, fontweight='bold')
    
    # 3. SLO 준수율 (Bar)
    ax = axes[0, 2]
    slo_rates = [emqx_stats['slo_compliant_rate'], rl_stats['slo_compliant_rate']]
    bars = ax.bar(methods, slo_rates, color=colors, alpha=0.7, edgecolor='black', linewidth=2)
    ax.set_ylabel('SLO Compliance Rate (%)', fontsize=12, fontweight='bold')
    ax.set_title('SLO Compliance (P99 < 300ms)', fontsize=13, fontweight='bold')
    ax.set_ylim(0, 100)
    ax.grid(True, alpha=0.3, axis='y')
    
    # 값 표시
    for bar, val in zip(bars, slo_rates):
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height+2,
                f'{val:.1f}%', ha='center', va='bottom', fontsize=11, fontweight='bold')
    
    # 4. P99 시계열
    ax = axes[1, 0]
    emqx_ts = list(range(len(emqx_stats['p99s'])))
    rl_ts = list(range(len(rl_stats['p99s'])))
    ax.plot(emqx_ts, emqx_stats['p99s'], 'r-', label='EMQX Flow Control', linewidth=2, alpha=0.7)
    ax.plot(rl_ts, rl_stats['p99s'], 'b-', label='eBPF+RL', linewidth=2, alpha=0.7)
    ax.axhline(y=300, color='g', linestyle='--', label='SLO', linewidth=2)
    ax.set_xlabel('Time (samples)', fontsize=12, fontweight='bold')
    ax.set_ylabel('P99 Latency (ms)', fontsize=12, fontweight='bold')
    ax.set_title('P99 over Time', fontsize=13, fontweight='bold')
    ax.set_yscale('log')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # 5. snd_ratio 시계열
    ax = axes[1, 1]
    ax.plot(emqx_ts, emqx_stats['snds'], 'r-', label='EMQX (No Kernel Signal)', linewidth=2, alpha=0.7)
    ax.plot(rl_ts, rl_stats['snds'], 'b-', label='eBPF (Kernel Signal)', linewidth=2, alpha=0.7)
    ax.axhline(y=1.0, color='orange', linestyle='--', label='Buffer Overflow', linewidth=2)
    ax.set_xlabel('Time (samples)', fontsize=12, fontweight='bold')
    ax.set_ylabel('snd_ratio', fontsize=12, fontweight='bold')
    ax.set_title('TCP Buffer Pressure over Time', fontsize=13, fontweight='bold')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # 6. snd_ratio vs P99 산점도
    ax = axes[1, 2]
    ax.scatter(emqx_stats['snds'], emqx_stats['p99s'], c='red', alpha=0.5, 
               s=50, label='EMQX', edgecolors='darkred')
    ax.scatter(rl_stats['snds'], rl_stats['p99s'], c='blue', alpha=0.5,
               s=50, label='eBPF+RL', edgecolors='darkblue')
    ax.axvline(x=1.0, color='orange', linestyle='--', linewidth=2, label='Buffer Overflow')
    ax.axhline(y=300, color='green', linestyle='--', linewidth=2, label='SLO')
    ax.set_xlabel('snd_ratio (Buffer Pressure)', fontsize=12, fontweight='bold')
    ax.set_ylabel('P99 Latency (ms)', fontsize=12, fontweight='bold')
    ax.set_title('Buffer Pressure vs Tail Latency', fontsize=13, fontweight='bold')
    ax.set_yscale('log')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    output_path = Path(output_dir) / 'congestion_comparison.png'
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"\n✅ 그래프 저장: {output_path}")

def main():
    print("="*80)
    print("혼잡 네트워크에서 EMQX Flow Control vs eBPF+RL")
    print("핵심: Application-level은 커널 신호를 못 봐서 실패한다")
    print("="*80)
    
    # 로그 로드
    emqx_log = load_log('logs/emqx_flow_control/conjestion.jsonl')
    rl_log = load_log('logs/torch_model_experiments/congestion/rl_bc_v2_congestion.jsonl')
    
    # 분석
    emqx_stats = analyze_method("🔴 EMQX Flow Control (Application-level)", emqx_log)
    rl_stats = analyze_method("🔵 eBPF+RL (Kernel-level)", rl_log)
    
    # 비교 테이블
    print(f"\n{'='*80}")
    print("📊 종합 비교")
    print(f"{'='*80}")
    print(f"{'지표':<30} {'EMQX Flow Control':>20} {'eBPF+RL':>20}")
    print(f"{'-'*80}")
    print(f"{'P99 (중앙값, ms)':<30} {emqx_stats['p99_med']:>20.1f} {rl_stats['p99_med']:>20.1f}")
    print(f"{'P99 (최대, ms)':<30} {emqx_stats['p99_max']:>20.1f} {rl_stats['p99_max']:>20.1f}")
    print(f"{'snd_ratio (중앙값)':<30} {emqx_stats['snd_med']:>20.3f} {rl_stats['snd_med']:>20.3f}")
    print(f"{'snd_ratio (최대)':<30} {emqx_stats['snd_max']:>20.3f} {rl_stats['snd_max']:>20.3f}")
    print(f"{'버퍼 넘침 비율 (%)':<30} {emqx_stats['snd_overflow_rate']:>20.1f} {rl_stats['snd_overflow_rate']:>20.1f}")
    print(f"{'RTT (중앙값, ms)':<30} {emqx_stats['rtt_med']:>20.1f} {rl_stats['rtt_med']:>20.1f}")
    print(f"{'SLO 준수율 (%)':<30} {emqx_stats['slo_compliant_rate']:>20.1f} {rl_stats['slo_compliant_rate']:>20.1f}")
    
    # 개선율
    p99_improvement = (1 - rl_stats['p99_med'] / emqx_stats['p99_med']) * 100
    snd_improvement = (1 - rl_stats['snd_med'] / emqx_stats['snd_med']) * 100
    slo_improvement = rl_stats['slo_compliant_rate'] - emqx_stats['slo_compliant_rate']
    
    print(f"\n{'='*80}")
    print("🎯 eBPF+RL의 개선 효과")
    print(f"{'='*80}")
    print(f"  • P99 Latency: {p99_improvement:.1f}% 개선 ({emqx_stats['p99_med']:.0f}ms → {rl_stats['p99_med']:.0f}ms)")
    print(f"  • Buffer Pressure: {snd_improvement:.1f}% 개선 ({emqx_stats['snd_med']:.3f} → {rl_stats['snd_med']:.3f})")
    print(f"  • SLO Compliance: {slo_improvement:.1f}%p 개선 ({emqx_stats['slo_compliant_rate']:.1f}% → {rl_stats['slo_compliant_rate']:.1f}%)")
    
    print(f"\n{'='*80}")
    print("💡 핵심 인사이트")
    print(f"{'='*80}")
    print(f"""
🔴 EMQX Flow Control의 실패 원인:
   1. 커널 TCP 버퍼 상태(snd_ratio)를 볼 수 없음
   2. snd_ratio {emqx_stats['snd_med']:.3f} (버퍼 {emqx_stats['snd_med']*100:.0f}% 넘침)
   3. {emqx_stats['snd_overflow_rate']:.0f}%의 시간 동안 버퍼 폭발 상태
   4. 결과: P99 {emqx_stats['p99_med']/1000:.0f}초로 폭증

🔵 eBPF+RL의 성공 원인:
   1. eBPF로 커널 TCP 신호 직접 모니터링
   2. snd_ratio {rl_stats['snd_med']:.3f}로 버퍼 압력 제어
   3. {rl_stats['snd_overflow_rate']:.0f}%만 버퍼 넘침 (대부분 안정)
   4. 결과: P99 {rl_stats['p99_med']:.0f}ms로 {p99_improvement:.0f}% 개선

🔑 결론:
   Tail Latency 제어에는 커널 레벨 신호 모니터링이 필수적이다.
   Application-level Flow Control만으로는 불가능하다.
""")
    
    # 시각화
    visualize_comparison(emqx_stats, rl_stats, 'results/congestion_analysis')
    
    print(f"\n{'='*80}")
    print("분석 완료!")
    print(f"{'='*80}")

if __name__ == '__main__':
    main()
