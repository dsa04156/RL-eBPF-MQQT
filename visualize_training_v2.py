#!/usr/bin/env python3
"""
논문 스타일 학습 과정 시각화 - 개선 버전
(d) Action Distribution을 더 풍부하게:
  - Shadow Mode vs Online Mode 비교
  - 시간에 따른 액션 진화
  - 3D 또는 시계열 히트맵
"""
import json
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
from matplotlib.gridspec import GridSpec

# 논문 스타일 설정
plt.rcParams['font.family'] = 'serif'
plt.rcParams['font.size'] = 11
plt.rcParams['axes.labelsize'] = 12
plt.rcParams['axes.titlesize'] = 13
plt.rcParams['xtick.labelsize'] = 10
plt.rcParams['ytick.labelsize'] = 10
plt.rcParams['legend.fontsize'] = 10
plt.rcParams['figure.titlesize'] = 14
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
        print(f"    ⚠️  파일 없음: {path}")
    return data

def compute_moving_average(data, window=5):
    if len(data) < window:
        return data
    return np.convolve(data, np.ones(window)/window, mode='valid')

print("="*80)
print("논문 스타일 학습 과정 시각화 v2 (Action Distribution 강화)")
print("="*80)

# 색상 팔레트
color_primary = '#2E86AB'
color_secondary = '#A23B72'
color_accent = '#F18F01'
color_good = '#06A77D'
color_shadow = '#7D8491'

# ==================== 데이터 로드 ====================
print("\n[*] 데이터 로드 중...")

# Online 학습 데이터
online_log = load_log('logs/eda_rl_torch_online.jsonl')
print(f"    ✓ Online: {len(online_log)} steps")

# Shadow 데이터 (학습 전 수집)
shadow_log = load_log('logs/rl/auto_shadow.jsonl')
print(f"    ✓ Shadow: {len(shadow_log)} steps")

# Validation 데이터
val_log = load_log('logs/rl/auto_torch_online.jsonl')
print(f"    ✓ Validation: {len(val_log)} steps")

# 데이터 추출
def extract_data(log):
    rewards = [d.get('r', 0) for d in log]
    p99s = [d.get('metrics', {}).get('p99_ms', 0) for d in log if d.get('metrics', {}).get('p99_ms')]
    actions = [d.get('a', {}).get('d_rate', 0) for d in log if d.get('a')]
    return rewards, p99s, actions

online_rewards, online_p99s, online_actions = extract_data(online_log)
shadow_rewards, shadow_p99s, shadow_actions = extract_data(shadow_log)
val_rewards, val_p99s, val_actions = extract_data(val_log)

steps = np.arange(len(online_rewards))
time_sec = steps * 2.0

# ==================== 2x2 그리드 생성 ====================
print("\n[*] 2x2 그리드 그래프 생성 중...")

fig = plt.figure(figsize=(14, 10))
gs = GridSpec(2, 2, figure=fig, hspace=0.3, wspace=0.3)
fig.suptitle('Reinforcement Learning Training Process', fontsize=16, fontweight='bold', y=0.995)

# ==================== (a) Training Curve ====================
ax1 = fig.add_subplot(gs[0, 0])

window = 10
rewards_smooth = compute_moving_average(online_rewards, window)
steps_smooth = steps[:len(rewards_smooth)]
time_smooth = time_sec[:len(rewards_smooth)]

ax1.plot(time_sec, online_rewards, color=color_primary, alpha=0.3, linewidth=1, label='Raw')
ax1.plot(time_smooth, rewards_smooth, color=color_primary, linewidth=2.5, label='Moving Avg (k=10)')

if len(online_rewards) > 10:
    z = np.polyfit(steps, online_rewards, 2)
    p = np.poly1d(z)
    ax1.plot(time_sec, p(steps), '--', color=color_accent, linewidth=2, alpha=0.7, label='Trend')

ax1.set_xlabel('Time (seconds)')
ax1.set_ylabel('Episode Reward')
ax1.set_title('(a) Reward Optimization', fontweight='bold', loc='left')
ax1.legend(loc='lower right', framealpha=0.9, fontsize=9)
ax1.grid(True, alpha=0.3)

textstr = f'Mean: {np.mean(online_rewards):.2f}\nStd: {np.std(online_rewards):.2f}'
ax1.text(0.02, 0.98, textstr, transform=ax1.transAxes, fontsize=9, verticalalignment='top',
         bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.7, pad=0.5))

# ==================== (b) P99 Latency Reduction ====================
ax2 = fig.add_subplot(gs[0, 1])

p99s_smooth = compute_moving_average(online_p99s, window)
p99_steps = np.arange(len(online_p99s)) * 2.0
p99_smooth_steps = p99_steps[:len(p99s_smooth)]

ax2.plot(p99_steps, online_p99s, color=color_secondary, alpha=0.3, linewidth=1, label='Raw')
ax2.plot(p99_smooth_steps, p99s_smooth, color=color_secondary, linewidth=2.5, label='Moving Avg (k=10)')
ax2.axhline(y=300, color=color_good, linestyle='--', linewidth=2, alpha=0.8, label='SLO Target (300ms)')

ax2.set_xlabel('Time (seconds)')
ax2.set_ylabel('P99 Latency (ms)')
ax2.set_title('(b) Performance Improvement', fontweight='bold', loc='left')
ax2.legend(loc='upper right', framealpha=0.9, fontsize=9)
ax2.grid(True, alpha=0.3)

reduction = (1 - online_p99s[-1]/online_p99s[0]) * 100
textstr = f'Initial: {online_p99s[0]:.0f}ms\nFinal: {online_p99s[-1]:.0f}ms\nReduction: {reduction:.1f}%'
ax2.text(0.02, 0.98, textstr, transform=ax2.transAxes, fontsize=9, verticalalignment='top',
         bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.7, pad=0.5))

# ==================== (c) Policy Convergence ====================
ax3 = fig.add_subplot(gs[1, 0])

# 액션 표준편차를 시간에 따라 계산
window_size = 20
entropy_proxy = []
entropy_steps = []

for i in range(window_size, len(online_actions), 5):
    chunk = online_actions[i-window_size:i]
    entropy_proxy.append(np.std(chunk))
    entropy_steps.append(i * 2.0)

ax3.plot(entropy_steps, entropy_proxy, color=color_accent, linewidth=2.5, marker='o', 
         markersize=4, markevery=3)

if entropy_proxy:
    mid_entropy = (max(entropy_proxy) + min(entropy_proxy)) / 2
    ax3.axhline(y=mid_entropy, color='gray', linestyle=':', linewidth=1.5, alpha=0.6)
    ax3.fill_between(entropy_steps, mid_entropy, max(entropy_proxy)*1.1, 
                     alpha=0.15, color='orange', label='Exploration')
    ax3.fill_between(entropy_steps, 0, mid_entropy, 
                     alpha=0.15, color='green', label='Exploitation')

ax3.set_xlabel('Time (seconds)')
ax3.set_ylabel('Action Std Dev (Entropy Proxy)')
ax3.set_title('(c) Policy Convergence', fontweight='bold', loc='left')
ax3.legend(loc='upper right', framealpha=0.9, fontsize=9)
ax3.grid(True, alpha=0.3)

if entropy_proxy:
    textstr = f'Early: {entropy_proxy[0]:.4f}\nLate: {entropy_proxy[-1]:.4f}\nChange: {entropy_proxy[-1]-entropy_proxy[0]:.4f}'
    ax3.text(0.02, 0.98, textstr, transform=ax3.transAxes, fontsize=9, verticalalignment='top',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.7, pad=0.5))

# ==================== (d) Action Evolution - 개선! ====================
ax4 = fig.add_subplot(gs[1, 1])

# 시간에 따른 액션 분포 변화를 히트맵으로 표시
bins = np.linspace(-0.25, 0.25, 20)
time_bins = 10  # 시간을 10개 구간으로 나눔

# 온라인 학습 데이터를 시간 구간별로 분할
chunk_size = len(online_actions) // time_bins
heatmap_data = []

for i in range(time_bins):
    start_idx = i * chunk_size
    end_idx = (i + 1) * chunk_size if i < time_bins - 1 else len(online_actions)
    chunk_actions = online_actions[start_idx:end_idx]
    
    if chunk_actions:
        hist, _ = np.histogram(chunk_actions, bins=bins, density=True)
        heatmap_data.append(hist)
    else:
        heatmap_data.append(np.zeros(len(bins)-1))

heatmap_data = np.array(heatmap_data).T

# 히트맵 그리기
im = ax4.imshow(heatmap_data, aspect='auto', cmap='YlOrRd', origin='lower',
                extent=[0, len(online_actions)*2, bins[0], bins[-1]], 
                interpolation='bilinear')

# Zero action 라인 강조
ax4.axhline(y=0, color='blue', linestyle='--', linewidth=2.5, alpha=0.8, label='Zero Action')

# 컬러바
cbar = plt.colorbar(im, ax=ax4, pad=0.02)
cbar.set_label('Probability Density', fontsize=9)
cbar.ax.tick_params(labelsize=8)

ax4.set_xlabel('Time (seconds)')
ax4.set_ylabel('Action Value (Rate Change Δr)')
ax4.set_title('(d) Action Evolution Over Time', fontweight='bold', loc='left')
ax4.legend(loc='upper right', fontsize=9, framealpha=0.9)

# 통계 텍스트
early_actions = online_actions[:len(online_actions)//3]
late_actions = online_actions[2*len(online_actions)//3:]
early_zeros = np.sum(np.array(early_actions) == 0) / len(early_actions) * 100
late_zeros = np.sum(np.array(late_actions) == 0) / len(late_actions) * 100

textstr = f'Early Zero: {early_zeros:.1f}%\nLate Zero: {late_zeros:.1f}%'
ax4.text(0.02, 0.02, textstr, transform=ax4.transAxes, fontsize=9, verticalalignment='bottom',
         bbox=dict(boxstyle='round', facecolor='lightgreen', alpha=0.7, pad=0.5))

# ==================== 저장 ====================
plt.tight_layout(rect=[0, 0, 1, 0.99])

output_dir = Path('results/rl_training')
output_dir.mkdir(parents=True, exist_ok=True)
output_path = output_dir / 'training_process_v2.png'

plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
print(f"\n[✓] 저장 완료: {output_path}")
print(f"    파일 크기: {output_path.stat().st_size / 1024:.0f}KB")
plt.close()

# ==================== 개별 그래프 (d) 강화 버전 ====================
print("\n[*] (d) Action Evolution 상세 버전 생성 중...")

fig = plt.figure(figsize=(14, 10))
gs = GridSpec(2, 2, figure=fig, hspace=0.35, wspace=0.35)

# (d-1) 히트맵 (시간에 따른 액션 분포 변화)
ax1 = fig.add_subplot(gs[0, :])
im = ax1.imshow(heatmap_data, aspect='auto', cmap='YlOrRd', origin='lower',
                extent=[0, len(online_actions)*2, bins[0], bins[-1]], 
                interpolation='bilinear')
ax1.axhline(y=0, color='blue', linestyle='--', linewidth=3, alpha=0.9, label='Zero Action (No Change)')
cbar = plt.colorbar(im, ax=ax1, pad=0.02)
cbar.set_label('Probability Density', fontsize=11)
ax1.set_xlabel('Training Time (seconds)', fontsize=12, fontweight='bold')
ax1.set_ylabel('Action Value (Δr)', fontsize=12, fontweight='bold')
ax1.set_title('Action Distribution Evolution: Heatmap Over Time', fontsize=14, fontweight='bold', pad=15)
ax1.legend(loc='upper right', fontsize=11, framealpha=0.95)
ax1.grid(True, alpha=0.2, axis='x')

# (d-2) Shadow vs Online 비교
ax2 = fig.add_subplot(gs[1, 0])
bins_hist = np.linspace(-0.25, 0.25, 30)

if shadow_actions:
    ax2.hist(shadow_actions, bins=bins_hist, alpha=0.6, color=color_shadow, 
             edgecolor='black', linewidth=0.5, label=f'Shadow Mode (n={len(shadow_actions)})', density=True)

ax2.hist(online_actions, bins=bins_hist, alpha=0.7, color=color_primary, 
         edgecolor='black', linewidth=0.5, label=f'Online Learning (n={len(online_actions)})', density=True)

if val_actions:
    ax2.hist(val_actions, bins=bins_hist, alpha=0.7, color=color_good, 
             edgecolor='black', linewidth=0.5, label=f'Validation (n={len(val_actions)})', density=True)

ax2.axvline(x=0, color='red', linestyle='--', linewidth=2.5, alpha=0.8, label='Zero Action')
ax2.set_xlabel('Action Value (Δr)', fontsize=11, fontweight='bold')
ax2.set_ylabel('Probability Density', fontsize=11, fontweight='bold')
ax2.set_title('Shadow vs Online Action Distribution', fontsize=12, fontweight='bold')
ax2.legend(loc='upper right', fontsize=9, framealpha=0.95)
ax2.grid(True, alpha=0.3, axis='y')

# 통계
if shadow_actions:
    shadow_std = np.std(shadow_actions)
    online_std = np.std(online_actions)
    textstr = f'Shadow Std: {shadow_std:.4f}\nOnline Std: {online_std:.4f}\nConvergence: {(1-online_std/shadow_std)*100:.1f}%'
    ax2.text(0.02, 0.98, textstr, transform=ax2.transAxes, fontsize=9, verticalalignment='top',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8, pad=0.5))

# (d-3) 액션 크기 시계열
ax3 = fig.add_subplot(gs[1, 1])

# 절댓값으로 액션 크기 표시
action_magnitudes = [abs(a) for a in online_actions]
action_time = np.arange(len(action_magnitudes)) * 2.0

# 원본
ax3.plot(action_time, action_magnitudes, color=color_primary, alpha=0.4, linewidth=1, label='Raw')

# 이동 평균
if len(action_magnitudes) > 10:
    mag_smooth = compute_moving_average(action_magnitudes, 10)
    mag_time = action_time[:len(mag_smooth)]
    ax3.plot(mag_time, mag_smooth, color=color_primary, linewidth=2.5, label='Moving Avg (k=10)')

# Zero 라인
ax3.axhline(y=0, color='green', linestyle='--', linewidth=2, alpha=0.7, label='Zero (Stable)')

ax3.set_xlabel('Time (seconds)', fontsize=11, fontweight='bold')
ax3.set_ylabel('Action Magnitude |Δr|', fontsize=11, fontweight='bold')
ax3.set_title('Action Magnitude Over Time', fontsize=12, fontweight='bold')
ax3.legend(loc='upper right', fontsize=9, framealpha=0.95)
ax3.grid(True, alpha=0.3)
ax3.set_ylim(bottom=0)

# 통계
mean_mag = np.mean(action_magnitudes)
final_mag = np.mean(action_magnitudes[-20:]) if len(action_magnitudes) >= 20 else action_magnitudes[-1]
textstr = f'Mean: {mean_mag:.4f}\nFinal (avg): {final_mag:.4f}\nStability: {(1-final_mag/mean_mag)*100:.1f}%'
ax3.text(0.02, 0.98, textstr, transform=ax3.transAxes, fontsize=9, verticalalignment='top',
         bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.8, pad=0.5))

plt.suptitle('Action Distribution Analysis', fontsize=16, fontweight='bold', y=0.995)
plt.tight_layout(rect=[0, 0, 1, 0.99])

output_path2 = output_dir / 'action_evolution_detailed.png'
plt.savefig(output_path2, dpi=300, bbox_inches='tight', facecolor='white')
print(f"[✓] 저장 완료: {output_path2}")
print(f"    파일 크기: {output_path2.stat().st_size / 1024:.0f}KB")
plt.close()

print("\n" + "="*80)
print("✅ 완료!")
print("="*80)
print(f"""
생성된 파일:
  1. training_process_v2.png           (2x2, (d) 히트맵 강화)
  2. action_evolution_detailed.png     (액션 분석 상세)

위치: {output_dir}/

개선 사항:
  ✓ (d) 히트맵: 시간에 따른 액션 분포 진화 시각화
  ✓ Shadow vs Online 비교
  ✓ 액션 크기 시계열 분석
  ✓ 3개 관점으로 행동 변화 증명
""")
