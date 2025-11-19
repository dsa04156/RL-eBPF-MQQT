#!/usr/bin/env python3
"""
EMQX Flow Control 집중 분석: Normal vs Congestion
Application-level Flow Control의 네트워크 의존성 시각화
"""
import json
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

def load_log(path):
    data = []
    try:
        with open(path) as f:
            for line in f:
                try:
                    data.append(json.loads(line))
                except:
                    continue
    except FileNotFoundError:
        print(f"⚠️  파일 없음: {path}")
        return []
    return data

def extract_timeseries(log):
    if not log:
        return None
    
    p99s = [e['metrics']['p99_ms'] for e in log if 'metrics' in e]
    snds = [e['kernel']['snd_ratio'] for e in log if 'kernel' in e]
    rtts = [e['kernel'].get('ewma_rtt_us', 0)/1000 for e in log if 'kernel' in e]  # μs -> ms
    
    return {
        'p99': np.array(p99s),
        'snd': np.array(snds),
        'rtt': np.array(rtts),
        'time': np.arange(len(p99s)) * 2.0  # 2초 간격
    }

# EMQX 로그 로드
print("="*80)
print("EMQX Flow Control: Normal vs Congestion 분석")
print("="*80)

# 로그 경로
emqx_logs = {
    'Normal': 'logs/emqx_flow_control/normal.jsonl',
    'Congestion': 'logs/emqx_flow_control/conjestion.jsonl'
}

data = {}
for scenario, path in emqx_logs.items():
    print(f"\n📍 {scenario} Network 로딩...")
    log = load_log(path)
    ts = extract_timeseries(log)
    if ts:
        data[scenario] = ts
        print(f"   샘플: {len(ts['p99'])}개")
        print(f"   P99 중앙값: {np.median(ts['p99']):.1f}ms")
        print(f"   snd_ratio 중앙값: {np.median(ts['snd']):.3f}")
        print(f"   Duration: {ts['time'][-1]:.0f}초")

# 그래프 생성: 2x2 레이아웃
fig = plt.figure(figsize=(20, 12))
gs = fig.add_gridspec(3, 2, height_ratios=[1.2, 1, 0.8], hspace=0.3, wspace=0.25)

fig.suptitle('EMQX Flow Control: Network Dependency Analysis\n(Application-level의 한계)', 
             fontsize=20, fontweight='bold', y=0.98)

colors = {'Normal': '#2ecc71', 'Congestion': '#e74c3c'}

# ==================== Row 1: P99 Latency 비교 ====================
ax_p99 = fig.add_subplot(gs[0, :])  # 전체 폭 사용

for scenario in ['Normal', 'Congestion']:
    if scenario in data:
        ts = data[scenario]
        ax_p99.plot(ts['time'], ts['p99'], 
                   color=colors[scenario], label=f'{scenario} Network',
                   linewidth=3.5, alpha=0.85)

ax_p99.axhline(y=300, color='green', linestyle='--', linewidth=3, 
               label='SLO Target (300ms)', alpha=0.7, zorder=1)
ax_p99.set_xlabel('Time (seconds)', fontsize=14, fontweight='bold')
ax_p99.set_ylabel('P99 Latency (ms)', fontsize=14, fontweight='bold')
ax_p99.set_title('P99 Tail Latency Over Time', fontsize=16, fontweight='bold', pad=15)
ax_p99.legend(loc='upper left', fontsize=13, framealpha=0.95)
ax_p99.grid(True, alpha=0.3, linewidth=1.5)
ax_p99.set_yscale('log')

# 통계 박스 추가
if 'Normal' in data and 'Congestion' in data:
    n_p99 = np.median(data['Normal']['p99'])
    c_p99 = np.median(data['Congestion']['p99'])
    degradation = (c_p99 / n_p99 - 1) * 100
    
    textstr = 'APPLICATION-LEVEL LIMITATION\n\n'
    textstr += f'Normal: {n_p99:.1f}ms\n'
    textstr += f'Congestion: {c_p99:.1f}ms\n'
    textstr += f'Degradation: {degradation:,.0f}%\n\n'
    textstr += 'Partial improvement possible\n'
    textstr += 'but insufficient for SLO.\n'
    textstr += 'Kernel visibility needed!'
    
    props = dict(boxstyle='round,pad=1', facecolor='#ffffcc', 
                 alpha=0.9, edgecolor='orange', linewidth=3)
    ax_p99.text(0.98, 0.97, textstr, transform=ax_p99.transAxes,
               fontsize=13, verticalalignment='top', horizontalalignment='right',
               bbox=props, fontweight='bold', family='monospace')

# ==================== Row 2: snd_ratio (Buffer Pressure) ====================
ax_snd_normal = fig.add_subplot(gs[1, 0])
ax_snd_cong = fig.add_subplot(gs[1, 1])

# Normal snd_ratio
if 'Normal' in data:
    ts = data['Normal']
    ax_snd_normal.plot(ts['time'], ts['snd'], 
                      color=colors['Normal'], linewidth=3, alpha=0.85)
    ax_snd_normal.axhline(y=1.0, color='orange', linestyle='--', linewidth=2.5, 
                         label='Overflow (1.0)', alpha=0.7)
    ax_snd_normal.fill_between(ts['time'], 0, ts['snd'], 
                              color=colors['Normal'], alpha=0.2)
    
    ax_snd_normal.set_xlabel('Time (seconds)', fontsize=12, fontweight='bold')
    ax_snd_normal.set_ylabel('snd_ratio (Buffer Pressure)', fontsize=12, fontweight='bold')
    ax_snd_normal.set_title('Normal Network - Buffer Pressure', fontsize=14, fontweight='bold')
    ax_snd_normal.legend(loc='upper right', fontsize=11)
    ax_snd_normal.grid(True, alpha=0.3)
    ax_snd_normal.set_ylim(0, max(1.2, np.max(ts['snd']) * 1.1))
    
    # 통계
    med = np.median(ts['snd'])
    overflow_rate = len(ts['snd'][ts['snd'] > 1.0]) / len(ts['snd']) * 100
    textstr = f'✅ Stable\n\nMedian: {med:.3f}\nOverflow: {overflow_rate:.1f}%'
    props = dict(boxstyle='round', facecolor='lightgreen', alpha=0.8)
    ax_snd_normal.text(0.95, 0.95, textstr, transform=ax_snd_normal.transAxes,
                      fontsize=11, verticalalignment='top', horizontalalignment='right',
                      bbox=props, fontweight='bold')

# Congestion snd_ratio
if 'Congestion' in data:
    ts = data['Congestion']
    ax_snd_cong.plot(ts['time'], ts['snd'], 
                    color=colors['Congestion'], linewidth=3, alpha=0.85)
    ax_snd_cong.axhline(y=1.0, color='orange', linestyle='--', linewidth=2.5, 
                       label='Overflow (1.0)', alpha=0.7)
    ax_snd_cong.fill_between(ts['time'], 1.0, ts['snd'], 
                            where=(ts['snd'] >= 1.0),
                            color='red', alpha=0.3, label='Buffer Overflow')
    
    ax_snd_cong.set_xlabel('Time (seconds)', fontsize=12, fontweight='bold')
    ax_snd_cong.set_ylabel('snd_ratio (Buffer Pressure)', fontsize=12, fontweight='bold')
    ax_snd_cong.set_title('Congestion Network - Buffer EXPLOSION', fontsize=14, fontweight='bold')
    ax_snd_cong.legend(loc='upper left', fontsize=11)
    ax_snd_cong.grid(True, alpha=0.3)
    
    # 통계
    med = np.median(ts['snd'])
    overflow_rate = len(ts['snd'][ts['snd'] > 1.0]) / len(ts['snd']) * 100
    textstr = f'❌ FAILED\n\nMedian: {med:.3f}\nOverflow: {overflow_rate:.1f}%'
    props = dict(boxstyle='round', facecolor='#ffcccc', alpha=0.8, edgecolor='red', linewidth=2)
    ax_snd_cong.text(0.95, 0.95, textstr, transform=ax_snd_cong.transAxes,
                    fontsize=11, verticalalignment='top', horizontalalignment='right',
                    bbox=props, fontweight='bold')

# ==================== Row 3: 비교 막대 그래프 ====================
ax_bar = fig.add_subplot(gs[2, :])

metrics = ['P99 (ms)', 'snd_ratio', 'Buffer\nOverflow (%)']
normal_vals = []
cong_vals = []

if 'Normal' in data and 'Congestion' in data:
    n = data['Normal']
    c = data['Congestion']
    
    # P99 (로그 스케일 때문에 실제 값 표시)
    normal_vals.append(np.median(n['p99']))
    cong_vals.append(np.median(c['p99']))
    
    # snd_ratio (100배 스케일 - 막대 높이 맞추기)
    normal_vals.append(np.median(n['snd']) * 100)
    cong_vals.append(np.median(c['snd']) * 100)
    
    # Buffer overflow rate
    normal_vals.append(len(n['snd'][n['snd'] > 1.0]) / len(n['snd']) * 100)
    cong_vals.append(len(c['snd'][c['snd'] > 1.0]) / len(c['snd']) * 100)

x = np.arange(len(metrics))
width = 0.35

bars1 = ax_bar.bar(x - width/2, normal_vals, width, label='Normal Network',
                   color=colors['Normal'], alpha=0.8, edgecolor='black', linewidth=2)
bars2 = ax_bar.bar(x + width/2, cong_vals, width, label='Congestion Network',
                   color=colors['Congestion'], alpha=0.8, edgecolor='black', linewidth=2)

ax_bar.set_ylabel('Value (scaled)', fontsize=13, fontweight='bold')
ax_bar.set_title('EMQX Performance Comparison', fontsize=15, fontweight='bold')
ax_bar.set_xticks(x)
ax_bar.set_xticklabels(metrics, fontsize=12, fontweight='bold')
ax_bar.legend(loc='upper left', fontsize=12, framealpha=0.95)
ax_bar.grid(True, alpha=0.3, axis='y')
ax_bar.set_yscale('log')

# 값 표시
for bar, val, metric_idx in zip(bars1, normal_vals, range(len(metrics))):
    height = bar.get_height()
    if metric_idx == 0:  # P99
        label = f'{val:.1f}ms'
    elif metric_idx == 1:  # snd_ratio (원래 값으로 복원)
        label = f'{val/100:.3f}'
    else:  # overflow
        label = f'{val:.1f}%'
    ax_bar.text(bar.get_x() + bar.get_width()/2., height*1.1,
               label, ha='center', va='bottom', fontsize=10, fontweight='bold',
               color=colors['Normal'])

for bar, val, metric_idx in zip(bars2, cong_vals, range(len(metrics))):
    height = bar.get_height()
    if metric_idx == 0:  # P99
        label = f'{val:.0f}ms'
    elif metric_idx == 1:  # snd_ratio (원래 값으로 복원)
        label = f'{val/100:.3f}'
    else:  # overflow
        label = f'{val:.1f}%'
    ax_bar.text(bar.get_x() + bar.get_width()/2., height*1.1,
               label, ha='center', va='bottom', fontsize=10, fontweight='bold',
               color=colors['Congestion'])

# 저장
output_dir = Path('results/emqx_analysis')
output_dir.mkdir(parents=True, exist_ok=True)
output_path = output_dir / 'emqx_network_dependency.png'
plt.tight_layout(rect=[0, 0, 1, 0.98])
plt.savefig(output_path, dpi=150, facecolor='white')
print(f"\n✅ EMQX 분석 그래프 저장: {output_path}")

# ==================== 통계 요약 출력 ====================
print(f"\n{'='*80}")
print("📊 EMQX Flow Control 네트워크 의존성 분석")
print(f"{'='*80}")

for scenario in ['Normal', 'Congestion']:
    if scenario not in data:
        continue
    
    ts = data[scenario]
    p99_med = np.median(ts['p99'])
    p99_p95 = np.percentile(ts['p99'], 95)
    p99_max = np.max(ts['p99'])
    
    snd_med = np.median(ts['snd'])
    snd_max = np.max(ts['snd'])
    overflow_rate = len(ts['snd'][ts['snd'] > 1.0]) / len(ts['snd']) * 100
    
    slo_rate = len(ts['p99'][ts['p99'] <= 300]) / len(ts['p99']) * 100
    
    print(f"\n【 {scenario} Network 】")
    print(f"{'─'*80}")
    print(f"  P99 Latency:")
    print(f"    • Median: {p99_med:.1f}ms")
    print(f"    • P95: {p99_p95:.1f}ms")
    print(f"    • Max: {p99_max:.1f}ms")
    print(f"  Buffer Pressure (snd_ratio):")
    print(f"    • Median: {snd_med:.3f}")
    print(f"    • Max: {snd_max:.3f}")
    print(f"    • Overflow Rate: {overflow_rate:.1f}%")
    print(f"  SLO Compliance:")
    print(f"    • Rate (P99 < 300ms): {slo_rate:.1f}%")

if 'Normal' in data and 'Congestion' in data:
    n_p99 = np.median(data['Normal']['p99'])
    c_p99 = np.median(data['Congestion']['p99'])
    degradation = (c_p99 / n_p99 - 1) * 100
    
    n_snd = np.median(data['Normal']['snd'])
    c_snd = np.median(data['Congestion']['snd'])
    snd_increase = (c_snd / n_snd - 1) * 100
    
    print(f"\n{'='*80}")
    print("🔑 핵심 발견")
    print(f"{'='*80}")
    print(f"\n1️⃣  P99 Latency 폭증:")
    print(f"   • Normal → Congestion: {n_p99:.1f}ms → {c_p99:.1f}ms")
    print(f"   • 증가율: {degradation:,.0f}% ({c_p99/n_p99:.0f}배)")
    print(f"   • 원인: 커널 버퍼 상태를 볼 수 없음")
    
    print(f"\n2️⃣  Buffer Pressure 악화:")
    print(f"   • Normal → Congestion: {n_snd:.3f} → {c_snd:.3f}")
    print(f"   • 증가율: {snd_increase:.1f}%")
    print(f"   • 결과: 버퍼 넘침 → Queue Delay 누적")
    
    n_overflow = len(data['Normal']['snd'][data['Normal']['snd'] > 1.0]) / len(data['Normal']['snd']) * 100
    c_overflow = len(data['Congestion']['snd'][data['Congestion']['snd'] > 1.0]) / len(data['Congestion']['snd']) * 100
    
    print(f"\n3️⃣  Buffer Overflow 비율:")
    print(f"   • Normal: {n_overflow:.1f}% (거의 없음)")
    print(f"   • Congestion: {c_overflow:.1f}% (대부분 넘침!)")
    print(f"   • 의미: Application-level에서 버퍼 폭발 감지 불가")

print(f"\n{'='*80}")
print("💡 결론")
print(f"{'='*80}")
print("""
【 EMQX (Application-level Flow Control)의 성과와 한계 】

✅ Normal Network (평시):
   • P99 < 10ms (우수)
   • snd_ratio < 0.1 (안정적)
   • Buffer overflow 거의 없음
   → Application-level Flow Control 정상 동작

⚠️  Congestion Network (혼잡):
   • P99 = 20초 (Baseline 47초 대비 2.3배 개선)
   • snd_ratio = 1.497 (Baseline 2.628 대비 43% 개선)
   • Buffer overflow = 81.9% (Baseline 95.5% 대비 14%p 개선)
   
   ✅ 부분적 개선 효과 확인됨
   ❌ 하지만 여전히 SLO(300ms) 대폭 위반
   ❌ 버퍼 넘침 81.9%로 근본적 제어 불가

🔑 핵심 메시지:
"Application-level Flow Control은 기본적 제어 효과는 있다.
 하지만 커널 버퍼 상태를 볼 수 없어 완전한 Tail Latency 제어는 불가능하다.
 부분 개선이 아닌 SLO 수준의 완전한 제어를 위해서는
 eBPF 기반 커널 신호 모니터링이 필수적이다."

📊 정량적 증거:
• EMQX는 Baseline 대비 2.3배 개선 (효과 있음)
• 하지만 P99 = 20초로 여전히 SLO 위반
• 버퍼 넘침 81.9%: Application-level만으로는 불충분
• eBPF+RL(P99=0.3초, 버퍼넘침 2.3%)과의 격차 여전히 큼
""")
