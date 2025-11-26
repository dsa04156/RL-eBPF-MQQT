import json
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import matplotlib
import matplotlib.font_manager as fm
import os

LOG_FILE = "ppo_train.jsonl"  # 현재 디렉토리에 있음
SLO_MS = 300.0
TARGET_THR = 50000.0

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
    'font.size': 14,
    'axes.titlesize': 18,
    'axes.labelsize': 16,
    'xtick.labelsize': 14,
    'ytick.labelsize': 14,
    'legend.fontsize': 14,
    'figure.figsize': (12, 8),
    'lines.linewidth': 2.5
})

# ==========================================
# 2. 데이터 로딩 및 전처리
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
df['rtt'] = df.apply(lambda r: safe_get_kernel(r, 'ewma_rtt_us', 0.0) / 1000.0, axis=1)  # ms로 변환
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

# -------------------------------------------------
# P99 / Throughput 클리핑 + 스무딩을 위한 추가 전처리
# -------------------------------------------------
# 유효한 구간만 선택 (p99>0, window>0)
mask_valid = (df['p99'] > 0) & (df['window'] > 0)
# mode/online 만 보고 싶으면 주석 해제
# if 'mode' in df.columns:
#     mask_valid &= (df['mode'] == 'online')

df_perf = df[mask_valid].copy()

if not df_perf.empty:
    # 상위 1% 기준으로 이상치 잘라냄
    p99_q99 = df_perf['p99'].quantile(0.99)
    thr_q99 = df_perf['throughput'].quantile(0.99)

    # 너무 작게 잡히면 최소 기준 부여
    p99_clip_max = max(p99_q99, SLO_MS * 4)        # 최소 4*SLO
    thr_clip_max = max(thr_q99, TARGET_THR * 1.2)  # 최소 타깃의 1.2배

    df_perf['p99_clip'] = df_perf['p99'].clip(upper=p99_clip_max)
    df_perf['thr_clip'] = df_perf['throughput'].clip(upper=thr_clip_max)

    # 롤링 평균으로 스무딩
    df_perf['p99_smooth'] = df_perf['p99_clip'].rolling(window=20, min_periods=1).mean()
    df_perf['thr_smooth'] = df_perf['thr_clip'].rolling(window=20, min_periods=1).mean()
else:
    # 비어 있으면 나중에 그래프 그릴 때 그냥 원본 사용
    p99_clip_max = None
    thr_clip_max = None

print("[DEBUG] 3. 그래프 그리기 시작 전 font.family =", matplotlib.rcParams.get('font.family'))

# ==========================================
# (1) 학습 수렴 곡선
# ==========================================
print("[DEBUG] (1) figure 전 font.family =", matplotlib.rcParams.get('font.family'))
plt.figure(figsize=(10, 6))
print("[DEBUG] (1) figure 후 font.family =", matplotlib.rcParams.get('font.family'))

plt.plot(df['time'], df['r'], color='lightgray', alpha=0.5, label='Raw Reward')
plt.plot(df['time'], df['reward_smooth'], color='#1f77b4', label='Smoothed Reward (Trend)')
plt.axhline(y=0, color='black', linestyle='--', linewidth=1)
plt.xlabel("시간 (초)")
plt.ylabel("보상 (Reward)")
plt.title("(a) 학습 수렴 곡선 (Learning Curve)")
plt.legend()
plt.tight_layout()
plt.savefig("graph_1_learning_curve.png", dpi=300)

print("[DEBUG] (1) 저장 후 font.family =", matplotlib.rcParams.get('font.family'))

# ==========================================
# (2) 성능 트레이드오프: P99 vs Throughput
#      (이상치 클리핑 + 스무딩 적용)
# ==========================================
if df_perf.empty:
    print("[WARN] df_perf가 비어 있어 원본 데이터로 성능 그래프를 그림")
    _df2 = df
    use_smooth = False
else:
    _df2 = df_perf
    use_smooth = True

fig, ax1 = plt.subplots(figsize=(12, 6))
color_lat = '#d62728'
color_thr = '#1f77b4'

ax1.set_xlabel("시간 (초)")
ax1.set_ylabel("P99 지연 시간 (ms)", color=color_lat)

if use_smooth:
    l1 = ax1.plot(_df2['time'], _df2['p99_smooth'],
                  color=color_lat, alpha=0.9,
                  label='P99 Latency (smoothed)')
else:
    l1 = ax1.plot(_df2['time'], _df2['p99'],
                  color=color_lat, alpha=0.8,
                  label='P99 Latency')

ax1.tick_params(axis='y', labelcolor=color_lat)
ax1.axhline(y=SLO_MS, color='red', linestyle='--', linewidth=2, label='SLO 목표 (300ms)')

# y축 범위 설정
if p99_clip_max is not None:
    ax1.set_ylim(0, p99_clip_max * 1.05)

ax2 = ax1.twinx()
ax2.set_ylabel("처리량 (msg/s)", color=color_thr)

if use_smooth:
    l2 = ax2.plot(_df2['time'], _df2['thr_smooth'],
                  color=color_thr, alpha=0.8,
                  label='Throughput (smoothed)')
else:
    l2 = ax2.plot(_df2['time'], _df2['throughput'],
                  color=color_thr, alpha=0.6,
                  label='Throughput')

ax2.tick_params(axis='y', labelcolor=color_thr)

if thr_clip_max is not None:
    ax2.set_ylim(0, thr_clip_max * 1.05)

# 범례 구성
lines = l1 + l2 + [ax1.get_lines()[-1]]  # SLO 라인 포함
labels = [l.get_label() for l in lines]
ax1.legend(lines, labels, loc='upper right')

plt.title("(b) 성능 최적화: 지연 시간 준수 및 처리량 유지")
plt.tight_layout()
plt.savefig("graph_2_performance.png", dpi=300)
print("[완료] graph_2_performance.png")

# ==========================================
# (3) 제어 행동 분석: Throttle rate 타임라인
# ==========================================
plt.figure(figsize=(12, 5))
plt.step(df['time'], df['rate'], where='post', color='#2ca02c', label='Throttle Rate')
plt.xlabel("시간 (초)")
plt.ylabel("발행 속도 (msg/s)")
plt.title("(c) 에이전트 제어 행동 (Control Action)")
plt.grid(True, alpha=0.3)
plt.legend()
plt.tight_layout()
plt.savefig("graph_3_control_action.png", dpi=300)
print("[완료] graph_3_control_action.png")

# ==========================================
# (4) 인과관계: snd_ratio vs P99 (클리핑/스무딩 적용)
# ==========================================
if not df_perf.empty:
    df4 = df_perf
else:
    df4 = df

fig, ax1 = plt.subplots(figsize=(12, 6))
color_buf = '#ff7f0e'
color_lat = '#d62728'

ax1.set_xlabel("시간 (초)")
ax1.set_ylabel("커널 송신 버퍼 비율 (Snd Ratio)", color=color_buf)
ax1.plot(df4['time'], df4['snd_ratio'], color=color_buf, label='Snd Buffer Ratio')
ax1.tick_params(axis='y', labelcolor=color_buf)
ax1.set_ylim(0, 1.1)

ax2 = ax1.twinx()
ax2.set_ylabel("P99 지연 시간 (ms)", color=color_lat)

if 'p99_smooth' in df4.columns:
    ax2.plot(df4['time'], df4['p99_smooth'],
             color=color_lat, alpha=0.7, label='P99 Latency (smoothed)')
else:
    ax2.plot(df4['time'], df4['p99'],
             color=color_lat, alpha=0.6, label='P99 Latency')

ax2.tick_params(axis='y', labelcolor=color_lat)
if p99_clip_max is not None:
    ax2.set_ylim(0, p99_clip_max * 1.05)

plt.title("(d) eBPF 커널 신호와 지연 시간의 상관관계")
fig.legend(loc="upper right", bbox_to_anchor=(0.9, 0.9))
plt.tight_layout()
plt.savefig("graph_4_causality.png", dpi=300)
print("[완료] graph_4_causality.png")
