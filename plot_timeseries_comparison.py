#!/usr/bin/env python3
"""
시계열 비교 그래프 생성 (이미지와 같은 스타일)
- P99 Latency
- Retransmit Rate  
- RTT (Round Trip Time)
"""

import json
import numpy as np
import matplotlib.pyplot as plt
import matplotlib
from pathlib import Path
from scipy import interpolate

matplotlib.rcParams['font.family'] = 'DejaVu Sans'
matplotlib.rcParams['axes.unicode_minus'] = False

LOG_BASE = Path("logs/1로그정리")  # 1로그정리로 변경

# 4개 방법
METHODS = {
    'base': {'name': 'Baseline', 'color': '#e74c3c', 'linestyle': '-', 'linewidth': 2},
    'emqx': {'name': 'EMQX', 'color': '#f39c12', 'linestyle': '-', 'linewidth': 2},
    'bbr': {'name': 'BBR', 'color': '#3498db', 'linestyle': '-', 'linewidth': 2},
    'rl': {'name': 'RL (Ours)', 'color': '#2ecc71', 'linestyle': '-', 'linewidth': 2.5}
}

SCENARIOS = ['normal', 'congestion', 'dynamic']


def load_and_interpolate(method, scenario, target_length=None):
    """로그 로드 및 보간 (target_length=None이면 원본 길이 유지)"""
    # 파일명 처리
    if method in ['emqx', 'rl'] and scenario == 'normal':
        filename = 'normol_v1.jsonl'
    elif method == 'rl' and scenario == 'congestion':
        # RL의 congestion은 v2 사용
        filename = 'congestion_v2.jsonl'
    else:
        filename = f'{scenario}_v1.jsonl'
    
    filepath = LOG_BASE / method / filename
    
    if not filepath.exists():
        print(f"⚠️  파일 없음: {filepath}")
        return None
    
    print(f"📂 로딩: {method}/{filename}")
    
    data = {'p99': [], 'p50': [], 'snd_ratio': [], 'rtt': [], 'thr': []}
    
    with open(filepath, 'r') as f:
        for line in f:
            try:
                entry = json.loads(line)
                
                # metrics 안에 있는 경우 (대부분의 로그)
                if 'metrics' in entry:
                    metrics = entry['metrics']
                    kernel = entry.get('kernel', {})
                    
                    if metrics.get('p99_ms') is not None:
                        data['p99'].append(metrics['p99_ms'])
                        data['p50'].append(metrics.get('p50_ms', 0))
                        
                        # Throughput (None 처리)
                        thr = metrics.get('thr')
                        data['thr'].append(thr if thr is not None else 0)
                        
                        # Send buffer ratio
                        snd_ratio = kernel.get('snd_ratio', 0)
                        data['snd_ratio'].append(snd_ratio)
                        
                        # RTT (ms로 변환, None 처리)
                        rtt_us = kernel.get('ewma_rtt_us')
                        data['rtt'].append(rtt_us / 1000.0 if rtt_us is not None else 0)  # us -> ms
                
                # p99_ms 직접 있는 경우 (구형 로그)
                elif 'p99_ms' in entry:
                    data['p99'].append(entry.get('p99_ms', 0))
                    data['p50'].append(entry.get('p50_ms', 0))
                    data['thr'].append(entry.get('thr', 0))
                    data['snd_ratio'].append(0)  
                    data['rtt'].append(0)
                    
            except Exception as e:
                continue
    
    if not data['p99']:
        print(f"  ⚠️  데이터 없음: {method}/{filename}")
        return None
    
    # 디버그: 원본 데이터 통계
    orig_len = len(data['p99'])
    thr_nonzero = sum(1 for x in data['thr'] if x > 0)
    rtt_nonzero = sum(1 for x in data['rtt'] if x > 0)
    snd_nonzero = sum(1 for x in data['snd_ratio'] if x > 0)
    
    print(f"  ✓ {orig_len} entries - thr:{thr_nonzero}, rtt:{rtt_nonzero}, snd:{snd_nonzero}")
    
    # 중복 제거 (p99 기준으로 모든 메트릭 함께 제거)
    def remove_dup_all(data_dict):
        if not data_dict['p99']:
            return data_dict
        
        indices_to_keep = [0]  # 첫 번째는 항상 유지
        for i in range(1, len(data_dict['p99'])):
            # p99가 이전과 다르면 유지
            if data_dict['p99'][i] != data_dict['p99'][i-1]:
                indices_to_keep.append(i)
        
        # 모든 메트릭에 같은 인덱스 적용
        for key in data_dict:
            data_dict[key] = [data_dict[key][i] for i in indices_to_keep]
        
        return data_dict
    
    data = remove_dup_all(data)
    
    # 보간 (target_length가 지정된 경우만)
    current_len = len(data['p99'])
    if current_len < 4:
        return None
    
    if target_length and target_length != current_len:
        x_orig = np.linspace(0, 1, current_len)
        x_target = np.linspace(0, 1, target_length)
        
        for key in data:
            try:
                data[key] = np.interp(x_target, x_orig, data[key]).tolist()
            except:
                data[key] = [0] * target_length
    
    return data


def remove_spikes(data, metric, percentile=90, max_deviation=5.0):
    """스파이크 제거 - IQR 기반 + percentile 클리핑 (snd_ratio는 제외)"""
    values = np.array(data[metric])
    
    # snd_ratio는 스파이크 제거 안함 (정상 범위가 0~15까지 다양)
    if metric == 'snd_ratio':
        return values.tolist()
    
    # IQR 기반 outlier 제거
    q1 = np.percentile(values, 25)
    q3 = np.percentile(values, 75)
    iqr = q3 - q1
    upper_bound = q3 + max_deviation * iqr
    
    # Percentile 클리핑
    percentile_threshold = np.percentile(values, percentile)
    
    # 둘 중 더 큰 값을 threshold로 사용 (너무 많이 자르지 않도록)
    threshold = max(upper_bound, percentile_threshold)
    
    clipped = np.clip(values, 0, threshold)
    return clipped.tolist()


def plot_scenario_comparison_cached(scenario, cached_data):
    """시나리오별 메트릭 비교 그래프 (캐시된 데이터 사용)"""
    # Normal은 3개, 나머지는 4개 메트릭
    num_metrics = 3 if scenario == 'normal' else 4
    fig, axes = plt.subplots(num_metrics, 1, figsize=(12, 10 if num_metrics == 3 else 13))
    
    scenario_title = {
        'normal': 'Normal Network',
        'congestion': 'Congestion Network', 
        'dynamic': 'Dynamic Network'
    }
    
    fig.suptitle(f'Comparison - {scenario_title[scenario]}', 
                 fontsize=16, fontweight='bold', y=0.995)
    
    # P99 Latency
    ax_p99 = axes[0]
    ax_p99.set_ylabel('P99 Latency (ms)', fontsize=11, fontweight='bold')
    ax_p99.set_title('P99 Tail Latency', fontsize=12, loc='left', pad=10)
    ax_p99.grid(True, alpha=0.3, linestyle='--')
    
    # Normal이 아닌 경우만 Send Buffer Ratio 표시
    if scenario != 'normal':
        ax_snd = axes[1]
        ax_snd.set_ylabel('Send Buffer Ratio', fontsize=11, fontweight='bold')
        ax_snd.set_title('TCP Send Buffer Usage', fontsize=12, loc='left', pad=10)
        ax_snd.grid(True, alpha=0.3, linestyle='--')
        rtt_idx = 2
        thr_idx = 3
    else:
        rtt_idx = 1
        thr_idx = 2
    
    # RTT
    ax_rtt = axes[rtt_idx]
    ax_rtt.set_ylabel('RTT (ms)', fontsize=11, fontweight='bold')
    ax_rtt.set_title('Round Trip Time', fontsize=12, loc='left', pad=10)
    ax_rtt.grid(True, alpha=0.3, linestyle='--')
    
    # Throughput
    ax_thr = axes[thr_idx]
    ax_thr.set_ylabel('Throughput (msg/s)', fontsize=11, fontweight='bold')
    ax_thr.set_xlabel('Time (seconds)', fontsize=11, fontweight='bold')
    ax_thr.set_title('Message Throughput', fontsize=12, loc='left', pad=10)
    ax_thr.grid(True, alpha=0.3, linestyle='--')
    
    # 데이터 플롯
    for method, config in METHODS.items():
        data = cached_data.get((method, scenario))
        if data:
            time_axis = np.arange(len(data['p99']))
            
            # 모든 시나리오에 스파이크 제거 적용
            if scenario == 'normal':
                p99_plot = remove_spikes(data, 'p99', percentile=90)
                rtt_plot = remove_spikes(data, 'rtt', percentile=90)
                thr_plot = remove_spikes(data, 'thr', percentile=90)
                snd_plot = remove_spikes(data, 'snd_ratio', percentile=90)
            elif scenario == 'congestion':
                p99_plot = remove_spikes(data, 'p99', percentile=85)
                rtt_plot = remove_spikes(data, 'rtt', percentile=90)
                thr_plot = remove_spikes(data, 'thr', percentile=85)
                snd_plot = remove_spikes(data, 'snd_ratio', percentile=90)
            else:  # dynamic
                p99_plot = remove_spikes(data, 'p99', percentile=90)
                rtt_plot = remove_spikes(data, 'rtt', percentile=90)
                thr_plot = remove_spikes(data, 'thr', percentile=90)
                snd_plot = remove_spikes(data, 'snd_ratio', percentile=90)
            
            # EMQX와 RL의 처리량 상한선 2500으로 제한
            if method in ['emqx', 'rl']:
                thr_plot = np.clip(thr_plot, 0, 2500)
            
            # P99
            ax_p99.plot(time_axis, p99_plot,
                       label=config['name'],
                       color=config['color'],
                       linestyle=config['linestyle'],
                       linewidth=config['linewidth'],
                       alpha=0.8)
            
            # Send buffer ratio (Normal이 아닌 경우만)
            if scenario != 'normal':
                snd_smooth = np.convolve(snd_plot, np.ones(20)/20, mode='same')
                ax_snd.plot(time_axis, snd_smooth,
                           label=config['name'],
                           color=config['color'],
                           linestyle=config['linestyle'],
                           linewidth=config['linewidth'],
                           alpha=0.8)
            
            # RTT
            ax_rtt.plot(time_axis, rtt_plot,
                       label=config['name'],
                       color=config['color'],
                       linestyle=config['linestyle'],
                       linewidth=config['linewidth'],
                       alpha=0.8)
            
            # Throughput
            ax_thr.plot(time_axis, thr_plot,
                       label=config['name'],
                       color=config['color'],
                       linestyle=config['linestyle'],
                       linewidth=config['linewidth'],
                       alpha=0.8)
    
    # 범례 (P99에만 표시)
    ax_p99.legend(loc='upper right', fontsize=10, framealpha=0.9)
    
    plt.tight_layout()
    plt.savefig(f'timeseries_{scenario}.png', dpi=300, bbox_inches='tight')
    print(f"✓ timeseries_{scenario}.png")
    plt.close()


def plot_combined_summary_cached(cached_data):
    """전체 요약 그래프 (4x3 grid) - 캐시된 데이터 사용"""
    fig, axes = plt.subplots(4, 3, figsize=(18, 16))
    
    metrics = ['p99', 'snd_ratio', 'rtt', 'thr']
    metric_labels = ['P99 Latency (ms)', 'Send Buffer Ratio', 'RTT (ms)', 'Throughput (msg/s)']
    metric_titles = ['P99 Tail Latency', 'TCP Send Buffer Usage', 'Round Trip Time', 'Message Throughput']
    
    for col_idx, scenario in enumerate(SCENARIOS):
        scenario_title = scenario.capitalize()
        
        for row_idx, (metric, label, title) in enumerate(zip(metrics, metric_labels, metric_titles)):
            ax = axes[row_idx, col_idx]
            
            # 첫 번째 컬럼에만 y-label
            if col_idx == 0:
                ax.set_ylabel(label, fontsize=10, fontweight='bold')
            
            # 첫 번째 행에만 제목
            if row_idx == 0:
                ax.set_title(scenario_title, fontsize=12, fontweight='bold')
            
            # 마지막 행에만 x-label
            if row_idx == 3:
                ax.set_xlabel('Time (s)', fontsize=10)
            
            ax.grid(True, alpha=0.3, linestyle='--')
            
            # 데이터 플롯
            for method, config in METHODS.items():
                data = cached_data.get((method, scenario))
                if data:
                    time_axis = np.arange(len(data[metric]))
                    
                    plot_data = data[metric]
                    
                    # 모든 시나리오에 스파이크 제거
                    if scenario == 'normal':
                        plot_data = remove_spikes(data, metric, percentile=90)
                    elif scenario == 'congestion':
                        if metric in ['p99', 'thr']:
                            plot_data = remove_spikes(data, metric, percentile=85)
                        else:
                            plot_data = remove_spikes(data, metric, percentile=90)
                    else:  # dynamic
                        plot_data = remove_spikes(data, metric, percentile=90)
                    
                    # EMQX와 RL의 처리량 상한선 2500으로 제한
                    if method in ['emqx', 'rl'] and metric == 'thr':
                        plot_data = np.clip(plot_data, 0, 2500)
                    
                    if metric == 'snd_ratio':
                        # 스무딩만 적용 (범위는 자동)
                        plot_data = np.convolve(plot_data, np.ones(20)/20, mode='same')
                    
                    ax.plot(time_axis, plot_data,
                           label=config['name'],
                           color=config['color'],
                           linestyle=config['linestyle'],
                           linewidth=config['linewidth'] * 0.8,
                           alpha=0.8)
            
            # 범례 (첫 행 첫 열에만)
            if row_idx == 0 and col_idx == 2:
                ax.legend(loc='upper right', fontsize=8, framealpha=0.9)
    
    plt.tight_layout()
    plt.savefig('timeseries_all_combined.png', dpi=300, bbox_inches='tight')
    print("✓ timeseries_all_combined.png")
    plt.close()


def generate_statistics_table(cached_data):
    """통계 요약 테이블 (캐시된 데이터 사용)"""
    print("\n" + "="*90)
    print("시계열 분석 통계 요약")
    print("="*90)
    
    for scenario in SCENARIOS:
        print(f"\n【{scenario.upper()}】")
        print("-" * 90)
        print(f"{'Method':<15} {'P99 Mean':<12} {'P99 Std':<12} {'Snd Ratio':<12} {'RTT Mean':<12} {'Throughput':<12}")
        print("-" * 90)
        
        baseline_p99 = None
        for method, config in METHODS.items():
            data = cached_data.get((method, scenario))
            if data:
                p99_mean = np.mean(data['p99'])
                p99_std = np.std(data['p99'])
                snd_mean = np.mean(data['snd_ratio'])
                rtt_mean = np.mean(data['rtt'])
                thr_mean = np.mean(data['thr'])
                
                print(f"{config['name']:<15} {p99_mean:<12.1f} {p99_std:<12.1f} "
                      f"{snd_mean:<12.3f} {rtt_mean:<12.1f} {thr_mean:<12.1f}")
                
                if method == 'base':
                    baseline_p99 = p99_mean
                elif baseline_p99 and p99_mean > 0:
                    improvement = ((baseline_p99 - p99_mean) / baseline_p99) * 100
                    print(f"  → P99 Improvement: {improvement:+.1f}%")


def main():
    print("="*80)
    print("시계열 비교 그래프 생성 (4-way comparison)")
    print("="*80)
    
    # 데이터 캐시 (한 번만 로드)
    print("\n📥 데이터 로딩 중...")
    
    # 각 시나리오별로 가장 짧은 길이를 찾고 그 길이로 통일
    cached_data = {}
    
    for scenario in SCENARIOS:
        # 1단계: 원본 데이터 로드하여 최소 길이 찾기
        temp_data = {}
        min_length = float('inf')
        
        for method in METHODS.keys():
            data = load_and_interpolate(method, scenario, target_length=None)
            if data:
                temp_data[method] = data
                data_len = len(data['p99'])
                min_length = min(min_length, data_len)
        
        print(f"  → {scenario}: 최소 길이 = {min_length}")
        
        # 2단계: 최소 길이로 다시 로드 (앞부분만 사용)
        for method in METHODS.keys():
            data = load_and_interpolate(method, scenario, target_length=None)
            if data:
                # 최소 길이만큼만 자르기 (보간 없이)
                for key in data:
                    data[key] = data[key][:min_length]
                cached_data[(method, scenario)] = data
    
    print(f"\n✓ {len(cached_data)} 데이터셋 로드 완료\n")
    
    # 시나리오별 개별 그래프
    for scenario in SCENARIOS:
        plot_scenario_comparison_cached(scenario, cached_data)
    
    # 전체 요약 그래프
    plot_combined_summary_cached(cached_data)
    
    # 통계 테이블
    generate_statistics_table(cached_data)
    
    print("\n" + "="*80)
    print("✅ 모든 그래프 생성 완료!")
    print("="*80)
    print("\n생성된 파일:")
    print("  - timeseries_normal.png")
    print("  - timeseries_congestion.png")
    print("  - timeseries_dynamic.png")
    print("  - timeseries_all_combined.png")
    print("="*80)


if __name__ == "__main__":
    main()
