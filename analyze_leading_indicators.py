#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
커널 지표가 P99 Latency의 선행 지표(Leading Indicator)인지 분석
"""

import json
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from pathlib import Path

# 한글 폰트 설정
def setup_korean_font():
    korean_fonts = ['NanumGothic', 'Noto Sans CJK KR', 'Malgun Gothic']
    available_fonts = [f.name for f in fm.fontManager.ttflist]
    
    for font_name in korean_fonts:
        if font_name in available_fonts:
            plt.rcParams['font.family'] = font_name
            print(f"[*] 폰트 설정: {font_name}")
            return
    
    font_paths = ['/usr/share/fonts/truetype/nanum/NanumGothic.ttf']
    for font_path in font_paths:
        if Path(font_path).exists():
            fm.fontManager.addfont(font_path)
            font_prop = fm.FontProperties(fname=font_path)
            plt.rcParams['font.family'] = font_prop.get_name()
            print(f"[*] 폰트 로드: {font_path}")
            return
    
    print("[!] 한글 폰트 없음, 기본 폰트 사용")

setup_korean_font()
plt.rcParams['axes.unicode_minus'] = False

def load_jsonl(path):
    data = []
    with open(path, 'r') as f:
        for line in f:
            data.append(json.loads(line))
    return data

def extract_metrics(log):
    """시계열 데이터 추출"""
    times = []
    p99s = []
    snd_ratios = []
    rtts = []
    congestion_scores = []
    
    for i, e in enumerate(log):
        if 'metrics' not in e or 'kernel' not in e:
            continue
        
        times.append(i * 2)  # 2초 간격
        p99s.append(e['metrics'].get('p99_ms', 0))
        snd_ratios.append(e['kernel'].get('snd_ratio', 0))
        rtts.append(e['kernel'].get('ewma_rtt_us', 0) / 1000.0)  # ms
        congestion_scores.append(e['kernel'].get('congestion_score', 0))
    
    return np.array(times), np.array(p99s), np.array(snd_ratios), np.array(rtts), np.array(congestion_scores)

def find_p99_spikes(times, p99s, threshold=300):
    """P99 급증 시점 찾기"""
    spikes = []
    for i in range(1, len(p99s)):
        # P99가 threshold를 넘는 순간
        if p99s[i] >= threshold and p99s[i-1] < threshold:
            spikes.append((i, times[i]))
    return spikes

def analyze_leading_indicators(log_path):
    """선행 지표 분석"""
    print(f"[*] 분석 중: {log_path}")
    log = load_jsonl(log_path)
    times, p99s, snd_ratios, rtts, congestion_scores = extract_metrics(log)
    
    # P99 급증 시점 찾기
    spikes = find_p99_spikes(times, p99s, threshold=300)
    print(f"[*] P99 >= 300ms 급증 시점: {len(spikes)}개 발견")
    
    # 각 급증 시점에 대해 분석
    for idx, (spike_idx, spike_time) in enumerate(spikes[:3]):  # 처음 3개만
        print(f"\n=== Spike #{idx+1} at {spike_time:.0f}s (index {spike_idx}) ===")
        
        # 10초 전부터 10초 후까지 확인
        before = max(0, spike_idx - 5)  # 5 steps = 10초 전
        after = min(len(p99s), spike_idx + 5)
        
        print(f"  P99 변화:")
        print(f"    10초 전: {p99s[before]:.1f}ms")
        print(f"    급증 시점: {p99s[spike_idx]:.1f}ms")
        
        print(f"  snd_ratio 변화:")
        print(f"    10초 전: {snd_ratios[before]:.3f}")
        print(f"    급증 시점: {snd_ratios[spike_idx]:.3f}")
        
        print(f"  RTT 변화:")
        print(f"    10초 전: {rtts[before]:.1f}ms")
        print(f"    급증 시점: {rtts[spike_idx]:.1f}ms")
        
        print(f"  congestion_score 변화:")
        print(f"    10초 전: {congestion_scores[before]:.3f}")
        print(f"    급증 시점: {congestion_scores[spike_idx]:.3f}")
    
    # 전체 시계열 그래프는 생략하고 확대 그래프만 생성
    print(f"\n[*] 전체 그래프 생략, 확대 그래프 생성 시작...")
    
    # 1. 산점도(Scatter Plot) 생성 - 커널 지표와 P99의 상관관계 규명
    create_scatter_plot(p99s, snd_ratios, rtts, congestion_scores)
    
    # 3. 구간별 영향 분석 (Impact Analysis) - 커널 지표가 지연에 미치는 영향
    analyze_impact(p99s, snd_ratios, rtts, congestion_scores)
    
    # 4. 각 Spike 주변 확대 그래프 생성 (임계값 기반으로 시작점 탐지)
    spikes_threshold = find_p99_spikes_threshold(times, p99s, threshold=100)
    print(f"[*] P99 급증 시작점(100ms 돌파): {len(spikes_threshold)}개 발견")

    for idx, (spike_idx, spike_time) in enumerate(spikes_threshold[:5], 1):  # 처음 5개
        create_zoomed_plot(times, p99s, snd_ratios, rtts, congestion_scores, 
                          spike_idx, spike_time, idx)
    
    return times, p99s, snd_ratios, rtts, congestion_scores

def analyze_impact(p99s, snd_ratios, rtts, congestion_scores):
    """커널 지표 구간별 P99 평균 분석 (Impact Analysis)"""
    fig, axes = plt.subplots(1, 2, figsize=(16, 7))
    
    # 1. snd_ratio 구간별 P99
    bins = np.linspace(0, 0.2, 11)
    bin_indices = np.digitize(snd_ratios, bins)
    
    bin_means = []
    bin_labels = []
    bin_counts = []
    
    for i in range(1, len(bins)):
        mask = bin_indices == i
        count = np.sum(mask)
        bin_counts.append(count)
        if count > 0:
            mean_p99 = np.mean(p99s[mask])
            bin_means.append(mean_p99)
        else:
            bin_means.append(0)
        bin_labels.append(f'{bins[i-1]:.2f}~{bins[i]:.2f}')
            
    bars = axes[0].bar(bin_labels, bin_means, color='green', alpha=0.7, edgecolor='black')
    axes[0].set_xlabel('송신 버퍼 비율 (snd_ratio)', fontweight='bold', fontsize=12)
    axes[0].set_ylabel('평균 P99 지연시간 (ms)', fontweight='bold', fontsize=12)
    axes[0].set_title('송신 버퍼 증가에 따른 지연시간 폭발', fontweight='bold', fontsize=14)
    axes[0].tick_params(axis='x', rotation=45)
    axes[0].grid(axis='y', alpha=0.3)
    
    # 막대 위에 샘플 수 표시
    for bar, count in zip(bars, bin_counts):
        if count > 0:
            height = bar.get_height()
            axes[0].text(bar.get_x() + bar.get_width()/2., height,
                        f'n={count}',
                        ha='center', va='bottom', fontsize=9, color='black')
    
    # 추세선 추가
    x_idx = np.arange(len(bin_means))
    valid_idx = np.array([i for i, m in enumerate(bin_means) if m > 0])
    if len(valid_idx) > 1:
        z = np.polyfit(valid_idx, np.array(bin_means)[valid_idx], 2)
        p = np.poly1d(z)
        axes[0].plot(x_idx, p(x_idx), 'r--', linewidth=2, label='추세선')
        axes[0].legend()

    # 2. RTT 구간별 P99
    rtt_bins = np.linspace(0, 150, 11)
    rtt_indices = np.digitize(rtts, rtt_bins)
    
    rtt_means = []
    rtt_labels = []
    rtt_counts = []
    
    for i in range(1, len(rtt_bins)):
        mask = rtt_indices == i
        count = np.sum(mask)
        rtt_counts.append(count)
        if count > 0:
            mean_p99 = np.mean(p99s[mask])
            rtt_means.append(mean_p99)
        else:
            rtt_means.append(0)
        rtt_labels.append(f'{rtt_bins[i-1]:.0f}~{rtt_bins[i]:.0f}')
            
    bars = axes[1].bar(rtt_labels, rtt_means, color='orange', alpha=0.7, edgecolor='black')
    axes[1].set_xlabel('RTT (ms)', fontweight='bold', fontsize=12)
    axes[1].set_ylabel('평균 P99 지연시간 (ms)', fontweight='bold', fontsize=12)
    axes[1].set_title('RTT 증가에 따른 지연시간 폭발', fontweight='bold', fontsize=14)
    axes[1].tick_params(axis='x', rotation=45)
    axes[1].grid(axis='y', alpha=0.3)
    
    # 막대 위에 샘플 수 표시
    for bar, count in zip(bars, rtt_counts):
        if count > 0:
            height = bar.get_height()
            axes[1].text(bar.get_x() + bar.get_width()/2., height,
                        f'n={count}',
                        ha='center', va='bottom', fontsize=9, color='black')
    
    # 추세선
    x_idx = np.arange(len(rtt_means))
    valid_idx = np.array([i for i, m in enumerate(rtt_means) if m > 0])
    if len(valid_idx) > 1:
        z = np.polyfit(valid_idx, np.array(rtt_means)[valid_idx], 2)
        p = np.poly1d(z)
        axes[1].plot(x_idx, p(x_idx), 'r--', linewidth=2, label='추세선')
        axes[1].legend()
    
    plt.suptitle('커널 지표가 지연시간(Latency)에 미치는 영향 분석 (RL 제어 환경)', fontsize=16, fontweight='bold')
    plt.tight_layout()
    
    output_path = 'results/impact_analysis.png'
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"[*] 저장: {output_path}")

def find_p99_spikes_threshold(times, p99s, threshold=100):
    """P99가 threshold를 돌파하는 시점 찾기"""
    spikes = []
    # 쿨다운: 한 번 찾으면 20초간 건너뜀
    last_spike_time = -100
    
    for i in range(1, len(p99s)):
        # 이전엔 낮았는데 지금 높아진 경우 (상승 엣지)
        if p99s[i-1] < threshold and p99s[i] >= threshold:
            if times[i] - last_spike_time > 20:
                spikes.append((i, times[i]))
                last_spike_time = times[i]
                
    return spikes

def create_scatter_plot(p99s, snd_ratios, rtts, congestion_scores):
    """커널 지표 vs P99 상관관계 산점도"""
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    
    # 1. snd_ratio vs P99
    axes[0].scatter(snd_ratios, p99s, alpha=0.3, color='g', s=10)
    axes[0].axhline(y=300, color='r', linestyle='--', label='SLO (300ms)')
    axes[0].set_xlabel('송신 버퍼 비율 (snd_ratio)', fontweight='bold', fontsize=12)
    axes[0].set_ylabel('P99 지연시간 (ms)', fontweight='bold', fontsize=12)
    axes[0].set_title('송신 버퍼 vs P99', fontweight='bold', fontsize=14)
    axes[0].grid(alpha=0.3)
    
    # 2. RTT vs P99
    axes[1].scatter(rtts, p99s, alpha=0.3, color='orange', s=10)
    axes[1].axhline(y=300, color='r', linestyle='--', label='SLO (300ms)')
    axes[1].set_xlabel('RTT (ms)', fontweight='bold', fontsize=12)
    axes[1].set_ylabel('P99 지연시간 (ms)', fontweight='bold', fontsize=12)
    axes[1].set_title('RTT vs P99', fontweight='bold', fontsize=14)
    axes[1].grid(alpha=0.3)
    
    # 3. Congestion Score vs P99
    axes[2].scatter(congestion_scores, p99s, alpha=0.3, color='purple', s=10)
    axes[2].axhline(y=300, color='r', linestyle='--', label='SLO (300ms)')
    axes[2].set_xlabel('혼잡도 점수', fontweight='bold', fontsize=12)
    axes[2].set_ylabel('P99 지연시간 (ms)', fontweight='bold', fontsize=12)
    axes[2].set_title('혼잡도 vs P99', fontweight='bold', fontsize=14)
    axes[2].grid(alpha=0.3)
    
    plt.suptitle('커널 지표와 P99 지연시간의 상관관계 분석', fontsize=16, fontweight='bold')
    plt.tight_layout()
    
    output_path = 'results/correlation_scatter.png'
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"[*] 저장: {output_path}")

def create_zoomed_plot(times, p99s, snd_ratios, rtts, congestion_scores, 
                       spike_idx, spike_time, spike_num):
    """특정 Spike 주변 ±15초 확대 그래프"""
    # 시간 범위 설정 (±15초)
    time_window = 15
    start_time = max(0, spike_time - time_window)
    end_time = spike_time + time_window
    
    # 해당 범위 데이터 추출
    mask = (times >= start_time) & (times <= end_time)
    t_zoom = times[mask]
    p99_zoom = p99s[mask]
    snd_zoom = snd_ratios[mask]
    rtt_zoom = rtts[mask]
    cong_zoom = congestion_scores[mask]
    
    if len(t_zoom) == 0:
        return
    
    # 그래프 생성
    fig, axes = plt.subplots(4, 1, figsize=(10, 12), sharex=True)
    
    # 관찰 구간 (Spike 이전 10초) 강조
    observe_start = spike_time - 10
    observe_end = spike_time
    
    for ax in axes:
        # 선행 지표 관찰 구간 표시 (노란색 배경)
        ax.axvspan(observe_start, observe_end, color='yellow', alpha=0.1, label='상승 전조 구간 (10초 전)')
        ax.axvline(x=spike_time, color='red', linestyle='--', linewidth=2, alpha=0.8, label='P99 급상승 시작점')

    # P99
    axes[0].plot(t_zoom, p99_zoom, 'b-', linewidth=3, marker='o', markersize=6, label='P99')
    axes[0].axhline(y=300, color='orange', linestyle='--', linewidth=2, label='SLO (300ms)')
    axes[0].set_ylabel('P99 지연시간 (ms)', fontweight='bold', fontsize=12)
    axes[0].grid(alpha=0.4)
    axes[0].legend(loc='upper left', fontsize=10)
    axes[0].set_title(f'급상승 #{spike_num} 주변 확대 분석 (±{time_window}초)', fontsize=14, fontweight='bold')
    
    # snd_ratio
    axes[1].plot(t_zoom, snd_zoom, 'g-', linewidth=3, marker='o', markersize=6, label='snd_ratio')
    axes[1].axhline(y=1.0, color='orange', linestyle='--', linewidth=2)
    axes[1].set_ylabel('송신 버퍼 비율', fontweight='bold', fontsize=12)
    axes[1].grid(alpha=0.4)
    axes[1].legend(loc='upper left', fontsize=10)
    
    # RTT
    axes[2].plot(t_zoom, rtt_zoom, 'orange', linewidth=3, marker='o', markersize=6, label='RTT')
    axes[2].set_ylabel('RTT (ms)', fontweight='bold', fontsize=12)
    axes[2].grid(alpha=0.4)
    axes[2].legend(loc='upper left', fontsize=10)
    
    # congestion_score
    axes[3].plot(t_zoom, cong_zoom, 'purple', linewidth=3, marker='o', markersize=6, label='Congestion Score')
    axes[3].set_ylabel('혼잡도 점수', fontweight='bold', fontsize=12)
    axes[3].set_xlabel('시간 (초)', fontweight='bold', fontsize=12)
    axes[3].grid(alpha=0.4)
    axes[3].legend(loc='upper left', fontsize=10)
    
    plt.tight_layout()
    
    output_path = f'results/spike_{spike_num}_zoom.png'
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"[*] 저장: {output_path}")
    plt.close()

if __name__ == '__main__':
    # PPO baseline 로그 분석
    log_path = 'logs/baseline/high_res.jsonl'
    analyze_leading_indicators(log_path)
