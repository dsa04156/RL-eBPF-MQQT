#!/usr/bin/env python3
"""
Panel (c): 인과관계 - snd_ratio가 P99보다 선행 (Leading Indicator)
"""
import json
import numpy as np
import matplotlib
from matplotlib import font_manager
import matplotlib.pyplot as plt
from pathlib import Path
from scipy.signal import correlate

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
snd_ratios = [d.get('kernel', {}).get('snd_ratio', 0) for d in data if 'kernel' in d]
p99s = [d.get('metrics', {}).get('p99_ms', 0) for d in data if 'metrics' in d]

snd_ratios = np.array(snd_ratios)
p99s = np.array(p99s)

# 극값 제거
snd_clip = np.percentile(snd_ratios, 99)
p99_clip = np.percentile(p99s, 95)
snd_ratios = np.clip(snd_ratios, 0, snd_clip)
p99s = np.clip(p99s, 0, p99_clip)

# Downsampling
snd_ratios = snd_ratios[::10]
p99s = p99s[::10]
steps = np.arange(len(snd_ratios))
time_sec = steps * 2.0 * 10

# Smoothing
snd_smooth = moving_average(snd_ratios, window=50)
p99s_smooth = moving_average(p99s, window=50)
time_smooth = time_sec[:len(snd_smooth)]

# ==================== 그래프 생성 (Dual Y-axis) ====================
fig, ax_snd = plt.subplots(figsize=(6.5, 4.5))

color_snd = '#ff7f0e'  # 주황
color_p99 = '#d62728'  # 빨강

# 왼쪽 Y축: snd_ratio (마커=삼각형)
markevery_main = max(1, len(time_smooth) // 35)
line1 = ax_snd.plot(
    time_smooth,
    snd_smooth,
    color=color_snd,
    linewidth=2.5,
    label='snd_ratio',
    zorder=2,
    marker='^',
    markersize=4.5,
    markerfacecolor='white',
    markeredgecolor=color_snd,
    markeredgewidth=1.0,
    markevery=markevery_main,
)
ax_snd.axhline(y=1.0, color='red', linestyle='--', linewidth=2.5, alpha=0.7, label='Overflow (1.0)', zorder=1)

ax_snd.set_xlabel('학습 시간 (초)', fontweight='bold', fontsize=13, fontproperties=FONT_PROP)
ax_snd.set_ylabel('송신 버퍼 압력 (snd_ratio)', fontweight='bold', fontsize=13, color=color_snd, fontproperties=FONT_PROP)
ax_snd.tick_params(axis='y', labelcolor=color_snd, labelsize=15)
ax_snd.set_ylim(bottom=0, top=min(max(snd_smooth)*1.5, 3.0))

# 오른쪽 Y축: P99 (마커=다이아)
ax_p99 = ax_snd.twinx()
line2 = ax_p99.plot(
    time_smooth,
    p99s_smooth,
    color=color_p99,
    linewidth=2.5,
    alpha=0.9,
    label='P99 레이턴시',
    zorder=2,
    linestyle='--',
    marker='D',
    markersize=4.5,
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
lines = line1 + line2 + [ax_snd.get_lines()[1]]
labels = [l.get_label() for l in lines]
ax_snd.legend(lines, labels, loc='upper right', fontsize=11, framealpha=0.95, edgecolor='gray', prop=FONT_PROP)
ax_snd.grid(True, alpha=0.25, linestyle='--', linewidth=0.8)

# 상관계수 박스
corr = np.corrcoef(snd_ratios[:min(len(snd_ratios), len(p99s))], p99s[:min(len(snd_ratios), len(p99s))])[0,1]
textstr = f'상관계수: {corr:.3f}\n(snd_ratio ↔ P99)'
fig.text(0.02, 0.97, textstr, fontsize=12, fontproperties=FONT_PROP,
         verticalalignment='top', bbox=dict(boxstyle='round', facecolor='white',
         alpha=0.9, edgecolor='gray', linewidth=2))

# ========== 확대 영역 (원본 데이터로 snd_ratio 스파이크 → P99 증가) ==========
# 원본 데이터에서 snd_ratio가 급등하는 구간 찾기
snd_orig = np.array([d.get('kernel', {}).get('snd_ratio', 0) for d in data if 'kernel' in d])
p99s_orig = np.array([d.get('metrics', {}).get('p99_ms', 0) for d in data if 'metrics' in d])
times_orig = np.arange(len(snd_orig)) * 2.0  # 2초 간격

# 원본 데이터에서 스파이크 찾기
snd_diffs_orig = np.diff(snd_orig)
if len(snd_diffs_orig) > 0:
    spike_candidates = np.where(snd_diffs_orig > np.percentile(snd_diffs_orig, 95))[0]
    if len(spike_candidates) > 0:
        spike_idx = spike_candidates[len(spike_candidates)//3]  # 앞쪽 1/3 지점 스파이크
        
        # 스파이크 전후 200초 구간 확대 (원본 데이터)
        zoom_center = times_orig[spike_idx]
        zoom_start = max(0, zoom_center - 100)
        zoom_end = min(times_orig[-1], zoom_center + 100)
        
        # Inset 축 생성 (우측 중앙, Y축 수치가 잘리지 않도록)
        ax_inset = fig.add_axes([0.50, 0.30, 0.38, 0.32])
        ax_inset_p99 = ax_inset.twinx()
        
        # 원본 데이터에서 확대 구간 추출
        zoom_mask = (times_orig >= zoom_start) & (times_orig <= zoom_end)
        time_zoom = times_orig[zoom_mask]
        snd_zoom = snd_orig[zoom_mask]
        p99_zoom = p99s_orig[zoom_mask]
        
        if len(time_zoom) > 10:  # 충분한 데이터가 있을 때만
            # 확대 그래프
            inset_markevery = max(1, len(time_zoom) // 12)
            ax_inset.plot(
                time_zoom,
                snd_zoom,
                color=color_snd,
                linewidth=2.0,
                marker='^',
                markersize=4,
                markerfacecolor='white',
                markeredgecolor=color_snd,
                markevery=inset_markevery,
            )
            ax_inset_p99.plot(
                time_zoom,
                p99_zoom,
                color=color_p99,
                linewidth=2.0,
                linestyle='--',
                alpha=0.9,
                marker='D',
                markersize=4,
                markerfacecolor='white',
                markeredgecolor=color_p99,
                markevery=inset_markevery,
            )
            
            # 단순 확대만 표시
            ax_inset.tick_params(axis='y', labelleft=False)
            ax_inset_p99.tick_params(axis='y', labelright=False)
            ax_inset.tick_params(axis='x', labelbottom=False)
            ax_inset.grid(True, alpha=0.4, linestyle='--', linewidth=1.0)

# tight_layout은 inset과 충돌하므로 수동 조정
plt.subplots_adjust(left=0.08, right=0.92, top=0.95, bottom=0.08)
output_path = Path('panel_c_correlation.png')
plt.savefig(output_path, dpi=300, bbox_inches='tight', pad_inches=0.3, facecolor='white')
print(f"✓ 저장: {output_path}")
plt.close()
