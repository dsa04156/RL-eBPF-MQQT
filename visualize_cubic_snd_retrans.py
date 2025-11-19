#!/usr/bin/env python3
"""
CUBIC+CoDel: snd_ratio와 retrans(재전송) 간의 관계 시각화
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
# 데이터 로드
# ========================================
print("\n" + "="*60)
print("CUBIC+CoDel 데이터 로드 중...")
print("="*60)

with open('logs/cubic/cubic_congestion.jsonl', 'r') as f:
    data = [json.loads(line) for line in f if line.strip()]

# snd_ratio와 retrans 추출
snd_ratio = []
retrans = []

for entry in data:
    if 'kernel' not in entry:
        continue
    
    kernel = entry['kernel']
    
    # snd_ratio
    if 'snd_ratio' in kernel:
        sr = kernel['snd_ratio']
    else:
        continue
    
    # retrans
    if 'retrans_out' in kernel:
        rt = kernel['retrans_out']
    elif 'retrans_count' in kernel:
        rt = kernel['retrans_count']
    else:
        continue
    
    snd_ratio.append(sr)
    retrans.append(rt)

snd_ratio = np.array(snd_ratio)
retrans = np.array(retrans)

print(f"\n[데이터 정보]")
print(f"  총 샘플: {len(snd_ratio)}")
print(f"  snd_ratio 범위: {snd_ratio.min():.2f} ~ {snd_ratio.max():.2f}")
print(f"  retrans 범위: {retrans.min():.0f} ~ {retrans.max():.0f}")
print(f"  버퍼 넘침 (snd_ratio>1.0): {np.sum(snd_ratio > 1.0)/len(snd_ratio)*100:.1f}%")
print(f"  평균 재전송: {retrans.mean():.2f}")

# ========================================
# Scatter Plot
# ========================================
print("\n" + "="*60)
print("Scatter Plot 생성 중...")
print("="*60)

fig, ax = plt.subplots(figsize=(12, 9))

# Scatter
scatter = ax.scatter(snd_ratio, retrans, alpha=0.5, s=60, c=snd_ratio, 
                     cmap='RdYlBu_r', edgecolors='black', linewidths=0.5)

# Colorbar
cbar = plt.colorbar(scatter, ax=ax)
cbar.set_label('snd_ratio 값', fontsize=12, fontweight='bold')

# Overflow line
ax.axvline(x=1.0, color='red', linestyle='--', linewidth=3, alpha=0.8, 
           label='버퍼 넘침 임계값 (snd_ratio=1.0)')

# Fill overflow zone
ax.fill_betweenx([0, retrans.max() * 1.1], 1.0, snd_ratio.max() * 1.1, 
                  color='red', alpha=0.15, label='버퍼 오버플로우 존')

ax.set_xlabel('snd_ratio (TCP Send Buffer 압력)', fontsize=14, fontweight='bold')
ax.set_ylabel('재전송 큐 크기 (retrans_out)', fontsize=14, fontweight='bold')
ax.set_title('CUBIC+CoDel: snd_ratio vs 재전송 관계 (Congestion Network)', 
             fontsize=16, fontweight='bold', pad=20)
ax.legend(loc='upper left', fontsize=12, framealpha=0.9)
ax.grid(alpha=0.3, linestyle='--')

# Statistics box
overflow_pct = np.sum(snd_ratio > 1.0) / len(snd_ratio) * 100
mean_retrans = retrans.mean()
median_retrans = np.median(retrans)
corr = np.corrcoef(snd_ratio, retrans)[0, 1]

stats_text = f'버퍼 넘침: {overflow_pct:.1f}%\n'
stats_text += f'평균 재전송: {mean_retrans:.1f}\n'
stats_text += f'중앙값 재전송: {median_retrans:.1f}\n'
stats_text += f'상관계수: {corr:.3f}'

ax.text(0.98, 0.02, stats_text,
        transform=ax.transAxes, fontsize=11, verticalalignment='bottom',
        horizontalalignment='right',
        bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

plt.tight_layout()

# Save
output_dir = Path('results/cubic_analysis')
output_dir.mkdir(parents=True, exist_ok=True)
output_path = output_dir / 'snd_ratio_vs_retrans.png'
plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
print(f"[*] 저장: {output_path} ({output_path.stat().st_size / 1024:.0f} KB)")
plt.close()

# ========================================
# Binned Analysis
# ========================================
print("\n" + "="*60)
print("Binned Analysis 생성 중...")
print("="*60)

# Bin by snd_ratio
bins = np.linspace(0, min(10, snd_ratio.max()), 20)
bin_centers = (bins[:-1] + bins[1:]) / 2
bin_means = []
bin_stds = []
bin_counts = []

for i in range(len(bins)-1):
    mask = (snd_ratio >= bins[i]) & (snd_ratio < bins[i+1])
    count = np.sum(mask)
    bin_counts.append(count)
    if count > 0:
        bin_means.append(retrans[mask].mean())
        bin_stds.append(retrans[mask].std())
    else:
        bin_means.append(0)
        bin_stds.append(0)

bin_means = np.array(bin_means)
bin_stds = np.array(bin_stds)
bin_counts = np.array(bin_counts)

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))

# Plot 1: Mean retrans by snd_ratio bin
ax1.errorbar(bin_centers, bin_means, yerr=bin_stds, fmt='o-', linewidth=2.5, 
             markersize=8, color='#f39c12', capsize=5, alpha=0.8,
             label='평균 ± 표준편차')
ax1.axvline(x=1.0, color='red', linestyle='--', linewidth=2.5, alpha=0.8, 
            label='버퍼 넘침 임계값')
ax1.set_xlabel('snd_ratio 구간', fontsize=13, fontweight='bold')
ax1.set_ylabel('평균 재전송 큐 크기', fontsize=13, fontweight='bold')
ax1.set_title('(a) snd_ratio 구간별 평균 재전송 분석', fontsize=14, fontweight='bold')
ax1.legend(fontsize=11)
ax1.grid(alpha=0.3, linestyle='--')

# Plot 2: Sample count per bin
ax2.bar(bin_centers, bin_counts, width=(bins[1]-bins[0])*0.8, 
        color='#3498db', alpha=0.7, edgecolor='black')
ax2.axvline(x=1.0, color='red', linestyle='--', linewidth=2.5, alpha=0.8)
ax2.set_xlabel('snd_ratio 구간', fontsize=13, fontweight='bold')
ax2.set_ylabel('샘플 수', fontsize=13, fontweight='bold')
ax2.set_title('(b) snd_ratio 분포', fontsize=14, fontweight='bold')
ax2.grid(alpha=0.3, linestyle='--', axis='y')

plt.tight_layout()

output_path2 = output_dir / 'binned_analysis.png'
plt.savefig(output_path2, dpi=300, bbox_inches='tight', facecolor='white')
print(f"[*] 저장: {output_path2} ({output_path2.stat().st_size / 1024:.0f} KB)")
plt.close()

# ========================================
# Summary
# ========================================
print("\n" + "="*60)
print("분석 완료!")
print("="*60)
print(f"\n[핵심 발견]")
print(f"  • 버퍼 넘침 (snd_ratio>1.0): {overflow_pct:.1f}%")
print(f"  • 평균 재전송: {mean_retrans:.1f}")
print(f"  • snd_ratio와 재전송 상관계수: {corr:.3f}")
print(f"\n출력 폴더: {output_dir}/")
print(f"  - snd_ratio_vs_retrans.png")
print(f"  - binned_analysis.png")
print("="*60)
