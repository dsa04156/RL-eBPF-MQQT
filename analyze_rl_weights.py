#!/usr/bin/env python3
"""
RL 에이전트가 사용하는 지표별 가중치 분석
baseline congestion 로그 기반으로 어떤 신호에 가중치를 많이 주는지 확인
"""

import json
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
import matplotlib.font_manager as fm

# ========================================
# 폰트 설정
# ========================================
def setup_korean_font():
    font_candidates = [
        'NanumGothic',
        'NanumBarunGothic', 
        'Malgun Gothic',
        'AppleGothic',
        'Noto Sans KR',
        'DejaVu Sans'
    ]
    
    available_fonts = [f.name for f in fm.fontManager.ttflist]
    
    for font_name in font_candidates:
        if any(font_name.lower() in f.lower() for f in available_fonts):
            plt.rcParams['font.family'] = font_name
            plt.rcParams['axes.unicode_minus'] = False
            print(f"[*] 폰트 설정: {font_name}")
            return
    
    print("[!] 한글 폰트를 찾지 못했습니다. 기본 폰트 사용")

setup_korean_font()

print("\n" + "="*70)
print("RL 에이전트 가중치 분석")
print("="*70)

print("\n【 보상 함수 구조 (코드 분석) 】")
print("\n1️⃣ 페널티 (Penalty) - 높을수록 나쁨")
print("-" * 70)
print("  지표                          가중치    설명")
print("-" * 70)
print("  RTT 정규화 (rtt_norm)          1.6     SLO 대비 RTT 비율")
print("  큐 압력 (queue_pressure)       1.0     tanh(max(snd,rcv)/2)")
print("  snd 버퍼 압력 (snd_pen)        0.8     snd_ratio>1: (sr-1)*10+1")
print("  rcv 버퍼 압력 (rcv_pen)        0.6     tanh(max(rcv-0.4, 0))")
print("  재전송 발생 (retrans_pen)      0.6     1 if 재전송 else 0")
print("  처리량 부족 (thr_penalty)      ?       1 - (thr/target)")
print("  P99 초과 (p99_penalty)         ?       (p99-SLO)/SLO if >SLO")
print("  고압력 추가벌점                0.3     if queue>0.6 or snd>0.8")
print("-" * 70)
print("  → 총 Penalty = Σ(가중치 × 정규화값)")

print("\n2️⃣ 보너스 (Bonus) - 높을수록 좋음")
print("-" * 70)
print("  지표                          가중치    설명")
print("-" * 70)
print("  유효 전송률 (eff_rate_norm)    0.35    thr/target (0~2.5)")
print("  낮은 큐압력 (low_queue_bonus)  0.25    1 - queue_pressure")
print("  낮은 snd압력 (1-snd_pen)       0.20    1 - snd_pen")
print("  낮은 rcv압력 (1-rcv_pen)       0.20    1 - rcv_pen")
print("  처리량 보너스 (thr_bonus)      ?       조건부")
print("  절대처리량 (abs_thr_bonus)     ?       min(thr/scale, 2.0)")
print("-" * 70)
print("  → 총 Bonus = Σ(가중치 × 정규화값)")

print("\n3️⃣ 최종 보상")
print("-" * 70)
print("  reward = -Penalty + Bonus")
print("="*70)

# ========================================
# 실제 데이터로 가중치 영향 분석
# ========================================
print("\n\n【 실제 데이터 분석 】")
print("="*70)

with open('logs/baseline/congestion.jsonl', 'r') as f:
    data = [json.loads(line) for line in f if line.strip()]

print(f"로드된 샘플: {len(data)}개")

# 지표 추출
rtt_values = []
snd_values = []
rcv_values = []
retrans_values = []
queue_values = []
p99_values = []

for entry in data:
    if 'kernel' not in entry:
        continue
    k = entry['kernel']
    
    rtt_values.append(k.get('ewma_rtt_us', 0))
    snd_values.append(k.get('snd_ratio', 0))
    rcv_values.append(k.get('rcv_ratio', 0))
    retrans_values.append(1.0 if k.get('had_retrans', False) else 0.0)
    queue_values.append(k.get('congestion_score', 0))
    
    if 'metrics' in entry:
        p99_values.append(entry['metrics'].get('p99_ms', 0))

rtt_values = np.array(rtt_values)
snd_values = np.array(snd_values)
rcv_values = np.array(rcv_values)
retrans_values = np.array(retrans_values)
queue_values = np.array(queue_values)
p99_values = np.array(p99_values)

print(f"\n[지표 통계]")
print(f"  RTT (us):         평균={rtt_values.mean():.0f}, 범위={rtt_values.min():.0f}~{rtt_values.max():.0f}")
print(f"  snd_ratio:        평균={snd_values.mean():.3f}, 범위={snd_values.min():.3f}~{snd_values.max():.3f}")
print(f"  rcv_ratio:        평균={rcv_values.mean():.3f}, 범위={rcv_values.min():.3f}~{rcv_values.max():.3f}")
print(f"  재전송 비율:       {retrans_values.mean()*100:.1f}%")
print(f"  queue_pressure:   평균={queue_values.mean():.3f}, 범위={queue_values.min():.3f}~{queue_values.max():.3f}")
print(f"  P99 (ms):         평균={p99_values.mean():.0f}, 범위={p99_values.min():.0f}~{p99_values.max():.0f}")

# ========================================
# 가중치 영향 계산
# ========================================
SLO_P99_MS = 300
import math

# Penalty 계산
rtt_norm = np.minimum(rtt_values / (SLO_P99_MS * 1000.0), 10.0)
queue_pen = queue_values

snd_pen = np.where(snd_values > 1.0, 
                    (snd_values - 1.0) * 10.0 + 1.0,
                    np.tanh(np.maximum(0.0, snd_values - 0.4)))

rcv_pen = np.tanh(np.maximum(0.0, rcv_values - 0.4))
retrans_pen = retrans_values

# 가중치 적용
rtt_contribution = 1.6 * rtt_norm
queue_contribution = 1.0 * queue_pen
snd_contribution = 0.8 * snd_pen
rcv_contribution = 0.6 * rcv_pen
retrans_contribution = 0.6 * retrans_pen

# 전체 페널티
total_penalty = (rtt_contribution + queue_contribution + snd_contribution + 
                 rcv_contribution + retrans_contribution)

print(f"\n[페널티 기여도 평균]")
print(f"  RTT (1.6x):           {rtt_contribution.mean():.3f}")
print(f"  Queue (1.0x):         {queue_contribution.mean():.3f}")
print(f"  snd_ratio (0.8x):     {snd_contribution.mean():.3f}")
print(f"  rcv_ratio (0.6x):     {rcv_contribution.mean():.3f}")
print(f"  Retrans (0.6x):       {retrans_contribution.mean():.3f}")
print(f"  총 페널티:             {total_penalty.mean():.3f}")

# ========================================
# 그래프 생성
# ========================================
print("\n\n【 그래프 생성 중... 】")

fig = plt.figure(figsize=(16, 12))

# Overall layout: 2x2 + bottom full-width
gs = fig.add_gridspec(3, 2, height_ratios=[1, 1, 1.2], hspace=0.35, wspace=0.3)

# ========================================
# Panel 1: 가중치 비교 (Bar chart)
# ========================================
ax1 = fig.add_subplot(gs[0, 0])

weights = [1.6, 1.0, 0.8, 0.6, 0.6]
labels = ['RTT\n(1.6x)', 'Queue\n(1.0x)', 'snd_ratio\n(0.8x)', 'rcv_ratio\n(0.6x)', 'Retrans\n(0.6x)']
colors_w = ['#e74c3c', '#f39c12', '#3498db', '#9b59b6', '#2ecc71']

bars = ax1.bar(labels, weights, color=colors_w, alpha=0.7, edgecolor='black', linewidth=2)
ax1.set_ylabel('페널티 가중치', fontsize=12, fontweight='bold')
ax1.set_title('(a) 페널티 가중치 비교', fontsize=13, fontweight='bold')
ax1.grid(alpha=0.3, linestyle='--', axis='y')

# Add values on bars
for bar, w in zip(bars, weights):
    height = bar.get_height()
    ax1.text(bar.get_x() + bar.get_width()/2., height + 0.05,
             f'{w:.1f}',
             ha='center', va='bottom', fontsize=11, fontweight='bold')

# ========================================
# Panel 2: 실제 기여도 (Pie chart)
# ========================================
ax2 = fig.add_subplot(gs[0, 1])

contributions = [
    rtt_contribution.mean(),
    queue_contribution.mean(),
    snd_contribution.mean(),
    rcv_contribution.mean(),
    retrans_contribution.mean()
]
labels_pie = ['RTT', 'Queue', 'snd_ratio', 'rcv_ratio', 'Retrans']

wedges, texts, autotexts = ax2.pie(contributions, labels=labels_pie, colors=colors_w,
                                     autopct='%1.1f%%', startangle=90,
                                     textprops={'fontsize': 11, 'fontweight': 'bold'})
ax2.set_title('(b) 실제 페널티 기여도 비율', fontsize=13, fontweight='bold')

# ========================================
# Panel 3: 시계열 - 페널티 구성
# ========================================
ax3 = fig.add_subplot(gs[1, :])

time_points = np.arange(len(rtt_contribution)) * 2.0

ax3.fill_between(time_points, 0, rtt_contribution, 
                 color=colors_w[0], alpha=0.6, label='RTT (1.6x)')
ax3.fill_between(time_points, rtt_contribution, 
                 rtt_contribution + queue_contribution,
                 color=colors_w[1], alpha=0.6, label='Queue (1.0x)')
ax3.fill_between(time_points, rtt_contribution + queue_contribution,
                 rtt_contribution + queue_contribution + snd_contribution,
                 color=colors_w[2], alpha=0.6, label='snd_ratio (0.8x)')
ax3.fill_between(time_points, 
                 rtt_contribution + queue_contribution + snd_contribution,
                 rtt_contribution + queue_contribution + snd_contribution + rcv_contribution,
                 color=colors_w[3], alpha=0.6, label='rcv_ratio (0.6x)')
ax3.fill_between(time_points,
                 rtt_contribution + queue_contribution + snd_contribution + rcv_contribution,
                 total_penalty,
                 color=colors_w[4], alpha=0.6, label='Retrans (0.6x)')

ax3.set_xlabel('시간 (초)', fontsize=12, fontweight='bold')
ax3.set_ylabel('누적 페널티', fontsize=12, fontweight='bold')
ax3.set_title('(c) 시계열: 페널티 구성 요소 (Stacked)', fontsize=13, fontweight='bold')
ax3.legend(loc='upper left', fontsize=10)
ax3.grid(alpha=0.3, linestyle='--', axis='y')

# ========================================
# Panel 4: 지표별 시계열
# ========================================
ax4 = fig.add_subplot(gs[2, :])

# Normalize for comparison
rtt_norm_plot = rtt_values / rtt_values.max()
snd_norm_plot = snd_values / max(snd_values.max(), 1.0)
queue_norm_plot = queue_values / max(queue_values.max(), 1.0)

ax4.plot(time_points, rtt_norm_plot, color=colors_w[0], linewidth=2.5, 
         alpha=0.8, label='RTT (정규화)')
ax4.plot(time_points, snd_norm_plot, color=colors_w[2], linewidth=2.5, 
         alpha=0.8, label='snd_ratio (정규화)')
ax4.plot(time_points, queue_norm_plot, color=colors_w[1], linewidth=2.5, 
         alpha=0.8, label='queue_pressure (정규화)')
ax4.axhline(y=0.3, color='red', linestyle='--', linewidth=2, alpha=0.6,
            label='임계값 예시 (0.3)')

ax4.set_xlabel('시간 (초)', fontsize=12, fontweight='bold')
ax4.set_ylabel('정규화된 값 (0~1)', fontsize=12, fontweight='bold')
ax4.set_title('(d) 주요 지표 시계열 비교', fontsize=13, fontweight='bold')
ax4.legend(loc='upper right', fontsize=10)
ax4.grid(alpha=0.3, linestyle='--')
ax4.set_ylim(-0.05, 1.1)

plt.suptitle('RL 에이전트 가중치 분석 (Baseline Congestion)', 
             fontsize=16, fontweight='bold', y=0.995)

output_dir = Path('results/weight_analysis')
output_dir.mkdir(parents=True, exist_ok=True)
output_path = output_dir / 'weight_analysis.png'
plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
print(f"[*] 저장: {output_path} ({output_path.stat().st_size / 1024:.0f} KB)")
plt.close()

# ========================================
# Summary
# ========================================
print("\n" + "="*70)
print("분석 완료!")
print("="*70)

print("\n【 핵심 발견 】")
print(f"\n🔴 가장 높은 가중치:")
print(f"   1위: RTT (1.6x) - 실제 기여도: {rtt_contribution.mean():.3f}")
print(f"   2위: Queue Pressure (1.0x) - 실제 기여도: {queue_contribution.mean():.3f}")
print(f"   3위: snd_ratio (0.8x) - 실제 기여도: {snd_contribution.mean():.3f}")

print(f"\n📊 페널티 비율:")
total = sum(contributions)
for label, contrib in zip(labels_pie, contributions):
    pct = contrib / total * 100
    print(f"   {label:12s}: {pct:5.1f}%")

print(f"\n💡 결론:")
print(f"   RL 에이전트는 RTT에 가장 높은 가중치(1.6x)를 부여")
print(f"   Queue Pressure(1.0x)와 snd_ratio(0.8x)가 그 다음")
print(f"   재전송(0.6x)과 rcv_ratio(0.6x)는 상대적으로 낮은 가중치")

print(f"\n출력: {output_dir}/weight_analysis.png")
print("="*70)
