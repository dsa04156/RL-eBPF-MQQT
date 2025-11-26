import json
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import os

# 설정
LOG_FILE = "/home/sslab/mqtt-ebpf-edge/logs/1로그정리/학습로그/ppo_reset_v1.jsonl"
OUTPUT_FILE = "training_results.png"
TARGET_THR = 1600
SLO_P99 = 300

def load_data(log_file):
    data = []
    with open(log_file, 'r') as f:
        for line in f:
            try:
                entry = json.loads(line)
                # 필요한 데이터 추출
                ts = entry.get('ts', 0)
                reward = entry.get('r', 0)
                
                metrics = entry.get('metrics', {})
                thr = metrics.get('thr', 0)
                p99 = metrics.get('p99_ms', 0)
                
                kernel = entry.get('kernel', {})
                snd_ratio = kernel.get('snd_ratio', 0)
                
                data.append({
                    'ts': ts,
                    'reward': reward,
                    'throughput': thr,
                    'p99_ms': p99,
                    'snd_ratio': snd_ratio
                })
            except json.JSONDecodeError:
                continue
    return pd.DataFrame(data)

def plot_training(df):
    if df.empty:
        print("No data found.")
        return

    # 시간 정규화 (분 단위)
    start_time = df['ts'].iloc[0]
    df['time_min'] = (df['ts'] - start_time) / 60.0
    
    # 이상치 필터링 (그래프 왜곡 방지)
    # P99가 5000ms(5초) 넘는 건 학습 초기 불안정으로 간주하고 클리핑
    df['p99_ms'] = df['p99_ms'].clip(upper=5000)
    
    # 이동 평균 (부드러운 그래프를 위해)
    window_size = 50 # 윈도우 사이즈 키움
    df['reward_ma'] = df['reward'].rolling(window=window_size, min_periods=1).mean()
    df['thr_ma'] = df['throughput'].rolling(window=window_size, min_periods=1).mean()
    df['p99_ma'] = df['p99_ms'].rolling(window=window_size, min_periods=1).mean()

    # 그래프 설정 (Reward 위주)
    fig, axes = plt.subplots(3, 1, figsize=(10, 12), sharex=True)
    
    # 1. Reward (Main)
    ax1 = axes[0]
    # ax1.plot(df['time_min'], df['reward'], alpha=0.1, color='gray') # Raw 데이터는 너무 지저분하면 뺌
    ax1.plot(df['time_min'], df['reward_ma'], color='blue', linewidth=2, label='Average Reward')
    ax1.set_ylabel('Reward')
    ax1.set_title('Learning Curve (Reward Convergence)')
    ax1.legend(loc='lower right')
    ax1.grid(True, alpha=0.3)

    # 2. Throughput (Goal: 1600)
    ax2 = axes[1]
    ax2.plot(df['time_min'], df['throughput'], alpha=0.1, color='green')
    ax2.plot(df['time_min'], df['thr_ma'], color='darkgreen', linewidth=2, label='Throughput (MA)')
    ax2.axhline(y=TARGET_THR, color='red', linestyle='--', label=f'Target ({TARGET_THR})')
    ax2.set_ylabel('Throughput (msg/s)')
    ax2.set_title('Throughput Improvement')
    ax2.legend(loc='lower right')
    ax2.grid(True, alpha=0.3)

    # 3. Latency (Constraint: < 300ms)
    ax3 = axes[2]
    ax3.plot(df['time_min'], df['p99_ms'], alpha=0.1, color='orange')
    ax3.plot(df['time_min'], df['p99_ma'], color='darkorange', linewidth=2, label='P99 Latency (MA)')
    ax3.axhline(y=SLO_P99, color='red', linestyle='--', label=f'SLO ({SLO_P99}ms)')
    ax3.set_ylabel('P99 Latency (ms)')
    ax3.set_xlabel('Training Time (minutes)')
    ax3.set_title('Latency Stability')
    ax3.legend(loc='upper right')
    ax3.grid(True, alpha=0.3)
    ax3.set_ylim(0, 1000) # 1초까지만 보여줌 (디테일 확인용)

    plt.tight_layout()
    plt.savefig(OUTPUT_FILE, dpi=300)
    print(f"Graph saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    df = load_data(LOG_FILE)
    plot_training(df)
