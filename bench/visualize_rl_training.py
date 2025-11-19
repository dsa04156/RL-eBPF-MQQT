#!/usr/bin/env python3
"""
RL 학습 과정 시각화 도구
- 학습 곡선 (Training Curve)
- 성능 메트릭 변화 (P99 Latency Reduction)
- 행동 분포 변화 (Action Distribution)
- Value Function 예측 정확도 (TD Error - 개념적)
- 정책 엔트로피 추정 (Policy Entropy)
"""

import json
import argparse
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
from collections import defaultdict
from typing import List, Dict, Tuple

# 한글 폰트 설정 (선택)
plt.rcParams['font.family'] = 'DejaVu Sans'
plt.rcParams['axes.unicode_minus'] = False

def load_logs(log_path: str) -> List[Dict]:
    """JSONL 로그 로드"""
    data = []
    with open(log_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data.append(json.loads(line))
            except:
                continue
    return data

def compute_episode_rewards(data: List[Dict], episode_len: int = 100) -> Tuple[List[int], List[float], List[float]]:
    """에피소드별 누적 보상 계산 (에피소드 = N스텝)"""
    episodes = []
    rewards_mean = []
    rewards_std = []
    
    for i in range(0, len(data), episode_len):
        chunk = data[i:i+episode_len]
        if not chunk:
            continue
        rs = [d.get('r', 0) for d in chunk]
        episodes.append(i // episode_len)
        rewards_mean.append(np.mean(rs))
        rewards_std.append(np.std(rs))
    
    return episodes, rewards_mean, rewards_std

def compute_p99_trend(data: List[Dict]) -> Tuple[List[int], List[float]]:
    """P99 지연 추이 추출"""
    steps = []
    p99_vals = []
    
    for i, d in enumerate(data):
        metrics = d.get('metrics', {})
        p99 = metrics.get('p99_ms')
        if p99 is not None:
            steps.append(i)
            p99_vals.append(p99)
    
    return steps, p99_vals

def compute_action_distribution(data: List[Dict], early_steps: int = 100, late_start: int = None) -> Tuple[Dict, Dict]:
    """초기 vs 후기 행동 분포"""
    if late_start is None:
        late_start = max(len(data) - 100, early_steps)
    
    early_actions = [d.get('a', {}) for d in data[:early_steps]]
    late_actions = [d.get('a', {}) for d in data[late_start:]]
    
    def extract_drate(actions):
        return [a.get('d_rate', 0) for a in actions if a]
    
    early_dist = {'d_rate': extract_drate(early_actions)}
    late_dist = {'d_rate': extract_drate(late_actions)}
    
    return early_dist, late_dist

def estimate_policy_entropy(action_dist: List[float], bins: int = 20) -> float:
    """행동 분포의 엔트로피 추정 (이산화)"""
    if not action_dist:
        return 0.0
    
    hist, _ = np.histogram(action_dist, bins=bins, density=True)
    hist = hist + 1e-10  # 0방지
    hist = hist / hist.sum()
    
    entropy = -np.sum(hist * np.log(hist + 1e-10))
    return entropy

def compute_entropy_trend(data: List[Dict], window: int = 50) -> Tuple[List[int], List[float]]:
    """정책 엔트로피 시간 추이"""
    steps = []
    entropies = []
    
    for i in range(window, len(data), window // 2):
        chunk = data[i-window:i]
        actions = [d.get('a', {}).get('d_rate', 0) for d in chunk]
        ent = estimate_policy_entropy(actions, bins=10)
        steps.append(i)
        entropies.append(ent)
    
    return steps, entropies

def plot_training_curve(episodes, rewards_mean, rewards_std, output_path):
    """1. 학습 곡선 (Episode Reward vs Training Episodes)"""
    plt.figure(figsize=(12, 7))
    
    episodes = np.array(episodes)
    rewards_mean = np.array(rewards_mean)
    rewards_std = np.array(rewards_std)
    
    # 주 곡선
    plt.plot(episodes, rewards_mean, linewidth=2.5, color='#3498db', label='Mean Reward', marker='o', markersize=5)
    plt.fill_between(episodes, 
                     rewards_mean - rewards_std, 
                     rewards_mean + rewards_std, 
                     alpha=0.25, color='#3498db', label='±1 Std Dev')
    
    # 추세선 추가
    if len(episodes) > 3:
        z = np.polyfit(episodes, rewards_mean, 2)
        p = np.poly1d(z)
        plt.plot(episodes, p(episodes), "--", linewidth=2, color='#e74c3c', alpha=0.7, label='Trend (poly-2)')
    
    plt.xlabel('Episode (1 episode = 100 steps)', fontsize=13, fontweight='bold')
    plt.ylabel('Average Reward', fontsize=13, fontweight='bold')
    plt.title('RL Training Curve: Episode Reward', fontsize=15, fontweight='bold', pad=20)
    plt.grid(alpha=0.3, linestyle='--')
    plt.legend(loc='best', fontsize=11, framealpha=0.9)
    
    # 통계 정보 추가
    textstr = f'Total Episodes: {len(episodes)}\nMean Reward: {np.mean(rewards_mean):.3f}\nFinal Reward: {rewards_mean[-1]:.3f}'
    plt.text(0.02, 0.98, textstr, transform=plt.gca().transAxes,
             fontsize=10, verticalalignment='top',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"[✓] Saved: {output_path}")

def plot_p99_reduction(steps, p99_vals, output_path, sample_every=10):
    """2. P99 Latency 감소 추이"""
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))
    
    # 샘플링으로 시각화 개선
    steps_orig = np.array(steps)
    p99_vals_orig = np.array(p99_vals)
    
    if len(steps) > 1000:
        steps = steps[::sample_every]
        p99_vals = p99_vals[::sample_every]
    
    # 상단: 선형 스케일
    ax1.plot(steps, p99_vals, marker='o', linewidth=2, markersize=3, color='#e74c3c', alpha=0.7)
    
    # 이동 평균 추가
    if len(p99_vals) > 10:
        window = min(20, len(p99_vals) // 5)
        p99_smooth = np.convolve(p99_vals, np.ones(window)/window, mode='valid')
        steps_smooth = steps[:len(p99_smooth)]
        ax1.plot(steps_smooth, p99_smooth, linewidth=3, color='#c0392b', label=f'Moving Avg (window={window})')
    
    ax1.set_xlabel('Training Step', fontsize=12, fontweight='bold')
    ax1.set_ylabel('P99 Latency (ms)', fontsize=12, fontweight='bold')
    ax1.set_title('P99 Latency Reduction During Training (Linear Scale)', fontsize=14, fontweight='bold')
    ax1.grid(alpha=0.3, linestyle='--')
    ax1.legend(loc='best')
    
    # 시작/종료 마커
    ax1.axhline(p99_vals[0], color='green', linestyle='--', alpha=0.5, label=f'Start: {p99_vals[0]:.0f}ms')
    ax1.axhline(p99_vals[-1], color='blue', linestyle='--', alpha=0.5, label=f'End: {p99_vals[-1]:.0f}ms')
    ax1.legend(loc='best')
    
    # 하단: 로그 스케일 (변화가 클 때만)
    if max(p99_vals) / min(p99_vals) > 3:
        ax2.plot(steps, p99_vals, marker='o', linewidth=2, markersize=3, color='#9b59b6', alpha=0.7)
        if len(p99_vals) > 10:
            ax2.plot(steps_smooth, p99_smooth, linewidth=3, color='#8e44ad', label=f'Moving Avg (window={window})')
        
        ax2.set_yscale('log')
        ax2.set_xlabel('Training Step', fontsize=12, fontweight='bold')
        ax2.set_ylabel('P99 Latency (ms) [log scale]', fontsize=12, fontweight='bold')
        ax2.set_title('P99 Latency Reduction (Log Scale)', fontsize=14, fontweight='bold')
        ax2.grid(alpha=0.3, linestyle='--')
        ax2.legend(loc='best')
        
        # 통계 정보
        reduction_pct = (1 - p99_vals[-1]/p99_vals[0]) * 100
        textstr = f'Reduction: {reduction_pct:.1f}%\nMin: {min(p99_vals):.0f}ms\nMax: {max(p99_vals):.0f}ms'
        ax2.text(0.98, 0.98, textstr, transform=ax2.transAxes,
                fontsize=11, verticalalignment='top', horizontalalignment='right',
                bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.7))
    else:
        fig.delaxes(ax2)
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"[✓] Saved: {output_path}")

def plot_action_distribution(early_dist, late_dist, output_path):
    """3. 행동 분포 변화 (Early vs Late Training)"""
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    
    bins = np.linspace(-0.25, 0.25, 30)
    
    # Early Training - Histogram
    ax1 = axes[0, 0]
    n1, _, patches1 = ax1.hist(early_dist['d_rate'], bins=bins, color='#95a5a6', alpha=0.7, edgecolor='black', linewidth=1.5)
    ax1.set_title('Early Training (Random Exploration)', fontsize=13, fontweight='bold', pad=15)
    ax1.set_xlabel('Rate Change (d_rate)', fontsize=12, fontweight='bold')
    ax1.set_ylabel('Frequency', fontsize=12, fontweight='bold')
    ax1.grid(alpha=0.3, axis='y', linestyle='--')
    ax1.axvline(0, color='red', linestyle='--', linewidth=2, alpha=0.7, label='No change')
    ax1.legend()
    
    # Early Training - Stats
    ax2 = axes[0, 1]
    ax2.axis('off')
    early_stats = f"""
Early Training Statistics:
━━━━━━━━━━━━━━━━━━━━━━━━
• Total Actions: {len(early_dist['d_rate'])}
• Mean: {np.mean(early_dist['d_rate']):.4f}
• Std Dev: {np.std(early_dist['d_rate']):.4f}
• Zero Actions: {np.sum(np.array(early_dist['d_rate']) == 0)} ({100*np.sum(np.array(early_dist['d_rate']) == 0)/len(early_dist['d_rate']):.1f}%)
• Positive: {np.sum(np.array(early_dist['d_rate']) > 0)} ({100*np.sum(np.array(early_dist['d_rate']) > 0)/len(early_dist['d_rate']):.1f}%)
• Negative: {np.sum(np.array(early_dist['d_rate']) < 0)} ({100*np.sum(np.array(early_dist['d_rate']) < 0)/len(early_dist['d_rate']):.1f}%)
━━━━━━━━━━━━━━━━━━━━━━━━
Interpretation: 
High variance indicates
exploration phase
    """
    ax2.text(0.1, 0.5, early_stats, fontsize=12, verticalalignment='center',
             family='monospace', bbox=dict(boxstyle='round', facecolor='#ecf0f1', alpha=0.8))
    
    # Late Training - Histogram
    ax3 = axes[1, 0]
    n2, _, patches2 = ax3.hist(late_dist['d_rate'], bins=bins, color='#2ecc71', alpha=0.7, edgecolor='black', linewidth=1.5)
    ax3.set_title('Late Training (Focused Control)', fontsize=13, fontweight='bold', pad=15)
    ax3.set_xlabel('Rate Change (d_rate)', fontsize=12, fontweight='bold')
    ax3.set_ylabel('Frequency', fontsize=12, fontweight='bold')
    ax3.grid(alpha=0.3, axis='y', linestyle='--')
    ax3.axvline(0, color='red', linestyle='--', linewidth=2, alpha=0.7, label='No change')
    ax3.legend()
    
    # Late Training - Stats
    ax4 = axes[1, 1]
    ax4.axis('off')
    late_stats = f"""
Late Training Statistics:
━━━━━━━━━━━━━━━━━━━━━━━━
• Total Actions: {len(late_dist['d_rate'])}
• Mean: {np.mean(late_dist['d_rate']):.4f}
• Std Dev: {np.std(late_dist['d_rate']):.4f}
• Zero Actions: {np.sum(np.array(late_dist['d_rate']) == 0)} ({100*np.sum(np.array(late_dist['d_rate']) == 0)/len(late_dist['d_rate']):.1f}%)
• Positive: {np.sum(np.array(late_dist['d_rate']) > 0)} ({100*np.sum(np.array(late_dist['d_rate']) > 0)/len(late_dist['d_rate']):.1f}%)
• Negative: {np.sum(np.array(late_dist['d_rate']) < 0)} ({100*np.sum(np.array(late_dist['d_rate']) < 0)/len(late_dist['d_rate']):.1f}%)
━━━━━━━━━━━━━━━━━━━━━━━━
Interpretation:
Low variance indicates
exploitation phase
    """
    ax4.text(0.1, 0.5, late_stats, fontsize=12, verticalalignment='center',
             family='monospace', bbox=dict(boxstyle='round', facecolor='#d5f4e6', alpha=0.8))
    
    plt.suptitle('Action Distribution Change: Exploration → Exploitation', fontsize=16, fontweight='bold', y=0.995)
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"[✓] Saved: {output_path}")

def plot_policy_entropy(steps, entropies, output_path):
    """4. 정책 엔트로피 추이 (Exploration -> Exploitation)"""
    plt.figure(figsize=(12, 7))
    
    steps = np.array(steps)
    entropies = np.array(entropies)
    
    # 메인 곡선
    plt.plot(steps, entropies, linewidth=2.5, color='#9b59b6', marker='o', markersize=5, 
             label='Policy Entropy', alpha=0.8)
    
    # 이동 평균
    if len(entropies) > 5:
        window = min(10, len(entropies) // 3)
        ent_smooth = np.convolve(entropies, np.ones(window)/window, mode='valid')
        steps_smooth = steps[:len(ent_smooth)]
        plt.plot(steps_smooth, ent_smooth, linewidth=3, color='#8e44ad', 
                label=f'Smoothed (window={window})', linestyle='--')
    
    plt.xlabel('Training Step', fontsize=13, fontweight='bold')
    plt.ylabel('Policy Entropy', fontsize=13, fontweight='bold')
    plt.title('Policy Entropy vs Training Step\n(High = Exploration, Low = Exploitation)', 
              fontsize=15, fontweight='bold', pad=20)
    plt.grid(alpha=0.3, linestyle='--')
    plt.legend(loc='best', fontsize=11)
    
    # 영역 구분
    if len(entropies) > 0:
        max_ent = max(entropies)
        min_ent = min(entropies)
        mid_ent = (max_ent + min_ent) / 2
        
        # 탐색/활용 구간 표시
        plt.axhspan(mid_ent, max_ent, alpha=0.2, color='orange', label='Exploration Zone')
        plt.axhspan(min_ent, mid_ent, alpha=0.2, color='green', label='Exploitation Zone')
        
        # 주석
        plt.annotate('High Entropy\n(Random Actions)', 
                    xy=(steps[0], entropies[0]), xytext=(steps[0] + (steps[-1]-steps[0])*0.1, max_ent * 0.9),
                    fontsize=11, ha='left', color='#9b59b6', fontweight='bold',
                    arrowprops=dict(arrowstyle='->', color='#9b59b6', lw=2))
        
        if entropies[-1] < mid_ent:
            plt.annotate('Low Entropy\n(Focused Policy)', 
                        xy=(steps[-1], entropies[-1]), xytext=(steps[-1] - (steps[-1]-steps[0])*0.15, min_ent * 1.2),
                        fontsize=11, ha='right', color='#27ae60', fontweight='bold',
                        arrowprops=dict(arrowstyle='->', color='#27ae60', lw=2))
    
    # 통계
    textstr = f'Start Entropy: {entropies[0]:.3f}\nEnd Entropy: {entropies[-1]:.3f}\nChange: {entropies[-1]-entropies[0]:.3f}'
    plt.text(0.02, 0.98, textstr, transform=plt.gca().transAxes,
             fontsize=11, verticalalignment='top',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.7))
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"[✓] Saved: {output_path}")

def compute_td_error_proxy(data: List[Dict], window: int = 50) -> Tuple[List[int], List[float]]:
    """5. TD 오차 대리지표 (보상 변동성 기반)"""
    steps = []
    td_errors = []
    
    for i in range(window, len(data), window // 2):
        chunk = data[i-window:i]
        rewards = [d.get('r', 0) for d in chunk]
        
        # 보상의 표준편차를 TD 오차 대리지표로 사용
        td_error = np.std(rewards)
        steps.append(i)
        td_errors.append(td_error)
    
    return steps, td_errors

def plot_td_error(steps, td_errors, output_path):
    """5. Value Prediction Error (TD Error Proxy)"""
    plt.figure(figsize=(10, 6))
    
    plt.plot(steps, td_errors, marker='o', linewidth=2, markersize=4, color='#e67e22')
    
    plt.xlabel('Training Step', fontsize=12)
    plt.ylabel('Reward Std Dev (TD Error Proxy)', fontsize=12)
    plt.title('Value Prediction Error During Training', fontsize=14, fontweight='bold')
    plt.grid(alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"[✓] Saved: {output_path}")

def generate_summary_stats(data: List[Dict]):
    """학습 통계 요약"""
    total_steps = len(data)
    
    rewards = [d.get('r', 0) for d in data]
    p99_vals = [d.get('metrics', {}).get('p99_ms') for d in data if d.get('metrics', {}).get('p99_ms') is not None]
    
    print("\n" + "="*60)
    print("RL Training Summary Statistics")
    print("="*60)
    print(f"Total Steps:        {total_steps}")
    print(f"Reward Mean:        {np.mean(rewards):.4f}")
    print(f"Reward Std:         {np.std(rewards):.4f}")
    print(f"Reward Min/Max:     {np.min(rewards):.4f} / {np.max(rewards):.4f}")
    
    if p99_vals:
        print(f"\nP99 Latency (ms):")
        print(f"  Initial:          {p99_vals[0]:.2f}")
        print(f"  Final:            {p99_vals[-1]:.2f}")
        print(f"  Min:              {np.min(p99_vals):.2f}")
        print(f"  Reduction:        {(1 - p99_vals[-1]/p99_vals[0])*100:.1f}%")
    
    # 행동 통계
    actions_d_rate = [d.get('a', {}).get('d_rate', 0) for d in data if d.get('a')]
    if actions_d_rate:
        print(f"\nAction Statistics (d_rate):")
        print(f"  Mean:             {np.mean(actions_d_rate):.4f}")
        print(f"  Std:              {np.std(actions_d_rate):.4f}")
        print(f"  Zeros:            {np.sum(np.array(actions_d_rate) == 0)} ({100*np.sum(np.array(actions_d_rate) == 0)/len(actions_d_rate):.1f}%)")
    
    print("="*60 + "\n")

def main():
    parser = argparse.ArgumentParser(description="RL 학습 과정 시각화")
    parser.add_argument('--log', type=str, required=True, help='RL 로그 파일 경로 (.jsonl)')
    parser.add_argument('--output-dir', type=str, default='./rl_training_plots', help='출력 디렉토리')
    parser.add_argument('--episode-len', type=int, default=100, help='에피소드 길이 (스텝 수)')
    args = parser.parse_args()
    
    # 출력 디렉토리 생성
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 로그 로드
    print(f"[*] Loading logs from: {args.log}")
    data = load_logs(args.log)
    print(f"[✓] Loaded {len(data)} steps")
    
    if len(data) < 10:
        print("[!] Not enough data to visualize")
        return
    
    # 1. 학습 곡선
    print("\n[*] Generating Training Curve...")
    episodes, rewards_mean, rewards_std = compute_episode_rewards(data, args.episode_len)
    if episodes:
        plot_training_curve(episodes, rewards_mean, rewards_std, 
                          output_dir / 'training_curve.png')
    
    # 2. P99 감소 추이
    print("[*] Generating P99 Reduction Plot...")
    steps_p99, p99_vals = compute_p99_trend(data)
    if len(steps_p99) > 0:
        plot_p99_reduction(steps_p99, p99_vals, 
                         output_dir / 'p99_reduction.png')
    
    # 3. 행동 분포 변화
    print("[*] Generating Action Distribution Plot...")
    early_dist, late_dist = compute_action_distribution(data)
    if early_dist['d_rate'] and late_dist['d_rate']:
        plot_action_distribution(early_dist, late_dist, 
                               output_dir / 'action_distribution.png')
    
    # 4. 정책 엔트로피
    print("[*] Generating Policy Entropy Plot...")
    steps_ent, entropies = compute_entropy_trend(data)
    if entropies:
        plot_policy_entropy(steps_ent, entropies, 
                          output_dir / 'policy_entropy.png')
    
    # 5. TD 오차 대리지표
    print("[*] Generating TD Error Plot...")
    steps_td, td_errors = compute_td_error_proxy(data)
    if td_errors:
        plot_td_error(steps_td, td_errors, 
                     output_dir / 'td_error.png')
    
    # 통계 요약
    generate_summary_stats(data)
    
    print(f"\n[✓] All plots saved to: {output_dir}")
    print("\n[Usage]")
    print(f"  View plots: ls {output_dir}/*.png")
    print(f"  Example: eog {output_dir}/training_curve.png")

if __name__ == '__main__':
    main()
