#!/usr/bin/env python3
"""
학술 논문 스타일의 학습 과정 시각화
- 깔끔한 레이아웃
- 논문에서 흔히 보는 2x2 그리드
- 통일된 스타일
- 명확한 라벨링
"""
import json
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

# 논문 스타일 설정
plt.rcParams['font.family'] = 'serif'
plt.rcParams['font.size'] = 11
plt.rcParams['axes.labelsize'] = 12
plt.rcParams['axes.titlesize'] = 13
plt.rcParams['xtick.labelsize'] = 10
plt.rcParams['ytick.labelsize'] = 10
plt.rcParams['legend.fontsize'] = 10
plt.rcParams['figure.titlesize'] = 14
plt.rcParams['axes.grid'] = True
plt.rcParams['grid.alpha'] = 0.3
plt.rcParams['grid.linestyle'] = '--'
plt.rcParams['lines.linewidth'] = 2

def load_log(path):
    data = []
    with open(path) as f:
        for line in f:
            try:
                data.append(json.loads(line))
            except:
                continue
    return data

def compute_moving_average(data, window=5):
    """이동 평균으로 부드럽게"""
    if len(data) < window:
        return data
    return np.convolve(data, np.ones(window)/window, mode='valid')

print("="*80)
print("학술 논문 스타일 학습 과정 시각화")
print("="*80)

# 로그 로드
log_path = 'logs/eda_rl_torch_online.jsonl'
print(f"\n[*] 로그 로드: {log_path}")
data = load_log(log_path)
print(f"    ✓ {len(data)} steps")

# 데이터 추출
rewards = [d.get('r', 0) for d in data]
p99s = [d.get('metrics', {}).get('p99_ms', 0) for d in data]
actions = [d.get('a', {}).get('d_rate', 0) for d in data]

steps = np.arange(len(rewards))
time_sec = steps * 2.0  # 2초 간격

# 이동 평균 계산
window = 10
rewards_smooth = compute_moving_average(rewards, window)
p99s_smooth = compute_moving_average(p99s, window)
steps_smooth = steps[:len(rewards_smooth)]
time_smooth = time_sec[:len(rewards_smooth)]

# 액션 통계 (초기 vs 후기)
split_point = len(actions) // 2
early_actions = actions[:split_point]
late_actions = actions[split_point:]

print(f"\n[*] 데이터 통계:")
print(f"    Reward: {np.mean(rewards):.3f} ± {np.std(rewards):.3f}")
print(f"    P99: {np.mean(p99s):.0f}ms (초기 {p99s[0]:.0f}ms → 최종 {p99s[-1]:.0f}ms)")
print(f"    개선율: {(1 - p99s[-1]/p99s[0])*100:.1f}%")

# ==================== 2x2 그리드 생성 ====================
print("\n[*] 2x2 그리드 그래프 생성 중...")

fig, axes = plt.subplots(2, 2, figsize=(12, 9))
fig.suptitle('Reinforcement Learning Training Process', fontsize=16, fontweight='bold', y=0.995)

# 색상 팔레트 (학술 논문 스타일)
color_primary = '#2E86AB'    # 파란색
color_secondary = '#A23B72'  # 보라색
color_accent = '#F18F01'     # 주황색
color_good = '#06A77D'       # 초록색

# ==================== (a) Training Curve ====================
ax1 = axes[0, 0]

# 원본 데이터 (연한 색)
ax1.plot(time_sec, rewards, color=color_primary, alpha=0.3, linewidth=1, label='Raw')
# 이동 평균 (진한 색)
ax1.plot(time_smooth, rewards_smooth, color=color_primary, linewidth=2.5, label='Moving Avg (k=10)')

# 추세선
if len(rewards) > 10:
    z = np.polyfit(steps, rewards, 2)
    p = np.poly1d(z)
    ax1.plot(time_sec, p(steps), '--', color=color_accent, linewidth=2, alpha=0.7, label='Trend')

ax1.set_xlabel('Time (seconds)')
ax1.set_ylabel('Episode Reward')
ax1.set_title('(a) Reward Optimization', fontweight='bold', loc='left')
ax1.legend(loc='lower right', framealpha=0.9)
ax1.grid(True, alpha=0.3)

# 통계 텍스트
textstr = f'Mean: {np.mean(rewards):.2f}\nStd: {np.std(rewards):.2f}'
ax1.text(0.02, 0.98, textstr, transform=ax1.transAxes,
         fontsize=9, verticalalignment='top',
         bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.7, pad=0.5))

# ==================== (b) P99 Latency Reduction ====================
ax2 = axes[0, 1]

# 원본 + 이동 평균
ax2.plot(time_sec, p99s, color=color_secondary, alpha=0.3, linewidth=1, label='Raw')
ax2.plot(time_smooth, p99s_smooth, color=color_secondary, linewidth=2.5, label='Moving Avg (k=10)')

# SLO 라인
ax2.axhline(y=300, color=color_good, linestyle='--', linewidth=2, alpha=0.8, label='SLO Target (300ms)')

ax2.set_xlabel('Time (seconds)')
ax2.set_ylabel('P99 Latency (ms)')
ax2.set_title('(b) Performance Improvement', fontweight='bold', loc='left')
ax2.legend(loc='upper right', framealpha=0.9)
ax2.grid(True, alpha=0.3)

# 개선율 텍스트
reduction = (1 - p99s[-1]/p99s[0]) * 100
textstr = f'Initial: {p99s[0]:.0f}ms\nFinal: {p99s[-1]:.0f}ms\nReduction: {reduction:.1f}%'
ax2.text(0.02, 0.98, textstr, transform=ax2.transAxes,
         fontsize=9, verticalalignment='top',
         bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.7, pad=0.5))

# ==================== (c) Policy Entropy (Proxy) ====================
ax3 = axes[1, 0]

# 액션 분산을 엔트로피 대리지표로 사용
window_size = 20
entropy_proxy = []
entropy_steps = []

for i in range(window_size, len(actions), 5):
    chunk = actions[i-window_size:i]
    entropy_proxy.append(np.std(chunk))
    entropy_steps.append(time_sec[i])

ax3.plot(entropy_steps, entropy_proxy, color=color_accent, linewidth=2.5, marker='o', 
         markersize=4, markevery=5)

# 탐색/활용 구분선
if entropy_proxy:
    mid_entropy = (max(entropy_proxy) + min(entropy_proxy)) / 2
    ax3.axhline(y=mid_entropy, color='gray', linestyle=':', linewidth=1.5, alpha=0.6)
    
    # 구간 표시
    ax3.fill_between(entropy_steps, mid_entropy, max(entropy_proxy)*1.1, 
                     alpha=0.15, color='orange', label='Exploration')
    ax3.fill_between(entropy_steps, 0, mid_entropy, 
                     alpha=0.15, color='green', label='Exploitation')

ax3.set_xlabel('Time (seconds)')
ax3.set_ylabel('Action Std Dev (Entropy Proxy)')
ax3.set_title('(c) Policy Convergence', fontweight='bold', loc='left')
ax3.legend(loc='upper right', framealpha=0.9)
ax3.grid(True, alpha=0.3)

# 변화 텍스트
if entropy_proxy:
    textstr = f'Early: {entropy_proxy[0]:.4f}\nLate: {entropy_proxy[-1]:.4f}\nChange: {entropy_proxy[-1]-entropy_proxy[0]:.4f}'
    ax3.text(0.02, 0.98, textstr, transform=ax3.transAxes,
             fontsize=9, verticalalignment='top',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.7, pad=0.5))

# ==================== (d) Action Distribution ====================
ax4 = axes[1, 1]

# 히스토그램 (Early vs Late)
bins = np.linspace(-0.25, 0.25, 25)

# Early (연한 색)
ax4.hist(early_actions, bins=bins, alpha=0.5, color='#95a5a6', 
         edgecolor='black', linewidth=0.5, label=f'Early Training (n={len(early_actions)})')

# Late (진한 색)
ax4.hist(late_actions, bins=bins, alpha=0.7, color=color_good, 
         edgecolor='black', linewidth=0.5, label=f'Late Training (n={len(late_actions)})')

# Zero action 라인
ax4.axvline(x=0, color='red', linestyle='--', linewidth=2, alpha=0.7, label='No Change')

ax4.set_xlabel('Action (Rate Change Δr)')
ax4.set_ylabel('Frequency')
ax4.set_title('(d) Action Distribution Evolution', fontweight='bold', loc='left')
ax4.legend(loc='upper right', framealpha=0.9)
ax4.grid(True, alpha=0.3, axis='y')

# 통계 텍스트
early_std = np.std(early_actions)
late_std = np.std(late_actions)
early_zeros = np.sum(np.array(early_actions) == 0) / len(early_actions) * 100
late_zeros = np.sum(np.array(late_actions) == 0) / len(late_actions) * 100

textstr = f'Early Std: {early_std:.4f}\nLate Std: {late_std:.4f}\n'
textstr += f'Zero Actions:\n  Early: {early_zeros:.1f}%\n  Late: {late_zeros:.1f}%'
ax4.text(0.98, 0.98, textstr, transform=ax4.transAxes,
         fontsize=9, verticalalignment='top', horizontalalignment='right',
         bbox=dict(boxstyle='round', facecolor='lightgreen', alpha=0.7, pad=0.5))

# ==================== 레이아웃 조정 ====================
plt.tight_layout(rect=[0, 0, 1, 0.99])

# 저장
output_dir = Path('results/rl_training')
output_dir.mkdir(parents=True, exist_ok=True)
output_path = output_dir / 'training_process_paper_style.png'

plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
print(f"\n[✓] 저장 완료: {output_path}")

# 파일 크기 확인
file_size = output_path.stat().st_size / 1024
print(f"    파일 크기: {file_size:.0f}KB")

plt.close()

# ==================== 개별 고해상도 버전 생성 ====================
print("\n[*] 개별 고해상도 그래프 생성 중...")

# (a) Training Curve - 개별
fig, ax = plt.subplots(figsize=(8, 5))
ax.plot(time_sec, rewards, color=color_primary, alpha=0.3, linewidth=1, label='Raw Data')
ax.plot(time_smooth, rewards_smooth, color=color_primary, linewidth=3, label='Moving Average (k=10)')
if len(rewards) > 10:
    ax.plot(time_sec, p(steps), '--', color=color_accent, linewidth=2.5, alpha=0.8, label='Polynomial Trend')
ax.set_xlabel('Training Time (seconds)', fontsize=14, fontweight='bold')
ax.set_ylabel('Episode Reward', fontsize=14, fontweight='bold')
ax.set_title('Training Curve: Reward Optimization', fontsize=16, fontweight='bold', pad=15)
ax.legend(loc='lower right', fontsize=12, framealpha=0.95)
ax.grid(True, alpha=0.3)
textstr = f'Mean Reward: {np.mean(rewards):.2f}\nStd Dev: {np.std(rewards):.2f}\nFinal Reward: {rewards[-1]:.2f}'
ax.text(0.02, 0.98, textstr, transform=ax.transAxes, fontsize=11, verticalalignment='top',
        bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))
plt.tight_layout()
plt.savefig(output_dir / 'training_curve_clean.png', dpi=300, bbox_inches='tight', facecolor='white')
plt.close()
print(f"    ✓ training_curve_clean.png")

# (b) P99 Reduction - 개별
fig, ax = plt.subplots(figsize=(8, 5))
ax.plot(time_sec, p99s, color=color_secondary, alpha=0.4, linewidth=1.5, label='Raw P99')
ax.plot(time_smooth, p99s_smooth, color=color_secondary, linewidth=3, label='Moving Average (k=10)')
ax.axhline(y=300, color=color_good, linestyle='--', linewidth=2.5, alpha=0.9, label='SLO Target (300ms)')
ax.fill_between(time_sec, 0, 300, alpha=0.1, color='green', label='SLO Compliant')
ax.set_xlabel('Training Time (seconds)', fontsize=14, fontweight='bold')
ax.set_ylabel('P99 Latency (ms)', fontsize=14, fontweight='bold')
ax.set_title('Performance Improvement During Training', fontsize=16, fontweight='bold', pad=15)
ax.legend(loc='upper right', fontsize=12, framealpha=0.95)
ax.grid(True, alpha=0.3)
ax.set_ylim(bottom=0)
reduction = (1 - p99s[-1]/p99s[0]) * 100
textstr = f'Initial P99: {p99s[0]:.0f}ms\nFinal P99: {p99s[-1]:.0f}ms\nReduction: {reduction:.1f}%\nMin P99: {min(p99s):.0f}ms'
ax.text(0.02, 0.98, textstr, transform=ax.transAxes, fontsize=11, verticalalignment='top',
        bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.8))
plt.tight_layout()
plt.savefig(output_dir / 'p99_reduction_clean.png', dpi=300, bbox_inches='tight', facecolor='white')
plt.close()
print(f"    ✓ p99_reduction_clean.png")

# (c) Action Distribution - 개별
fig, ax = plt.subplots(figsize=(8, 5))
bins = np.linspace(-0.25, 0.25, 30)
ax.hist(early_actions, bins=bins, alpha=0.6, color='#95a5a6', edgecolor='black', 
        linewidth=1, label=f'Early Training (first {len(early_actions)} steps)', density=True)
ax.hist(late_actions, bins=bins, alpha=0.7, color=color_good, edgecolor='black', 
        linewidth=1, label=f'Late Training (last {len(late_actions)} steps)', density=True)
ax.axvline(x=0, color='red', linestyle='--', linewidth=3, alpha=0.8, label='Zero Action (No Change)')
ax.set_xlabel('Action Value (Rate Change Δr)', fontsize=14, fontweight='bold')
ax.set_ylabel('Probability Density', fontsize=14, fontweight='bold')
ax.set_title('Action Distribution: Exploration to Exploitation', fontsize=16, fontweight='bold', pad=15)
ax.legend(loc='upper right', fontsize=11, framealpha=0.95)
ax.grid(True, alpha=0.3, axis='y')
early_std = np.std(early_actions)
late_std = np.std(late_actions)
textstr = f'Early Std Dev: {early_std:.4f}\nLate Std Dev: {late_std:.4f}\n'
textstr += f'Convergence: {(1-late_std/early_std)*100:.1f}%'
ax.text(0.02, 0.98, textstr, transform=ax.transAxes, fontsize=11, verticalalignment='top',
        bbox=dict(boxstyle='round', facecolor='lightgreen', alpha=0.8))
plt.tight_layout()
plt.savefig(output_dir / 'action_distribution_clean.png', dpi=300, bbox_inches='tight', facecolor='white')
plt.close()
print(f"    ✓ action_distribution_clean.png")

print("\n" + "="*80)
print("✅ 완료!")
print("="*80)
print(f"""
생성된 파일:
  1. training_process_paper_style.png  (2x2 그리드, 논문용)
  2. training_curve_clean.png          (개별, 고해상도)
  3. p99_reduction_clean.png           (개별, 고해상도)
  4. action_distribution_clean.png     (개별, 고해상도)

위치: {output_dir}/

논문 스타일 특징:
  ✓ Serif 폰트 (학술 논문 표준)
  ✓ 깔끔한 그리드
  ✓ 통일된 색상 팔레트
  ✓ (a), (b), (c), (d) 라벨링
  ✓ 명확한 범례와 축 레이블
  ✓ 300 DPI (출판 품질)
""")
