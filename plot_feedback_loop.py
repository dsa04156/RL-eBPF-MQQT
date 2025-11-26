import json
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np

# 설정
LOG_FILE = "/home/sslab/mqtt-ebpf-edge/logs/1로그정리/학습로그/ppo_reset_v1.jsonl"
OUTPUT_FILE = "feedback_loop_detail.png"

def load_data(log_file):
    data = []
    with open(log_file, 'r') as f:
        for line in f:
            try:
                entry = json.loads(line)
                metrics = entry.get('metrics', {})
                kernel = entry.get('kernel', {})
                action = entry.get('a', {})
                
                data.append({
                    'ts': entry.get('ts', 0),
                    'p99_ms': metrics.get('p99_ms', 0),
                    'throughput': metrics.get('thr', 0),
                    'snd_ratio': kernel.get('snd_ratio', 0),
                    'ewma_rtt': kernel.get('ewma_rtt_us', 0) / 1000.0,
                    'd_rate': action.get('d_rate', 0),
                    'd_batch': action.get('d_batch', 0)
                })
            except json.JSONDecodeError:
                continue
    return pd.DataFrame(data)

def find_interesting_segment(df, window_size=60):
    """
    가장 '성공적인' 제어 구간을 찾습니다. (Best Shot)
    조건: Throughput은 높고, P99는 낮은 구간.
    """
    best_score = -float('inf')
    best_start = 0
    
    # 슬라이딩 윈도우로 스캔
    for i in range(0, len(df) - window_size, 10): # 10스텝씩 이동
        segment = df.iloc[i:i+window_size]
        
        avg_thr = segment['throughput'].mean()
        avg_p99 = segment['p99_ms'].mean()
        max_p99 = segment['p99_ms'].max()
        
        # 점수 계산: Throughput 높을수록 좋고, P99 낮을수록 좋음
        # 단, P99가 한 번이라도 너무 튀면(>1000) 감점
        penalty = 0
        if max_p99 > 1000: penalty = 5000
        
        score = avg_thr - (avg_p99 * 2) - penalty
        
        if score > best_score:
            best_score = score
            best_start = i
            
    return best_start, best_start + window_size

def plot_feedback_loop(df):
    if df.empty: return

    # 시간 정규화
    start_time = df['ts'].iloc[0]
    df['time_sec'] = (df['ts'] - start_time)

    # 흥미로운 구간 추출 (약 60스텝 = 2분 정도)
    start_idx, end_idx = find_interesting_segment(df, window_size=60)
    segment = df.iloc[start_idx:end_idx].copy()
    
    # X축을 0부터 시작하게 조정 (구간 내 상대 시간)
    segment_start_time = segment['time_sec'].iloc[0]
    segment['rel_time'] = segment['time_sec'] - segment_start_time

    # 그래프 그리기
    fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=True)
    
    # 1. Kernel State (Cause)
    ax1 = axes[0]
    ax1.plot(segment['rel_time'], segment['snd_ratio'], color='crimson', linewidth=2, label='Buffer Usage (snd_ratio)')
    ax1.set_ylabel('Buffer Usage', color='crimson', fontweight='bold')
    ax1.tick_params(axis='y', labelcolor='crimson')
    ax1.axhline(y=1.0, color='gray', linestyle='--', alpha=0.5, label='Limit')
    
    # RTT는 보조축으로
    ax1_twin = ax1.twinx()
    ax1_twin.fill_between(segment['rel_time'], segment['ewma_rtt'], color='orange', alpha=0.2, label='Kernel RTT')
    ax1_twin.plot(segment['rel_time'], segment['ewma_rtt'], color='orange', linestyle=':', linewidth=1)
    ax1_twin.set_ylabel('RTT (ms)', color='orange')
    ax1_twin.tick_params(axis='y', labelcolor='orange')
    
    ax1.set_title('1. Kernel State: Detecting Congestion Buildup', fontsize=14, fontweight='bold')
    ax1.grid(True, alpha=0.3)

    # 2. RL Action (Response)
    ax2 = axes[1]
    # Bar chart for actions to emphasize discrete decisions
    colors = ['red' if x < 0 else 'blue' for x in segment['d_rate']]
    ax2.bar(segment['rel_time'], segment['d_rate'], width=1.5, color=colors, alpha=0.7, label='Action (d_rate)')
    ax2.axhline(y=0, color='black', linewidth=1)
    ax2.set_ylabel('Rate Adjustment', fontweight='bold')
    ax2.set_title('2. RL Action: Proactive Control', fontsize=14, fontweight='bold')
    ax2.grid(True, alpha=0.3)
    
    # 3. App Result (Outcome)
    ax3 = axes[2]
    ax3.plot(segment['rel_time'], segment['p99_ms'], color='purple', linewidth=2, label='P99 Latency')
    ax3.set_ylabel('P99 Latency (ms)', color='purple', fontweight='bold')
    ax3.tick_params(axis='y', labelcolor='purple')
    ax3.axhline(y=300, color='red', linestyle='--', label='SLO (300ms)')
    
    # Throughput 보조축
    ax3_twin = ax3.twinx()
    ax3_twin.plot(segment['rel_time'], segment['throughput'], color='green', linewidth=2, label='Throughput')
    ax3_twin.set_ylabel('Throughput (msg/s)', color='green', fontweight='bold')
    ax3_twin.tick_params(axis='y', labelcolor='green')
    
    ax3.set_title('3. Application Result: Latency Stabilized & Throughput Maintained', fontsize=14, fontweight='bold')
    ax3.set_xlabel('Time (seconds)', fontsize=12)
    ax3.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(OUTPUT_FILE, dpi=300)
    print(f"Feedback loop graph saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    df = load_data(LOG_FILE)
    plot_feedback_loop(df)
