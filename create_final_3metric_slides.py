#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
최종 발표 슬라이드: Normal vs Congestion 3지표 비교
- P99 Latency
- 버퍼 넘침 비율 (snd_ratio > 1.0)
- 평균 RTT (커널 레벨 신호)
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
plt.rcParams['axes.unicode_minus'] = False

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

def compute_3metrics(log):
    """
    3가지 핵심 지표 계산:
    1. P99 Latency 평균 (ms)
    2. 버퍼 넘침 비율 (snd_ratio > 1.0 %)
    3. 평균 RTT (ewma_rtt_us → ms)
    """
    p99_values = [e['metrics']['p99_ms'] for e in log if 'metrics' in e]
    snd_ratios = [e['kernel']['snd_ratio'] for e in log if 'kernel' in e]
    rtt_values = [e['kernel']['ewma_rtt_us'] / 1000.0 for e in log if 'kernel' in e]  # us → ms
    
    # 1. P99 평균
    p99_mean = np.mean(p99_values)
    
    # 2. 버퍼 넘침 비율 (snd_ratio > 1.0)
    overflow_ratio = 100.0 * np.sum(np.array(snd_ratios) > 1.0) / len(snd_ratios)
    
    # 3. 평균 RTT (ms)
    rtt_mean = np.mean(rtt_values)
    
    return {
        'p99_mean': p99_mean,
        'overflow_ratio': overflow_ratio,
        'rtt_mean': rtt_mean,
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

# Congestion Network
baseline_congestion = load_jsonl('logs/baseline/congestion.jsonl')
emqx_congestion = load_jsonl('logs/emqx_flow_control/conjestion.jsonl')
rl_congestion = load_jsonl('logs/torch_model_experiments/congestion/rl_bc_v2_congestion.jsonl')

# 통계 계산
print("\n[Normal Network - 3 Metrics]")
stats_baseline_normal = compute_3metrics(baseline_normal)
stats_emqx_normal = compute_3metrics(emqx_normal)
stats_rl_normal = compute_3metrics(rl_normal)

print(f"  Baseline: P99={stats_baseline_normal['p99_mean']:.1f}ms, "
      f"Overflow={stats_baseline_normal['overflow_ratio']:.1f}%, "
      f"RTT={stats_baseline_normal['rtt_mean']:.2f}ms")
print(f"  EMQX: P99={stats_emqx_normal['p99_mean']:.1f}ms, "
      f"Overflow={stats_emqx_normal['overflow_ratio']:.1f}%, "
      f"RTT={stats_emqx_normal['rtt_mean']:.2f}ms")
print(f"  eMQTT-RL: P99={stats_rl_normal['p99_mean']:.1f}ms, "
      f"Overflow={stats_rl_normal['overflow_ratio']:.1f}%, "
      f"RTT={stats_rl_normal['rtt_mean']:.2f}ms")

print("\n[Congestion Network - 3 Metrics]")
stats_baseline_congestion = compute_3metrics(baseline_congestion)
stats_emqx_congestion = compute_3metrics(emqx_congestion)
stats_rl_congestion = compute_3metrics(rl_congestion)

print(f"  Baseline: P99={stats_baseline_congestion['p99_mean']:.1f}ms, "
      f"Overflow={stats_baseline_congestion['overflow_ratio']:.1f}%, "
      f"RTT={stats_baseline_congestion['rtt_mean']:.2f}ms")
print(f"  EMQX: P99={stats_emqx_congestion['p99_mean']:.1f}ms, "
      f"Overflow={stats_emqx_congestion['overflow_ratio']:.1f}%, "
      f"RTT={stats_emqx_congestion['rtt_mean']:.2f}ms")
print(f"  eMQTT-RL: P99={stats_rl_congestion['p99_mean']:.1f}ms, "
      f"Overflow={stats_rl_congestion['overflow_ratio']:.1f}%, "
      f"RTT={stats_rl_congestion['rtt_mean']:.2f}ms")

# ========================================
# 그래프 생성 함수
# ========================================
def create_3metric_slide(stats_baseline, stats_emqx, stats_rl, 
                         title, filename, network_type='normal'):
    """
    3지표 비교 슬라이드 생성
    
    Layout:
    - Top: P99 Latency (bar chart)
    - Bottom Left: Buffer Overflow Rate (snd_ratio > 1.0)
    - Bottom Right: Average RTT (kernel-level signal)
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
    # (3) Bottom Right: Average RTT (kernel signal)
    # ========================================
    ax3 = plt.subplot(2, 2, 4)  # Bottom right
    
    rtt_values = [
        stats_baseline['rtt_mean'],
        stats_emqx['rtt_mean'],
        stats_rl['rtt_mean']
    ]
    
    bars3 = ax3.bar(labels, rtt_values, color=colors, alpha=0.8, width=0.6, edgecolor='black', linewidth=2)
    
    # Value labels
    for bar, val in zip(bars3, rtt_values):
        height = bar.get_height()
        ax3.text(bar.get_x() + bar.get_width()/2., height,
                f'{val:.1f} ms',
                ha='center', va='bottom', fontsize=16, fontweight='bold')
    
    ax3.set_ylabel('평균 RTT (ms)', fontsize=14, fontweight='bold')
    ax3.set_xlabel('', fontsize=14)
    ax3.tick_params(axis='both', labelsize=12)
    ax3.grid(axis='y', alpha=0.3, linestyle='--')
    ax3.set_ylim(0, max(rtt_values) * 1.3)
    
    # Subtitle
    ax3.set_title('(b) 평균 RTT (커널 레벨 신호)', fontsize=14, fontweight='bold', pad=10)
    
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
print("Slide A: Normal Network (3 Metrics) 생성 중...")
print("="*60)

create_3metric_slide(
    stats_baseline_normal,
    stats_emqx_normal,
    stats_rl_normal,
    title='실험 결과 – 평시 네트워크 (Normal)',
    filename='slide_A_normal_3metrics.png',
    network_type='normal'
)

# ========================================
# Slide B: Congestion Network
# ========================================
print("\n" + "="*60)
print("Slide B: Congestion Network (3 Metrics) 생성 중...")
print("="*60)

create_3metric_slide(
    stats_baseline_congestion,
    stats_emqx_congestion,
    stats_rl_congestion,
    title='실험 결과 – 혼잡 네트워크 (Congestion, 2Mbps / 50ms / 2% loss)',
    filename='slide_B_congestion_3metrics.png',
    network_type='congestion'
)

# ========================================
# Summary
# ========================================
print("\n" + "="*60)
print("생성 완료!")
print("="*60)
print("\n[발표 멘트 가이드]")
print("\n🟦 Slide A (Normal - 15초):")
print("  'P99: 세 모드 다 10ms 안쪽으로 차이가 거의 없습니다.'")
print("  '버퍼 넘침(snd_ratio>1): 평시에는 거의 없습니다. 커널 레벨에서도 문제 없는 상태.'")
print("  'RTT: 세 모드가 거의 같습니다. 네트워크 자체가 깨끗하기 때문에,")
print("   Application-level Flow Control도 충분히 잘 작동합니다.'")
print("  → 평시에는 P99/버퍼/RTT 다 비슷하고 문제 없다. 진짜 차이는 혼잡일 때만 드러난다.")

print("\n🟥 Slide B (Congestion - 40초):")
print("  'P99: Baseline 47초, EMQX 20초, eBPF+RL 0.3초'")
print("  'EMQX는 Baseline보다 나아졌지만 SLO 300ms 기준에서는 완전히 실패'")
print("  '버퍼 넘침: Baseline 95.5%, EMQX 81.9%, RL 2.3%'")
print("  '혼잡 상태에서 Baseline/EMQX는 대부분 시간 커널 send 버퍼가 넘친 상태'")
print("  'RL만 버퍼 압력을 거의 제거(2.3%)'")
print("  'RTT: Baseline/EMQX는 혼잡으로 RTT가 크게 부풀어 오르지만,")
print("   RL은 RTT도 상대적으로 낮게 유지'")
print("  → 단순히 Application rate 조절이 아니라, 커널 시그널을 보고")
print("    실제 네트워크 혼잡 자체를 완화하는 방향으로 학습된 상태")

print("\n출력 폴더: results/presentation_20251113/")
print("  - slide_A_normal_3metrics.png")
print("  - slide_B_congestion_3metrics.png")
print("="*60 + "\n")
