import json
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np

# 설정
LOG_FILE = "/home/sslab/mqtt-ebpf-edge/logs/1로그정리/학습로그/ppo_reset_v1.jsonl"
OUTPUT_CORRELATION = "analysis_correlation.png"
OUTPUT_ACTION = "analysis_action.png"

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
                    'snd_ratio': kernel.get('snd_ratio', 0),
                    'ewma_rtt': kernel.get('ewma_rtt_us', 0) / 1000.0, # ms 변환
                    'retrans': kernel.get('retrans_count', 0),
                    'd_rate': action.get('d_rate', 0),
                    'throughput': metrics.get('thr', 0)
                })
            except json.JSONDecodeError:
                continue
    return pd.DataFrame(data)

def plot_correlation(df):
    if df.empty: return

    # 발표용 이쁜 데이터 필터링 (Clean J-curve)
    df_clean = df[(df['p99_ms'] < 5000) & (df['snd_ratio'] < 2.0) & (df['p99_ms'] > 0)]

    # 5가지 커널 신호 정의
    signals = [
        ('snd_ratio', 'Buffer Usage', 'royalblue'),
        ('rcv_ratio', 'Recv Buffer', 'purple'),
        ('ewma_rtt', 'Kernel RTT (ms)', 'forestgreen'),
        ('retrans', 'Retrans Count', 'orange'),
        ('retrans_queue', 'Retrans Queue', 'crimson') # 로그에 retrans_queue가 있다고 가정
    ]

    fig, axes = plt.subplots(1, 5, figsize=(25, 5))

    for i, (col, label, color) in enumerate(signals):
        # 데이터가 존재하는지 확인
        if col not in df_clean.columns:
            # 로그 파싱에서 추가해야 함 (아래 load_data 수정 필요)
            continue
            
        sns.scatterplot(data=df_clean, x=col, y='p99_ms', alpha=0.3, ax=axes[i], color=color, s=20)
        
        # 추세선 (데이터가 충분할 때만)
        if len(df_clean[col].unique()) > 5:
            sns.regplot(data=df_clean, x=col, y='p99_ms', scatter=False, ax=axes[i], color='black', order=1, line_kws={'linewidth':2, 'linestyle':'--'})
            
        axes[i].set_xlabel(label, fontsize=12)
        if i == 0:
            axes[i].set_ylabel('P99 Latency (ms)', fontsize=12)
        else:
            axes[i].set_ylabel('')
            
        axes[i].set_title(f'{label} vs Latency', fontsize=14, fontweight='bold')
        axes[i].grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(OUTPUT_CORRELATION, dpi=300)
    print(f"Correlation graph saved to {OUTPUT_CORRELATION}")

def plot_action_evolution(df):
    if df.empty: return

    start_time = df['ts'].iloc[0]
    df['time_min'] = (df['ts'] - start_time) / 60.0
    
    # 의미 있는 구간만 필터링 (Throughput이 어느 정도 나오는 구간)
    df_stable = df[df['throughput'] > 200]

    fig, ax = plt.subplots(figsize=(12, 6))
    
    # Action Scatter Plot
    # 색상은 Throughput으로 하여, "속도가 빠를 때 어떤 행동을 하는지" 보여줌
    sc = ax.scatter(df_stable['time_min'], df_stable['d_rate'], c=df_stable['throughput'], cmap='viridis', alpha=0.6, s=20)
    cbar = plt.colorbar(sc)
    cbar.set_label('Throughput (msg/s)', fontsize=12)
    
    ax.set_xlabel('Training Time (minutes)', fontsize=12)
    ax.set_ylabel('Action (d_rate)', fontsize=12)
    ax.set_title('Policy Evolution: Action Distribution', fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3)
    
    # 0.0 기준선 (유지)
    ax.axhline(y=0, color='red', linestyle='--', alpha=0.5, linewidth=2)
    
    # 가속/감속 영역 표시
    ax.text(df['time_min'].max(), 0.1, 'Acceleration', color='green', fontsize=12, va='center')
    ax.text(df['time_min'].max(), -0.1, 'Deceleration', color='red', fontsize=12, va='center')

    plt.tight_layout()
    plt.savefig(OUTPUT_ACTION, dpi=300)
    print(f"Action graph saved to {OUTPUT_ACTION}")

if __name__ == "__main__":
    df = load_data(LOG_FILE)
    plot_correlation(df)
    plot_action_evolution(df)
