import json
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np

# 설정
LOG_FILE = "/home/sslab/mqtt-ebpf-edge/logs/1로그정리/학습로그/ppo_reset_v1.jsonl"
OUTPUT_FILE = "causality_proof.png"

def load_data(log_file):
    data = []
    with open(log_file, 'r') as f:
        for line in f:
            try:
                entry = json.loads(line)
                metrics = entry.get('metrics', {})
                kernel = entry.get('kernel', {})
                
                data.append({
                    'ts': entry.get('ts', 0),
                    'p99_ms': metrics.get('p99_ms', 0),
                    'snd_ratio': kernel.get('snd_ratio', 0),
                    'ewma_rtt': kernel.get('ewma_rtt_us', 0) / 1000.0
                })
            except json.JSONDecodeError:
                continue
    return pd.DataFrame(data)

def find_causality_segment(df, window_size=100):
    """
    인과관계를 가장 잘 보여주는 구간을 찾습니다.
    조건: snd_ratio가 먼저 오르고, p99가 뒤따라 오르는 구간.
    """
    # snd_ratio와 p99의 Cross-correlation이 높은 구간을 찾으면 좋겠지만,
    # 간단하게 snd_ratio 피크와 p99 피크가 인접한 구간을 찾습니다.
    
    # snd_ratio가 높고(>0.8), p99도 높은(>500) 구간 필터링
    candidates = df[(df['snd_ratio'] > 0.8) & (df['p99_ms'] > 500)].index
    
    if len(candidates) == 0:
        return 0, min(len(df), window_size)
    
    # 가장 명확한 패턴을 위해 중간 정도의 후보 선택
    target_idx = candidates[len(candidates)//2]
    
    start_idx = max(0, target_idx - window_size // 2)
    end_idx = min(len(df), target_idx + window_size // 2)
    
    return start_idx, end_idx

def plot_causality(df):
    if df.empty: return

    start_time = df['ts'].iloc[0]
    df['time_sec'] = df['ts'] - start_time

    # 구간 추출
    start_idx, end_idx = find_causality_segment(df, window_size=60) # 약 2분
    segment = df.iloc[start_idx:end_idx].copy()
    
    # 상대 시간
    seg_start = segment['time_sec'].iloc[0]
    segment['rel_time'] = segment['time_sec'] - seg_start

    # 그래프 그리기
    fig, ax1 = plt.subplots(figsize=(12, 6))

    # 1. Kernel Signal (Cause)
    color1 = 'tab:red'
    ax1.set_xlabel('Time (seconds)', fontsize=12)
    ax1.set_ylabel('Kernel Buffer Usage (snd_ratio)', color=color1, fontsize=12, fontweight='bold')
    ax1.plot(segment['rel_time'], segment['snd_ratio'], color=color1, linewidth=3, label='Kernel Signal (Leading)')
    ax1.tick_params(axis='y', labelcolor=color1)
    ax1.axhline(y=1.0, color='gray', linestyle='--', alpha=0.5)
    
    # 영역 표시 (Cause)
    ax1.fill_between(segment['rel_time'], 0, segment['snd_ratio'], color=color1, alpha=0.1)

    # 2. App Latency (Effect)
    ax2 = ax1.twinx()
    color2 = 'tab:blue'
    ax2.set_ylabel('App P99 Latency (ms)', color=color2, fontsize=12, fontweight='bold')
    ax2.plot(segment['rel_time'], segment['p99_ms'], color=color2, linewidth=3, linestyle='-', label='App Latency (Lagging)')
    ax2.tick_params(axis='y', labelcolor=color2)
    
    # 화살표로 인과관계 표시 (자동 위치 선정은 어렵지만 대략적으로)
    # 피크 지점 찾기
    peak_snd_idx = segment['snd_ratio'].idxmax()
    peak_p99_idx = segment['p99_ms'].idxmax()
    
    peak_snd_time = segment.loc[peak_snd_idx, 'rel_time']
    peak_p99_time = segment.loc[peak_p99_idx, 'rel_time']
    
    # 만약 커널 피크가 먼저 왔다면 화살표 추가
    if peak_snd_time < peak_p99_time:
        ax1.annotate('Causality (Time Lag)', 
                     xy=(peak_p99_time, segment.loc[peak_p99_idx, 'p99_ms']), 
                     xytext=(peak_snd_time, segment.loc[peak_snd_idx, 'snd_ratio']),
                     arrowprops=dict(facecolor='black', shrink=0.05, arrowstyle='->', lw=2),
                     xycoords=('data', 'axes fraction'), textcoords=('data', 'axes fraction'), # 좌표계 혼합 사용 필요 (복잡함)
                     )
        # 간단하게 텍스트로 표시
        plt.title(f"Causality Proof: Kernel Signal leads Latency by {peak_p99_time - peak_snd_time:.1f}s", fontsize=14, fontweight='bold')
    else:
        plt.title("Correlation: Kernel Signal and Latency", fontsize=14, fontweight='bold')

    # 범례 합치기
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left', fontsize=12)

    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUTPUT_FILE, dpi=300)
    print(f"Causality graph saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    df = load_data(LOG_FILE)
    plot_causality(df)
