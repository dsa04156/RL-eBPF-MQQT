#!/usr/bin/env python3
"""
슬라이드용 타임시리즈 비교 그래프
1. P99 Latency vs Time (3개 모드가 어떻게 망하고/눌리는지)
2. snd_ratio vs Time (버퍼 압력 제어)
"""
import json
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
from datetime import datetime
import matplotlib
from matplotlib import font_manager
from matplotlib.font_manager import FontProperties
import os

# 한글 폰트 설정
candidates = ["NanumGothic", "Noto Sans CJK KR", "AppleGothic", "Malgun Gothic"]
available = {f.name for f in font_manager.fontManager.ttflist}

def pick_font(cands):
    for c in cands:
        m = [name for name in available if c in name]
        if m:
            return m[0]
    return None

kfont = pick_font(candidates)
if kfont is None:
    local_paths = [
        "assets/NanumGothic.ttf",
        "assets/NanumGothic-Regular.ttf",
        "assets/NotoSansKR-Regular.otf",
        "assets/NotoSansCJKkr-Regular.otf",
    ]
    local_path = next((p for p in local_paths if os.path.exists(p)), None)
    if local_path:
        fp = FontProperties(fname=local_path)
        matplotlib.rcParams['font.family'] = fp.get_name()
    else:
        matplotlib.rcParams['font.family'] = 'sans-serif'
else:
    matplotlib.rcParams['font.family'] = kfont

matplotlib.rcParams['axes.unicode_minus'] = False

def load_log(path):
    data = []
    with open(path) as f:
        for line in f:
            try:
                data.append(json.loads(line))
            except:
                continue
    return data

def extract_timeseries(log, interval=2.0):
    """시계열 데이터 추출"""
    p99s = [e['metrics']['p99_ms'] for e in log if 'metrics' in e and 'p99_ms' in e['metrics']]
    snds = [e['kernel']['snd_ratio'] for e in log if 'kernel' in e and 'snd_ratio' in e['kernel']]
    
    time_sec = np.arange(len(p99s)) * interval
    
    return time_sec, p99s, snds

def moving_average(data, window=5):
    """이동 평균"""
    if len(data) < window:
        return data
    return np.convolve(data, np.ones(window)/window, mode='valid')

# ==================== 데이터 로드 ====================
print("="*80)
print("타임시리즈 비교 그래프 생성")
print("="*80)

baseline_log = load_log('logs/baseline/congestion.jsonl')
emqx_log = load_log('logs/emqx_flow_control/conjestion.jsonl')
rl_log = load_log('logs/torch_model_experiments/congestion/rl_bc_v2_congestion.jsonl')

baseline_time, baseline_p99, baseline_snd = extract_timeseries(baseline_log)
emqx_time, emqx_p99, emqx_snd = extract_timeseries(emqx_log)
rl_time, rl_p99, rl_snd = extract_timeseries(rl_log)

print(f"\n[데이터 길이]")
print(f"  Baseline: {len(baseline_p99)} samples ({baseline_time[-1]:.0f}s)")
print(f"  EMQX: {len(emqx_p99)} samples ({emqx_time[-1]:.0f}s)")
print(f"  eBPF+RL: {len(rl_p99)} samples ({rl_time[-1]:.0f}s)")

print(f"\n[평균 통계]")
print(f"  Baseline: P99={np.median(baseline_p99):.0f}ms, snd_ratio={np.median(baseline_snd):.3f}")
print(f"  EMQX: P99={np.median(emqx_p99):.0f}ms, snd_ratio={np.median(emqx_snd):.3f}")
print(f"  eBPF+RL: P99={np.median(rl_p99):.0f}ms, snd_ratio={np.median(rl_snd):.3f}")

# 출력 디렉토리
today = datetime.now().strftime('%Y%m%d')
output_dir = Path(f'results/presentation_{today}')
output_dir.mkdir(parents=True, exist_ok=True)

# ==================== 그래프 1: P99 Latency vs Time ====================
print("\n[*] 그래프 1: P99 Latency 타임시리즈 생성 중...")

fig, ax = plt.subplots(figsize=(14, 7))

# Smoothing
window = 5
baseline_p99_smooth = moving_average(baseline_p99, window)
emqx_p99_smooth = moving_average(emqx_p99, window)
rl_p99_smooth = moving_average(rl_p99, window)

baseline_time_smooth = baseline_time[:len(baseline_p99_smooth)]
emqx_time_smooth = emqx_time[:len(emqx_p99_smooth)]
rl_time_smooth = rl_time[:len(rl_p99_smooth)]

# Raw data (연하게)
ax.plot(baseline_time, baseline_p99, color='#808080', alpha=0.15, linewidth=1)
ax.plot(emqx_time, emqx_p99, color='#e74c3c', alpha=0.15, linewidth=1)
ax.plot(rl_time, rl_p99, color='#2E86AB', alpha=0.2, linewidth=1)

# Smoothed lines (진하게)
ax.plot(baseline_time_smooth, baseline_p99_smooth, color='#808080', linewidth=3, 
        label=f'Baseline (P99 ≈ {np.median(baseline_p99)/1000:.0f} s)', zorder=3)
ax.plot(emqx_time_smooth, emqx_p99_smooth, color='#e74c3c', linewidth=3, 
        label=f'EMQX (P99 ≈ {np.median(emqx_p99)/1000:.0f} s)', zorder=3)
ax.plot(rl_time_smooth, rl_p99_smooth, color='#2E86AB', linewidth=3.5, 
        label=f'eMQTT-RL (P99 ≈ {np.median(rl_p99)/1000:.1f} s)', zorder=4)

# SLO 기준선
ax.axhline(y=300, color='green', linestyle='--', linewidth=2.5, alpha=0.9, 
           label='SLO Target (300ms)', zorder=2)

ax.set_xlabel('Time (seconds)', fontsize=15, fontweight='bold')
ax.set_ylabel('P99 Latency (ms)', fontsize=15, fontweight='bold')
ax.set_title('P99 Tail Latency Over Time (Congestion Network)', 
             fontsize=17, fontweight='bold', pad=20)
ax.set_yscale('log')
ax.legend(fontsize=12, loc='upper right', framealpha=0.95)
ax.grid(True, alpha=0.3)

# 통계 박스
overflow_baseline = len([s for s in baseline_snd if s > 1.0]) / len(baseline_snd) * 100
overflow_emqx = len([s for s in emqx_snd if s > 1.0]) / len(emqx_snd) * 100
overflow_rl = len([s for s in rl_snd if s > 1.0]) / len(rl_snd) * 100

textstr = f'''P99 (Congestion)
  Baseline: {np.median(baseline_p99)/1000:.0f} s
  EMQX: {np.median(emqx_p99)/1000:.0f} s
  eMQTT-RL: {np.median(rl_p99)/1000:.1f} s

Overflow (snd_ratio>1.0)
  Baseline: {overflow_baseline:.1f}%
  EMQX: {overflow_emqx:.1f}%
  eMQTT-RL: {overflow_rl:.1f}%'''

ax.text(0.02, 0.98, textstr, transform=ax.transAxes, fontsize=11, 
        verticalalignment='top', family='monospace',
        bbox=dict(boxstyle='round,pad=0.8', facecolor='wheat', edgecolor='black', 
                 linewidth=2, alpha=0.95))

plt.tight_layout()
output_path = output_dir / 'timeseries1_p99_comparison.png'
plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
print(f"    ✓ 저장: {output_path} ({output_path.stat().st_size / 1024:.0f}KB)")
plt.close()

# ==================== 그래프 2: snd_ratio vs Time ====================
print("\n[*] 그래프 2: snd_ratio (버퍼 압력) 타임시리즈 생성 중...")

fig, ax = plt.subplots(figsize=(14, 7))

# Smoothing
baseline_snd_smooth = moving_average(baseline_snd, window)
emqx_snd_smooth = moving_average(emqx_snd, window)
rl_snd_smooth = moving_average(rl_snd, window)

baseline_time_smooth = baseline_time[:len(baseline_snd_smooth)]
emqx_time_smooth = emqx_time[:len(emqx_snd_smooth)]
rl_time_smooth = rl_time[:len(rl_snd_smooth)]

# Raw data (연하게)
ax.plot(baseline_time, baseline_snd, color='#808080', alpha=0.15, linewidth=1)
ax.plot(emqx_time, emqx_snd, color='#e74c3c', alpha=0.15, linewidth=1)
ax.plot(rl_time, rl_snd, color='#2E86AB', alpha=0.2, linewidth=1)

# Smoothed lines (진하게)
ax.plot(baseline_time_smooth, baseline_snd_smooth, color='#808080', linewidth=3, 
        label=f'Baseline (avg={np.mean(baseline_snd):.3f})', zorder=3)
ax.plot(emqx_time_smooth, emqx_snd_smooth, color='#e74c3c', linewidth=3, 
        label=f'EMQX (avg={np.mean(emqx_snd):.3f})', zorder=3)
ax.plot(rl_time_smooth, rl_snd_smooth, color='#2E86AB', linewidth=3.5, 
        label=f'eMQTT-RL (avg={np.mean(rl_snd):.3f})', zorder=4)

# Overflow threshold
ax.axhline(y=1.0, color='red', linestyle='--', linewidth=2.5, alpha=0.9, 
           label='Overflow Threshold (1.0)', zorder=2)

# Overflow zone
ax.fill_between(baseline_time, 1.0, max(max(baseline_snd), max(emqx_snd)) * 1.1, 
                color='red', alpha=0.1, label='Overflow Zone', zorder=1)

ax.set_xlabel('Time (seconds)', fontsize=15, fontweight='bold')
ax.set_ylabel('snd_ratio (Buffer Pressure)', fontsize=15, fontweight='bold')
ax.set_title('Kernel Buffer Pressure Over Time (Congestion Network)', 
             fontsize=17, fontweight='bold', pad=20)
ax.legend(fontsize=12, loc='upper right', framealpha=0.95)
ax.grid(True, alpha=0.3)
ax.set_ylim(bottom=0)

# 메시지 박스
textstr = '''Application-level (EMQX)은
snd_ratio를 1.0 아래로 못 눌러서
버퍼가 계속 넘치고,

eBPF+RL만 커널 버퍼 압력을
거의 0.0x 수준으로 유지'''

ax.text(0.02, 0.98, textstr, transform=ax.transAxes, fontsize=12, 
        verticalalignment='top', fontweight='bold',
        bbox=dict(boxstyle='round,pad=0.8', facecolor='lightgreen', edgecolor='black', 
                 linewidth=2, alpha=0.95))

plt.tight_layout()
output_path = output_dir / 'timeseries2_snd_ratio.png'
plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
print(f"    ✓ 저장: {output_path} ({output_path.stat().st_size / 1024:.0f}KB)")
plt.close()

# ==================== 그래프 3: 결합 (2-panel) ====================
print("\n[*] 그래프 3: P99 + snd_ratio 결합 생성 중...")

fig, axes = plt.subplots(2, 1, figsize=(14, 12))
# fig.suptitle('Congestion Network: Real-time Control Performance', 
#              fontsize=18, fontweight='bold', y=0.995)

# ========== 상단: P99 Latency ==========
ax = axes[0]

# Raw + Smooth
ax.plot(baseline_time, baseline_p99, color='#808080', alpha=0.15, linewidth=1)
ax.plot(emqx_time, emqx_p99, color='#e74c3c', alpha=0.15, linewidth=1)
ax.plot(rl_time, rl_p99, color='#2E86AB', alpha=0.2, linewidth=1)

ax.plot(baseline_time_smooth, baseline_p99_smooth, color='#808080', linewidth=3, 
        label=f'Baseline (≈{np.median(baseline_p99)/1000:.0f}s)', zorder=3)
ax.plot(emqx_time_smooth, emqx_p99_smooth, color='#e74c3c', linewidth=3, 
        label=f'EMQX (≈{np.median(emqx_p99)/1000:.0f}s)', zorder=3)
ax.plot(rl_time_smooth, rl_p99_smooth, color='#2E86AB', linewidth=3.5, 
        label=f'eMQTT-RL (≈{np.median(rl_p99)/1000:.1f}s)', zorder=4)

ax.axhline(y=300, color='green', linestyle='--', linewidth=2.5, alpha=0.9, 
           label='SLO (300ms)', zorder=2)

ax.set_ylabel('P99 Latency (ms)', fontsize=15, fontweight='bold')
ax.set_title('(a) Tail Latency Control', fontsize=16, fontweight='bold', loc='left', pad=15)
ax.set_yscale('log')
ax.legend(fontsize=11, loc='upper right', framealpha=0.95, ncol=2)
ax.grid(True, alpha=0.3)

# ========== 하단: snd_ratio ==========
ax = axes[1]

# Raw + Smooth
ax.plot(baseline_time, baseline_snd, color='#808080', alpha=0.15, linewidth=1)
ax.plot(emqx_time, emqx_snd, color='#e74c3c', alpha=0.15, linewidth=1)
ax.plot(rl_time, rl_snd, color='#2E86AB', alpha=0.2, linewidth=1)

ax.plot(baseline_time_smooth, baseline_snd_smooth, color='#808080', linewidth=3, 
        label=f'Baseline (avg={np.mean(baseline_snd):.2f})', zorder=3)
ax.plot(emqx_time_smooth, emqx_snd_smooth, color='#e74c3c', linewidth=3, 
        label=f'EMQX (avg={np.mean(emqx_snd):.2f})', zorder=3)
ax.plot(rl_time_smooth, rl_snd_smooth, color='#2E86AB', linewidth=3.5, 
        label=f'eMQTT-RL (avg={np.mean(rl_snd):.2f})', zorder=4)

ax.axhline(y=1.0, color='red', linestyle='--', linewidth=2.5, alpha=0.9, 
           label='Overflow (1.0)', zorder=2)
ax.fill_between(baseline_time, 1.0, max(max(baseline_snd), max(emqx_snd)) * 1.1, 
                color='red', alpha=0.1, zorder=1)

ax.set_xlabel('Time (seconds)', fontsize=15, fontweight='bold')
ax.set_ylabel('snd_ratio (Buffer Pressure)', fontsize=15, fontweight='bold')
ax.set_title('(b) Kernel Buffer Pressure', fontsize=16, fontweight='bold', loc='left', pad=15)
ax.legend(fontsize=11, loc='upper right', framealpha=0.95, ncol=2)
ax.grid(True, alpha=0.3)
ax.set_ylim(bottom=0)

plt.tight_layout()
output_path = output_dir / 'timeseries3_combined.png'
plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
print(f"    ✓ 저장: {output_path} ({output_path.stat().st_size / 1024:.0f}KB)")
plt.close()

# ==================== 요약 ====================
print("\n" + "="*80)
print("✅ 완료!")
print("="*80)
print(f"""
생성된 파일 (저장 위치: {output_dir}):

1️⃣  timeseries1_p99_comparison.png
   → P99 Latency vs Time
   → "누가 tail을 진짜로 눌렀는지" 직관적으로 보임
   → 통계 박스 포함
   
2️⃣  timeseries2_snd_ratio.png
   → snd_ratio (버퍼 압력) vs Time
   → "Application-level은 버퍼 못 눌러, eBPF+RL만 성공"
   
3️⃣  timeseries3_combined.png
   → P99 + snd_ratio 2-panel 결합
   → 한 슬라이드에 전체 스토리

핵심 메시지:
  • Baseline/EMQX: 수천~수만 ms에서 들쭉날쭉, 안 내려감
  • eMQTT-RL: 초반 짧은 튀는 구간 이후 300ms 근처 유지
  • 버퍼 압력도 eMQTT-RL만 1.0 밑으로 눌러버림
""")
