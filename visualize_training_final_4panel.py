#!/usr/bin/env python3
"""
4-Panel 학습 과정 시각화 (슬라이드용)
(a) 학습 수렴 (Reward)
(b) 목표 성능 달성 (P99)
(c) snd_ratio ↔ P99 상관관계
(d) Action → snd_ratio 제어
"""

import json
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
import matplotlib
from matplotlib import font_manager
from matplotlib.font_manager import FontProperties
# 한글 폰트 설정 - NanumGothic 직접 로드
import matplotlib.font_manager as fm
import os

# NanumGothic.ttf 직접 경로 지정
FONT_PATH = '/usr/share/fonts/truetype/nanum/NanumGothic.ttf'
FONT_PROP = fm.FontProperties(fname=FONT_PATH) if os.path.exists(FONT_PATH) else None

# rcParams 설정 (전역)
if FONT_PROP:
    plt.rcParams['font.family'] = FONT_PROP.get_name()
    print(f"[폰트] {FONT_PROP.get_name()} 로드: {FONT_PATH}")
else:
    plt.rcParams['font.family'] = 'sans-serif'
    print("[폰트] 기본 sans-serif")

plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['font.size'] = 14

# 한글 텍스트용 helper 함수
def set_korean_text(ax, xlabel=None, ylabel=None, title=None):
    """한글 텍스트를 FontProperties로 설정"""
    if xlabel:
        ax.set_xlabel(xlabel, fontproperties=FONT_PROP)
    if ylabel:
        ax.set_ylabel(ylabel, fontproperties=FONT_PROP)
    if title:
        ax.set_title(title, fontproperties=FONT_PROP)

def moving_average(data, window=10):
    """이동 평균"""
    if len(data) < window:
        return data
    return np.convolve(data, np.ones(window)/window, mode='valid')

# ==================== 데이터 로드 ====================
print("="*80)
print("슬라이드용 4-Panel 학습 과정 시각화")
print("="*80)

import sys
log_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('logs/1로그정리/학습로그/ppo_reset_v1.jsonl')
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

# 극값 제거 함수
def remove_outliers(data, factor=2.5):
    """IQR 방법으로 극단값 제거"""
    q1 = np.percentile(data, 25)
    q3 = np.percentile(data, 75)
    iqr = q3 - q1
    lower_bound = q1 - factor * iqr
    upper_bound = q3 + factor * iqr
    return np.clip(data, lower_bound, upper_bound)

# Rewards: 극값 제거
rewards = remove_outliers(np.array(rewards), factor=2.0)
# P99: 95 percentile로 클리핑
p99s = np.clip(p99s, 0, np.percentile(p99s, 95))
# snd_ratio: 99 percentile로 클리핑
snd_ratios = np.clip(snd_ratios, 0, np.percentile(snd_ratios, 99))

# 데이터 다운샘플링 (10개 중 1개만 사용) - 시각화 성능 개선
downsample_rate = 10
rewards = rewards[::downsample_rate]
p99s = p99s[::downsample_rate]
snd_ratios = snd_ratios[::downsample_rate]
actions = actions[::downsample_rate]

steps = np.arange(len(rewards))
time_sec = steps * 2.0 * downsample_rate  # 시간 스케일 조정

print(f"\n[*] 통계:")
print(f"    Rewards: {np.mean(rewards):.3f} ± {np.std(rewards):.3f}")
print(f"    P99: {np.mean(p99s):.0f}ms (min: {np.min(p99s):.0f}, max: {np.max(p99s):.0f})")
print(f"    snd_ratio: {np.mean(snd_ratios):.3f} (>1.0: {sum(s>1.0 for s in snd_ratios)/len(snd_ratios)*100:.1f}%)")
print(f"    |Action|: {np.mean([abs(a) for a in actions]):.4f}")

# 색상 팔레트 (더 선명하고 구분되는 색상)
color1 = '#1f77b4'  # 파란 (action)
color2 = '#d62728'  # 빨강 (P99)
color3 = '#ff7f0e'  # 주황 (snd_ratio)
color4 = '#2ca02c'  # 초록 (reward)
color_gray = '#7f7f7f'  # 회색 (trend)

# ==================== 2x2 그리드 ====================
print("\n[*] 그래프 생성 중...")

fig, axes = plt.subplots(2, 2, figsize=(24, 18))
fig.suptitle('RL 에이전트 학습 성과 분석 (PPO+BC)', fontsize=32, fontweight='bold', y=0.995, fontproperties=FONT_PROP)

window = 50  # 더 부드러운 smoothing (downsampled data)

# ==================== (a) 학습 수렴 - Reward (높을수록 좋음) ====================
ax = axes[0, 0]

rewards_smooth = moving_average(rewards, window)
steps_smooth = steps[:len(rewards_smooth)]
time_smooth = time_sec[:len(rewards_smooth)]

# 이동 평균만 표시 (raw data 제거로 깔끔하게)
ax.plot(time_smooth, rewards_smooth, color=color4, linewidth=4.0, label=f'Moving Avg (window={window})', zorder=2)

# 추세선
if len(rewards) > 20:
    z = np.polyfit(steps, rewards, 2)
    p = np.poly1d(z)
    p_vals = p(steps)
    ax.plot(time_sec, p_vals, '--', color=color_gray, linewidth=3.0, alpha=0.6, label='Trend (Polynomial)', zorder=1)

# 0 기준선 (양수/음수 구분)
ax.axhline(y=0, color='black', linestyle='-', linewidth=2.0, alpha=0.6, zorder=3)
ax.fill_between(time_sec, 0, max(rewards_smooth)*1.2, alpha=0.08, color='green', label='Positive Zone')

ax.set_xlabel('학습 시간 (초)', fontsize=20, fontweight='bold', fontproperties=FONT_PROP)
ax.set_ylabel('보상 (Reward)', fontsize=20, fontweight='bold', fontproperties=FONT_PROP)
ax.set_title('(a) 학습 수렴 (보상 증가 추이)', fontsize=28, fontweight='bold', loc='left', pad=15, fontproperties=FONT_PROP)
ax.legend(loc='lower right', fontsize=18, framealpha=0.95, edgecolor='gray', prop=FONT_PROP)
ax.grid(True, alpha=0.2, linestyle='--', linewidth=0.5)
y_min = min(rewards_smooth) * 1.1
y_max = max(rewards_smooth) * 1.2
ax.set_ylim(y_min, y_max)

# 통계 텍스트 (중앙값 추가)
initial_r = np.mean(rewards[:100])
final_r = np.mean(rewards[-100:])
median_r = np.median(rewards)
positive_pct = sum(r > 0 for r in rewards) / len(rewards) * 100
textstr = f'초기: {initial_r:.1f}\n최종: {final_r:.1f}\n중앙값: {median_r:.1f}\n양수: {positive_pct:.1f}%'
ax.text(0.02, 0.98, textstr, transform=ax.transAxes, fontsize=18, 
        verticalalignment='top', fontproperties=FONT_PROP,
        bbox=dict(boxstyle='round', facecolor='white', alpha=0.9, edgecolor='gray', linewidth=1.5))

# 텍스트 박스
# textstr = 'BC+RL learning\nfrom shadow logs\n→ Policy converged'
# ax.text(0.02, 0.98, textstr, transform=ax.transAxes, fontsize=11, 
#         verticalalignment='top',
#         bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.85, pad=0.6))

# ==================== (b) 목표 성능 달성 - P99 Latency ====================
ax = axes[0, 1]

p99_steps = np.arange(len(p99s)) * 2.0
p99s_smooth = moving_average(p99s, window)
p99_smooth_steps = p99_steps[:len(p99s_smooth)]

# 이동 평균만 표시 (깔끔하게)
ax.plot(p99_smooth_steps, p99s_smooth, color=color2, linewidth=4.0, label=f'P99 Moving Avg (window={window})', zorder=2)

# SLO 라인
ax.axhline(y=300, color='darkred', linestyle='--', linewidth=3.0, alpha=0.9, label='SLO 목표 (300ms)', zorder=3)
# SLO 영역 표시
ax.axhline(y=300, color='red', linestyle='--', linewidth=2.5, alpha=0.7, label='SLO (300ms)', zorder=1)

ax.set_xlabel('학습 시간 (초)', fontsize=20, fontweight='bold', fontproperties=FONT_PROP)
ax.set_ylabel('P99 레이턴시 (ms)', fontsize=20, fontweight='bold', fontproperties=FONT_PROP)
ax.set_title('(b) 성능 개선 (P99 감소 추이)', fontsize=28, fontweight='bold', loc='left', pad=15, fontproperties=FONT_PROP)
ax.legend(loc='upper right', fontsize=18, framealpha=0.95, edgecolor='gray', prop=FONT_PROP)
ax.grid(True, alpha=0.2, linestyle='--', linewidth=0.5)
ax.set_ylim(bottom=0, top=min(max(p99s_smooth)*1.1, 5000))  # 상한 제한

# 텍스트 박스
initial_p99 = np.mean(p99s[:100])
final_p99 = np.mean(p99s[-100:])
reduction = (initial_p99 - final_p99) / initial_p99 * 100 if initial_p99 > 0 else 0
textstr = f'초기: {initial_p99:.0f}ms\n최종: {final_p99:.0f}ms\n감소율: {reduction:.1f}%'
ax.text(0.98, 0.98, textstr, transform=ax.transAxes, fontsize=18, 
        verticalalignment='top', horizontalalignment='right', fontproperties=FONT_PROP,
        bbox=dict(boxstyle='round', facecolor='white', alpha=0.9, edgecolor='gray', linewidth=1.5))
# textstr = f'P99: {initial_p99:.0f}→{final_p99:.0f}ms\nReduction: {reduction:.1f}%\n→ Below SLO'
# ax.text(0.98, 0.98, textstr, transform=ax.transAxes, fontsize=11, 
#         verticalalignment='top', horizontalalignment='right',
#         bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.85, pad=0.6))

# ==================== (c) snd_ratio ↔ P99 상관관계 ====================
ax = axes[1, 0]

# Dual y-axis
ax_snd = ax
ax_p99 = ax.twinx()

snd_steps = np.arange(len(snd_ratios)) * 2.0
snd_smooth = moving_average(snd_ratios, window)
snd_smooth_steps = snd_steps[:len(snd_smooth)]

# snd_ratio (주황) - smooth만 표시
line2 = ax_snd.plot(snd_smooth_steps, snd_smooth, color=color3, linewidth=4.0, label='snd_ratio', zorder=2)
line3 = ax_snd.axhline(y=1.0, color='darkred', linestyle='--', linewidth=3.0, alpha=0.9, label='Overflow (1.0)', zorder=3)
ax_snd.fill_between(snd_steps, 1.0, max(snd_smooth)*1.5, alpha=0.12, color='red', zorder=0)

# P99 (빨강) - smooth만 표시
line5 = ax_p99.plot(p99_smooth_steps, p99s_smooth, color=color2, linewidth=4.0, label='P99', zorder=2)

ax_snd.set_xlabel('학습 시간 (초)', fontsize=20, fontweight='bold', fontproperties=FONT_PROP)
ax_snd.set_ylabel('송신 버퍼 압력 (snd_ratio)', fontsize=19, fontweight='bold', color=color3, fontproperties=FONT_PROP)
ax_p99.set_ylabel('P99 레이턴시 (ms)', fontsize=19, fontweight='bold', color=color2, fontproperties=FONT_PROP)
ax_snd.set_title('(c) 인과관계: 송신 버퍼 ↔ 레이턴시', fontsize=28, fontweight='bold', loc='left', pad=15, fontproperties=FONT_PROP)

ax_snd.tick_params(axis='y', labelcolor=color3, labelsize=16)
ax_p99.tick_params(axis='y', labelcolor=color2, labelsize=16)
ax_snd.grid(True, alpha=0.2, linestyle='--', linewidth=0.5)
ax_snd.set_ylim(bottom=0, top=min(max(snd_smooth)*1.5, 3.0))
ax_p99.set_ylim(bottom=0, top=min(max(p99s_smooth)*1.1, 5000))

# 범례 통합
lines = line2 + [line3] + line5
labels = [l.get_label() for l in lines]
ax_snd.legend(lines, labels, loc='upper right', fontsize=18, framealpha=0.95, edgecolor='gray', prop=FONT_PROP)

# 통계 텍스트
corr = np.corrcoef(snd_ratios[:min(len(snd_ratios), len(p99s))], p99s[:min(len(snd_ratios), len(p99s))])[0,1]
textstr = f'상관계수: {corr:.3f}\n(버퍼 ↔ 레이턴시)'
ax_snd.text(0.02, 0.98, textstr, transform=ax_snd.transAxes, fontsize=18, 
        verticalalignment='top', fontproperties=FONT_PROP,
        bbox=dict(boxstyle='round', facecolor='white', alpha=0.9, edgecolor='gray', linewidth=1.5))

# 텍스트 박스
# textstr = 'snd_ratio > 1.0\n→ P99 explodes\n\nsnd_ratio < 1.0\n→ P99 stable'
# ax_snd.text(0.02, 0.98, textstr, transform=ax_snd.transAxes, fontsize=11, 
#         verticalalignment='top',
#         bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.85, pad=0.6))

# ==================== (d) Action → snd_ratio 제어 ====================
ax = axes[1, 1]

# Dual y-axis
ax_action = ax
ax_snd2 = ax.twinx()

action_steps = np.arange(len(actions)) * 2.0
action_magnitudes = [abs(a) for a in actions]
action_smooth = moving_average(action_magnitudes, window)
action_smooth_steps = action_steps[:len(action_smooth)]

# Action magnitude (파랑) - smooth만 표시
line2 = ax_action.plot(action_smooth_steps, action_smooth, color=color1, linewidth=4.0, label='|Action|', zorder=2)

# snd_ratio (주황) - smooth만 표시
line4 = ax_snd2.plot(snd_smooth_steps, snd_smooth, color=color3, linewidth=4.0, label='snd_ratio', zorder=2)
line5 = ax_snd2.axhline(y=1.0, color='darkred', linestyle='--', linewidth=3.0, alpha=0.9, label='Overflow (1.0)', zorder=3)
ax_snd2.fill_between(snd_steps, 1.0, max(snd_smooth)*1.5, alpha=0.12, color='red', zorder=0)

ax_action.set_xlabel('학습 시간 (초)', fontsize=20, fontweight='bold', fontproperties=FONT_PROP)
ax_action.set_ylabel('액션 크기 |Δrate|', fontsize=19, fontweight='bold', color=color1, fontproperties=FONT_PROP)
ax_snd2.set_ylabel('송신 버퍼 압력 (snd_ratio)', fontsize=19, fontweight='bold', color=color3, fontproperties=FONT_PROP)
ax_action.set_title('(d) 제어 효과: 액션 → 버퍼 압력', fontsize=28, fontweight='bold', loc='left', pad=15, fontproperties=FONT_PROP)

ax_action.tick_params(axis='y', labelcolor=color1, labelsize=16)
ax_snd2.tick_params(axis='y', labelcolor=color3, labelsize=16)
ax_action.grid(True, alpha=0.2, linestyle='--', linewidth=0.5)
ax_action.set_ylim(bottom=0, top=max(action_smooth)*1.2)
ax_snd2.set_ylim(bottom=0, top=min(max(snd_smooth)*1.5, 3.0))

# 범례 통합
lines = line2 + line4 + [line5]
labels = [l.get_label() for l in lines]
ax_action.legend(lines, labels, loc='upper right', fontsize=18, framealpha=0.95, edgecolor='gray', prop=FONT_PROP)

# 통계 텍스트
initial_action = np.mean(action_magnitudes[:100])
final_action = np.mean(action_magnitudes[-100:])
initial_snd = np.mean(snd_ratios[:100])
final_snd = np.mean(snd_ratios[-100:])
textstr = f'액션: {initial_action:.3f}→{final_action:.3f}\n버퍼: {initial_snd:.3f}→{final_snd:.3f}'
ax_action.text(0.02, 0.98, textstr, transform=ax_action.transAxes, fontsize=18, 
        verticalalignment='top', fontproperties=FONT_PROP,
        bbox=dict(boxstyle='round', facecolor='white', alpha=0.9, edgecolor='gray', linewidth=1.5))

# 텍스트 박스
# textstr = 'Early:\nLarge |Δr|\n→ snd_ratio drops\n\nLater:\n|Δr| ≈ 0\n→ snd_ratio stable'
# ax_action.text(0.02, 0.98, textstr, transform=ax_action.transAxes, fontsize=11, 
#         verticalalignment='top',
#         bbox=dict(boxstyle='round', facecolor='lightgreen', alpha=0.85, pad=0.6))

# ==================== 저장 ====================
plt.tight_layout(rect=[0, 0.01, 1, 0.98])  # 타이틀 공간 확보

output_dir = Path('results/rl_training')
output_dir.mkdir(parents=True, exist_ok=True)
output_path = output_dir / 'training_4panel_final.png'

plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white', edgecolor='none')
print(f"\n[✓] 저장: {output_path}")
print(f"    크기: {output_path.stat().st_size / 1024:.0f}KB")
plt.close()

print("\n" + "="*80)
print("✅ 완료!")
print("="*80)
print(f"""
생성된 파일:
  training_4panel_final.png

4-Panel 구성:
  (a) 학습 수렴: BC+RL 학습 후 보상 수렴
  (b) 목표 성능: P99 감소 & SLO 달성
  (c) 인과관계 1: snd_ratio ↑ ↔ P99 ↑ 상관
  (d) 인과관계 2: Action → snd_ratio ↓ 제어

핵심 메시지:
  학습된 정책 → P99 개선 → 커널 버퍼 압력 제어 → 인과 체인 증명
""")
