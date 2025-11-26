#!/usr/bin/env python3
"""
실험 결과 그래프 생성
- 4가지 방법 비교: base, bbr, emqx, emqttrl
- 3가지 시나리오: normal, congestion, dynamic
"""

import json
import numpy as np
import matplotlib.pyplot as plt
import matplotlib
from pathlib import Path

# 한글 폰트 설정
matplotlib.rcParams['font.family'] = 'DejaVu Sans'
matplotlib.rcParams['axes.unicode_minus'] = False

# 로그 디렉토리
LOG_BASE = Path("logs/2로그정리")

# 방법별 설정
METHODS = {
    'base': {'name': 'Baseline', 'color': '#e74c3c', 'marker': 'o'},
    'bbr': {'name': 'BBR', 'color': '#3498db', 'marker': 's'},
    'emqx': {'name': 'EMQX Flow Control', 'color': '#f39c12', 'marker': '^'},
    'emqttrl': {'name': 'eBPF-RL (Ours)', 'color': '#2ecc71', 'marker': 'D'}
}

SCENARIOS = ['normal', 'congestion', 'dynamic']


def load_log(method, scenario):
    """로그 파일 로드"""
    # emqx와 emqttrl의 normal은 normol로 오타
    if method in ['emqx', 'emqttrl'] and scenario == 'normal':
        filename = 'normol_v1.jsonl'
    else:
        filename = f'{scenario}_v1.jsonl'
    
    filepath = LOG_BASE / method / filename
    
    if not filepath.exists():
        print(f"Warning: {filepath} not found")
        return None
    
    data = {
        'p50': [], 'p95': [], 'p99': [],
        'throughput': [], 'timestamps': []
    }
    
    with open(filepath, 'r') as f:
        for line in f:
            try:
                entry = json.loads(line)
                
                # 새 형식: p99_ms, thr 직접 있음
                if 'p99_ms' in entry:
                    data['p50'].append(entry.get('p50_ms', 0))
                    data['p95'].append(entry.get('p95_ms', 0))
                    data['p99'].append(entry.get('p99_ms', 0))
                    data['throughput'].append(entry.get('thr', 0))
                    data['timestamps'].append(entry.get('idx', 0))  # idx를 timestamp로 사용
                # 구 형식: metrics 안에 있음
                elif 'metrics' in entry:
                    metrics = entry['metrics']
                    if metrics.get('p99_ms') is not None:
                        data['p50'].append(metrics.get('p50_ms', 0))
                        data['p95'].append(metrics.get('p95_ms', 0))
                        data['p99'].append(metrics.get('p99_ms', 0))
                        data['throughput'].append(metrics.get('n', 0) / metrics.get('window_sec', 30))
                        data['timestamps'].append(entry.get('ts', 0))
            except:
                continue
    
    return data if data['p99'] else None


def compute_stats(values):
    """통계 계산"""
    if not values:
        return {'mean': 0, 'median': 0, 'std': 0, 'min': 0, 'max': 0}
    
    arr = np.array(values)
    return {
        'mean': np.mean(arr),
        'median': np.median(arr),
        'std': np.std(arr),
        'min': np.min(arr),
        'max': np.max(arr)
    }


def plot_p99_comparison():
    """그래프 1: P99 Latency 비교 (Bar Chart)"""
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    
    for idx, scenario in enumerate(SCENARIOS):
        ax = axes[idx]
        
        methods_list = []
        p99_means = []
        p99_stds = []
        colors = []
        
        for method, config in METHODS.items():
            data = load_log(method, scenario)
            if data:
                stats = compute_stats(data['p99'])
                methods_list.append(config['name'])
                p99_means.append(stats['mean'])
                p99_stds.append(stats['std'])
                colors.append(config['color'])
        
        x = np.arange(len(methods_list))
        bars = ax.bar(x, p99_means, yerr=p99_stds, capsize=5, 
                      color=colors, alpha=0.8, edgecolor='black', linewidth=1.5)
        
        # 값 표시
        for i, (bar, val) in enumerate(zip(bars, p99_means)):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height,
                   f'{val:.0f}ms',
                   ha='center', va='bottom', fontsize=10, fontweight='bold')
        
        ax.set_title(f'{scenario.capitalize()} Network', fontsize=14, fontweight='bold')
        ax.set_ylabel('P99 Latency (ms)', fontsize=12)
        ax.set_xticks(x)
        ax.set_xticklabels(methods_list, rotation=15, ha='right')
        ax.grid(axis='y', alpha=0.3, linestyle='--')
        ax.set_ylim(bottom=0)
    
    plt.tight_layout()
    plt.savefig('result_1_p99_comparison.png', dpi=300, bbox_inches='tight')
    print("✓ result_1_p99_comparison.png 생성 완료")
    plt.close()


def plot_latency_cdf():
    """그래프 2: P99 Latency CDF (Cumulative Distribution)"""
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    
    for idx, scenario in enumerate(SCENARIOS):
        ax = axes[idx]
        
        for method, config in METHODS.items():
            data = load_log(method, scenario)
            if data and data['p99']:
                sorted_data = np.sort(data['p99'])
                cdf = np.arange(1, len(sorted_data) + 1) / len(sorted_data)
                
                ax.plot(sorted_data, cdf, 
                       label=config['name'],
                       color=config['color'],
                       linewidth=2.5,
                       marker=config['marker'],
                       markevery=max(1, len(sorted_data) // 10),
                       markersize=8,
                       alpha=0.8)
        
        ax.set_title(f'{scenario.capitalize()} Network', fontsize=14, fontweight='bold')
        ax.set_xlabel('P99 Latency (ms)', fontsize=12)
        ax.set_ylabel('CDF', fontsize=12)
        ax.legend(loc='lower right', fontsize=10)
        ax.grid(True, alpha=0.3, linestyle='--')
        ax.set_xlim(left=0)
    
    plt.tight_layout()
    plt.savefig('result_2_latency_cdf.png', dpi=300, bbox_inches='tight')
    print("✓ result_2_latency_cdf.png 생성 완료")
    plt.close()


def plot_throughput_comparison():
    """그래프 3: Throughput 비교"""
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    
    for idx, scenario in enumerate(SCENARIOS):
        ax = axes[idx]
        
        methods_list = []
        throughput_means = []
        throughput_stds = []
        colors = []
        
        for method, config in METHODS.items():
            data = load_log(method, scenario)
            if data:
                stats = compute_stats(data['throughput'])
                methods_list.append(config['name'])
                throughput_means.append(stats['mean'])
                throughput_stds.append(stats['std'])
                colors.append(config['color'])
        
        x = np.arange(len(methods_list))
        bars = ax.bar(x, throughput_means, yerr=throughput_stds, capsize=5,
                      color=colors, alpha=0.8, edgecolor='black', linewidth=1.5)
        
        # 값 표시
        for bar, val in zip(bars, throughput_means):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height,
                   f'{val:.0f}',
                   ha='center', va='bottom', fontsize=10, fontweight='bold')
        
        ax.set_title(f'{scenario.capitalize()} Network', fontsize=14, fontweight='bold')
        ax.set_ylabel('Throughput (msg/s)', fontsize=12)
        ax.set_xticks(x)
        ax.set_xticklabels(methods_list, rotation=15, ha='right')
        ax.grid(axis='y', alpha=0.3, linestyle='--')
        ax.set_ylim(bottom=0)
    
    plt.tight_layout()
    plt.savefig('result_3_throughput.png', dpi=300, bbox_inches='tight')
    print("✓ result_3_throughput.png 생성 완료")
    plt.close()


def plot_timeseries():
    """그래프 4: P99 Latency 시계열 (Dynamic 시나리오)"""
    fig, ax = plt.subplots(1, 1, figsize=(12, 6))
    
    scenario = 'dynamic'
    
    for method, config in METHODS.items():
        data = load_log(method, scenario)
        if data and data['timestamps']:
            # 시간 정규화 (시작점을 0으로)
            timestamps = np.array(data['timestamps'])
            if len(timestamps) > 0:
                timestamps = timestamps - timestamps[0]
                
                ax.plot(timestamps, data['p99'],
                       label=config['name'],
                       color=config['color'],
                       linewidth=2.5,
                       marker=config['marker'],
                       markevery=max(1, len(timestamps) // 20),
                       markersize=8,
                       alpha=0.8)
    
    ax.set_title('P99 Latency Over Time (Dynamic Network)', fontsize=14, fontweight='bold')
    ax.set_xlabel('Time (seconds)', fontsize=12)
    ax.set_ylabel('P99 Latency (ms)', fontsize=12)
    ax.legend(loc='upper right', fontsize=11)
    ax.grid(True, alpha=0.3, linestyle='--')
    
    plt.tight_layout()
    plt.savefig('result_4_timeseries.png', dpi=300, bbox_inches='tight')
    print("✓ result_4_timeseries.png 생성 완료")
    plt.close()


def plot_improvement_heatmap():
    """그래프 5: Baseline 대비 개선율 히트맵"""
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # 데이터 수집
    improvements = []
    methods_display = []
    
    for method, config in METHODS.items():
        if method == 'base':
            continue
        
        method_improvements = []
        for scenario in SCENARIOS:
            baseline_data = load_log('base', scenario)
            method_data = load_log(method, scenario)
            
            if baseline_data and method_data:
                baseline_p99 = np.mean(baseline_data['p99'])
                method_p99 = np.mean(method_data['p99'])
                improvement = ((baseline_p99 - method_p99) / baseline_p99) * 100
                method_improvements.append(improvement)
            else:
                method_improvements.append(0)
        
        improvements.append(method_improvements)
        methods_display.append(config['name'])
    
    improvements = np.array(improvements)
    
    # 히트맵 그리기
    im = ax.imshow(improvements, cmap='RdYlGn', aspect='auto', vmin=-50, vmax=100)
    
    # 축 설정
    ax.set_xticks(np.arange(len(SCENARIOS)))
    ax.set_yticks(np.arange(len(methods_display)))
    ax.set_xticklabels([s.capitalize() for s in SCENARIOS])
    ax.set_yticklabels(methods_display)
    
    # 값 표시
    for i in range(len(methods_display)):
        for j in range(len(SCENARIOS)):
            text = ax.text(j, i, f'{improvements[i, j]:.1f}%',
                          ha="center", va="center", color="black",
                          fontsize=12, fontweight='bold')
    
    ax.set_title('P99 Latency Improvement vs Baseline (%)', 
                 fontsize=14, fontweight='bold', pad=20)
    
    # 컬러바
    cbar = plt.colorbar(im, ax=ax)
    cbar.set_label('Improvement (%)', rotation=270, labelpad=20, fontsize=11)
    
    plt.tight_layout()
    plt.savefig('result_5_improvement_heatmap.png', dpi=300, bbox_inches='tight')
    print("✓ result_5_improvement_heatmap.png 생성 완료")
    plt.close()


def generate_summary_table():
    """요약 통계 테이블 생성"""
    print("\n" + "="*80)
    print("실험 결과 요약 (P99 Latency)")
    print("="*80)
    
    for scenario in SCENARIOS:
        print(f"\n【{scenario.upper()} Network】")
        print("-" * 70)
        print(f"{'Method':<25} {'Mean (ms)':<15} {'Median (ms)':<15} {'Std (ms)':<15}")
        print("-" * 70)
        
        baseline_mean = None
        for method, config in METHODS.items():
            data = load_log(method, scenario)
            if data:
                stats = compute_stats(data['p99'])
                print(f"{config['name']:<25} {stats['mean']:<15.2f} "
                      f"{stats['median']:<15.2f} {stats['std']:<15.2f}")
                
                if method == 'base':
                    baseline_mean = stats['mean']
                elif baseline_mean and stats['mean'] > 0:
                    improvement = ((baseline_mean - stats['mean']) / baseline_mean) * 100
                    print(f"  └─ Improvement: {improvement:+.1f}%")


def main():
    print("="*80)
    print("실험 결과 그래프 생성 시작")
    print("="*80)
    
    plot_p99_comparison()
    plot_latency_cdf()
    plot_throughput_comparison()
    plot_timeseries()
    plot_improvement_heatmap()
    
    generate_summary_table()
    
    print("\n" + "="*80)
    print("✅ 모든 그래프 생성 완료!")
    print("="*80)
    print("\n생성된 파일:")
    print("  1. result_1_p99_comparison.png    - P99 레이턴시 비교 (Bar)")
    print("  2. result_2_latency_cdf.png        - 레이턴시 CDF")
    print("  3. result_3_throughput.png         - 처리량 비교")
    print("  4. result_4_timeseries.png         - 시계열 분석 (Dynamic)")
    print("  5. result_5_improvement_heatmap.png - 개선율 히트맵")
    print("="*80)


if __name__ == "__main__":
    main()
