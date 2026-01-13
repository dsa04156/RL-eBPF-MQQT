#!/usr/bin/env python3
"""
Panel (d): 제어 효과 - Action → snd_ratio 제어
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

# 데이터 로드
log_path = Path('학습로그/ppo_reset_v1.jsonl')
print(f"로드: {log_path}")
data = load_log(log_path)
print(f"✓ {len(data)} steps")

# 데이터 추출
actions = [abs(d.get('a', {}).get('d_rate', 0)) for d in data if 'a' in d]
snd_ratios = [d.get('kernel', {}).get('snd_ratio', 0) for d in data if 'kernel' in d]

actions = np.array(actions)
snd_ratios = np.array(snd_ratios)

# 극값 제거
snd_clip = np.percentile(snd_ratios, 99)
snd_ratios = np.clip(snd_ratios, 0, snd_clip)

# Downsampling
actions = actions[::10]
snd_ratios = snd_ratios[::10]
steps = np.arange(len(actions))
time_sec = steps * 2.0 * 10

# Smoothing
action_smooth = moving_average(actions, window=50)
snd_smooth = moving_average(snd_ratios, window=50)
time_smooth = time_sec[:len(action_smooth)]

# ==================== 그래프 생성 (Dual Y-axis) ====================
fig, ax_action = plt.subplots(figsize=(6.5, 4.5))

color_action = '#1f77b4'  # 파랑
color_snd = '#ff7f0e'     # 주황

# 왼쪽 Y축: Action Magnitude (마커=역삼각)
markevery_main = max(1, len(time_smooth) // 35)
line1 = ax_action.plot(
    time_smooth,
    action_smooth,
    color=color_action,
    linewidth=2.5,
    label='액션 크기 |Δrate|',
    zorder=2,
    marker='v',
    markersize=4.5,
    markerfacecolor='white',
    markeredgecolor=color_action,
    markeredgewidth=1.0,
    markevery=markevery_main,
)

ax_action.set_xlabel('학습 시간 (초)', fontweight='bold', fontsize=13, fontproperties=FONT_PROP)
ax_action.set_ylabel('액션 크기 |Δrate|', fontweight='bold', fontsize=13, color=color_action, fontproperties=FONT_PROP)
ax_action.tick_params(axis='y', labelcolor=color_action, labelsize=15)
ax_action.set_ylim(bottom=0, top=max(action_smooth)*1.2)

# 오른쪽 Y축: snd_ratio (마커=마름모)
ax_snd = ax_action.twinx()
line2 = ax_snd.plot(
    time_smooth,
    snd_smooth,
    color=color_snd,
    linewidth=2.5,
    alpha=0.9,
    label='snd_ratio',
    zorder=2,
    marker='D',
    markersize=4.5,
    markerfacecolor='white',
    markeredgecolor=color_snd,
    markeredgewidth=1.0,
    markevery=markevery_main,
)
line3 = ax_snd.axhline(y=1.0, color='red', linestyle='--', linewidth=2.0, alpha=0.7, label='Overflow (1.0)', zorder=1)

ax_snd.set_ylabel('송신 버퍼 압력 (snd_ratio)', fontweight='bold', fontsize=13, color=color_snd, fontproperties=FONT_PROP)
ax_snd.tick_params(axis='y', labelcolor=color_snd, labelsize=15)
ax_snd.set_ylim(bottom=0, top=min(max(snd_smooth)*1.5, 3.0))

# Overflow 영역
ax_snd.fill_between(time_smooth, 1.0, max(snd_smooth)*1.5, alpha=0.12, color='red', zorder=0)

# 제목
# 제목 제거 (사용자 요청)

# 범례 통합
lines = line1 + line2 + [line3]
labels = [l.get_label() for l in lines]
ax_action.legend(lines, labels, loc='upper right', fontsize=11, framealpha=0.95, edgecolor='gray', prop=FONT_PROP)
ax_action.grid(True, alpha=0.25, linestyle='--', linewidth=0.8)

# 통계 박스
initial_action = np.mean(actions[:100])
final_action = np.mean(actions[-100:])
initial_snd = np.mean(snd_ratios[:100])
final_snd = np.mean(snd_ratios[-100:])
textstr = f'액션: {initial_action:.3f}→{final_action:.3f}\n버퍼: {initial_snd:.3f}→{final_snd:.3f}'
ax_action.text(0.02, 0.98, textstr, transform=ax_action.transAxes, fontsize=12, 
    verticalalignment='top', fontproperties=FONT_PROP,
    bbox=dict(boxstyle='round', facecolor='white', alpha=0.9, edgecolor='gray', linewidth=2))

plt.tight_layout()
output_path = Path('panel_d_control.png')
plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
print(f"✓ 저장: {output_path}")
plt.close()
