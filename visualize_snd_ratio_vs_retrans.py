#!/usr/bin/env python3
"""
snd_ratio와 retrans(재전송) 간의 관계 시각화
- Scatter plot: snd_ratio vs retrans count
- 4-way comparison: Baseline, EMQX, CUBIC+CoDel, eBPF+RL
"""

import json
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
import matplotlib.font_manager as fm

# ========================================
# 폰트 설정
# ========================================
def setup_korean_font():
    font_candidates = [
        'NanumGothic',
        'NanumBarunGothic', 
        'Malgun Gothic',
        'AppleGothic',
        'Noto Sans KR',
        'DejaVu Sans'
    ]
    
    available_fonts = [f.name for f in fm.fontManager.ttflist]
    
    for font_name in font_candidates:
        if any(font_name.lower() in f.lower() for f in available_fonts):
            plt.rcParams['font.family'] = font_name
            plt.rcParams['axes.unicode_minus'] = False
            print(f"[*] 폰트 설정: {font_name}")
            return
    
    print("[!] 한글 폰트를 찾지 못했습니다. 기본 폰트 사용")

setup_korean_font()

# ========================================
# 데이터 로드 함수
# ========================================
def load_jsonl(path):
    """JSONL 파일 로드"""
    with open(path, 'r') as f:
        return [json.loads(line) for line in f if line.strip()]

def extract_snd_retrans(data):
    """snd_ratio와 retrans 추출"""
    snd_ratio = []
    retrans = []
    
    for entry in data:
        if 'kernel' not in entry:
            continue
        
        kernel = entry['kernel']
        
        # snd_ratio
        if 'snd_ratio' in kernel:
            sr = kernel['snd_ratio']
        elif 'snd_buf_ratio' in kernel:
            sr = kernel['snd_buf_ratio']
        else:
            continue
        
        # retrans - 여러 필드 시도
        rt = None
        if 'retrans_out' in kernel:
            rt = kernel['retrans_out']
        elif 'retrans' in kernel:
            rt = kernel['retrans']
        elif 'retrans_count' in kernel:
            rt = kernel['retrans_count']
        elif 'had_retrans' in kernel:
            rt = kernel['had_retrans']
        
        if rt is not None:
            snd_ratio.append(sr)
            retrans.append(rt)
    
    return np.array(snd_ratio), np.array(retrans)

# ========================================
# 데이터 로드
# ========================================
print("\n" + "="*60)
print("데이터 로드 중...")
print("="*60)

# Congestion 데이터만 사용
baseline = load_jsonl('logs/baseline/congestion.jsonl')
emqx = load_jsonl('logs/emqx_flow_control/conjestion.jsonl')
cubic = load_jsonl('logs/cubic/cubic_congestion.jsonl')
rl = load_jsonl('logs/torch_model_experiments/congestion/rl_bc_v2_congestion.jsonl')

# snd_ratio와 retrans 추출
snd_bl, retrans_bl = extract_snd_retrans(baseline)
snd_eq, retrans_eq = extract_snd_retrans(emqx)
snd_cu, retrans_cu = extract_snd_retrans(cubic)
snd_rl, retrans_rl = extract_snd_retrans(rl)

print(f"\n[데이터 크기]")
print(f"  Baseline: {len(snd_bl)} samples (retrans range: {retrans_bl.min():.0f}-{retrans_bl.max():.0f})")
print(f"  EMQX: {len(snd_eq)} samples (retrans range: {retrans_eq.min():.0f}-{retrans_eq.max():.0f})")
print(f"  CUBIC+CoDel: {len(snd_cu)} samples (retrans range: {retrans_cu.min():.0f}-{retrans_cu.max():.0f})")
print(f"  eMQTT-RL: {len(snd_rl)} samples (retrans range: {retrans_rl.min():.0f}-{retrans_rl.max():.0f})")

# ========================================
# Figure 1: 4-way Scatter Plot (2x2)
# ========================================
print("\n" + "="*60)
print("Figure 1: 4-way Scatter Plot 생성 중...")
print("="*60)

fig, axes = plt.subplots(2, 2, figsize=(16, 14))
fig.suptitle('snd_ratio vs 재전송(retrans) 관계 분석 - Congestion Network', 
             fontsize=20, fontweight='bold', y=0.995)

colors = {
    'baseline': '#7f8c8d',
    'emqx': '#e74c3c',
    'cubic': '#f39c12',
    'rl': '#3498db'
}

# (a) Baseline
ax1 = axes[0, 0]
ax1.scatter(snd_bl, retrans_bl, alpha=0.4, s=30, color=colors['baseline'], edgecolors='none')
ax1.axvline(x=1.0, color='red', linestyle='--', linewidth=2, alpha=0.7, label='버퍼 넘침 (snd_ratio=1.0)')
ax1.set_xlabel('snd_ratio (TCP Send Buffer 압력)', fontsize=13, fontweight='bold')
ax1.set_ylabel('재전송 큐 크기 (retrans_out)', fontsize=13, fontweight='bold')
ax1.set_title('(a) Baseline - 제어 없음', fontsize=15, fontweight='bold')
ax1.grid(alpha=0.3, linestyle='--')
ax1.legend(fontsize=11)
ax1.set_xlim(0, max(5, snd_bl.max() * 1.1))

# Statistics
overflow_bl = np.sum(snd_bl > 1.0) / len(snd_bl) * 100
mean_retrans_bl = retrans_bl.mean()
ax1.text(0.02, 0.98, 
         f'버퍼 넘침: {overflow_bl:.1f}%\n평균 재전송: {mean_retrans_bl:.1f}',
         transform=ax1.transAxes, fontsize=11, verticalalignment='top',
         bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.7))

# (b) EMQX
ax2 = axes[0, 1]
ax2.scatter(snd_eq, retrans_eq, alpha=0.4, s=30, color=colors['emqx'], edgecolors='none')
ax2.axvline(x=1.0, color='red', linestyle='--', linewidth=2, alpha=0.7, label='버퍼 넘침 (snd_ratio=1.0)')
ax2.set_xlabel('snd_ratio (TCP Send Buffer 압력)', fontsize=13, fontweight='bold')
ax2.set_ylabel('재전송 큐 크기 (retrans_out)', fontsize=13, fontweight='bold')
ax2.set_title('(b) EMQX Flow Control', fontsize=15, fontweight='bold')
ax2.grid(alpha=0.3, linestyle='--')
ax2.legend(fontsize=11)
ax2.set_xlim(0, max(5, snd_eq.max() * 1.1))

# Statistics
overflow_eq = np.sum(snd_eq > 1.0) / len(snd_eq) * 100
mean_retrans_eq = retrans_eq.mean()
ax2.text(0.02, 0.98, 
         f'버퍼 넘침: {overflow_eq:.1f}%\n평균 재전송: {mean_retrans_eq:.1f}',
         transform=ax2.transAxes, fontsize=11, verticalalignment='top',
         bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.7))

# (c) CUBIC+CoDel
ax3 = axes[1, 0]
ax3.scatter(snd_cu, retrans_cu, alpha=0.4, s=30, color=colors['cubic'], edgecolors='none')
ax3.axvline(x=1.0, color='red', linestyle='--', linewidth=2, alpha=0.7, label='버퍼 넘침 (snd_ratio=1.0)')
ax3.set_xlabel('snd_ratio (TCP Send Buffer 압력)', fontsize=13, fontweight='bold')
ax3.set_ylabel('재전송 큐 크기 (retrans_out)', fontsize=13, fontweight='bold')
ax3.set_title('(c) CUBIC+CoDel', fontsize=15, fontweight='bold')
ax3.grid(alpha=0.3, linestyle='--')
ax3.legend(fontsize=11)
ax3.set_xlim(0, max(5, snd_cu.max() * 1.1))

# Statistics
overflow_cu = np.sum(snd_cu > 1.0) / len(snd_cu) * 100
mean_retrans_cu = retrans_cu.mean()
ax3.text(0.02, 0.98, 
         f'버퍼 넘침: {overflow_cu:.1f}%\n평균 재전송: {mean_retrans_cu:.1f}',
         transform=ax3.transAxes, fontsize=11, verticalalignment='top',
         bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.7))

# (d) eBPF+RL
ax4 = axes[1, 1]
ax4.scatter(snd_rl, retrans_rl, alpha=0.4, s=30, color=colors['rl'], edgecolors='none')
ax4.axvline(x=1.0, color='red', linestyle='--', linewidth=2, alpha=0.7, label='버퍼 넘침 (snd_ratio=1.0)')
ax4.set_xlabel('snd_ratio (TCP Send Buffer 압력)', fontsize=13, fontweight='bold')
ax4.set_ylabel('재전송 큐 크기 (retrans_out)', fontsize=13, fontweight='bold')
ax4.set_title('(d) eBPF+RL (제안 방법)', fontsize=15, fontweight='bold')
ax4.grid(alpha=0.3, linestyle='--')
ax4.legend(fontsize=11)
ax4.set_xlim(0, max(5, snd_rl.max() * 1.1))

# Statistics
overflow_rl = np.sum(snd_rl > 1.0) / len(snd_rl) * 100
mean_retrans_rl = retrans_rl.mean()
ax4.text(0.02, 0.98, 
         f'버퍼 넘침: {overflow_rl:.1f}%\n평균 재전송: {mean_retrans_rl:.1f}',
         transform=ax4.transAxes, fontsize=11, verticalalignment='top',
         bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.7))

plt.tight_layout()

# Save
output_dir = Path('results/snd_retrans_analysis')
output_dir.mkdir(parents=True, exist_ok=True)
output_path1 = output_dir / 'scatter_4way.png'
plt.savefig(output_path1, dpi=300, bbox_inches='tight', facecolor='white')
print(f"[*] 저장: {output_path1} ({output_path1.stat().st_size / 1024:.0f} KB)")
plt.close()

# ========================================
# Figure 2: Overlay Comparison
# ========================================
print("\n" + "="*60)
print("Figure 2: Overlay Comparison 생성 중...")
print("="*60)

fig, ax = plt.subplots(figsize=(14, 10))

# Plot all methods
ax.scatter(snd_bl, retrans_bl, alpha=0.3, s=40, color=colors['baseline'], 
           label='Baseline', edgecolors='none')
ax.scatter(snd_eq, retrans_eq, alpha=0.3, s=40, color=colors['emqx'], 
           label='EMQX', edgecolors='none')
ax.scatter(snd_cu, retrans_cu, alpha=0.3, s=40, color=colors['cubic'], 
           label='CUBIC+CoDel', edgecolors='none')
ax.scatter(snd_rl, retrans_rl, alpha=0.4, s=50, color=colors['rl'], 
           label='eBPF+RL', edgecolors='black', linewidths=0.5)

# Overflow line
ax.axvline(x=1.0, color='red', linestyle='--', linewidth=2.5, alpha=0.8, 
           label='버퍼 넘침 임계값 (snd_ratio=1.0)')

# Fill overflow zone
ax.fill_betweenx([0, max(retrans_bl.max(), retrans_eq.max(), retrans_cu.max())], 
                  1.0, 20, color='red', alpha=0.1, label='버퍼 오버플로우 존')

ax.set_xlabel('snd_ratio (TCP Send Buffer 압력)', fontsize=14, fontweight='bold')
ax.set_ylabel('재전송 큐 크기 (retrans_out)', fontsize=14, fontweight='bold')
ax.set_title('snd_ratio vs 재전송 관계 - 4가지 방법 비교 (Congestion)', 
             fontsize=16, fontweight='bold')
ax.legend(loc='upper right', fontsize=12, framealpha=0.9)
ax.grid(alpha=0.3, linestyle='--')
ax.set_xlim(0, 10)

plt.tight_layout()

output_path2 = output_dir / 'scatter_overlay.png'
plt.savefig(output_path2, dpi=300, bbox_inches='tight', facecolor='white')
print(f"[*] 저장: {output_path2} ({output_path2.stat().st_size / 1024:.0f} KB)")
plt.close()

# ========================================
# Figure 3: Correlation Analysis with Binning
# ========================================
print("\n" + "="*60)
print("Figure 3: Correlation Analysis 생성 중...")
print("="*60)

def bin_analysis(snd_ratio, retrans, bins=10):
    """snd_ratio를 bin으로 나눠서 평균 retrans 계산"""
    bin_edges = np.linspace(0, min(10, snd_ratio.max()), bins+1)
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
    bin_means = []
    bin_stds = []
    
    for i in range(len(bin_edges)-1):
        mask = (snd_ratio >= bin_edges[i]) & (snd_ratio < bin_edges[i+1])
        if np.sum(mask) > 0:
            bin_means.append(retrans[mask].mean())
            bin_stds.append(retrans[mask].std())
        else:
            bin_means.append(0)
            bin_stds.append(0)
    
    return bin_centers, np.array(bin_means), np.array(bin_stds)

fig, ax = plt.subplots(figsize=(14, 10))

# Bin analysis for each method
bins_bl, means_bl, stds_bl = bin_analysis(snd_bl, retrans_bl, bins=15)
bins_eq, means_eq, stds_eq = bin_analysis(snd_eq, retrans_eq, bins=15)
bins_cu, means_cu, stds_cu = bin_analysis(snd_cu, retrans_cu, bins=15)
bins_rl, means_rl, stds_rl = bin_analysis(snd_rl, retrans_rl, bins=15)

# Plot with error bars
ax.errorbar(bins_bl, means_bl, yerr=stds_bl, fmt='o-', linewidth=2.5, markersize=8, 
            color=colors['baseline'], label='Baseline', alpha=0.8, capsize=5)
ax.errorbar(bins_eq, means_eq, yerr=stds_eq, fmt='s-', linewidth=2.5, markersize=8, 
            color=colors['emqx'], label='EMQX', alpha=0.8, capsize=5)
ax.errorbar(bins_cu, means_cu, yerr=stds_cu, fmt='^-', linewidth=2.5, markersize=8, 
            color=colors['cubic'], label='CUBIC+CoDel', alpha=0.8, capsize=5)
ax.errorbar(bins_rl, means_rl, yerr=stds_rl, fmt='d-', linewidth=2.5, markersize=8, 
            color=colors['rl'], label='eBPF+RL', alpha=0.8, capsize=5)

# Overflow line
ax.axvline(x=1.0, color='red', linestyle='--', linewidth=2.5, alpha=0.8, 
           label='버퍼 넘침 임계값')

ax.set_xlabel('snd_ratio (TCP Send Buffer 압력)', fontsize=14, fontweight='bold')
ax.set_ylabel('평균 재전송 큐 크기 (retrans_out)', fontsize=14, fontweight='bold')
ax.set_title('snd_ratio 구간별 평균 재전송 분석 (Congestion)', 
             fontsize=16, fontweight='bold')
ax.legend(loc='upper left', fontsize=12, framealpha=0.9)
ax.grid(alpha=0.3, linestyle='--')
ax.set_xlim(0, 8)

plt.tight_layout()

output_path3 = output_dir / 'correlation_binned.png'
plt.savefig(output_path3, dpi=300, bbox_inches='tight', facecolor='white')
print(f"[*] 저장: {output_path3} ({output_path3.stat().st_size / 1024:.0f} KB)")
plt.close()

# ========================================
# Summary Statistics
# ========================================
print("\n" + "="*60)
print("통계 요약")
print("="*60)

print("\n[버퍼 넘침 (snd_ratio > 1.0)]")
print(f"  Baseline: {overflow_bl:.1f}%")
print(f"  EMQX: {overflow_eq:.1f}%")
print(f"  CUBIC+CoDel: {overflow_cu:.1f}%")
print(f"  eBPF+RL: {overflow_rl:.1f}%")

print("\n[평균 재전송 큐 크기]")
print(f"  Baseline: {mean_retrans_bl:.2f}")
print(f"  EMQX: {mean_retrans_eq:.2f}")
print(f"  CUBIC+CoDel: {mean_retrans_cu:.2f}")
print(f"  eBPF+RL: {mean_retrans_rl:.2f}")

print("\n[상관계수 (Numpy correlation)]")
if len(snd_bl) > 1:
    corr_bl = np.corrcoef(snd_bl, retrans_bl)[0, 1]
    print(f"  Baseline: {corr_bl:.3f}")
if len(snd_eq) > 1:
    corr_eq = np.corrcoef(snd_eq, retrans_eq)[0, 1]
    print(f"  EMQX: {corr_eq:.3f}")
if len(snd_cu) > 1:
    corr_cu = np.corrcoef(snd_cu, retrans_cu)[0, 1]
    print(f"  CUBIC+CoDel: {corr_cu:.3f}")
if len(snd_rl) > 1:
    corr_rl = np.corrcoef(snd_rl, retrans_rl)[0, 1]
    print(f"  eBPF+RL: {corr_rl:.3f}")

print("\n" + "="*60)
print("생성 완료!")
print("="*60)
print(f"\n출력 폴더: {output_dir}/")
print(f"  - scatter_4way.png (2x2 scatter plots)")
print(f"  - scatter_overlay.png (overlay comparison)")
print(f"  - correlation_binned.png (binned correlation analysis)")
print("="*60)
