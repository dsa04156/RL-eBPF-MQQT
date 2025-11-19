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
candidates = ["NanumGothic", "Noto Sans CJK KR", "AppleGothic", "Malgun Gothic"]
available = {f.name for f in font_manager.fontManager.ttflist}

def pick_font(cands):
    # 부분일치 허용 (환경마다 이름이 조금씩 다름)
    for c in cands:
        m = [name for name in available if c in name]
        if m:
            return m[0]
    return None
kfont = pick_font(candidates)

if kfont is None:
    # 2) 로컬 폴백: 리포지토리에 TTF/OTF를 넣고 쓰기 (아래 경로 중 하나만 있어도 됨)
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
        # 마지막 최후통첩: 일단 실행은 되게 하되 경고만
        print("[경고] 한글 폰트가 없습니다. 'fonts-nanum' 또는 'fonts-noto-cjk'를 설치하거나 assets/*.ttf를 추가하세요.")
        matplotlib.rcParams['font.family'] = 'sans-serif'
else:
    matplotlib.rcParams['font.family'] = kfont

matplotlib.rcParams['axes.unicode_minus'] = False  # 음수기호 깨짐 방지

# 한글 폰트 설정
# plt.rcParams['font.family'] = 'DejaVu Sans'
plt.rcParams['axes.unicode_minus'] = False

def moving_average(data, window=10):
    """이동 평균"""
    if len(data) < window:
        return data
    return np.convolve(data, np.ones(window)/window, mode='valid')

# ==================== 데이터 로드 ====================
print("="*80)
print("슬라이드용 4-Panel 학습 과정 시각화")
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

print(f"\n[*] 통계:")
print(f"    Rewards: {np.mean(rewards):.3f} ± {np.std(rewards):.3f}")
print(f"    P99: {np.mean(p99s):.0f}ms (min: {np.min(p99s):.0f}, max: {np.max(p99s):.0f})")
print(f"    snd_ratio: {np.mean(snd_ratios):.3f} (>1.0: {sum(s>1.0 for s in snd_ratios)/len(snd_ratios)*100:.1f}%)")
print(f"    |Action|: {np.mean([abs(a) for a in actions]):.4f}")

# 색상
color1 = '#2E86AB'  # 파란
color2 = '#A23B72'  # 보라
color3 = '#F18F01'  # 주황
color4 = '#06A77D'  # 초록

# ==================== 2x2 그리드 ====================
print("\n[*] 그래프 생성 중...")

fig, axes = plt.subplots(2, 2, figsize=(16, 12))
# fig.suptitle('강화학습 학습 과저', fontsize=20, fontweight='bold', y=0.995)

window = 10

# ==================== (a) 학습 수렴 - Reward (높을수록 좋음) ====================
ax = axes[0, 0]

rewards_smooth = moving_average(rewards, window)
steps_smooth = steps[:len(rewards_smooth)]
time_smooth = time_sec[:len(rewards_smooth)]

# Raw data (연하게)
ax.plot(time_sec, rewards, color=color1, alpha=0.3, linewidth=1.2, label='Raw Data', zorder=1)
# 이동 평균 (진하게)
ax.plot(time_smooth, rewards_smooth, color=color1, linewidth=3.5, label='Smoothed (MA-10)', zorder=2)

# 추세선
if len(rewards) > 20:
    z = np.polyfit(steps, rewards, 2)
    p = np.poly1d(z)
    ax.plot(time_sec, p(steps), '--', color='gray', linewidth=2, alpha=0.6, label='Trend', zorder=1)

ax.set_xlabel('Time (seconds)', fontweight='bold', fontsize=12)
ax.set_ylabel('Reward', fontweight='bold', fontsize=12)
ax.set_title('(a) 학습 수렴', fontweight='bold', loc='left', pad=10, fontsize=14)
ax.legend(loc='lower right', fontsize=11, framealpha=0.9)
ax.grid(True, alpha=0.3)

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

# Raw data (연하게)
ax.plot(p99_steps, p99s, color=color2, alpha=0.3, linewidth=1.2, label='Raw Data', zorder=1)
# 이동 평균 (진하게)
ax.plot(p99_smooth_steps, p99s_smooth, color=color2, linewidth=3.5, label='Smoothed (MA-10)', zorder=2)

# SLO 라인
ax.axhline(y=300, color='red', linestyle='--', linewidth=2.5, alpha=0.9, label='SLO Target (300ms)', zorder=3)

ax.set_xlabel('Time (seconds)', fontweight='bold', fontsize=12)
ax.set_ylabel('P99 Latency (ms)', fontweight='bold', fontsize=12)
ax.set_title('(b) 목표 성능 달성', fontweight='bold', loc='left', pad=10, fontsize=14)
ax.legend(loc='upper right', fontsize=11, framealpha=0.9)
ax.grid(True, alpha=0.3)
ax.set_ylim(bottom=0)

# 텍스트 박스
initial_p99 = np.mean(p99s[:10])
final_p99 = np.mean(p99s[-10:])
reduction = (initial_p99 - final_p99) / initial_p99 * 100 if initial_p99 > 0 else 0
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

# snd_ratio (주황)
line1 = ax_snd.plot(snd_steps, snd_ratios, color=color3, alpha=0.3, linewidth=1.2, label='snd_ratio (raw)', zorder=1)
line2 = ax_snd.plot(snd_smooth_steps, snd_smooth, color=color3, linewidth=3.5, label='snd_ratio (smooth)', zorder=2)
line3 = ax_snd.axhline(y=1.0, color='red', linestyle='--', linewidth=2.5, alpha=0.8, label='Overflow Threshold', zorder=3)

# P99 (보라)
line4 = ax_p99.plot(p99_steps, p99s, color=color2, alpha=0.3, linewidth=1.2, label='P99 (raw)', zorder=1)
line5 = ax_p99.plot(p99_smooth_steps, p99s_smooth, color=color2, linewidth=3.5, label='P99 (smooth)', zorder=2)

ax_snd.set_xlabel('Time (seconds)', fontweight='bold', fontsize=12)
ax_snd.set_ylabel('snd_ratio (Buffer Pressure)', fontweight='bold', fontsize=12, color=color3)
ax_p99.set_ylabel('P99 Latency (ms)', fontweight='bold', fontsize=12, color=color2)
ax_snd.set_title('(c) 인과관계 1: snd_ratio ↔ P99', fontweight='bold', loc='left', pad=10, fontsize=14)

ax_snd.tick_params(axis='y', labelcolor=color3)
ax_p99.tick_params(axis='y', labelcolor=color2)
ax_snd.grid(True, alpha=0.3)
ax_snd.set_ylim(bottom=0)
ax_p99.set_ylim(bottom=0)

# 범례 통합
lines = line1 + line2 + [line3] + line4 + line5
labels = [l.get_label() for l in lines]
ax_snd.legend(lines, labels, loc='upper right', fontsize=10, framealpha=0.9)

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

# Action magnitude (파랑)
line1 = ax_action.plot(action_steps, action_magnitudes, color=color1, alpha=0.3, linewidth=1.2, label='|Action| (raw)', zorder=1)
line2 = ax_action.plot(action_smooth_steps, action_smooth, color=color1, linewidth=3.5, label='|Action| (smooth)', zorder=2)

# snd_ratio (주황)
line3 = ax_snd2.plot(snd_steps, snd_ratios, color=color3, alpha=0.3, linewidth=1.2, label='snd_ratio (raw)', zorder=1)
line4 = ax_snd2.plot(snd_smooth_steps, snd_smooth, color=color3, linewidth=3.5, label='snd_ratio (smooth)', zorder=2)
line5 = ax_snd2.axhline(y=1.0, color='red', linestyle='--', linewidth=2.5, alpha=0.8, label='Overflow Threshold', zorder=3)

ax_action.set_xlabel('Time (seconds)', fontweight='bold', fontsize=12)
ax_action.set_ylabel('|Action Magnitude| |Δr|', fontweight='bold', fontsize=12, color=color1)
ax_snd2.set_ylabel('snd_ratio (Buffer Pressure)', fontweight='bold', fontsize=12, color=color3)
ax_action.set_title('(d) 인과관계 2: Action → snd_ratio', fontweight='bold', loc='left', pad=10, fontsize=14)

ax_action.tick_params(axis='y', labelcolor=color1)
ax_snd2.tick_params(axis='y', labelcolor=color3)
ax_action.grid(True, alpha=0.3)
ax_action.set_ylim(bottom=0)
ax_snd2.set_ylim(bottom=0)

# 범례 통합
lines = line1 + line2 + line3 + line4 + [line5]
labels = [l.get_label() for l in lines]
ax_action.legend(lines, labels, loc='upper right', fontsize=10, framealpha=0.9)

# 텍스트 박스
# textstr = 'Early:\nLarge |Δr|\n→ snd_ratio drops\n\nLater:\n|Δr| ≈ 0\n→ snd_ratio stable'
# ax_action.text(0.02, 0.98, textstr, transform=ax_action.transAxes, fontsize=11, 
#         verticalalignment='top',
#         bbox=dict(boxstyle='round', facecolor='lightgreen', alpha=0.85, pad=0.6))

# ==================== 저장 ====================
plt.tight_layout(rect=[0, 0, 1, 0.99])

output_dir = Path('results/rl_training')
output_dir.mkdir(parents=True, exist_ok=True)
output_path = output_dir / 'training_4panel_final.png'

plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
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
