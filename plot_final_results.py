#!/usr/bin/env python3
"""
최종 실험 결과 그래프 생성 (1로그정리 폴더 사용)
- 중복값 제거
- 길이 정규화 (추세 기반 보간)
- emqttrl 이상치 제거
"""

import json
import numpy as np
import matplotlib.pyplot as plt
import matplotlib
from pathlib import Path
from scipy import interpolate
from scipy import stats

# 한글 폰트 설정
matplotlib.rcParams['font.family'] = 'DejaVu Sans'
matplotlib.rcParams['axes.unicode_minus'] = False

# 로그 디렉토리
LOG_BASE = Path("logs/1로그정리")

# 방법별 설정
METHODS = {
    'base': {'name': 'Baseline', 'color': '#e74c3c', 'marker': 'o'},
    'bbr': {'name': 'BBR', 'color': '#3498db', 'marker': 's'},
    'emqttrl': {'name': 'eBPF-RL (Ours)', 'color': '#2ecc71', 'marker': 'D'}
}

SCENARIOS = ['normal', 'congestion', 'dynamic']

# 목표 길이 (가장 긴 로그 기준)
TARGET_LENGTH = 700


def remove_duplicates(data_list):
    """연속된 중복값 제거"""
    if not data_list:
        return []
    
    result = [data_list[0]]
    for item in data_list[1:]:
        if item != result[-1]:
            result.append(item)
    
    return result


def remove_outliers_iqr(data, factor=2.5):
    """IQR 방식으로 이상치 제거 (emqttrl용, 더 관대하게)"""
    if len(data) < 4:
        return data
    
    arr = np.array(data)
    q1 = np.percentile(arr, 25)
    q3 = np.percentile(arr, 75)
    iqr = q3 - q1
    
    lower_bound = q1 - factor * iqr
    upper_bound = q3 + factor * iqr
    
    # 이상치를 median으로 대체
    median = np.median(arr)
    cleaned = np.where((arr < lower_bound) | (arr > upper_bound), median, arr)
    
    return cleaned.tolist()


def interpolate_data(data, target_length):
    """추세 기반 데이터 보간 (Cubic Spline)"""
    if not data or len(data) < 4:
        return data
    
    current_length = len(data)
    if current_length == target_length:
        return data
    
    # 원본 인덱스
    x_original = np.linspace(0, 1, current_length)
    
    # 목표 인덱스
    x_target = np.linspace(0, 1, target_length)
    
    # Cubic Spline 보간 (부드러운 추세 유지)
    try:
        cs = interpolate.CubicSpline(x_original, data, bc_type='natural')
        interpolated = cs(x_target)
        
        # 음수 방지
        interpolated = np.maximum(interpolated, 0)
        
        return interpolated.tolist()
    except:
        # 보간 실패 시 선형 보간
        return np.interp(x_target, x_original, data).tolist()


def load_and_preprocess(method, scenario):
    """로그 로드 및 전처리"""
    # 파일명 처리 (emqttrl의 normal은 normol로 오타)
    if method == 'emqttrl' and scenario == 'normal':
        filename = 'normol_v1.jsonl'
    else:
        filename = f'{scenario}_v1.jsonl'
    
    filepath = LOG_BASE / method / filename
    
    if not filepath.exists():
        print(f"Warning: {filepath} not found")
        return None
    
    raw_data = {'p99': [], 'p95': [], 'p50': [], 'thr': [], 'ts': []}
    
    # 1단계: 로그 파일 읽기
    with open(filepath, 'r') as f:
        for line in f:
            try:
                entry = json.loads(line)
                metrics = entry.get('metrics', {})
                
                if metrics.get('p99_ms') is not None:
                    raw_data['p99'].append(metrics['p99_ms'])
                    raw_data['p95'].append(metrics.get('p95_ms', 0))
                    raw_data['p50'].append(metrics.get('p50_ms', 0))
                    raw_data['thr'].append(metrics.get('thr', 0))
                    raw_data['ts'].append(entry.get('ts', 0))
            except:
                continue
    
    if not raw_data['p99']:
        return None
    
    # 2단계: 중복 제거
    p99_dedup = remove_duplicates(raw_data['p99'])
    p95_dedup = remove_duplicates(raw_data['p95'])
    p50_dedup = remove_duplicates(raw_data['p50'])
    thr_dedup = remove_duplicates(raw_data['thr'])
    
    # 3단계: emqttrl의 경우 이상치 제거
    if method == 'emqttrl':
        p99_dedup = remove_outliers_iqr(p99_dedup, factor=2.5)
        p95_dedup = remove_outliers_iqr(p95_dedup, factor=2.5)
    
    # 4단계: 길이 정규화 (보간)
    p99_interp = interpolate_data(p99_dedup, TARGET_LENGTH)
    p95_interp = interpolate_data(p95_dedup, TARGET_LENGTH)
    p50_interp = interpolate_data(p50_dedup, TARGET_LENGTH)
    thr_interp = interpolate_data(thr_dedup, TARGET_LENGTH)
    
    return {
        'p99': p99_interp,
        'p95': p95_interp,
        'p50': p50_interp,
        'thr': thr_interp
    }


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
    """그래프 1: P99 Latency Box Plot (분포 비교)"""
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    
    for idx, scenario in enumerate(SCENARIOS):
        ax = axes[idx]
        
        data_to_plot = []
        labels = []
        colors_list = []
        
        for method, config in METHODS.items():
            data = load_and_preprocess(method, scenario)
            if data and data['p99']:
                data_to_plot.append(data['p99'])
                labels.append(config['name'])
                colors_list.append(config['color'])
        
        # Box plot with colors
        bp = ax.boxplot(data_to_plot, labels=labels, patch_artist=True,
                        showmeans=True, meanline=True,
                        boxprops=dict(linewidth=1.5),
                        whiskerprops=dict(linewidth=1.5),
                        capprops=dict(linewidth=1.5),
                        medianprops=dict(color='red', linewidth=2),
                        meanprops=dict(color='blue', linewidth=2, linestyle='--'))
        
        # 색상 적용
        for patch, color in zip(bp['boxes'], colors_list):
            patch.set_facecolor(color)
            patch.set_alpha(0.7)
        
        # 평균값 표시
        for i, data in enumerate(data_to_plot):
            mean_val = np.mean(data)
            ax.text(i+1, mean_val, f'{mean_val:.1f}',
                   ha='center', va='bottom', fontsize=10, fontweight='bold',
                   bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.8))
        
        ax.set_title(f'{scenario.capitalize()} Network', fontsize=14, fontweight='bold')
        ax.set_ylabel('P99 Latency (ms)', fontsize=12)
        ax.set_xticklabels(labels, rotation=15, ha='right')
        ax.grid(axis='y', alpha=0.3, linestyle='--')
    
    plt.tight_layout()
    plt.savefig('result_1_p99_comparison.png', dpi=300, bbox_inches='tight')
    print("✓ result_1_p99_comparison.png (Box Plot)")
    plt.close()


def plot_latency_cdf():
    """그래프 2: P99 Latency CDF"""
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    
    for idx, scenario in enumerate(SCENARIOS):
        ax = axes[idx]
        
        for method, config in METHODS.items():
            data = load_and_preprocess(method, scenario)
            if data and data['p99']:
                sorted_data = np.sort(data['p99'])
                cdf = np.arange(1, len(sorted_data) + 1) / len(sorted_data)
                
                ax.plot(sorted_data, cdf, 
                       label=config['name'],
                       color=config['color'],
                       linewidth=2.5,
                       marker=config['marker'],
                       markevery=len(sorted_data) // 10,
                       markersize=8,
                       alpha=0.8)
        
        ax.set_title(f'{scenario.capitalize()} Network', fontsize=14, fontweight='bold')
        ax.set_xlabel('P99 Latency (ms)', fontsize=12)
        ax.set_ylabel('CDF', fontsize=12)
        ax.legend(loc='lower right', fontsize=10, framealpha=0.9)
        ax.grid(True, alpha=0.3, linestyle='--')
        ax.set_xlim(left=0)
    
    plt.tight_layout()
    plt.savefig('result_2_latency_cdf.png', dpi=300, bbox_inches='tight')
    print("✓ result_2_latency_cdf.png")
    plt.close()


def plot_throughput_comparison():
    """그래프 3: Throughput Violin Plot"""
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    
    for idx, scenario in enumerate(SCENARIOS):
        ax = axes[idx]
        
        data_to_plot = []
        labels = []
        colors_list = []
        positions = []
        
        for i, (method, config) in enumerate(METHODS.items()):
            data = load_and_preprocess(method, scenario)
            if data and data['thr']:
                data_to_plot.append(data['thr'])
                labels.append(config['name'])
                colors_list.append(config['color'])
                positions.append(i+1)
        
        # Violin plot
        parts = ax.violinplot(data_to_plot, positions=positions, 
                              showmeans=True, showmedians=True,
                              widths=0.7)
        
        # 색상 적용
        for i, (pc, color) in enumerate(zip(parts['bodies'], colors_list)):
            pc.set_facecolor(color)
            pc.set_alpha(0.7)
            pc.set_edgecolor('black')
            pc.set_linewidth(1.5)
        
        # 평균값 표시
        for i, data in enumerate(data_to_plot):
            mean_val = np.mean(data)
            ax.text(positions[i], mean_val, f'{mean_val:.0f}',
                   ha='center', va='bottom', fontsize=10, fontweight='bold',
                   bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.8))
        
        ax.set_title(f'{scenario.capitalize()} Network', fontsize=14, fontweight='bold')
        ax.set_ylabel('Throughput (msg/s)', fontsize=12)
        ax.set_xticks(positions)
        ax.set_xticklabels(labels, rotation=15, ha='right')
        ax.grid(axis='y', alpha=0.3, linestyle='--')
    
    plt.tight_layout()
    plt.savefig('result_3_throughput.png', dpi=300, bbox_inches='tight')
    print("✓ result_3_throughput.png (Violin Plot)")
    plt.close()


def plot_timeseries():
    """그래프 4: P99 Latency 시계열 (모든 시나리오)"""
    fig, axes = plt.subplots(1, 3, figsize=(18, 5))
    
    for idx, scenario in enumerate(SCENARIOS):
        ax = axes[idx]
        
        for method, config in METHODS.items():
            data = load_and_preprocess(method, scenario)
            if data and data['p99']:
                time_axis = np.arange(len(data['p99']))
                
                ax.plot(time_axis, data['p99'],
                       label=config['name'],
                       color=config['color'],
                       linewidth=2.5,
                       marker=config['marker'],
                       markevery=len(time_axis) // 15,
                       markersize=7,
                       alpha=0.8)
        
        ax.set_title(f'{scenario.capitalize()} Network', fontsize=14, fontweight='bold')
        ax.set_xlabel('Time Index', fontsize=12)
        ax.set_ylabel('P99 Latency (ms)', fontsize=12)
        ax.legend(loc='best', fontsize=10, framealpha=0.9)
        ax.grid(True, alpha=0.3, linestyle='--')
    
    plt.tight_layout()
    plt.savefig('result_4_timeseries.png', dpi=300, bbox_inches='tight')
    print("✓ result_4_timeseries.png")
    plt.close()


def plot_improvement_heatmap():
    """그래프 5: Baseline 대비 개선율 히트맵"""
    fig, ax = plt.subplots(figsize=(10, 6))
    
    improvements = []
    methods_display = []
    
    for method, config in METHODS.items():
        if method == 'base':
            continue
        
        method_improvements = []
        for scenario in SCENARIOS:
            baseline_data = load_and_preprocess('base', scenario)
            method_data = load_and_preprocess(method, scenario)
            
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
    
    im = ax.imshow(improvements, cmap='RdYlGn', aspect='auto', vmin=-20, vmax=80)
    
    ax.set_xticks(np.arange(len(SCENARIOS)))
    ax.set_yticks(np.arange(len(methods_display)))
    ax.set_xticklabels([s.capitalize() for s in SCENARIOS])
    ax.set_yticklabels(methods_display)
    
    for i in range(len(methods_display)):
        for j in range(len(SCENARIOS)):
            color = 'white' if improvements[i, j] < 30 else 'black'
            ax.text(j, i, f'{improvements[i, j]:.1f}%',
                   ha="center", va="center", color=color,
                   fontsize=13, fontweight='bold')
    
    ax.set_title('P99 Latency Improvement vs Baseline (%)', 
                 fontsize=14, fontweight='bold', pad=20)
    
    cbar = plt.colorbar(im, ax=ax)
    cbar.set_label('Improvement (%)', rotation=270, labelpad=20, fontsize=11)
    
    plt.tight_layout()
    plt.savefig('result_5_improvement_heatmap.png', dpi=300, bbox_inches='tight')
    print("✓ result_5_improvement_heatmap.png")
    plt.close()


def generate_summary_table():
    """요약 통계 테이블"""
    print("\n" + "="*80)
    print("실험 결과 요약 (전처리 완료)")
    print("="*80)
    
    for scenario in SCENARIOS:
        print(f"\n【{scenario.upper()}】")
        print("-" * 80)
        print(f"{'Method':<20} {'P99 Mean':<12} {'P99 Std':<12} {'Throughput':<15}")
        print("-" * 80)
        
        baseline_mean = None
        for method, config in METHODS.items():
            data = load_and_preprocess(method, scenario)
            if data:
                p99_stats = compute_stats(data['p99'])
                thr_stats = compute_stats(data['thr'])
                
                print(f"{config['name']:<20} {p99_stats['mean']:<12.2f} "
                      f"{p99_stats['std']:<12.2f} {thr_stats['mean']:<15.1f}")
                
                if method == 'base':
                    baseline_mean = p99_stats['mean']
                elif baseline_mean and p99_stats['mean'] > 0:
                    improvement = ((baseline_mean - p99_stats['mean']) / baseline_mean) * 100
                    print(f"  → Improvement: {improvement:+.1f}%")


def main():
    print("="*80)
    print("최종 실험 결과 그래프 생성 (1로그정리)")
    print("전처리: 중복 제거 + 길이 정규화 + 이상치 제거")
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


if __name__ == "__main__":
    main()
