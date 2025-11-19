#!/usr/bin/env python3
"""
Baseline (제어 없음) vs RL 제어 비교
"""
import json
import numpy as np
import matplotlib.pyplot as plt

def analyze_log(log_path, label):
    """로그 파일 분석"""
    data = {
        'throughput': [],
        'p50': [],
        'p95': [],
        'p99': [],
        'snd_ratio': [],
        'rtt': [],
        'retrans_count': [],
        'retrans_queue': [],
        'had_retrans': 0,
        'total': 0
    }
    
    with open(log_path) as f:
        for line in f:
            if not line.strip():
                continue
            entry = json.loads(line)
            
            data['total'] += 1
            
            metrics = entry.get('metrics', {})
            kernel = entry.get('kernel', {})
            
            n = metrics.get('n', 0)
            window_sec = metrics.get('window_sec', 30.0)
            throughput = n / window_sec if window_sec > 0 else 0
            
            data['throughput'].append(throughput)
            data['p50'].append(metrics.get('p50_ms', 0))
            data['p95'].append(metrics.get('p95_ms', 0))
            data['p99'].append(metrics.get('p99_ms', 0))
            data['snd_ratio'].append(kernel.get('snd_ratio', 0))
            data['rtt'].append(kernel.get('ewma_rtt_us', 0) / 1000.0)
            
            retrans_count = kernel.get('retrans_count', 0)
            retrans_queue = kernel.get('retrans_queue', 0)
            data['retrans_count'].append(retrans_count)
            data['retrans_queue'].append(retrans_queue)
            
            if kernel.get('had_retrans', False) or retrans_count > 0:
                data['had_retrans'] += 1
    
    # 통계 계산
    stats = {
        'label': label,
        'samples': data['total'],
        'throughput_avg': np.mean(data['throughput']),
        'throughput_std': np.std(data['throughput']),
        'throughput_min': np.min(data['throughput']),
        'throughput_max': np.max(data['throughput']),
        'p50_avg': np.mean(data['p50']),
        'p50_p95': np.percentile(data['p50'], 95),
        'p95_avg': np.mean(data['p95']),
        'p95_p95': np.percentile(data['p95'], 95),
        'p99_avg': np.mean(data['p99']),
        'p99_p95': np.percentile(data['p99'], 95),
        'p99_max': np.max(data['p99']),
        'snd_ratio_avg': np.mean(data['snd_ratio']),
        'snd_ratio_median': np.median(data['snd_ratio']),
        'snd_ratio_p95': np.percentile(data['snd_ratio'], 95),
        'snd_ratio_max': np.max(data['snd_ratio']),
        'rtt_avg': np.mean(data['rtt']),
        'rtt_p95': np.percentile(data['rtt'], 95),
        'retrans_rate': data['had_retrans'] / data['total'] * 100 if data['total'] > 0 else 0,
        'retrans_count_avg': np.mean(data['retrans_count']),
        'retrans_count_total': np.sum(data['retrans_count']),
        'retrans_queue_avg': np.mean(data['retrans_queue']),
        'raw': data
    }
    
    return stats

print("🔥 Baseline vs RL 제어 비교")
print("=" * 100)

# 로그 파일 정의
comparisons = [
    {
        'title': 'Normal Network (정상 네트워크)',
        'baseline': None,  # 없음
        'rl': 'logs/torch_model_experiments/normal/rl_torch_normal.jsonl'
    },
    {
        'title': 'Dynamic Network (동적 변화)',
        'baseline': None,  # 없음
        'rl': 'logs/torch_model_experiments/dynamic/rl_bc_v2_dynamic.jsonl'
    },
    {
        'title': 'Congestion Network (혼잡)',
        'baseline': 'logs/emqx_flow_control/congestion.jsonl',
        'rl': 'logs/torch_model_experiments/congestion/rl_bc_v2_congestion.jsonl'
    }
]

all_results = []

for comp in comparisons:
    print(f"\n{'='*100}")
    print(f"📊 {comp['title']}")
    print(f"{'='*100}")
    
    results = {}
    
    # Baseline 분석
    if comp['baseline']:
        try:
            baseline = analyze_log(comp['baseline'], 'Baseline (EMQX)')
            results['baseline'] = baseline
            
            print(f"\n📉 Baseline (제어 없음)")
            print(f"  샘플:         {baseline['samples']}")
            print(f"  처리량:       {baseline['throughput_avg']:6.1f} msg/s (±{baseline['throughput_std']:5.1f})")
            print(f"  P50:          {baseline['p50_avg']:8.1f} ms")
            print(f"  P95:          {baseline['p95_avg']:8.1f} ms")
            print(f"  P99:          {baseline['p99_avg']:8.1f} ms (최악: {baseline['p99_max']:8.1f})")
            print(f"  snd_ratio:    {baseline['snd_ratio_avg']:6.4f} (중앙값: {baseline['snd_ratio_median']:6.4f}, P95: {baseline['snd_ratio_p95']:6.4f})")
            print(f"  RTT:          {baseline['rtt_avg']:8.1f} ms (P95: {baseline['rtt_p95']:8.1f})")
            print(f"  재전송률:     {baseline['retrans_rate']:5.1f}%")
            print(f"  재전송 횟수:  {baseline['retrans_count_total']:.0f} (평균 {baseline['retrans_count_avg']:.1f}/interval)")
        except Exception as e:
            print(f"  ❌ Baseline 로드 실패: {e}")
    else:
        print(f"\n  ⚠️  Baseline 로그 없음")
    
    # RL 분석
    try:
        rl = analyze_log(comp['rl'], 'RL Control')
        results['rl'] = rl
        
        print(f"\n🎯 RL Control")
        print(f"  샘플:         {rl['samples']}")
        print(f"  처리량:       {rl['throughput_avg']:6.1f} msg/s (±{rl['throughput_std']:5.1f})")
        print(f"  P50:          {rl['p50_avg']:8.1f} ms")
        print(f"  P95:          {rl['p95_avg']:8.1f} ms")
        print(f"  P99:          {rl['p99_avg']:8.1f} ms (최악: {rl['p99_max']:8.1f})")
        print(f"  snd_ratio:    {rl['snd_ratio_avg']:6.4f} (중앙값: {rl['snd_ratio_median']:6.4f}, P95: {rl['snd_ratio_p95']:6.4f})")
        print(f"  RTT:          {rl['rtt_avg']:8.1f} ms (P95: {rl['rtt_p95']:8.1f})")
        print(f"  재전송률:     {rl['retrans_rate']:5.1f}%")
        print(f"  재전송 횟수:  {rl['retrans_count_total']:.0f} (평균 {rl['retrans_count_avg']:.1f}/interval)")
    except Exception as e:
        print(f"  ❌ RL 로드 실패: {e}")
        continue
    
    # 비교
    if 'baseline' in results:
        baseline = results['baseline']
        rl = results['rl']
        
        throughput_change = (rl['throughput_avg'] - baseline['throughput_avg']) / baseline['throughput_avg'] * 100
        p99_improvement = (baseline['p99_avg'] - rl['p99_avg']) / baseline['p99_avg'] * 100
        snd_ratio_improvement = (baseline['snd_ratio_avg'] - rl['snd_ratio_avg']) / baseline['snd_ratio_avg'] * 100
        retrans_reduction = (baseline['retrans_count_total'] - rl['retrans_count_total']) / baseline['retrans_count_total'] * 100 if baseline['retrans_count_total'] > 0 else 0
        
        print(f"\n✨ 개선 효과")
        print(f"  처리량:       {throughput_change:+6.1f}% ({baseline['throughput_avg']:.1f} → {rl['throughput_avg']:.1f} msg/s)")
        print(f"  P99:          {p99_improvement:+6.1f}% ({baseline['p99_avg']:.1f} → {rl['p99_avg']:.1f} ms) {'✅' if p99_improvement > 0 else '⚠️'}")
        print(f"  snd_ratio:    {snd_ratio_improvement:+6.1f}% ({baseline['snd_ratio_avg']:.4f} → {rl['snd_ratio_avg']:.4f}) {'✅' if snd_ratio_improvement > 0 else '⚠️'}")
        print(f"  재전송 감소:  {retrans_reduction:+6.1f}% ({baseline['retrans_count_total']:.0f} → {rl['retrans_count_total']:.0f}) {'✅' if retrans_reduction > 0 else '⚠️'}")
        
        results['improvements'] = {
            'throughput': throughput_change,
            'p99': p99_improvement,
            'snd_ratio': snd_ratio_improvement,
            'retrans': retrans_reduction
        }
    
    all_results.append({
        'title': comp['title'],
        'results': results
    })

# Congestion 조건 그래프 생성 (가장 중요한 비교)
congestion_result = [r for r in all_results if 'Congestion' in r['title']]
if congestion_result and 'baseline' in congestion_result[0]['results']:
    result = congestion_result[0]['results']
    baseline = result['baseline']
    rl = result['rl']
    
    fig, axes = plt.subplots(2, 3, figsize=(18, 12))
    fig.suptitle('Baseline (EMQX) vs RL Control - Congestion Network', fontsize=16, fontweight='bold')
    
    # 1. Throughput 시계열
    ax = axes[0, 0]
    ax.plot(baseline['raw']['throughput'], label='Baseline (EMQX)', alpha=0.7, linewidth=1, color='red')
    ax.plot(rl['raw']['throughput'], label='RL Control', alpha=0.7, linewidth=1, color='green')
    ax.axhline(baseline['throughput_avg'], color='red', linestyle='--', alpha=0.5)
    ax.axhline(rl['throughput_avg'], color='green', linestyle='--', alpha=0.5)
    ax.set_xlabel('Time Window')
    ax.set_ylabel('Throughput (msg/s)')
    ax.set_title('Throughput Over Time')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # 2. P99 Latency 시계열
    ax = axes[0, 1]
    ax.plot(baseline['raw']['p99'], label='Baseline (EMQX)', alpha=0.7, linewidth=1, color='red')
    ax.plot(rl['raw']['p99'], label='RL Control', alpha=0.7, linewidth=1, color='green')
    ax.axhline(300, color='orange', linestyle='--', alpha=0.5, label='SLO (300ms)')
    ax.set_xlabel('Time Window')
    ax.set_ylabel('P99 Latency (ms)')
    ax.set_title('P99 Latency Over Time')
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.set_ylim([0, min(max(baseline['raw']['p99']), 60000)])  # 상한선 설정
    
    # 3. snd_ratio 시계열
    ax = axes[0, 2]
    ax.plot(baseline['raw']['snd_ratio'], label='Baseline (EMQX)', alpha=0.7, linewidth=1, color='red')
    ax.plot(rl['raw']['snd_ratio'], label='RL Control', alpha=0.7, linewidth=1, color='green')
    ax.axhline(0.1, color='orange', linestyle='--', alpha=0.5, label='Caution')
    ax.axhline(0.3, color='red', linestyle='--', alpha=0.5, label='Warning')
    ax.set_xlabel('Time Window')
    ax.set_ylabel('snd_ratio')
    ax.set_title('TCP Send Buffer Pressure')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # 4. Bar 비교 - Throughput & P99
    ax = axes[1, 0]
    metrics = ['Throughput\n(msg/s)', 'P99\n(ms)']
    baseline_vals = [baseline['throughput_avg'], baseline['p99_avg']]
    rl_vals = [rl['throughput_avg'], rl['p99_avg']]
    
    x = np.arange(len(metrics))
    width = 0.35
    
    # Normalize P99 for visualization
    baseline_norm = [baseline['throughput_avg'], baseline['p99_avg'] / 100]
    rl_norm = [rl['throughput_avg'], rl['p99_avg'] / 100]
    
    ax.bar(x - width/2, baseline_norm, width, label='Baseline', color='red', alpha=0.7)
    ax.bar(x + width/2, rl_norm, width, label='RL', color='green', alpha=0.7)
    ax.set_ylabel('Value (P99 scaled /100)')
    ax.set_title('Throughput & P99 Comparison')
    ax.set_xticks(x)
    ax.set_xticklabels(metrics)
    ax.legend()
    ax.grid(True, alpha=0.3, axis='y')
    
    # Add actual values as text
    for i, (b, r) in enumerate(zip(baseline_vals, rl_vals)):
        if i == 1:  # P99
            b_display, r_display = b/100, r/100
        else:
            b_display, r_display = b, r
        ax.text(i - width/2, b_display + max(baseline_norm[i], rl_norm[i])*0.02, 
                f'{b:.0f}', ha='center', fontsize=9, fontweight='bold')
        ax.text(i + width/2, r_display + max(baseline_norm[i], rl_norm[i])*0.02, 
                f'{r:.0f}', ha='center', fontsize=9, fontweight='bold')
    
    # 5. snd_ratio 분포
    ax = axes[1, 1]
    ax.hist(baseline['raw']['snd_ratio'], bins=50, alpha=0.6, label='Baseline', color='red', edgecolor='black')
    ax.hist(rl['raw']['snd_ratio'], bins=50, alpha=0.6, label='RL', color='green', edgecolor='black')
    ax.axvline(0.1, color='orange', linestyle='--', alpha=0.5)
    ax.axvline(0.3, color='red', linestyle='--', alpha=0.5)
    ax.set_xlabel('snd_ratio')
    ax.set_ylabel('Frequency')
    ax.set_title('Buffer Pressure Distribution')
    ax.legend()
    ax.grid(True, alpha=0.3, axis='y')
    
    # 6. Summary table
    ax = axes[1, 2]
    ax.axis('off')
    summary_text = f"""
Baseline vs RL Summary
{'='*45}

Throughput:
  Baseline: {baseline['throughput_avg']:.1f} msg/s
  RL:       {rl['throughput_avg']:.1f} msg/s
  Change:   {result['improvements']['throughput']:+.1f}%

P99 Latency:
  Baseline: {baseline['p99_avg']:.1f} ms
  RL:       {rl['p99_avg']:.1f} ms
  Improve:  {result['improvements']['p99']:+.1f}%

Buffer Pressure (snd_ratio):
  Baseline: {baseline['snd_ratio_avg']:.4f}
  RL:       {rl['snd_ratio_avg']:.4f}
  Improve:  {result['improvements']['snd_ratio']:+.1f}%

Retransmissions:
  Baseline: {baseline['retrans_count_total']:.0f}
  RL:       {rl['retrans_count_total']:.0f}
  Reduce:   {result['improvements']['retrans']:+.1f}%

Stability:
  Baseline P99 max: {baseline['p99_max']:.0f} ms
  RL P99 max:       {rl['p99_max']:.0f} ms
"""
    ax.text(0.1, 0.5, summary_text, fontsize=10, family='monospace',
            verticalalignment='center')
    
    plt.tight_layout()
    plt.savefig('results/baseline_vs_rl_congestion.png', dpi=300, bbox_inches='tight')
    print(f"\n✅ 저장: results/baseline_vs_rl_congestion.png")

# 최종 요약
print(f"\n{'='*100}")
print("🎯 최종 결론")
print(f"{'='*100}")

congestion_comp = [r for r in all_results if 'Congestion' in r['title']]
if congestion_comp and 'baseline' in congestion_comp[0]['results']:
    impr = congestion_comp[0]['results']['improvements']
    baseline = congestion_comp[0]['results']['baseline']
    rl = congestion_comp[0]['results']['rl']
    
    print(f"\n혼잡 네트워크 조건에서:")
    print(f"  ✅ P99 Latency:   {impr['p99']:+6.1f}% 개선 ({baseline['p99_avg']:.0f}ms → {rl['p99_avg']:.0f}ms)")
    print(f"  ✅ Buffer 안정성: {impr['snd_ratio']:+6.1f}% 개선 (snd_ratio {baseline['snd_ratio_avg']:.2f} → {rl['snd_ratio_avg']:.2f})")
    print(f"  ⚠️  처리량:        {impr['throughput']:+6.1f}% 변화 ({baseline['throughput_avg']:.0f} → {rl['throughput_avg']:.0f} msg/s)")
    print(f"  ⚠️  재전송:        {impr['retrans']:+6.1f}% 변화 (재전송은 네트워크 품질 의존)")
    
    print(f"\n💡 Trade-off 분석:")
    print(f"  - 처리량 {abs(impr['throughput']):.1f}% 희생")
    print(f"  - P99 {impr['p99']:.1f}% 개선")
    print(f"  - 효율성: {abs(impr['p99']/impr['throughput']):.2f}x (처리량 1% 감소당 P99 개선율)")
else:
    print("\n⚠️  Baseline 비교 데이터 없음")
    print("  - Normal, Dynamic 조건에서는 Baseline 로그 필요")
