#!/usr/bin/env python3
"""
PPO 학습 로그 시각화 스크립트
학습이 잘 수렴했는지 확인하는 그래프 생성
"""

import json
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import matplotlib
import matplotlib.font_manager as fm
import os

LOG_FILE = "ppo_train.jsonl"
SLO_MS = 300.0

# -------------------------------------------------
# 폰트 설정
# -------------------------------------------------
nanum_path = "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"

if os.path.exists(nanum_path):
    fontprop = fm.FontProperties(fname=nanum_path)
    nanum_name = fontprop.get_name()
    print(f"[FONT] Using: {nanum_name}")
else:
    nanum_name = "DejaVu Sans"
    print("[FONT] NanumGothic not found, fallback to DejaVu Sans")

# 스타일 및 폰트 설정
plt.style.use('seaborn-v0_8-whitegrid')
matplotlib.rcParams['font.family'] = nanum_name
matplotlib.rcParams['axes.unicode_minus'] = False
plt.rcParams.update({
    'font.size': 12,
    'axes.titlesize': 14,
    'axes.labelsize': 12,
    'xtick.labelsize': 11,
    'ytick.labelsize': 11,
    'legend.fontsize': 10,
    'figure.figsize': (12, 8),
    'lines.linewidth': 2
})

# ==========================================
# 데이터 로딩 및 전처리
# ==========================================
data = []
try:
    with open(LOG_FILE, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data.append(json.loads(line))
            except Exception:
                pass
except FileNotFoundError:
    print(f"오류: {LOG_FILE} 파일을 찾을 수 없습니다.")
    raise SystemExit(1)

if not data:
    print("데이터가 비어있습니다.")
    raise SystemExit(1)

df = pd.DataFrame(data)
print(f"[INFO] 로드된 샘플 수: {len(df)}")

# ts 기준 상대 시간 (분 단위)
start_ts = df['ts'].iloc[0]
df['time_sec'] = df['ts'] - start_ts
df['time_min'] = df['time_sec'] / 60.0

# 에피소드/스텝 번호
df['step'] = range(len(df))

# metrics / kernel 안전 파싱
def safe_get_metrics(row, key, default=0.0):
    m = row.get("metrics", {})
    if not isinstance(m, dict):
        return default
    val = m.get(key, default)
    return val if val is not None else default

def safe_get_kernel(row, key, default=0.0):
    k = row.get("kernel", {})
    if not isinstance(k, dict):
        return default
    return k.get(key, default)

df['p99'] = df.apply(lambda r: safe_get_metrics(r, 'p99_ms', 0.0), axis=1)
df['p95'] = df.apply(lambda r: safe_get_metrics(r, 'p95_ms', 0.0), axis=1)
df['p50'] = df.apply(lambda r: safe_get_metrics(r, 'p50_ms', 0.0), axis=1)
df['n'] = df.apply(lambda r: safe_get_metrics(r, 'n', 0.0), axis=1)
df['window'] = df.apply(lambda r: safe_get_metrics(r, 'window_sec', 1.0), axis=1)
df['throughput'] = df.apply(
    lambda r: (r['n'] / r['window']) if r['window'] and r['window'] > 0 else 0.0,
    axis=1,
)
df['snd_ratio'] = df.apply(lambda r: safe_get_kernel(r, 'snd_ratio', 0.0), axis=1)
df['rtt'] = df.apply(lambda r: safe_get_kernel(r, 'ewma_rtt_us', 0.0) / 1000.0, axis=1)
df['retrans_count'] = df.apply(lambda r: safe_get_kernel(r, 'retrans_count', 0.0), axis=1)

# Action 추출
def get_action(row, key):
    a = row.get('a', {})
    if not isinstance(a, dict):
        return 0.0
    return a.get(key, 0.0)

df['d_rate'] = df.apply(lambda r: get_action(r, 'd_rate'), axis=1)
df['d_batch'] = df.apply(lambda r: get_action(r, 'd_batch'), axis=1)

# throttle rate 추출
def get_rate(row):
    if row.get('applied') and row.get('cmds'):
        for c in row['cmds']:
            if c.get('cmd') == 'throttle':
                return c.get('rate')
    return None

df['rate'] = df.apply(get_rate, axis=1)
df['rate'] = df['rate'].ffill().fillna(0)

# 보상 smoothing (학습 수렴 확인용)
if 'r' in df.columns:
    df['reward_raw'] = df['r']
    df['reward_smooth'] = df['r'].rolling(window=10, min_periods=1).mean()
    df['reward_cumsum'] = df['r'].cumsum()
else:
    df['reward_raw'] = 0.0
    df['reward_smooth'] = 0.0
    df['reward_cumsum'] = 0.0

print(f"[INFO] 시간 범위: {df['time_min'].min():.1f} ~ {df['time_min'].max():.1f} 분")
print(f"[INFO] 평균 보상: {df['reward_raw'].mean():.3f}")
print(f"[INFO] 최종 보상 (마지막 10개 평균): {df['reward_raw'].tail(10).mean():.3f}")

# ==========================================
# 학습 결과 시각화 (4-panel)
# ==========================================

fig = plt.figure(figsize=(16, 10))

# (1) 학습 수렴 곡선 - Reward
ax1 = plt.subplot(2, 2, 1)
ax1.plot(df['step'], df['reward_raw'], color='lightgray', alpha=0.4, linewidth=1, label='Raw Reward')
ax1.plot(df['step'], df['reward_smooth'], color='#1f77b4', linewidth=2.5, label='Moving Avg (10 steps)')
ax1.axhline(y=0, color='black', linestyle='--', linewidth=1, alpha=0.5)
ax1.set_xlabel("Training Step")
ax1.set_ylabel("Reward")
ax1.set_title("(a) 학습 수렴: 보상 추이 (Reward Convergence)")
ax1.legend(loc='lower right')
ax1.grid(True, alpha=0.3)

# (2) P99 지연 시간 감소
ax2 = plt.subplot(2, 2, 2)
# None 값 필터링
p99_valid = df[df['p99'] > 0]['p99']
step_valid = df[df['p99'] > 0]['step']
if len(p99_valid) > 0:
    ax2.plot(step_valid, p99_valid, color='#d62728', linewidth=2, alpha=0.7, label='P99 Latency')
    ax2.axhline(y=SLO_MS, color='red', linestyle='--', linewidth=2, label=f'SLO Target ({SLO_MS}ms)')
    # 로그 스케일로 변경 (더 명확한 감소 추세)
    ax2.set_yscale('log')
    ax2.set_ylabel("P99 Latency (ms, log scale)")
else:
    ax2.text(0.5, 0.5, 'No P99 data', ha='center', va='center', transform=ax2.transAxes)
    ax2.set_ylabel("P99 Latency (ms)")
ax2.set_xlabel("Training Step")
ax2.set_title("(b) P99 지연 시간 감소 (Latency Reduction)")
ax2.legend(loc='upper right')
ax2.grid(True, alpha=0.3)

# (3) 액션 분포 - d_rate와 d_batch
ax3 = plt.subplot(2, 2, 3)
# d_rate 히스토그램
ax3.hist(df['d_rate'], bins=30, alpha=0.6, color='#2ca02c', label='d_rate', edgecolor='black')
ax3.set_xlabel("Action Value (d_rate)")
ax3.set_ylabel("Frequency")
ax3.set_title("(c) 액션 분포: 속도 조정 (d_rate Distribution)")
ax3.legend()
ax3.grid(True, alpha=0.3, axis='y')

# (4) 누적 보상 (Cumulative Reward)
ax4 = plt.subplot(2, 2, 4)
ax4.plot(df['step'], df['reward_cumsum'], color='#9467bd', linewidth=2.5)
ax4.set_xlabel("Training Step")
ax4.set_ylabel("Cumulative Reward")
ax4.set_title("(d) 누적 보상 증가 (Cumulative Reward Growth)")
ax4.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig("ppo_training_results.png", dpi=300, bbox_inches='tight')
print(f"[완료] ppo_training_results.png 저장 완료 ({len(df)} steps)")

# ==========================================
# 추가 분석 그래프 (개별 저장)
# ==========================================

# (5) 제어 행동 타임라인 (시간축)
plt.figure(figsize=(14, 5))
plt.step(df['time_min'], df['rate'], where='post', color='#2ca02c', linewidth=2, label='Throttle Rate')
plt.xlabel("Training Time (minutes)")
plt.ylabel("Throttle Rate (msg/s)")
plt.title("에이전트 제어 행동 타임라인 (Control Action Timeline)")
plt.grid(True, alpha=0.3)
plt.legend()
plt.tight_layout()
plt.savefig("control_timeline.png", dpi=300, bbox_inches='tight')
print("[완료] control_timeline.png")

# (6) 커널 신호 vs P99 (상관관계)
fig, ax1 = plt.subplots(figsize=(14, 6))
color_buf = '#ff7f0e'
color_lat = '#d62728'

ax1.set_xlabel("Training Step")
ax1.set_ylabel("Kernel snd_ratio", color=color_buf)
ax1.plot(df['step'], df['snd_ratio'], color=color_buf, linewidth=1.5, alpha=0.7, label='snd_ratio')
ax1.tick_params(axis='y', labelcolor=color_buf)
ax1.set_ylim(0, max(df['snd_ratio'].max() * 1.1, 0.1))

ax2 = ax1.twinx()
ax2.set_ylabel("P99 Latency (ms)", color=color_lat)
p99_plot = df[df['p99'] > 0]
if len(p99_plot) > 0:
    ax2.plot(p99_plot['step'], p99_plot['p99'], color=color_lat, linewidth=2, alpha=0.6, label='P99 Latency')
ax2.tick_params(axis='y', labelcolor=color_lat)

plt.title("커널 신호와 지연 시간 상관관계 (Kernel Signal vs Latency)")
fig.legend(loc="upper right", bbox_to_anchor=(0.95, 0.95))
plt.tight_layout()
plt.savefig("kernel_signal_correlation.png", dpi=300, bbox_inches='tight')
print("[완료] kernel_signal_correlation.png")

# ==========================================
# 학습 요약 통계
# ==========================================
print("\n" + "="*60)
print("학습 결과 요약 (Training Summary)")
print("="*60)
print(f"총 Training Steps: {len(df)}")
print(f"학습 시간: {df['time_min'].max():.1f} 분")
print(f"\n[보상 (Reward)]")
print(f"  초기 10 steps 평균: {df['reward_raw'].head(10).mean():.3f}")
print(f"  최종 10 steps 평균: {df['reward_raw'].tail(10).mean():.3f}")
print(f"  전체 평균: {df['reward_raw'].mean():.3f}")
print(f"  최대/최소: {df['reward_raw'].max():.3f} / {df['reward_raw'].min():.3f}")

p99_valid = df[df['p99'] > 0]['p99']
if len(p99_valid) > 10:
    print(f"\n[P99 지연시간 (ms)]")
    print(f"  초기 평균 (처음 10개): {p99_valid.head(10).mean():.1f} ms")
    print(f"  최종 평균 (마지막 10개): {p99_valid.tail(10).mean():.1f} ms")
    reduction = (1 - p99_valid.tail(10).mean() / p99_valid.head(10).mean()) * 100
    print(f"  개선율: {reduction:.1f}%")
    slo_rate = (p99_valid < SLO_MS).sum() / len(p99_valid) * 100
    print(f"  SLO({SLO_MS}ms) 달성률: {slo_rate:.1f}%")

print(f"\n[제어 행동]")
print(f"  Rate 범위: {df['rate'].min():.0f} ~ {df['rate'].max():.0f} msg/s")
print(f"  d_rate 평균: {df['d_rate'].mean():.3f}")
print(f"  d_rate 표준편차: {df['d_rate'].std():.3f}")
print(f"  가속(+) 비율: {(df['d_rate'] > 0).sum() / len(df) * 100:.1f}%")
print(f"  감속(-) 비율: {(df['d_rate'] < 0).sum() / len(df) * 100:.1f}%")

print("="*60)
print("\n생성된 그래프:")
print("  1. ppo_training_results.png - 4-panel 종합 결과")
print("  2. control_timeline.png - 제어 행동 타임라인")
print("  3. kernel_signal_correlation.png - 커널 신호 상관관계")
