#!/usr/bin/env python3
"""
실제 의미있는 학습 데이터로 시각화
- all_dyn.jsonl: 1285 steps, 645 non-zero actions (50%)
- 실제 학습 과정을 보여주는 데이터
"""
import json
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
from matplotlib.gridspec import GridSpec

# 논문 스타일
plt.rcParams['font.family'] = 'serif'
plt.rcParams['font.size'] = 11
plt.rcParams['axes.labelsize'] = 12
plt.rcParams['axes.titlesize'] = 13
plt.rcParams['lines.linewidth'] = 2

def load_log(path):
    data = []
    try:
        with open(path) as f:
            for line in f:
                try:
                    data.append(json.loads(line))
                except:
                    continue
    except FileNotFoundError:
        print(f"⚠️  {path} not found")
        return []
    return data

def compute_moving_average(data, window=20):
    if len(data) < window:
        return data
    return np.convolve(data, np.ones(window)/window, mode='valid')

print("="*80)
print("실제 학습 데이터 시각화 (all_dyn.jsonl - 의미있는 액션 포함)")
print("="*80)

# 데이터 로드
log = load_log('logs/rl/all_dyn.jsonl')
print(f"\n[*] 로드: {len(log)} steps")

if not log:
    print("❌ 데이터 없음!")
    exit(1)

# 데이터 추출
rewards = []
p99s = []
actions = []
action_raw = []  # 모델 출력
action_applied = []  # 실제 적용
applied_flags = []

for d in log:
    rewards.append(d.get('r', 0))
    p99 = d.get('metrics', {}).get('p99_ms')
    if p99:
        p99s.append(p99)
    
    a = d.get('a', {})
    a_raw = d.get('a_raw', {})
    actions.append(a.get('d_rate', 0))
    action_raw.append(a_raw.get('d_rate', 0))
    applied_flags.append(d.get('applied', False))

steps = np.arange(len(rewards))
time_sec = steps * 2.0

# 통계
applied_count = sum(applied_flags)
nonzero_count = sum(1 for a in actions if a != 0)
nonzero_applied = sum(1 for i, a in enumerate(actions) if a != 0 and applied_flags[i])

print(f"\n[*] 통계:")
print(f"    Total steps: {len(log)}")
print(f"    Applied actions: {applied_count} ({applied_count/len(log)*100:.1f}%)")
print(f"    Non-zero actions: {nonzero_count} ({nonzero_count/len(log)*100:.1f}%)")
print(f"    P99 range: {min(p99s):.0f}ms ~ {max(p99s):.0f}ms")
print(f"    Reward range: {min(rewards):.2f} ~ {max(rewards):.2f}")

# 색상
color_primary = '#2E86AB'
color_secondary = '#A23B72'
color_accent = '#F18F01'
color_good = '#06A77D'

# ==================== Figure 생성 ====================
print("\n[*] 그래프 생성 중...")

fig = plt.figure(figsize=(14, 10))
gs = GridSpec(2, 2, figure=fig, hspace=0.35, wspace=0.3)
fig.suptitle('RL Training Process with Dynamic Network Conditions', 
             fontsize=16, fontweight='bold', y=0.995)

# ==================== (a) Training Curve ====================
ax1 = fig.add_subplot(gs[0, 0])

window = 30
rewards_smooth = compute_moving_average(rewards, window)
steps_smooth = steps[:len(rewards_smooth)]
time_smooth = time_sec[:len(rewards_smooth)]

ax1.plot(time_sec, rewards, color=color_primary, alpha=0.2, linewidth=0.5)
ax1.plot(time_smooth, rewards_smooth, color=color_primary, linewidth=2.5, 
         label=f'Moving Avg (k={window})')

# 추세선
if len(rewards) > 50:
    z = np.polyfit(steps, rewards, 3)
    p = np.poly1d(z)
    ax1.plot(time_sec, p(steps), '--', color=color_accent, linewidth=2, 
             alpha=0.7, label='Trend (poly-3)')

ax1.set_xlabel('Time (seconds)', fontweight='bold')
ax1.set_ylabel('Reward', fontweight='bold')
ax1.set_title('(a) Reward Optimization', fontweight='bold', loc='left', pad=10)
ax1.legend(loc='best', framealpha=0.9, fontsize=9)
ax1.grid(True, alpha=0.3)

# 통계
textstr = f'Mean: {np.mean(rewards):.2f}\nStd: {np.std(rewards):.2f}\nSteps: {len(rewards)}'
ax1.text(0.02, 0.98, textstr, transform=ax1.transAxes, fontsize=9, 
         verticalalignment='top',
         bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8, pad=0.5))

# ==================== (b) P99 Reduction ====================
ax2 = fig.add_subplot(gs[0, 1])

if p99s:
    p99_steps = np.arange(len(p99s)) * 2.0
    p99s_smooth = compute_moving_average(p99s, window)
    p99_smooth_steps = p99_steps[:len(p99s_smooth)]
    
    ax2.plot(p99_steps, p99s, color=color_secondary, alpha=0.2, linewidth=0.5)
    ax2.plot(p99_smooth_steps, p99s_smooth, color=color_secondary, 
             linewidth=2.5, label=f'Moving Avg (k={window})')
    
    # SLO 라인
    ax2.axhline(y=300, color=color_good, linestyle='--', linewidth=2, 
                alpha=0.8, label='SLO Target (300ms)')
    ax2.fill_between(p99_steps, 0, 300, alpha=0.1, color='green')

ax2.set_xlabel('Time (seconds)', fontweight='bold')
ax2.set_ylabel('P99 Latency (ms)', fontweight='bold')
ax2.set_title('(b) Performance Improvement', fontweight='bold', loc='left', pad=10)
ax2.legend(loc='best', framealpha=0.9, fontsize=9)
ax2.grid(True, alpha=0.3)
ax2.set_ylim(bottom=0)

if p99s:
    initial = p99s[0]
    final = np.mean(p99s[-50:])
    reduction = (1 - final/initial) * 100 if initial > 0 else 0
    textstr = f'Initial: {initial:.0f}ms\nFinal: {final:.0f}ms\nReduction: {reduction:.1f}%'
    ax2.text(0.98, 0.98, textstr, transform=ax2.transAxes, fontsize=9, 
             verticalalignment='top', horizontalalignment='right',
             bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.8, pad=0.5))

# ==================== (c) Action Statistics ====================
ax3 = fig.add_subplot(gs[1, 0])

# 시간에 따른 액션 적용률
window_size = 50
apply_rate = []
apply_steps = []

for i in range(window_size, len(applied_flags), 10):
    chunk = applied_flags[i-window_size:i]
    rate = sum(chunk) / len(chunk) * 100
    apply_rate.append(rate)
    apply_steps.append(i * 2.0)

ax3.plot(apply_steps, apply_rate, color=color_accent, linewidth=2.5, 
         marker='o', markersize=3)

ax3.axhline(y=50, color='gray', linestyle=':', linewidth=1.5, alpha=0.6, 
            label='50% threshold')

ax3.set_xlabel('Time (seconds)', fontweight='bold')
ax3.set_ylabel('Action Application Rate (%)', fontweight='bold')
ax3.set_title('(c) Control Effectiveness', fontweight='bold', loc='left', pad=10)
ax3.legend(loc='best', framealpha=0.9, fontsize=9)
ax3.grid(True, alpha=0.3)
ax3.set_ylim(0, 100)

# 통계
if apply_rate:
    mean_rate = np.mean(apply_rate)
    final_rate = np.mean(apply_rate[-10:]) if len(apply_rate) >= 10 else apply_rate[-1]
    textstr = f'Mean: {mean_rate:.1f}%\nFinal: {final_rate:.1f}%\nTotal Applied: {applied_count}'
    ax3.text(0.02, 0.98, textstr, transform=ax3.transAxes, fontsize=9, 
             verticalalignment='top',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8, pad=0.5))

# ==================== (d) Action Distribution Evolution ====================
ax4 = fig.add_subplot(gs[1, 1])

# 히트맵: 시간 × 액션 값
bins = np.linspace(-0.25, 0.25, 25)
time_bins = 15
chunk_size = len(actions) // time_bins

heatmap_data = []
for i in range(time_bins):
    start_idx = i * chunk_size
    end_idx = (i + 1) * chunk_size if i < time_bins - 1 else len(actions)
    chunk_actions = actions[start_idx:end_idx]
    
    if chunk_actions:
        hist, _ = np.histogram(chunk_actions, bins=bins, density=True)
        heatmap_data.append(hist)
    else:
        heatmap_data.append(np.zeros(len(bins)-1))

heatmap_data = np.array(heatmap_data).T

# 히트맵 그리기
im = ax4.imshow(heatmap_data, aspect='auto', cmap='YlOrRd', origin='lower',
                extent=[0, len(actions)*2, bins[0], bins[-1]], 
                interpolation='bilinear')

# Zero action 강조
ax4.axhline(y=0, color='blue', linestyle='--', linewidth=2.5, alpha=0.9, 
            label='Zero Action')

# 컬러바
cbar = plt.colorbar(im, ax=ax4, pad=0.02)
cbar.set_label('Density', fontsize=9)
cbar.ax.tick_params(labelsize=8)

ax4.set_xlabel('Time (seconds)', fontweight='bold')
ax4.set_ylabel('Action Value (Δr)', fontweight='bold')
ax4.set_title('(d) Action Distribution Evolution', fontweight='bold', loc='left', pad=10)
ax4.legend(loc='upper right', fontsize=9, framealpha=0.9)

# 통계
early = actions[:len(actions)//3]
late = actions[2*len(actions)//3:]
early_nonzero = sum(1 for a in early if a != 0) / len(early) * 100
late_nonzero = sum(1 for a in late if a != 0) / len(late) * 100

textstr = f'Early NZ: {early_nonzero:.1f}%\nLate NZ: {late_nonzero:.1f}%'
ax4.text(0.02, 0.02, textstr, transform=ax4.transAxes, fontsize=9, 
         verticalalignment='bottom',
         bbox=dict(boxstyle='round', facecolor='lightgreen', alpha=0.8, pad=0.5))

# ==================== 저장 ====================
plt.tight_layout(rect=[0, 0, 1, 0.99])

output_dir = Path('results/rl_training')
output_dir.mkdir(parents=True, exist_ok=True)
output_path = output_dir / 'training_process_final.png'

plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
print(f"\n[✓] 저장: {output_path}")
print(f"    크기: {output_path.stat().st_size / 1024:.0f}KB")
plt.close()

# ==================== 개별 상세 그래프 ====================
print("\n[*] 상세 그래프 생성 중...")

# Action Analysis
fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle('Detailed Action Analysis', fontsize=16, fontweight='bold', y=0.995)

# (1) Raw vs Applied Actions
ax = axes[0, 0]
action_time = steps * 2.0
ax.scatter(action_time, action_raw, c='lightgray', s=10, alpha=0.5, label='Raw (Model Output)')
ax.scatter([action_time[i] for i in range(len(actions)) if applied_flags[i]], 
           [actions[i] for i in range(len(actions)) if applied_flags[i]], 
           c=color_accent, s=30, marker='*', alpha=0.8, label='Applied (Shield Passed)')
ax.axhline(y=0, color='red', linestyle='--', linewidth=2, alpha=0.7)
ax.set_xlabel('Time (seconds)', fontweight='bold')
ax.set_ylabel('Action Value', fontweight='bold')
ax.set_title('(a) Model Output vs Applied Actions', fontweight='bold', loc='left')
ax.legend(loc='best', fontsize=9)
ax.grid(True, alpha=0.3)

# (2) Action Magnitude Over Time
ax = axes[0, 1]
magnitudes = [abs(a) for a in actions]
mag_smooth = compute_moving_average(magnitudes, 30)
ax.plot(action_time, magnitudes, color=color_primary, alpha=0.3, linewidth=0.5)
ax.plot(action_time[:len(mag_smooth)], mag_smooth, color=color_primary, linewidth=2.5, 
        label='Moving Avg')
ax.axhline(y=0, color='green', linestyle='--', linewidth=2, alpha=0.7, label='Stable')
ax.set_xlabel('Time (seconds)', fontweight='bold')
ax.set_ylabel('|Action Magnitude|', fontweight='bold')
ax.set_title('(b) Action Magnitude Reduction', fontweight='bold', loc='left')
ax.legend(loc='best', fontsize=9)
ax.grid(True, alpha=0.3)
ax.set_ylim(bottom=0)

# (3) Early vs Late Distribution
ax = axes[1, 0]
early_actions = actions[:len(actions)//3]
late_actions = actions[2*len(actions)//3:]
bins_hist = np.linspace(-0.25, 0.25, 40)
ax.hist(early_actions, bins=bins_hist, alpha=0.6, color='#95a5a6', 
        edgecolor='black', linewidth=0.5, label=f'Early (n={len(early_actions)})', density=True)
ax.hist(late_actions, bins=bins_hist, alpha=0.7, color=color_good, 
        edgecolor='black', linewidth=0.5, label=f'Late (n={len(late_actions)})', density=True)
ax.axvline(x=0, color='red', linestyle='--', linewidth=2.5, alpha=0.8, label='Zero')
ax.set_xlabel('Action Value', fontweight='bold')
ax.set_ylabel('Density', fontweight='bold')
ax.set_title('(c) Distribution Evolution', fontweight='bold', loc='left')
ax.legend(loc='best', fontsize=9)
ax.grid(True, alpha=0.3, axis='y')

# (4) Cumulative Action Statistics
ax = axes[1, 1]
cumulative_nonzero = []
cumulative_steps = []
nonzero_count = 0
for i, a in enumerate(actions):
    if a != 0:
        nonzero_count += 1
    if i % 10 == 0:
        cumulative_nonzero.append(nonzero_count / (i+1) * 100)
        cumulative_steps.append(i * 2.0)

ax.plot(cumulative_steps, cumulative_nonzero, color=color_secondary, linewidth=2.5)
ax.axhline(y=50, color='gray', linestyle=':', linewidth=1.5, alpha=0.6, label='50%')
ax.set_xlabel('Time (seconds)', fontweight='bold')
ax.set_ylabel('Cumulative Non-Zero Rate (%)', fontweight='bold')
ax.set_title('(d) Control Activity Over Time', fontweight='bold', loc='left')
ax.legend(loc='best', fontsize=9)
ax.grid(True, alpha=0.3)
ax.set_ylim(0, 100)

plt.tight_layout(rect=[0, 0, 1, 0.99])
output_path2 = output_dir / 'action_analysis_detailed.png'
plt.savefig(output_path2, dpi=300, bbox_inches='tight', facecolor='white')
print(f"[✓] 저장: {output_path2}")
print(f"    크기: {output_path2.stat().st_size / 1024:.0f}KB")
plt.close()

print("\n" + "="*80)
print("✅ 완료!")
print("="*80)
print(f"""
생성된 파일:
  1. training_process_final.png     (2x2, 실제 학습 데이터)
  2. action_analysis_detailed.png   (액션 분석 상세)

데이터:
  • Total steps: {len(log)}
  • Non-zero actions: {nonzero_count} ({nonzero_count/len(log)*100:.1f}%)
  • Applied actions: {applied_count} ({applied_count/len(log)*100:.1f}%)
  
개선 사항:
  ✓ 의미있는 액션이 50% 포함된 실제 데이터 사용
  ✓ Shield 통과/차단 비교 시각화
  ✓ 액션 적용률 추세 추가
  ✓ 모델 출력 vs 실제 적용 비교
""")
