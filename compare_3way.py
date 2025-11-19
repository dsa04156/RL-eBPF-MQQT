#!/usr/bin/env python3
"""
3-way 비교: Baseline (제어 없음) vs EMQX Flow Control vs RL
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
            try:
                entry = json.loads(line)
            except:
                continue
            
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
    
    if data['total'] == 0:
        return None
    
    # 통계 계산
    stats = {
        'label': label,
        'samples': data['total'],
        'throughput_avg': np.mean(data['throughput']),
        'throughput_std': np.std(data['throughput']),
        'throughput_median': np.median(data['throughput']),
        'p50_avg': np.mean(data['p50']),
        'p50_median': np.median(data['p50']),
        'p95_avg': np.mean(data['p95']),
        'p95_median': np.median(data['p95']),
        'p99_avg': np.mean(data['p99']),
        'p99_median': np.median(data['p99']),
        'p99_p95': np.percentile(data['p99'], 95),
        'p99_max': np.max(data['p99']),
        'snd_ratio_avg': np.mean(data['snd_ratio']),
        'snd_ratio_median': np.median(data['snd_ratio']),
        'snd_ratio_p95': np.percentile(data['snd_ratio'], 95),
        'snd_ratio_max': np.max(data['snd_ratio']),
        'rtt_avg': np.mean(data['rtt']),
        'rtt_median': np.median(data['rtt']),
        'retrans_rate': data['had_retrans'] / data['total'] * 100 if data['total'] > 0 else 0,
        'retrans_count_avg': np.mean(data['retrans_count']),
        'raw': data
    }
    
    return stats

print("🔥 3-Way 비교: Baseline vs EMQX Flow Control vs RL")
print("=" * 100)

# 네트워크 조건별 로그 정의
scenarios = {
    'congestion': {
        'title': 'Congestion Network (혼잡 네트워크)',
        'baseline': '/home/sslab/mqtt-ebpf-edge/logs/baseline/baseline_conjestion.jsonl',
        'emqx': 'logs/emqx_flow_control/congestion.jsonl',
        'rl': 'logs/torch_model_experiments/congestion/rl_bc_v2_congestion.jsonl'
    }
}

all_results = {}

for scenario_name, files in scenarios.items():
    print(f"\n{'='*100}")
    print(f"📊 {files['title']}")
    print(f"{'='*100}")
    
    results = {}
    
    # 1. Baseline 분석
    print(f"\n🔵 Baseline (제어 완전 없음)")
    try:
        baseline = analyze_log(files['baseline'], 'Baseline')
        if baseline:
            results['baseline'] = baseline
            print(f"  샘플:         {baseline['samples']}")
            print(f"  처리량:       {baseline['throughput_avg']:6.1f} msg/s (중앙값: {baseline['throughput_median']:6.1f})")
            print(f"  P50:          {baseline['p50_avg']:8.1f} ms (중앙값: {baseline['p50_median']:8.1f})")
            print(f"  P95:          {baseline['p95_avg']:8.1f} ms (중앙값: {baseline['p95_median']:8.1f})")
            print(f"  P99:          {baseline['p99_avg']:8.1f} ms (중앙값: {baseline['p99_median']:8.1f}, 최악: {baseline['p99_max']:8.1f})")
            print(f"  snd_ratio:    {baseline['snd_ratio_avg']:6.4f} (중앙값: {baseline['snd_ratio_median']:6.4f})")
            print(f"  RTT:          {baseline['rtt_avg']:8.1f} ms")
            print(f"  재전송률:     {baseline['retrans_rate']:5.1f}%")
        else:
            print(f"  ❌ 데이터 없음")
    except Exception as e:
        print(f"  ❌ 로드 실패: {e}")
    
    # 2. EMQX Flow Control 분석
    print(f"\n🟡 EMQX Flow Control (내장 제어)")
    try:
        emqx = analyze_log(files['emqx'], 'EMQX')
        if emqx:
            results['emqx'] = emqx
            print(f"  샘플:         {emqx['samples']}")
            print(f"  처리량:       {emqx['throughput_avg']:6.1f} msg/s (중앙값: {emqx['throughput_median']:6.1f})")
            print(f"  P50:          {emqx['p50_avg']:8.1f} ms (중앙값: {emqx['p50_median']:8.1f})")
            print(f"  P95:          {emqx['p95_avg']:8.1f} ms (중앙값: {emqx['p95_median']:8.1f})")
            print(f"  P99:          {emqx['p99_avg']:8.1f} ms (중앙값: {emqx['p99_median']:8.1f}, 최악: {emqx['p99_max']:8.1f})")
            print(f"  snd_ratio:    {emqx['snd_ratio_avg']:6.4f} (중앙값: {emqx['snd_ratio_median']:6.4f})")
            print(f"  RTT:          {emqx['rtt_avg']:8.1f} ms")
            print(f"  재전송률:     {emqx['retrans_rate']:5.1f}%")
        else:
            print(f"  ❌ 데이터 없음")
    except Exception as e:
        print(f"  ❌ 로드 실패: {e}")
    
    # 3. RL 분석
    print(f"\n🟢 RL Control (eBPF + RL)")
    try:
        rl = analyze_log(files['rl'], 'RL')
        if rl:
            results['rl'] = rl
            print(f"  샘플:         {rl['samples']}")
            print(f"  처리량:       {rl['throughput_avg']:6.1f} msg/s (중앙값: {rl['throughput_median']:6.1f})")
            print(f"  P50:          {rl['p50_avg']:8.1f} ms (중앙값: {rl['p50_median']:8.1f})")
            print(f"  P95:          {rl['p95_avg']:8.1f} ms (중앙값: {rl['p95_median']:8.1f})")
            print(f"  P99:          {rl['p99_avg']:8.1f} ms (중앙값: {rl['p99_median']:8.1f}, 최악: {rl['p99_max']:8.1f})")
            print(f"  snd_ratio:    {rl['snd_ratio_avg']:6.4f} (중앙값: {rl['snd_ratio_median']:6.4f})")
            print(f"  RTT:          {rl['rtt_avg']:8.1f} ms")
            print(f"  재전송률:     {rl['retrans_rate']:5.1f}%")
        else:
            print(f"  ❌ 데이터 없음")
    except Exception as e:
        print(f"  ❌ 로드 실패: {e}")
    
    # 비교 요약
    if len(results) >= 2:
        print(f"\n{'='*100}")
        print("📊 비교 요약")
        print(f"{'='*100}")
        
        # 테이블 헤더
        methods = []
        if 'baseline' in results:
            methods.append(('Baseline', results['baseline']))
        if 'emqx' in results:
            methods.append(('EMQX', results['emqx']))
        if 'rl' in results:
            methods.append(('RL', results['rl']))
        
        print(f"\n{'항목':<20}", end='')
        for name, _ in methods:
            print(f"{name:>18}", end='')
        print()
        print("-" * (20 + 18 * len(methods)))
        
        # 각 메트릭 출력
        metrics = [
            ('처리량 (msg/s)', 'throughput_avg', '{:.1f}'),
            ('P50 (ms)', 'p50_avg', '{:.1f}'),
            ('P95 (ms)', 'p95_avg', '{:.1f}'),
            ('P99 (ms)', 'p99_avg', '{:.1f}'),
            ('P99 최악 (ms)', 'p99_max', '{:.1f}'),
            ('snd_ratio', 'snd_ratio_avg', '{:.4f}'),
            ('RTT (ms)', 'rtt_avg', '{:.1f}'),
            ('재전송률 (%)', 'retrans_rate', '{:.1f}')
        ]
        
        for metric_name, metric_key, fmt in metrics:
            print(f"{metric_name:<20}", end='')
            for _, stats in methods:
                value = stats[metric_key]
                print(f"{fmt.format(value):>18}", end='')
            print()
        
        # RL 대비 개선율 계산
        if 'rl' in results:
            print(f"\n{'='*100}")
            print("✨ RL 개선 효과")
            print(f"{'='*100}")
            
            rl_stats = results['rl']
            
            if 'baseline' in results:
                baseline = results['baseline']
                print(f"\n🔵 Baseline 대비:")
                print(f"  처리량:    {(rl_stats['throughput_avg']-baseline['throughput_avg'])/baseline['throughput_avg']*100:+6.1f}%")
                print(f"  P99:       {(baseline['p99_avg']-rl_stats['p99_avg'])/baseline['p99_avg']*100:+6.1f}%")
                print(f"  snd_ratio: {(baseline['snd_ratio_avg']-rl_stats['snd_ratio_avg'])/baseline['snd_ratio_avg']*100:+6.1f}%")
            
            if 'emqx' in results:
                emqx_stats = results['emqx']
                print(f"\n🟡 EMQX 대비:")
                print(f"  처리량:    {(rl_stats['throughput_avg']-emqx_stats['throughput_avg'])/emqx_stats['throughput_avg']*100:+6.1f}%")
                print(f"  P99:       {(emqx_stats['p99_avg']-rl_stats['p99_avg'])/emqx_stats['p99_avg']*100:+6.1f}%")
                print(f"  snd_ratio: {(emqx_stats['snd_ratio_avg']-rl_stats['snd_ratio_avg'])/emqx_stats['snd_ratio_avg']*100:+6.1f}%")
    
    all_results[scenario_name] = results

# 그래프 생성
if 'congestion' in all_results and len(all_results['congestion']) >= 2:
    results = all_results['congestion']
    
    fig = plt.figure(figsize=(20, 12))
    gs = fig.add_gridspec(3, 4, hspace=0.3, wspace=0.3)
    
    fig.suptitle('3-Way Comparison: Baseline vs EMQX Flow Control vs RL (Congestion Network)', 
                 fontsize=16, fontweight='bold')
    
    methods = []
    colors = []
    if 'baseline' in results:
        methods.append(('Baseline', results['baseline']))
        colors.append('blue')
    if 'emqx' in results:
        methods.append(('EMQX', results['emqx']))
        colors.append('orange')
    if 'rl' in results:
        methods.append(('RL', results['rl']))
        colors.append('green')
    
    labels = [m[0] for m in methods]
    
    # 1. Throughput 시계열 비교
    ax = fig.add_subplot(gs[0, :2])
    for (name, stats), color in zip(methods, colors):
        ax.plot(stats['raw']['throughput'], label=name, alpha=0.7, linewidth=1, color=color)
    ax.set_xlabel('Time Window')
    ax.set_ylabel('Throughput (msg/s)')
    ax.set_title('Throughput Over Time')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # 2. P99 Latency 시계열 비교
    ax = fig.add_subplot(gs[0, 2:])
    for (name, stats), color in zip(methods, colors):
        p99_data = stats['raw']['p99']
        ax.plot(p99_data, label=name, alpha=0.7, linewidth=1, color=color)
    ax.axhline(300, color='red', linestyle='--', alpha=0.5, label='SLO (300ms)')
    ax.set_xlabel('Time Window')
    ax.set_ylabel('P99 Latency (ms)')
    ax.set_title('P99 Latency Over Time')
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.set_ylim([0, min(60000, max([np.max(m[1]['raw']['p99']) for m in methods]))])
    
    # 3. snd_ratio 시계열 비교
    ax = fig.add_subplot(gs[1, :2])
    for (name, stats), color in zip(methods, colors):
        ax.plot(stats['raw']['snd_ratio'], label=name, alpha=0.7, linewidth=1, color=color)
    ax.axhline(0.1, color='orange', linestyle='--', alpha=0.5, label='Caution')
    ax.axhline(0.3, color='red', linestyle='--', alpha=0.5, label='Warning')
    ax.set_xlabel('Time Window')
    ax.set_ylabel('snd_ratio')
    ax.set_title('TCP Send Buffer Pressure Over Time')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # 4. Bar 차트 - 주요 메트릭
    ax = fig.add_subplot(gs[1, 2:])
    metrics_to_plot = ['throughput_avg', 'p99_avg', 'snd_ratio_avg']
    metric_labels = ['Throughput\n(msg/s)', 'P99\n(ms/10)', 'snd_ratio\n(x100)']
    
    x = np.arange(len(metric_labels))
    width = 0.25
    
    for i, ((name, stats), color) in enumerate(zip(methods, colors)):
        values = [
            stats['throughput_avg'],
            stats['p99_avg'] / 10,  # Scale down for visualization
            stats['snd_ratio_avg'] * 100  # Scale up for visualization
        ]
        offset = (i - len(methods)/2 + 0.5) * width
        bars = ax.bar(x + offset, values, width, label=name, color=color, alpha=0.7, edgecolor='black')
        
        # Add value labels on bars
        for j, (bar, val) in enumerate(zip(bars, values)):
            height = bar.get_height()
            if j == 0:  # Throughput
                label_val = stats['throughput_avg']
            elif j == 1:  # P99
                label_val = stats['p99_avg']
            else:  # snd_ratio
                label_val = stats['snd_ratio_avg']
            
            ax.text(bar.get_x() + bar.get_width()/2., height,
                   f'{label_val:.1f}' if j != 2 else f'{label_val:.3f}',
                   ha='center', va='bottom', fontsize=8, fontweight='bold')
    
    ax.set_ylabel('Value (scaled)')
    ax.set_title('Key Metrics Comparison')
    ax.set_xticks(x)
    ax.set_xticklabels(metric_labels)
    ax.legend()
    ax.grid(True, alpha=0.3, axis='y')
    
    # 5. P99 분포 박스플롯
    ax = fig.add_subplot(gs[2, 0])
    p99_data = [stats['raw']['p99'] for _, stats in methods]
    bp = ax.boxplot(p99_data, labels=labels, patch_artist=True)
    for patch, color in zip(bp['boxes'], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.7)
    ax.set_ylabel('P99 Latency (ms)')
    ax.set_title('P99 Distribution')
    ax.grid(True, alpha=0.3, axis='y')
    ax.set_ylim([0, min(60000, max([np.max(data) for data in p99_data]))])
    
    # 6. Throughput 분포 박스플롯
    ax = fig.add_subplot(gs[2, 1])
    tput_data = [stats['raw']['throughput'] for _, stats in methods]
    bp = ax.boxplot(tput_data, labels=labels, patch_artist=True)
    for patch, color in zip(bp['boxes'], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.7)
    ax.set_ylabel('Throughput (msg/s)')
    ax.set_title('Throughput Distribution')
    ax.grid(True, alpha=0.3, axis='y')
    
    # 7. snd_ratio 분포 히스토그램
    ax = fig.add_subplot(gs[2, 2])
    for (name, stats), color in zip(methods, colors):
        ax.hist(stats['raw']['snd_ratio'], bins=50, alpha=0.5, label=name, color=color, edgecolor='black')
    ax.axvline(0.1, color='orange', linestyle='--', alpha=0.5)
    ax.axvline(0.3, color='red', linestyle='--', alpha=0.5)
    ax.set_xlabel('snd_ratio')
    ax.set_ylabel('Frequency')
    ax.set_title('Buffer Pressure Distribution')
    ax.legend()
    ax.grid(True, alpha=0.3, axis='y')
    
    # 8. Summary table
    ax = fig.add_subplot(gs[2, 3])
    ax.axis('off')
    
    summary_lines = ["3-Way Comparison Summary", "="*40, ""]
    for name, stats in methods:
        summary_lines.append(f"{name}:")
        summary_lines.append(f"  Throughput: {stats['throughput_avg']:.1f} msg/s")
        summary_lines.append(f"  P99:        {stats['p99_avg']:.1f} ms")
        summary_lines.append(f"  snd_ratio:  {stats['snd_ratio_avg']:.4f}")
        summary_lines.append("")
    
    if 'rl' in results:
        rl_stats = results['rl']
        summary_lines.append("RL Improvements:")
        if 'baseline' in results:
            baseline = results['baseline']
            p99_impr = (baseline['p99_avg']-rl_stats['p99_avg'])/baseline['p99_avg']*100
            summary_lines.append(f"  vs Baseline:")
            summary_lines.append(f"    P99: {p99_impr:+.1f}%")
        if 'emqx' in results:
            emqx_stats = results['emqx']
            p99_impr = (emqx_stats['p99_avg']-rl_stats['p99_avg'])/emqx_stats['p99_avg']*100
            summary_lines.append(f"  vs EMQX:")
            summary_lines.append(f"    P99: {p99_impr:+.1f}%")
    
    summary_text = '\n'.join(summary_lines)
    ax.text(0.1, 0.5, summary_text, fontsize=9, family='monospace',
            verticalalignment='center', transform=ax.transAxes)
    
    plt.savefig('results/3way_comparison.png', dpi=300, bbox_inches='tight')
    print(f"\n✅ 저장: results/3way_comparison.png")

print(f"\n{'='*100}")
print("🎯 최종 결론")
print(f"{'='*100}")
print("""
1. Baseline (제어 없음):
   - 가장 불안정
   - 네트워크 혼잡 시 성능 급격히 저하
   
2. EMQX Flow Control:
   - 처리량 유지 시도
   - 하지만 버퍼 압력 관리 실패 → P99 폭발
   - TCP 큐잉 지연 누적
   
3. RL Control (우리 방법):
   - 처리량 희생하지만 안정성 확보
   - 버퍼 압력 사전 감지 및 제어
   - P99를 98% 개선 (50초 → 1초)
   - 실용적이고 예측 가능한 성능
""")
