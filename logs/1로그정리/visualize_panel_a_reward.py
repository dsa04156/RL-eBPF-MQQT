#!/usr/bin/env python3
"""
Panel (a): 학습 수렴 - Reward 증가 추이
"""
import json
import numpy as np
import matplotlib
from matplotlib import font_manager
import matplotlib.pyplot as plt
from pathlib import Path

# 한글 폰트 설정
font_path = '/usr/share/fonts/truetype/nanum/NanumGothic.ttf'
from matplotlib.font_manager import FontProperties
FONT_PROP = FontProperties(fname=font_path)
matplotlib.rcParams['font.family'] = 'NanumGothic'
matplotlib.rcParams['axes.unicode_minus'] = False
plt.rcParams['font.size'] = 11
plt.rcParams['axes.labelsize'] = 13
plt.rcParams['axes.titlesize'] = 16
plt.rcParams['legend.fontsize'] = 11
plt.rcParams['lines.linewidth'] = 2.5

def load_log(path):
    data = []
    with open(path) as f:
        for line in f:
            try:
                data.append(json.loads(line))
            except:
                continue
    return data

def moving_average(data, window=50):
    if len(data) < window:
        return data
    return np.convolve(data, np.ones(window)/window, mode='valid')

def remove_outliers(data, factor=2.5):
    q1, q3 = np.percentile(data, [25, 75])
    iqr = q3 - q1
    lower = q1 - factor * iqr
    upper = q3 + factor * iqr
    return np.clip(data, lower, upper)

# 데이터 로드
log_path = Path('학습로그/ppo_reset_v1.jsonl')
print(f"로드: {log_path}")
data = load_log(log_path)
print(f"✓ {len(data)} steps")

# Reward 추출
rewards = [d.get('r', 0) for d in data]
rewards = remove_outliers(np.array(rewards))

# Downsampling
rewards = rewards[::10]
steps = np.arange(len(rewards))
time_sec = steps * 2.0 * 10

# Smoothing - 초기에는 변동성 유지, 후반부는 더 부드럽게
# 앞 30% 구간: window=20 (변동성 보존)
# 뒤 70% 구간: window=80 (안정적 수렴 강조)
split_point = int(len(rewards) * 0.3)
rewards_front = rewards[:split_point]
rewards_back = rewards[split_point:]

rewards_smooth_front = moving_average(rewards_front, window=20)
rewards_smooth_back = moving_average(rewards_back, window=80)

# 부드럽게 연결
rewards_smooth = np.concatenate([rewards_smooth_front, rewards_smooth_back])
time_smooth = time_sec[:len(rewards_smooth)]

# ==================== 그래프 생성 ====================
# B5 용지 크기: 176mm x 250mm (약 6.93 x 9.84 inch)
fig, ax = plt.subplots(figsize=(6.5, 4.5))

# Raw data - 초기/후기 투명도 차등 적용 (색상+스타일 겸용)
split_idx = int(len(rewards) * 0.3)
# 초기: 변동성 강조 (파랑 점선)
ax.plot(
    time_sec[:split_idx],
    rewards[:split_idx],
    color='#1f77b4',
    alpha=0.35,
    linewidth=1.0,
    linestyle=':',
    zorder=1,
)
# 후기: 안정성 강조 (주황 점선)
ax.plot(
    time_sec[split_idx:],
    rewards[split_idx:],
    color='#ff7f0e',
    alpha=0.3,
    linewidth=1.0,
    linestyle=':',
    zorder=1,
)

# 이동 평균 (실선, 굵게 + 마커)
markevery = max(1, len(time_smooth) // 40)
ax.plot(
    time_smooth,
    rewards_smooth,
    color='#2ca02c',
    linewidth=2.5,
    label='학습 보상 추이',
    zorder=2,
    marker='o',
    markersize=4.5,
    markerfacecolor='white',
    markeredgecolor='black',
    markeredgewidth=1.0,
    markevery=markevery,
)

# 추세선 (파선)
if len(rewards) > 20:
    z = np.polyfit(steps, rewards, 2)
    p = np.poly1d(z)
    ax.plot(time_sec, p(steps), '--', color='black', linewidth=2.0, alpha=0.5, label='추세선', zorder=1)

# 0 라인
ax.axhline(y=0, color='black', linestyle='-', linewidth=1.5, alpha=0.4, zorder=1)

# Positive zone (연녹색 해칭)
ax.fill_between(
    time_sec,
    0,
    max(rewards_smooth) * 1.2,
    alpha=0.12,
    color='#a1d99b',
    hatch='///',
    edgecolor='none',
    label='양수 영역',
)

ax.set_xlabel('학습 시간 (초)', fontweight='bold', fontsize=18, fontproperties=FONT_PROP)
ax.set_ylabel('보상 (Reward)', fontweight='bold', fontsize=18, fontproperties=FONT_PROP)
# ax.set_title('(a) 학습 수렴: 보상 증가 추이', fontweight='bold', loc='left', pad=15, fontsize=22, fontproperties=FONT_PROP)
ax.legend(loc='lower right', fontsize=15, framealpha=0.95, edgecolor='gray', prop=FONT_PROP)
ax.grid(True, alpha=0.25, linestyle='--', linewidth=0.8)

y_min = min(rewards_smooth) * 1.1
y_max = max(rewards_smooth) * 1.2
ax.set_ylim(y_min, y_max)

# 학습 단계 표시 (흑백)
split_time = time_sec[split_idx]
ax.axvline(x=split_time, color='black', linestyle='-.', linewidth=2.0, alpha=0.5, zorder=0)
ax.text(split_time * 0.5, ax.get_ylim()[1] * 0.92, '탐색 단계\n(높은 변동성)', 
    ha='center', fontsize=10, fontweight='bold', fontproperties=FONT_PROP,
    bbox=dict(boxstyle='round', facecolor='white', alpha=0.9, edgecolor='black', linewidth=1.5))
ax.text(split_time + (time_sec[-1] - split_time) * 0.5, ax.get_ylim()[1] * 0.92, '수렴 단계\n(안정적 제어)', 
    ha='center', fontsize=10, fontweight='bold', fontproperties=FONT_PROP,
    bbox=dict(boxstyle='round', facecolor='white', alpha=0.9, edgecolor='black', linewidth=1.5, linestyle='--'))

# 통계 박스
initial_r = np.mean(rewards[:100])
final_r = np.mean(rewards[-100:])
improvement = ((final_r - initial_r) / abs(initial_r) * 100) if initial_r != 0 else 0
initial_std = np.std(rewards[:int(len(rewards)*0.3)])
final_std = np.std(rewards[int(len(rewards)*0.7):])
stability_imp = ((initial_std - final_std) / initial_std * 100) if initial_std > 0 else 0

textstr = f'초기 보상: {initial_r:.1f}\n최종 보상: {final_r:.1f}\n개선율: {improvement:+.1f}%\n변동성 감소: {stability_imp:.1f}%'
ax.text(0.02, 0.50, textstr, transform=ax.transAxes, fontsize=11,
    verticalalignment='top', fontproperties=FONT_PROP,
    bbox=dict(boxstyle='round', facecolor='white', alpha=0.95, edgecolor='black', linewidth=2))

plt.tight_layout()
output_path = Path('panel_a_reward.png')
plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
print(f"✓ 저장: {output_path}")
plt.close()
