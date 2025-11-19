#!/usr/bin/env python3
"""
4-Panel 학습 과정 시각화 (개별 저장용)
각 subplot을 독립된 이미지 파일로 저장
"""

import json
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
import matplotlib
from matplotlib import font_manager
from matplotlib.font_manager import FontProperties
import os

candidates = ["NanumGothic", "Noto Sans CJK KR", "AppleGothic", "Malgun Gothic"]
available = {f.name for f in font_manager.fontManager.ttflist}

def pick_font(cands):
    for c in cands:
        m = [name for name in available if c in name]
        if m:
            return m[0]
    return None

kfont = pick_font(candidates)

if kfont is None:
    local_paths = [
        "assets/NanumGothic.ttf",
        "assets/NanumGothic-Regular.ttf",
        "assets/NotoSansKR-Regular.otf",
        "assets/NotoSansCJKkr-Regular.otf",
    ]
    local_path = next((p for p in local_paths if os.path.exists(p)), None)
    if local_path:
        fp = FontProperties(fname=local_path)
        matplotlib.rcParams['font.family'] = fp.get_name()
    else:
        print("[경고] 한글 폰트가 없습니다.")
        matplotlib.rcParams['font.family'] = 'sans-serif'
else:
    matplotlib.rcParams['font.family'] = kfont

matplotlib.rcParams['axes.unicode_minus'] = False

def moving_average(data, window=10):
    """이동 평균"""
    if len(data) < window:
        return data
    return np.convolve(data, np.ones(window)/window, mode='valid')

# ==================== 데이터 로드 ====================
print("="*80)
print("4-Panel 개별 이미지 생성")
print("="*80)

log_path = Path('logs/torch_model_experiments/congestion/rl_bc_v2_congestion.jsonl')
print(f"\n[*] 로드: {log_path}")

data = []
with open(log_path, 'r') as f:
    for line in f:
        try:
            entry = json.loads(line.strip())
            data.append(entry)
        except:
            continue

print(f"    ✓ {len(data)} steps")

# 데이터 추출
rewards = [d['r'] for d in data if 'r' in d]
p99s = [d['metrics']['p99_ms'] for d in data if 'metrics' in d and 'p99_ms' in d['metrics']]
snd_ratios = [d['kernel']['snd_ratio'] for d in data if 'kernel' in d and 'snd_ratio' in d['kernel']]
actions = [d['a']['d_rate'] for d in data if 'a' in d and 'd_rate' in d['a']]

steps = np.arange(len(rewards))
time_sec = steps * 2.0

# 색상
color1 = '#2E86AB'  # 파란
color2 = '#A23B72'  # 보라
color3 = '#F18F01'  # 주황
color4 = '#06A77D'  # 초록

window = 10

output_dir = Path('results/rl_training/individual_panels')
output_dir.mkdir(parents=True, exist_ok=True)

# ==================== (a) 학습 수렴 ====================
print("\n[*] (a) 학습 수렴 생성 중...")

fig, ax = plt.subplots(1, 1, figsize=(8, 6))

rewards_smooth = moving_average(rewards, window)
steps_smooth = steps[:len(rewards_smooth)]
time_smooth = time_sec[:len(rewards_smooth)]

# Raw data
ax.plot(time_sec, rewards, color=color1, alpha=0.3, linewidth=1.2, label='Raw Data', zorder=1)
# Smoothed
ax.plot(time_smooth, rewards_smooth, color=color1, linewidth=3.5, label='Smoothed (MA-10)', zorder=2)

# Trend
if len(rewards) > 20:
    z = np.polyfit(steps, rewards, 2)
    p = np.poly1d(z)
    ax.plot(time_sec, p(steps), '--', color='gray', linewidth=2, alpha=0.6, label='Trend', zorder=1)

ax.set_xlabel('Time (seconds)', fontweight='bold', fontsize=14)
ax.set_ylabel('Reward', fontweight='bold', fontsize=14)
ax.set_title('(a) 학습 수렴', fontweight='bold', loc='left', pad=15, fontsize=16)
ax.legend(loc='lower right', fontsize=12, framealpha=0.9)
ax.grid(True, alpha=0.3)

plt.tight_layout()
output_path = output_dir / 'panel_a_learning_convergence.png'
plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
print(f"    ✓ 저장: {output_path} ({output_path.stat().st_size / 1024:.0f}KB)")
plt.close()

# ==================== (b) 목표 성능 달성 ====================
print("\n[*] (b) 목표 성능 달성 생성 중...")

fig, ax = plt.subplots(1, 1, figsize=(8, 6))

p99_steps = np.arange(len(p99s)) * 2.0
p99s_smooth = moving_average(p99s, window)
p99_smooth_steps = p99_steps[:len(p99s_smooth)]

# Raw data
ax.plot(p99_steps, p99s, color=color2, alpha=0.3, linewidth=1.2, label='Raw Data', zorder=1)
# Smoothed
ax.plot(p99_smooth_steps, p99s_smooth, color=color2, linewidth=3.5, label='Smoothed (MA-10)', zorder=2)

# SLO line
ax.axhline(y=300, color='red', linestyle='--', linewidth=2.5, alpha=0.9, label='SLO Target (300ms)', zorder=3)

ax.set_xlabel('Time (seconds)', fontweight='bold', fontsize=14)
ax.set_ylabel('P99 Latency (ms)', fontweight='bold', fontsize=14)
ax.set_title('(b) 목표 성능 달성', fontweight='bold', loc='left', pad=15, fontsize=16)
ax.legend(loc='upper right', fontsize=12, framealpha=0.9)
ax.grid(True, alpha=0.3)
ax.set_ylim(bottom=0)

plt.tight_layout()
output_path = output_dir / 'panel_b_goal_achievement.png'
plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
print(f"    ✓ 저장: {output_path} ({output_path.stat().st_size / 1024:.0f}KB)")
plt.close()

# ==================== (c) snd_ratio ↔ P99 상관관계 ====================
print("\n[*] (c) 인과관계 1 생성 중...")

fig, ax_snd = plt.subplots(1, 1, figsize=(8, 6))
ax_p99 = ax_snd.twinx()

snd_steps = np.arange(len(snd_ratios)) * 2.0
snd_smooth = moving_average(snd_ratios, window)
snd_smooth_steps = snd_steps[:len(snd_smooth)]

# snd_ratio (주황)
line1 = ax_snd.plot(snd_steps, snd_ratios, color=color3, alpha=0.3, linewidth=1.2, label='snd_ratio (raw)', zorder=1)
line2 = ax_snd.plot(snd_smooth_steps, snd_smooth, color=color3, linewidth=3.5, label='snd_ratio (smooth)', zorder=2)
line3 = ax_snd.axhline(y=1.0, color='red', linestyle='--', linewidth=2.5, alpha=0.8, label='Overflow Threshold', zorder=3)

# P99 (보라)
line4 = ax_p99.plot(p99_steps, p99s, color=color2, alpha=0.3, linewidth=1.2, label='P99 (raw)', zorder=1)
line5 = ax_p99.plot(p99_smooth_steps, p99s_smooth, color=color2, linewidth=3.5, label='P99 (smooth)', zorder=2)

ax_snd.set_xlabel('Time (seconds)', fontweight='bold', fontsize=14)
ax_snd.set_ylabel('snd_ratio (Buffer Pressure)', fontweight='bold', fontsize=14, color=color3)
ax_p99.set_ylabel('P99 Latency (ms)', fontweight='bold', fontsize=14, color=color2)
ax_snd.set_title('(c) 인과관계 1: snd_ratio ↔ P99', fontweight='bold', loc='left', pad=15, fontsize=16)

ax_snd.tick_params(axis='y', labelcolor=color3)
ax_p99.tick_params(axis='y', labelcolor=color2)
ax_snd.grid(True, alpha=0.3)
ax_snd.set_ylim(bottom=0)
ax_p99.set_ylim(bottom=0)

# 범례 통합
lines = line1 + line2 + [line3] + line4 + line5
labels = [l.get_label() for l in lines]
ax_snd.legend(lines, labels, loc='upper right', fontsize=11, framealpha=0.9)

plt.tight_layout()
output_path = output_dir / 'panel_c_causal_chain_1.png'
plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
print(f"    ✓ 저장: {output_path} ({output_path.stat().st_size / 1024:.0f}KB)")
plt.close()

# ==================== (d) Action → snd_ratio 제어 ====================
print("\n[*] (d) 인과관계 2 생성 중...")

fig, ax_action = plt.subplots(1, 1, figsize=(8, 6))
ax_snd2 = ax_action.twinx()

action_steps = np.arange(len(actions)) * 2.0
action_magnitudes = [abs(a) for a in actions]
action_smooth = moving_average(action_magnitudes, window)
action_smooth_steps = action_steps[:len(action_smooth)]

# Action magnitude (파랑)
line1 = ax_action.plot(action_steps, action_magnitudes, color=color1, alpha=0.3, linewidth=1.2, label='|Action| (raw)', zorder=1)
line2 = ax_action.plot(action_smooth_steps, action_smooth, color=color1, linewidth=3.5, label='|Action| (smooth)', zorder=2)

# snd_ratio (주황)
line3 = ax_snd2.plot(snd_steps, snd_ratios, color=color3, alpha=0.3, linewidth=1.2, label='snd_ratio (raw)', zorder=1)
line4 = ax_snd2.plot(snd_smooth_steps, snd_smooth, color=color3, linewidth=3.5, label='snd_ratio (smooth)', zorder=2)
line5 = ax_snd2.axhline(y=1.0, color='red', linestyle='--', linewidth=2.5, alpha=0.8, label='Overflow Threshold', zorder=3)

ax_action.set_xlabel('Time (seconds)', fontweight='bold', fontsize=14)
ax_action.set_ylabel('|Action Magnitude| |Δr|', fontweight='bold', fontsize=14, color=color1)
ax_snd2.set_ylabel('snd_ratio (Buffer Pressure)', fontweight='bold', fontsize=14, color=color3)
ax_action.set_title('(d) 인과관계 2: Action → snd_ratio', fontweight='bold', loc='left', pad=15, fontsize=16)

ax_action.tick_params(axis='y', labelcolor=color1)
ax_snd2.tick_params(axis='y', labelcolor=color3)
ax_action.grid(True, alpha=0.3)
ax_action.set_ylim(bottom=0)
ax_snd2.set_ylim(bottom=0)

# 범례 통합
lines = line1 + line2 + line3 + line4 + [line5]
labels = [l.get_label() for l in lines]
ax_action.legend(lines, labels, loc='upper right', fontsize=11, framealpha=0.9)

plt.tight_layout()
output_path = output_dir / 'panel_d_causal_chain_2.png'
plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
print(f"    ✓ 저장: {output_path} ({output_path.stat().st_size / 1024:.0f}KB)")
plt.close()

print("\n" + "="*80)
print("✅ 완료!")
print("="*80)
print(f"""
생성된 개별 파일:
  1. panel_a_learning_convergence.png  (학습 수렴)
  2. panel_b_goal_achievement.png      (목표 성능 달성)
  3. panel_c_causal_chain_1.png        (인과관계 1: snd_ratio ↔ P99)
  4. panel_d_causal_chain_2.png        (인과관계 2: Action → snd_ratio)

저장 위치: {output_dir}
""")
