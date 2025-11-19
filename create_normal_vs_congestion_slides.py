#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
발표 슬라이드 생성: Normal vs Congestion 3-way 비교
Slide A: Normal Network (평시)
Slide B: Congestion Network (혼잡)

레이아웃:
- 위: P99 Tail Latency (막대 그래프)
- 아래 왼쪽: 버퍼 넘침 비율 (snd_ratio > 1.0)
- 아래 오른쪽: SLO 준수율 (P99 < 300ms)
"""

import json
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

# ========================================
# 한글 폰트 설정
# ========================================
def setup_korean_font():
    """한글 폰트 설정 with fallback"""
    korean_fonts = [
        'NanumGothic',
        'Noto Sans CJK KR',
        'Malgun Gothic',
        'DejaVu Sans'
    ]
    
    available_fonts = [f.name for f in fm.fontManager.ttflist]
    
    for font_name in korean_fonts:
        if font_name in available_fonts:
            plt.rcParams['font.family'] = font_name
            print(f"[*] 폰트 설정: {font_name}")
            return
    
    # Fallback: TTF 파일 직접 로드
    font_paths = [
        '/usr/share/fonts/truetype/nanum/NanumGothic.ttf',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    ]
    
    for font_path in font_paths:
        if Path(font_path).exists():
            fm.fontManager.addfont(font_path)
            font_prop = fm.FontProperties(fname=font_path)
            plt.rcParams['font.family'] = font_prop.get_name()
            print(f"[*] 폰트 로드: {font_path}")
            return
    
    print("[!] 경고: 한글 폰트를 찾을 수 없습니다. 기본 폰트 사용")
    plt.rcParams['font.family'] = 'DejaVu Sans'

setup_korean_font()
plt.rcParams['axes.unicode_minus'] = False  # 마이너스 기호 깨짐 방지

# ========================================
# 데이터 로드 함수
# ========================================
def load_jsonl(path):
    """JSONL 파일 로드"""
    data = []
    with open(path, 'r') as f:
        for line in f:
            data.append(json.loads(line))
    return data

def compute_stats(log):
    """
    통계 계산:
    - P99 평균
    - snd_ratio > 1.0 비율 (%)
    - SLO 준수율 (P99 < 300ms 윈도우 비율, %)
    """
    p99_values = [e['metrics']['p99_ms'] for e in log if 'metrics' in e]
    snd_ratios = [e['kernel']['snd_ratio'] for e in log if 'kernel' in e]
    
    # P99 평균
    p99_mean = np.mean(p99_values)
    
    # snd_ratio > 1.0 비율
    overflow_ratio = 100.0 * np.sum(np.array(snd_ratios) > 1.0) / len(snd_ratios)
    
    # SLO 준수율 (P99 < 300ms)
    slo_compliance = 100.0 * np.sum(np.array(p99_values) < 300.0) / len(p99_values)
    
    return {
        'p99_mean': p99_mean,
        'overflow_ratio': overflow_ratio,
        'slo_compliance': slo_compliance,
        'n_samples': len(p99_values)
    }

# ========================================
# 데이터 로드
# ========================================
print("\n" + "="*60)
print("데이터 로드 중...")
print("="*60)

# Normal Network
baseline_normal = load_jsonl('logs/baseline/normal.jsonl')
emqx_normal = load_jsonl('logs/emqx_flow_control/normal.jsonl')
rl_normal = load_jsonl('logs/torch_model_experiments/normal/rl_torch_normal.jsonl')

# Congestion Network (기존 데이터)
baseline_congestion = load_jsonl('logs/baseline/congestion.jsonl')
emqx_congestion = load_jsonl('logs/emqx_flow_control/conjestion.jsonl')  # 오타 그대로
rl_congestion = load_jsonl('logs/torch_model_experiments/congestion/rl_bc_v2_congestion.jsonl')

# 통계 계산
print("\n[Normal Network]")
stats_baseline_normal = compute_stats(baseline_normal)
stats_emqx_normal = compute_stats(emqx_normal)
stats_rl_normal = compute_stats(rl_normal)

print(f"  Baseline: P99={stats_baseline_normal['p99_mean']:.1f}ms, "
      f"Overflow={stats_baseline_normal['overflow_ratio']:.1f}%, "
      f"SLO={stats_baseline_normal['slo_compliance']:.1f}%")
print(f"  EMQX: P99={stats_emqx_normal['p99_mean']:.1f}ms, "
      f"Overflow={stats_emqx_normal['overflow_ratio']:.1f}%, "
      f"SLO={stats_emqx_normal['slo_compliance']:.1f}%")
print(f"  eMQTT-RL: P99={stats_rl_normal['p99_mean']:.1f}ms, "
      f"Overflow={stats_rl_normal['overflow_ratio']:.1f}%, "
      f"SLO={stats_rl_normal['slo_compliance']:.1f}%")

print("\n[Congestion Network]")
stats_baseline_congestion = compute_stats(baseline_congestion)
stats_emqx_congestion = compute_stats(emqx_congestion)
stats_rl_congestion = compute_stats(rl_congestion)

print(f"  Baseline: P99={stats_baseline_congestion['p99_mean']:.1f}ms, "
      f"Overflow={stats_baseline_congestion['overflow_ratio']:.1f}%, "
      f"SLO={stats_baseline_congestion['slo_compliance']:.1f}%")
print(f"  EMQX: P99={stats_emqx_congestion['p99_mean']:.1f}ms, "
      f"Overflow={stats_emqx_congestion['overflow_ratio']:.1f}%, "
      f"SLO={stats_emqx_congestion['slo_compliance']:.1f}%")
print(f"  eMQTT-RL: P99={stats_rl_congestion['p99_mean']:.1f}ms, "
      f"Overflow={stats_rl_congestion['overflow_ratio']:.1f}%, "
      f"SLO={stats_rl_congestion['slo_compliance']:.1f}%")

# ========================================
# 그래프 생성 함수
# ========================================
def create_comparison_slide(stats_baseline, stats_emqx, stats_rl, 
                            title, filename, network_type='normal'):
    """
    3-way 비교 슬라이드 생성
    
    Layout:
    - Top: P99 Latency (bar chart)
    - Bottom Left: Buffer Overflow Rate (snd_ratio > 1.0)
    - Bottom Right: SLO Compliance Rate (P99 < 300ms)
    """
    
    fig = plt.figure(figsize=(16, 10))
    
    # Color scheme
    colors = ['#808080', '#e74c3c', '#2E86AB']  # Gray, Red, Blue
    labels = ['Baseline', 'EMQX', 'eMQTT-RL']
    
    # ========================================
    # (1) Top: P99 Latency
    # ========================================
    ax1 = plt.subplot(2, 2, (1, 2))  # Top span both columns
    
    p99_values = [
        stats_baseline['p99_mean'],
        stats_emqx['p99_mean'],
        stats_rl['p99_mean']
    ]
    
    # Normal: ms 단위, Congestion: 초 단위
    if network_type == 'normal':
        y_values = p99_values
        y_label = 'P99 Tail Latency (ms)'
        y_format = lambda x: f'{x:.1f} ms'
    else:  # congestion
        y_values = [v / 1000.0 for v in p99_values]  # ms → seconds
        y_label = 'P99 Tail Latency (seconds)'
        y_format = lambda x: f'{x:.1f} s'
    
    bars1 = ax1.bar(labels, y_values, color=colors, alpha=0.8, width=0.6, edgecolor='black', linewidth=2)
    
    # Value labels on bars
    for bar, val in zip(bars1, y_values):
        height = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width()/2., height,
                y_format(val),
                ha='center', va='bottom', fontsize=18, fontweight='bold')
    
    ax1.set_ylabel(y_label, fontsize=16, fontweight='bold')
    ax1.tick_params(axis='both', labelsize=14)
    ax1.grid(axis='y', alpha=0.3, linestyle='--')
    
    # Normal: 작은 스케일, Congestion: 큰 스케일
    if network_type == 'normal':
        ax1.set_ylim(0, max(y_values) * 1.3)
    else:
        ax1.set_ylim(0, max(y_values) * 1.2)
    
    # Title
    ax1.set_title(title, fontsize=20, fontweight='bold', pad=20)
    
    # ========================================
    # (2) Bottom Left: Buffer Overflow Rate (snd_ratio > 1.0)
    # ========================================
    ax2 = plt.subplot(2, 2, 3)  # Bottom left
    
    overflow_values = [
        stats_baseline['overflow_ratio'],
        stats_emqx['overflow_ratio'],
        stats_rl['overflow_ratio']
    ]
    
    bars2 = ax2.bar(labels, overflow_values, color=colors, alpha=0.8, width=0.6, edgecolor='black', linewidth=2)
    
    # Value labels
    for bar, val in zip(bars2, overflow_values):
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height,
                f'{val:.1f}%',
                ha='center', va='bottom', fontsize=16, fontweight='bold')
    
    ax2.set_ylabel('버퍼 넘침 비율 (%)', fontsize=14, fontweight='bold')
    ax2.set_xlabel('', fontsize=14)
    ax2.tick_params(axis='both', labelsize=12)
    ax2.grid(axis='y', alpha=0.3, linestyle='--')
    ax2.set_ylim(0, max(overflow_values) * 1.3 if max(overflow_values) > 0 else 10)
    
    # Subtitle
    ax2.set_title('(a) 버퍼 넘침 비율 (snd_ratio > 1.0)', fontsize=14, fontweight='bold', pad=10)
    
    # ========================================
    # (3) Bottom Right: SLO Compliance Rate (P99 < 300ms)
    # ========================================
    ax3 = plt.subplot(2, 2, 4)  # Bottom right
    
    slo_values = [
        stats_baseline['slo_compliance'],
        stats_emqx['slo_compliance'],
        stats_rl['slo_compliance']
    ]
    
    bars3 = ax3.bar(labels, slo_values, color=colors, alpha=0.8, width=0.6, edgecolor='black', linewidth=2)
    
    # Value labels
    for bar, val in zip(bars3, slo_values):
        height = bar.get_height()
        ax3.text(bar.get_x() + bar.get_width()/2., height,
                f'{val:.1f}%',
                ha='center', va='bottom', fontsize=16, fontweight='bold')
    
    ax3.set_ylabel('SLO 준수율 (%)', fontsize=14, fontweight='bold')
    ax3.set_xlabel('', fontsize=14)
    ax3.tick_params(axis='both', labelsize=12)
    ax3.grid(axis='y', alpha=0.3, linestyle='--')
    ax3.set_ylim(0, 105)  # 0-100% + margin
    
    # Subtitle
    ax3.set_title('(b) SLO 준수율 (P99 < 300ms)', fontsize=14, fontweight='bold', pad=10)
    
    plt.tight_layout()
    
    # Save
    output_dir = Path('results/presentation_20251113')
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename
    
    plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
    print(f"\n[*] 저장: {output_path} ({output_path.stat().st_size / 1024:.0f} KB)")
    plt.close()

# ========================================
# Slide A: Normal Network
# ========================================
print("\n" + "="*60)
print("Slide A: Normal Network 생성 중...")
print("="*60)

create_comparison_slide(
    stats_baseline_normal,
    stats_emqx_normal,
    stats_rl_normal,
    title='실험 결과 – 평시 네트워크 (Normal)',
    filename='slide_A_normal_network.png',
    network_type='normal'
)

# ========================================
# Slide B: Congestion Network
# ========================================
print("\n" + "="*60)
print("Slide B: Congestion Network 생성 중...")
print("="*60)

create_comparison_slide(
    stats_baseline_congestion,
    stats_emqx_congestion,
    stats_rl_congestion,
    title='실험 결과 – 혼잡 네트워크 (Congestion, 2Mbps / 50ms / 2% loss)',
    filename='slide_B_congestion_network.png',
    network_type='congestion'
)

# ========================================
# Summary
# ========================================
print("\n" + "="*60)
print("생성 완료!")
print("="*60)
print("\n[발표 멘트 가이드]")
print("\n🟦 Slide A (Normal - 10-15초):")
print("  '평시에는 세 모드 모두 P99가 10ms 안쪽이라 사실상 차이가 없다.'")
print("  '버퍼 넘침도 거의 없고, SLO도 대부분 만족한다.'")
print("  '즉, 평시에는 Application-level만으로도 충분하다.'")
print("  '진짜 문제는 혼잡일 때.'")

print("\n🟥 Slide B (Congestion - 30-40초):")
print("  'P99: Baseline 47초, EMQX 20초, eMQTT-RL 0.3초'")
print("  'EMQX는 Baseline보다 나아졌지만 SLO 300ms 기준에서는 완전히 실패'")
print("  '버퍼 넘침: Baseline 95.5%, EMQX 81.9%, eMQTT-RL 2.3%'")
print("  '혼잡 상태에서 Baseline/EMQX는 거의 항상 버퍼가 꽉 찬 상태'")
print("  'eMQTT-RL만 평시와 거의 동일한 수준으로 버퍼 넘침 제거'")
print("  'SLO 준수율: Baseline/EMQX는 거의 0%, eMQTT-RL만 24%'")
print("  '→ Application-level Flow Control만으로는 혼잡에서 SLO 수준 Tail 제어가 구조적으로 불가능'")

print("\n출력 폴더: results/presentation_20251113/")
print("  - slide_A_normal_network.png")
print("  - slide_B_congestion_network.png")
print("="*60 + "\n")
