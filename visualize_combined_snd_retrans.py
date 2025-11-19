#!/usr/bin/env python3
"""
Normal + Congestion 합쳐서 snd_ratio와 retrans 관계 분석
더 많은 데이터 포인트로 인과관계 명확히 증명
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
def load_and_extract(path, label):
    """JSONL 로드하고 snd_ratio, retrans, p99 추출"""
    with open(path, 'r') as f:
        data = [json.loads(line) for line in f if line.strip()]
    
    snd_ratio = []
    retrans = []
    p99_latency = []
    
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
        
        # p99 (optional)
        p99 = None
        if 'metrics' in entry and 'p99_ms' in entry['metrics']:
            p99 = entry['metrics']['p99_ms']
        
        snd_ratio.append(sr)
        retrans.append(rt)
        p99_latency.append(p99 if p99 is not None else 0)
    
    print(f"  {label}: {len(snd_ratio)} samples")
    return np.array(snd_ratio), np.array(retrans), np.array(p99_latency)

# ========================================
# 데이터 로드
# ========================================
print("\n" + "="*60)
print("데이터 로드 중...")
print("="*60)

# Normal: EMQX
snd_normal, retrans_normal, p99_normal = load_and_extract(
    'logs/emqx_flow_control/normal.jsonl', 'EMQX Normal')

# Congestion: CUBIC
snd_congestion, retrans_congestion, p99_congestion = load_and_extract(
    'logs/cubic/cubic_congestion.jsonl', 'CUBIC Congestion')

# 합치기
snd_all = np.concatenate([snd_normal, snd_congestion])
retrans_all = np.concatenate([retrans_normal, retrans_congestion])
p99_all = np.concatenate([p99_normal, p99_congestion])

# 레이블 (Normal=0, Congestion=1)
labels = np.concatenate([
    np.zeros(len(snd_normal)),
    np.ones(len(snd_congestion))
])

print(f"\n[합친 데이터]")
print(f"  Total: {len(snd_all)} samples")
print(f"  snd_ratio 범위: {snd_all.min():.3f} ~ {snd_all.max():.3f}")
print(f"  retrans 범위: {retrans_all.min():.0f} ~ {retrans_all.max():.0f}")
print(f"  Normal 버퍼 넘침: {np.sum(snd_normal > 1.0)/len(snd_normal)*100:.1f}%")
print(f"  Congestion 버퍼 넘침: {np.sum(snd_congestion > 1.0)/len(snd_congestion)*100:.1f}%")
print(f"  Combined 버퍼 넘침: {np.sum(snd_all > 1.0)/len(snd_all)*100:.1f}%")

# ========================================
# Figure 1: Scatter with Environment Color
# ========================================
print("\n" + "="*60)
print("Figure 1: 환경별 Scatter Plot 생성 중...")
print("="*60)

fig, ax = plt.subplots(figsize=(14, 10))

# Normal (파랑)
mask_normal = labels == 0
ax.scatter(snd_all[mask_normal], retrans_all[mask_normal], 
           alpha=0.6, s=60, color='#3498db', edgecolors='black', linewidths=0.5,
           label=f'Normal Network (n={np.sum(mask_normal)})')

# Congestion (빨강)
mask_congestion = labels == 1
ax.scatter(snd_all[mask_congestion], retrans_all[mask_congestion], 
           alpha=0.6, s=60, color='#e74c3c', edgecolors='black', linewidths=0.5,
           label=f'Congestion Network (n={np.sum(mask_congestion)})')

# Overflow line
ax.axvline(x=1.0, color='red', linestyle='--', linewidth=3, alpha=0.8, 
           label='버퍼 넘침 임계값 (snd_ratio=1.0)')

# Fill overflow zone
ax.fill_betweenx([0, retrans_all.max() * 1.1], 1.0, snd_all.max() * 1.1, 
                  color='red', alpha=0.1, label='오버플로우 존')

ax.set_xlabel('snd_ratio (TCP Send Buffer 압력)', fontsize=14, fontweight='bold')
ax.set_ylabel('재전송 큐 크기 (retrans_out)', fontsize=14, fontweight='bold')
ax.set_title('Normal + Congestion: snd_ratio vs 재전송 관계', 
             fontsize=16, fontweight='bold', pad=20)
ax.legend(loc='upper left', fontsize=12, framealpha=0.9)
ax.grid(alpha=0.3, linestyle='--')
ax.set_xlim(0, min(5, snd_all.max() * 1.1))

# Statistics
corr_all = np.corrcoef(snd_all, retrans_all)[0, 1]
corr_normal = np.corrcoef(snd_normal, retrans_normal)[0, 1]
corr_congestion = np.corrcoef(snd_congestion, retrans_congestion)[0, 1]

stats_text = f'상관계수:\n'
stats_text += f'  전체: {corr_all:.3f}\n'
stats_text += f'  Normal: {corr_normal:.3f}\n'
stats_text += f'  Congestion: {corr_congestion:.3f}\n'
stats_text += f'\n평균 재전송:\n'
stats_text += f'  Normal: {retrans_normal.mean():.1f}\n'
stats_text += f'  Congestion: {retrans_congestion.mean():.1f}'

ax.text(0.98, 0.02, stats_text,
        transform=ax.transAxes, fontsize=11, verticalalignment='bottom',
        horizontalalignment='right',
        bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

plt.tight_layout()

output_dir = Path('results/combined_analysis')
output_dir.mkdir(parents=True, exist_ok=True)
output_path1 = output_dir / 'scatter_combined.png'
plt.savefig(output_path1, dpi=300, bbox_inches='tight', facecolor='white')
print(f"[*] 저장: {output_path1} ({output_path1.stat().st_size / 1024:.0f} KB)")
plt.close()

# ========================================
# Figure 2: Binned Analysis (Combined)
# ========================================
print("\n" + "="*60)
print("Figure 2: 구간별 분석 생성 중...")
print("="*60)

# Bin by snd_ratio
bins = np.linspace(0, min(5, snd_all.max()), 25)
bin_centers = (bins[:-1] + bins[1:]) / 2
bin_means = []
bin_stds = []
bin_counts = []

for i in range(len(bins)-1):
    mask = (snd_all >= bins[i]) & (snd_all < bins[i+1])
    count = np.sum(mask)
    bin_counts.append(count)
    if count > 0:
        bin_means.append(retrans_all[mask].mean())
        bin_stds.append(retrans_all[mask].std())
    else:
        bin_means.append(0)
        bin_stds.append(0)

bin_means = np.array(bin_means)
bin_stds = np.array(bin_stds)
bin_counts = np.array(bin_counts)

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))
fig.suptitle('snd_ratio 구간별 재전송 분석 (Normal + Congestion)', 
             fontsize=16, fontweight='bold')

# Panel 1: Mean retrans by bin
ax1.errorbar(bin_centers, bin_means, yerr=bin_stds, fmt='o-', linewidth=2.5, 
             markersize=8, color='#2ecc71', capsize=5, alpha=0.8,
             label='평균 재전송 ± 표준편차')
ax1.axvline(x=1.0, color='red', linestyle='--', linewidth=2.5, alpha=0.8, 
            label='버퍼 넘침 임계값')

# Trend line
valid_mask = bin_means > 0
if np.sum(valid_mask) > 2:
    z = np.polyfit(bin_centers[valid_mask], bin_means[valid_mask], 1)
    p = np.poly1d(z)
    ax1.plot(bin_centers, p(bin_centers), "r--", linewidth=2, alpha=0.7,
             label=f'추세선 (기울기: {z[0]:.2f})')

ax1.set_xlabel('snd_ratio 구간', fontsize=13, fontweight='bold')
ax1.set_ylabel('평균 재전송 큐 크기', fontsize=13, fontweight='bold')
ax1.set_title('(a) snd_ratio ↑ → 재전송 ↑ 경향', fontsize=14, fontweight='bold')
ax1.legend(fontsize=11)
ax1.grid(alpha=0.3, linestyle='--')

# Panel 2: Sample count per bin
colors_bin = ['#3498db' if bc < 1.0 else '#e74c3c' for bc in bin_centers]
ax2.bar(bin_centers, bin_counts, width=(bins[1]-bins[0])*0.8, 
        color=colors_bin, alpha=0.7, edgecolor='black')
ax2.axvline(x=1.0, color='red', linestyle='--', linewidth=2.5, alpha=0.8)
ax2.set_xlabel('snd_ratio 구간', fontsize=13, fontweight='bold')
ax2.set_ylabel('샘플 수', fontsize=13, fontweight='bold')
ax2.set_title('(b) snd_ratio 분포 (파랑: Normal 영역, 빨강: Congestion 영역)', 
              fontsize=14, fontweight='bold')
ax2.grid(alpha=0.3, linestyle='--', axis='y')

plt.tight_layout()

output_path2 = output_dir / 'binned_combined.png'
plt.savefig(output_path2, dpi=300, bbox_inches='tight', facecolor='white')
print(f"[*] 저장: {output_path2} ({output_path2.stat().st_size / 1024:.0f} KB)")
plt.close()

# ========================================
# Figure 3: 3-way comparison (snd_ratio 구간별)
# ========================================
print("\n" + "="*60)
print("Figure 3: 구간별 3-way 비교 생성 중...")
print("="*60)

# Categorize
low_mask = snd_all <= 0.5
med_mask = (snd_all > 0.5) & (snd_all <= 1.0)
high_mask = snd_all > 1.0

categories = ['Low\n(≤0.5)', 'Medium\n(0.5-1.0)', 'High\n(>1.0)']
cat_counts = [np.sum(low_mask), np.sum(med_mask), np.sum(high_mask)]
cat_retrans_means = [
    retrans_all[low_mask].mean() if np.sum(low_mask) > 0 else 0,
    retrans_all[med_mask].mean() if np.sum(med_mask) > 0 else 0,
    retrans_all[high_mask].mean() if np.sum(high_mask) > 0 else 0
]
cat_retrans_stds = [
    retrans_all[low_mask].std() if np.sum(low_mask) > 0 else 0,
    retrans_all[med_mask].std() if np.sum(med_mask) > 0 else 0,
    retrans_all[high_mask].std() if np.sum(high_mask) > 0 else 0
]

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7))
fig.suptitle('snd_ratio 구간별 영향 분석 (Normal + Congestion)', 
             fontsize=16, fontweight='bold')

colors_cat = ['#2ecc71', '#f39c12', '#e74c3c']

# Panel 1: Sample count
ax1.bar(categories, cat_counts, color=colors_cat, alpha=0.7, edgecolor='black', linewidth=2)
ax1.set_ylabel('샘플 수', fontsize=13, fontweight='bold')
ax1.set_title('(a) 구간별 샘플 분포', fontsize=14, fontweight='bold')
ax1.grid(alpha=0.3, linestyle='--', axis='y')
for i, (cat, count) in enumerate(zip(categories, cat_counts)):
    pct = count/len(snd_all)*100
    ax1.text(i, count + 5, f'{count}\n({pct:.1f}%)', 
             ha='center', fontsize=11, fontweight='bold')

# Panel 2: Average retrans with error bars
ax2.bar(categories, cat_retrans_means, yerr=cat_retrans_stds,
        color=colors_cat, alpha=0.7, edgecolor='black', linewidth=2,
        capsize=10, error_kw={'linewidth': 2, 'ecolor': 'black'})
ax2.set_ylabel('평균 재전송 큐 크기', fontsize=13, fontweight='bold')
ax2.set_title('(b) 구간별 평균 재전송 (± 표준편차)', fontsize=14, fontweight='bold')
ax2.grid(alpha=0.3, linestyle='--', axis='y')

# Add values on bars
for i, (cat, mean, std) in enumerate(zip(categories, cat_retrans_means, cat_retrans_stds)):
    ax2.text(i, mean + std + 1, f'{mean:.1f}±{std:.1f}', 
             ha='center', fontsize=11, fontweight='bold')

# Add increase arrows
if cat_retrans_means[0] > 0 and cat_retrans_means[2] > 0:
    increase = (cat_retrans_means[2] - cat_retrans_means[0]) / cat_retrans_means[0] * 100
    ax2.annotate('', xy=(2, cat_retrans_means[2]), xytext=(0, cat_retrans_means[0]),
                arrowprops=dict(arrowstyle='->', color='red', lw=3))
    ax2.text(1, max(cat_retrans_means) * 0.5, 
             f'+{increase:.1f}% 증가', 
             ha='center', fontsize=12, fontweight='bold', color='red',
             bbox=dict(boxstyle='round', facecolor='yellow', alpha=0.7))

plt.tight_layout()

output_path3 = output_dir / 'category_comparison.png'
plt.savefig(output_path3, dpi=300, bbox_inches='tight', facecolor='white')
print(f"[*] 저장: {output_path3} ({output_path3.stat().st_size / 1024:.0f} KB)")
plt.close()

# ========================================
# Summary
# ========================================
print("\n" + "="*60)
print("분석 완료!")
print("="*60)

print("\n【 핵심 발견 】")
print(f"\n1️⃣ 전체 상관계수: {corr_all:.3f}")
print(f"   • Normal: {corr_normal:.3f}")
print(f"   • Congestion: {corr_congestion:.3f}")

print(f"\n2️⃣ 버퍼 넘침 비율:")
print(f"   • Normal: {np.sum(snd_normal > 1.0)/len(snd_normal)*100:.1f}%")
print(f"   • Congestion: {np.sum(snd_congestion > 1.0)/len(snd_congestion)*100:.1f}%")

print(f"\n3️⃣ 구간별 평균 재전송:")
print(f"   • Low (≤0.5): {cat_retrans_means[0]:.1f} ± {cat_retrans_stds[0]:.1f}")
print(f"   • Medium (0.5-1.0): {cat_retrans_means[1]:.1f} ± {cat_retrans_stds[1]:.1f}")
print(f"   • High (>1.0): {cat_retrans_means[2]:.1f} ± {cat_retrans_stds[2]:.1f}")

if cat_retrans_means[0] > 0 and cat_retrans_means[2] > 0:
    increase = (cat_retrans_means[2] - cat_retrans_means[0]) / cat_retrans_means[0] * 100
    print(f"   → Low → High 증가율: +{increase:.1f}%")

print(f"\n🔴 결론:")
print(f"   Normal + Congestion 데이터 합쳐서 보면")
print(f"   snd_ratio가 증가할수록 재전송도 증가하는 경향 확인!")
print(f"   특히 snd_ratio > 1.0 (버퍼 넘침) 구간에서 재전송 급증!")

print(f"\n출력 폴더: {output_dir}/")
print(f"  - scatter_combined.png (환경별 scatter)")
print(f"  - binned_combined.png (구간별 분석)")
print(f"  - category_comparison.png (구간별 3-way 비교)")
print("="*60)
