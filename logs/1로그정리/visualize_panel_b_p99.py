#!/usr/bin/env python3
"""
Panel (b): 커널 신호 (RTT) ↔ P99 상관관계
"""
import json
import numpy as np
import matplotlib
from matplotlib import font_manager
import matplotlib.pyplot as plt
from pathlib import Path

# 한글 폰트 설정
font_path = '/usr/share/fonts/truetype/nanum/NanumGothic.ttf'
from matplotlib.font_manager import FontProperties
FONT_PROP = FontProperties(fname=font_path)
matplotlib.rcParams['font.family'] = 'NanumGothic'
matplotlib.rcParams['axes.unicode_minus'] = False
plt.rcParams['font.size'] = 11
plt.rcParams['axes.labelsize'] = 13
plt.rcParams['axes.titlesize'] = 16
plt.rcParams['legend.fontsize'] = 11
plt.rcParams['lines.linewidth'] = 2.5

def load_log(path):
    data = []
    with open(path) as f:
        for line in f:
            try:
                data.append(json.loads(line))
            except:
                continue
    return data

def moving_average(data, window=50):
    if len(data) < window:
        return data
    return np.convolve(data, np.ones(window)/window, mode='valid')

# 데이터 로드
log_path = Path('학습로그/ppo_reset_v1.jsonl')
print(f"로드: {log_path}")
data = load_log(log_path)
print(f"✓ {len(data)} steps")

# 데이터 추출
rtts = [d.get('kernel', {}).get('ewma_rtt_us', 0) / 1000.0 for d in data if 'kernel' in d]  # us -> ms
p99s = [d.get('metrics', {}).get('p99_ms', 0) for d in data if 'metrics' in d]

rtts = np.array(rtts)
p99s = np.array(p99s)

# 극값 제거
rtt_clip = np.percentile(rtts, 95)
p99_clip = np.percentile(p99s, 95)
rtts = np.clip(rtts, 0, rtt_clip)
p99s = np.clip(p99s, 0, p99_clip)

# Downsampling
rtts = rtts[::10]
p99s = p99s[::10]
steps = np.arange(len(rtts))
time_sec = steps * 2.0 * 10

# Smoothing
rtt_smooth = moving_average(rtts, window=50)
p99s_smooth = moving_average(p99s, window=50)
time_smooth = time_sec[:len(rtt_smooth)]

# ==================== 그래프 생성 (Dual Y-axis) ====================
fig, ax_rtt = plt.subplots(figsize=(6.5, 4.5))

color_rtt = '#9467bd'  # 보라
color_p99 = '#d62728'  # 빨강

# 왼쪽 Y축: RTT (마커=원)
markevery_main = max(1, len(time_smooth) // 35)
line1 = ax_rtt.plot(
    time_smooth,
    rtt_smooth,
    color=color_rtt,
    linewidth=2.5,
    label='RTT (커널 신호)',
    zorder=2,
    marker='o',
    markersize=4.2,
    markerfacecolor='white',
    markeredgecolor=color_rtt,
    markeredgewidth=1.0,
    markevery=markevery_main,
)

ax_rtt.set_xlabel('학습 시간 (초)', fontweight='bold', fontsize=13, fontproperties=FONT_PROP)
ax_rtt.set_ylabel('RTT (ms)', fontweight='bold', fontsize=13, color=color_rtt, fontproperties=FONT_PROP)
ax_rtt.tick_params(axis='y', labelcolor=color_rtt, labelsize=15)
ax_rtt.set_ylim(bottom=0)

# 오른쪽 Y축: P99 (마커=사각형)
ax_p99 = ax_rtt.twinx()
line2 = ax_p99.plot(
    time_smooth,
    p99s_smooth,
    color=color_p99,
    linewidth=2.5,
    alpha=0.9,
    label='P99 레이턴시',
    zorder=2,
    linestyle='--',
    marker='s',
    markersize=4.2,
    markerfacecolor='white',
    markeredgecolor=color_p99,
    markeredgewidth=1.0,
    markevery=markevery_main,
)

ax_p99.set_ylabel('P99 레이턴시 (ms)', fontweight='bold', fontsize=13, color=color_p99, fontproperties=FONT_PROP)
ax_p99.tick_params(axis='y', labelcolor=color_p99, labelsize=15)
ax_p99.set_ylim(bottom=0, top=min(max(p99s_smooth)*1.1, 5000))

# 제목
# 제목 제거 (사용자 요청)

# 범례 통합
lines = line1 + line2
labels = [l.get_label() for l in lines]
ax_rtt.legend(lines, labels, loc='upper right', fontsize=11, framealpha=0.95, edgecolor='gray', prop=FONT_PROP)
ax_rtt.grid(True, alpha=0.25, linestyle='--', linewidth=0.8)

# 상관계수 박스
min_len = min(len(rtts), len(p99s))
corr = np.corrcoef(rtts[:min_len], p99s[:min_len])[0,1]
textstr = f'상관계수: {corr:.3f}\n(RTT ↔ P99)'
fig.text(0.02, 0.97, textstr, fontsize=12, fontproperties=FONT_PROP,
     verticalalignment='top', bbox=dict(boxstyle='round', facecolor='white',
     alpha=0.9, edgecolor='gray', linewidth=2))

# ========== 확대 영역 (원본 데이터로 RTT 스파이크 → P99 지연) ==========
# 원본 데이터에서 RTT가 급등하는 구간 찾기
rtts_orig = np.array([d.get('kernel', {}).get('ewma_rtt_us', 0) / 1000.0 for d in data if 'kernel' in d])
p99s_orig = np.array([d.get('metrics', {}).get('p99_ms', 0) for d in data if 'metrics' in d])
times_orig = np.arange(len(rtts_orig)) * 2.0  # 2초 간격

# 원본 데이터에서 스파이크 찾기
rtt_diffs_orig = np.diff(rtts_orig)
if len(rtt_diffs_orig) > 0:
    spike_candidates = np.where(rtt_diffs_orig > np.percentile(rtt_diffs_orig, 95))[0]
    if len(spike_candidates) > 0:
        spike_idx = spike_candidates[len(spike_candidates)//3]  # 앞쪽 1/3 지점 스파이크
        
        # 스파이크 전후 200초 구간 확대 (원본 데이터)
        zoom_center = times_orig[spike_idx]
        zoom_start = max(0, zoom_center - 100)
        zoom_end = min(times_orig[-1], zoom_center + 100)
        
        # Inset 축 생성 (우하단)
        ax_inset = fig.add_axes([0.52, 0.15, 0.42, 0.35])
        ax_inset_p99 = ax_inset.twinx()
        
        # 원본 데이터에서 확대 구간 추출
        zoom_mask = (times_orig >= zoom_start) & (times_orig <= zoom_end)
        time_zoom = times_orig[zoom_mask]
        rtt_zoom = rtts_orig[zoom_mask]
        p99_zoom = p99s_orig[zoom_mask]
        
        if len(time_zoom) > 10:  # 충분한 데이터가 있을 때만
            # 확대 그래프
            inset_markevery = max(1, len(time_zoom) // 12)
            ax_inset.plot(
                time_zoom,
                rtt_zoom,
                color=color_rtt,
                linewidth=2.0,
                label='RTT',
                marker='o',
                markersize=4,
                markerfacecolor='white',
                markeredgecolor=color_rtt,
                markevery=inset_markevery,
            )
            ax_inset_p99.plot(
                time_zoom,
                p99_zoom,
                color=color_p99,
                linewidth=2.0,
                linestyle='--',
                alpha=0.9,
                label='P99',
                marker='s',
                markersize=4,
                markerfacecolor='white',
                markeredgecolor=color_p99,
                markevery=inset_markevery,
            )
            
            # 단순 확대만 보여주기 위해 추가 마커/하이라이트 제거
            ax_inset.tick_params(axis='y', labelleft=False)
            ax_inset_p99.tick_params(axis='y', labelright=False)
            ax_inset.tick_params(axis='x', labelbottom=False)
            ax_inset.grid(True, alpha=0.4, linestyle='--', linewidth=1.0)

plt.tight_layout()
output_path = Path('panel_b_rtt_p99.png')
plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
print(f"✓ 저장: {output_path}")
plt.close()
