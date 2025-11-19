#!/usr/bin/env python3
"""
재전송 증가 vs Throughput 유지 역설 분석
왜 재전송이 100%인데도 Throughput이 6%만 감소하는가?
"""

import json
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.gridspec import GridSpec

def load_log(log_path):
    data = []
    with open(log_path) as f:
        for line in f:
            if line.strip():
                try:
                    data.append(json.loads(line))
                except:
                    continue
    return data

def extract_detailed_metrics(data):
    """더 상세한 지표 추출"""
    timestamps = []
    p99_values = []
    p50_values = []
    throughputs = []
    retrans_flags = []
    rtt_values = []
    snd_ratios = []
    
    # 추가: 총 메시지 수와 윈도우 크기
    total_msgs = []
    window_secs = []
    msg_counts = []
    
    for d in data:
        ts = d.get('ts', 0)
        timestamps.append(ts)
        
        metrics = d.get('metrics', {})
        p99_values.append(metrics.get('p99_ms', 0))
        p50_values.append(metrics.get('p50_ms', 0))
        
        n = metrics.get('n', 0)
        window = metrics.get('window_sec', 30.0)
        total = metrics.get('total_msgs', 0)
        
        msg_counts.append(n)
        total_msgs.append(total)
        window_secs.append(window)
        
        thr = n / window if window > 0 else 0
        throughputs.append(thr)
        
        kernel = d.get('kernel', {})
        retrans_flags.append(1 if kernel.get('had_retrans', False) else 0)
        rtt_values.append(kernel.get('ewma_rtt_us', 0) / 1000.0)
        snd_ratios.append(kernel.get('snd_ratio', 0))
    
    if timestamps:
        t_start = timestamps[0]
        timestamps = [(t - t_start) for t in timestamps]
    
    return {
        't': timestamps,
        'p99': p99_values,
        'p50': p50_values,
        'throughput': throughputs,
        'retrans': retrans_flags,
        'rtt': rtt_values,
        'snd_ratio': snd_ratios,
        'msg_count': msg_counts,
        'total_msgs': total_msgs,
        'window_sec': window_secs
    }

print("=" * 80)
print("🔍 재전송 vs Throughput 역설 분석")
print("=" * 80)

# Load logs
normal_raw = load_log("logs/emqx_flow_control/normal.jsonl")
congestion_raw = load_log("logs/emqx_flow_control/congestion.jsonl")

normal = extract_detailed_metrics(normal_raw)
congestion = extract_detailed_metrics(congestion_raw)

print(f"\n✅ Loaded:")
print(f"   Normal: {len(normal_raw)} steps")
print(f"   Congestion: {len(congestion_raw)} steps")

# 상세 분석
print("\n" + "=" * 80)
print("📊 상세 메트릭 비교")
print("=" * 80)

normal_avg_msg_count = np.mean(normal['msg_count'])
congestion_avg_msg_count = np.mean(congestion['msg_count'])

normal_avg_throughput = np.mean(normal['throughput'])
congestion_avg_throughput = np.mean(congestion['throughput'])

normal_retrans_rate = np.mean(normal['retrans']) * 100
congestion_retrans_rate = np.mean(congestion['retrans']) * 100

normal_avg_p50 = np.mean(normal['p50'])
congestion_avg_p50 = np.mean(congestion['p50'])

normal_avg_p99 = np.mean(normal['p99'])
congestion_avg_p99 = np.mean(congestion['p99'])

print(f"\n{'Metric':<30} | {'Normal':<15} | {'Congestion':<15} | {'Change':<15}")
print("-" * 85)
print(f"{'Avg msg per window':<30} | {normal_avg_msg_count:>13.1f} | {congestion_avg_msg_count:>13.1f} | "
      f"{((congestion_avg_msg_count - normal_avg_msg_count) / normal_avg_msg_count * 100):>+13.1f}%")
print(f"{'Throughput (msg/s)':<30} | {normal_avg_throughput:>13.1f} | {congestion_avg_throughput:>13.1f} | "
      f"{((congestion_avg_throughput - normal_avg_throughput) / normal_avg_throughput * 100):>+13.1f}%")
print(f"{'Retrans Rate (%)':<30} | {normal_retrans_rate:>13.1f} | {congestion_retrans_rate:>13.1f} | "
      f"{congestion_retrans_rate - normal_retrans_rate:>+13.1f}pp")
print(f"{'P50 Latency (ms)':<30} | {normal_avg_p50:>13.1f} | {congestion_avg_p50:>13.1f} | "
      f"{((congestion_avg_p50 - normal_avg_p50) / normal_avg_p50 * 100):>+13.1f}%")
print(f"{'P99 Latency (ms)':<30} | {normal_avg_p99:>13.1f} | {congestion_avg_p99:>13.1f} | "
      f"{((congestion_avg_p99 - normal_avg_p99) / normal_avg_p99 * 100):>+13.1f}%")

# 핵심 분석: Throughput이 유지되는 이유
print("\n" + "=" * 80)
print("🔑 왜 재전송은 증가하는데 Throughput은 유지되는가?")
print("=" * 80)

print("""
📌 핵심 원인 분석:

1️⃣ **재전송 플래그의 의미**
   - `had_retrans=true`는 "해당 관찰 윈도우 동안 1번 이상 재전송 발생"
   - 재전송 **빈도**나 **재전송된 패킷 수**를 나타내지 않음
   - 100% 재전송률 = 모든 윈도우에서 최소 1번 이상 재전송
   
2️⃣ **Throughput의 정의**
   - Throughput = 응용 계층에서 전달된 메시지 수 / 시간
   - TCP는 재전송을 **투명하게 처리** (응용 계층은 모름)
   - 재전송이 성공하면 → 메시지는 결국 전달됨
   
3️⃣ **왜 Throughput이 6%만 감소하는가?**
   
   a) **TCP의 신뢰성 메커니즘**
      - 재전송이 발생해도 패킷은 결국 전달됨
      - Throughput = "성공적으로 전달된 메시지"
      - 재전송은 지연을 증가시키지만, 전달 실패는 아님
   
   b) **큐잉과 버퍼링**
      - 네트워크 혼잡 시 패킷이 큐에 대기
      - 지연은 증가하지만 처리량은 유지
      - P99는 폭발하지만, 평균 처리 속도는 비슷
   
   c) **윈도우 크기 효과**
      - 30초 윈도우 = 매우 긴 관찰 기간
      - 순간적 지연 spike는 평균에 희석됨
      - 메시지는 늦게 도착하지만 결국 도착함
   
   d) **송신 속도 제한**
      - Publisher가 일정 속도로 메시지 생성
      - 재전송이 증가해도 송신 속도는 동일
      - Throughput = min(송신속도, 네트워크용량)
      - 병목은 송신 측에 있음
""")

# 실제 증거 찾기
print("\n" + "=" * 80)
print("📈 실제 데이터에서 증거 찾기")
print("=" * 80)

# P50 vs P99 비교
normal_p50_p99_ratio = normal_avg_p99 / normal_avg_p50
congestion_p50_p99_ratio = congestion_avg_p99 / congestion_avg_p50

print(f"\nP99 / P50 비율 (Tail 증폭):")
print(f"  Normal:     {normal_p50_p99_ratio:.1f}x")
print(f"  Congestion: {congestion_p50_p99_ratio:.1f}x")
print(f"  → Congestion에서 tail이 {congestion_p50_p99_ratio / normal_p50_p99_ratio:.1f}배 더 증폭")
print(f"  💡 대부분의 메시지는 빨리 처리되지만, 일부가 극단적으로 지연됨")

# 메시지 변동성
normal_msg_std = np.std(normal['msg_count'])
congestion_msg_std = np.std(congestion['msg_count'])

print(f"\n메시지 수 변동성 (표준편차):")
print(f"  Normal:     {normal_msg_std:.1f}")
print(f"  Congestion: {congestion_msg_std:.1f}")
print(f"  → Congestion에서 {((congestion_msg_std - normal_msg_std) / normal_msg_std * 100):+.1f}% 변화")

# RTT와 Throughput 상관관계
corr_rtt_thr_normal = np.corrcoef(normal['rtt'], normal['throughput'])[0, 1]
corr_rtt_thr_congestion = np.corrcoef(congestion['rtt'], congestion['throughput'])[0, 1]

print(f"\nRTT vs Throughput 상관관계:")
print(f"  Normal:     r = {corr_rtt_thr_normal:+.3f}")
print(f"  Congestion: r = {corr_rtt_thr_congestion:+.3f}")

if abs(corr_rtt_thr_congestion) < 0.3:
    print(f"  💡 약한 상관관계 → RTT 증가가 Throughput에 직접 영향 적음")
    print(f"     이유: TCP 재전송이 지연을 흡수하지만 전달은 보장")

# 진짜 문제: 유효 성능 (Goodput) vs Throughput
print("\n" + "=" * 80)
print("⚠️ 진짜 문제: Throughput vs Goodput")
print("=" * 80)

print("""
🔴 **Throughput이 유지되는 게 문제가 아닙니다!**

실제 성능 저하는 다음에서 나타납니다:

1️⃣ **사용자 경험 (Latency)**
   - P99: 269ms → 50,803ms (188배 증가!)
   - 사용자가 느끼는 지연은 극단적으로 악화
   - Throughput은 유지되지만 반응성은 파괴됨

2️⃣ **네트워크 효율성 (Goodput)**
   - Goodput = 유용한 데이터 / 총 전송 데이터
   - 재전송 100% = 많은 패킷이 중복 전송됨
   - 네트워크 대역폭 낭비, 에너지 낭비
   
3️⃣ **시스템 자원 소비**
   - 재전송으로 인한 CPU 사용량 증가
   - 버퍼 메모리 압박
   - 커널 오버헤드 증가

4️⃣ **SLO 위반**
   - Throughput SLO는 달성
   - 하지만 Latency SLO는 완전 실패
   - 실시간 응용에서는 치명적

💡 **결론:**
   "재전송이 증가해도 Throughput이 유지되는 것"은
   TCP가 잘 작동한다는 증거이지만,
   동시에 "P99가 폭발하는데도 평균 지표가 정상"이라는
   **tail latency 문제의 위험성**을 보여줍니다!
   
   → 이것이 바로 P99 제어가 필요한 이유입니다!
""")

# Visualization
fig = plt.figure(figsize=(16, 10))
gs = GridSpec(3, 2, figure=fig, hspace=0.35, wspace=0.3)

# 1. Throughput over time
ax1 = fig.add_subplot(gs[0, :])
ax1.plot(normal['t'], normal['throughput'], 'g-', linewidth=1.5, alpha=0.7, label='Normal')
ax1.plot(congestion['t'], congestion['throughput'], 'r-', linewidth=1.5, alpha=0.7, label='Congestion')
ax1.axhline(y=normal_avg_throughput, color='green', linestyle='--', linewidth=2, alpha=0.5, 
            label=f'Normal Avg: {normal_avg_throughput:.1f}')
ax1.axhline(y=congestion_avg_throughput, color='red', linestyle='--', linewidth=2, alpha=0.5,
            label=f'Congestion Avg: {congestion_avg_throughput:.1f}')
ax1.set_xlabel('Time (seconds)', fontsize=12, fontweight='bold')
ax1.set_ylabel('Throughput (msg/s)', fontsize=12, fontweight='bold')
ax1.set_title('Throughput: 재전송 100%인데도 6%만 감소 (왜?)', fontsize=14, fontweight='bold')
ax1.legend(fontsize=10, loc='upper right')
ax1.grid(True, alpha=0.3)

# 2. P50 vs P99 comparison
ax2 = fig.add_subplot(gs[1, 0])
scenarios = ['Normal', 'Congestion']
p50_vals = [normal_avg_p50, congestion_avg_p50]
p99_vals = [normal_avg_p99, congestion_avg_p99]

x = np.arange(len(scenarios))
width = 0.35

bars1 = ax2.bar(x - width/2, p50_vals, width, label='P50 (Median)', alpha=0.8, color='steelblue')
bars2 = ax2.bar(x + width/2, p99_vals, width, label='P99 (Tail)', alpha=0.8, color='coral')

for bar, val in zip(bars1, p50_vals):
    ax2.text(bar.get_x() + bar.get_width()/2., bar.get_height(),
             f'{val:.0f}ms', ha='center', va='bottom', fontweight='bold', fontsize=10)

for bar, val in zip(bars2, p99_vals):
    ax2.text(bar.get_x() + bar.get_width()/2., bar.get_height(),
             f'{val:.0f}ms', ha='center', va='bottom', fontweight='bold', fontsize=10)

ax2.set_xticks(x)
ax2.set_xticklabels(scenarios, fontsize=11, fontweight='bold')
ax2.set_ylabel('Latency (ms)', fontsize=12, fontweight='bold')
ax2.set_title('P50는 괜찮지만 P99는 폭발 (Tail Latency Problem)', fontsize=12, fontweight='bold')
ax2.legend(fontsize=10)
ax2.set_yscale('log')
ax2.grid(True, alpha=0.3, axis='y')

# 3. P99/P50 ratio
ax3 = fig.add_subplot(gs[1, 1])
ratios = [normal_p50_p99_ratio, congestion_p50_p99_ratio]
colors = ['green', 'red']
bars = ax3.bar(scenarios, ratios, color=colors, alpha=0.7, edgecolor='black', linewidth=2)

for bar, ratio in zip(bars, ratios):
    ax3.text(bar.get_x() + bar.get_width()/2., bar.get_height(),
             f'{ratio:.1f}x', ha='center', va='bottom', fontweight='bold', fontsize=12)

ax3.set_ylabel('P99 / P50 Ratio', fontsize=12, fontweight='bold')
ax3.set_title('Tail 증폭 비율 (높을수록 일부 메시지만 극단 지연)', fontsize=12, fontweight='bold')
ax3.axhline(y=10, color='orange', linestyle='--', linewidth=2, alpha=0.5, label='경고 수준 (10x)')
ax3.legend(fontsize=10)
ax3.grid(True, alpha=0.3, axis='y')

# 4. Retransmission timeline with throughput overlay
ax4 = fig.add_subplot(gs[2, :])
ax4_twin = ax4.twinx()

# Retransmission cumulative
cumul_retrans_normal = np.cumsum(normal['retrans'])
cumul_retrans_congestion = np.cumsum(congestion['retrans'])

line1 = ax4.plot(normal['t'], cumul_retrans_normal, 'g-', linewidth=2, alpha=0.7, label='Normal (Cumulative Retrans)')
line2 = ax4.plot(congestion['t'], cumul_retrans_congestion, 'r-', linewidth=2, alpha=0.7, label='Congestion (Cumulative Retrans)')
ax4.set_ylabel('Cumulative Retransmissions', fontsize=12, fontweight='bold', color='black')
ax4.set_xlabel('Time (seconds)', fontsize=12, fontweight='bold')

# Throughput overlay
line3 = ax4_twin.plot(normal['t'], normal['throughput'], 'g--', linewidth=1.5, alpha=0.5, label='Normal (Throughput)')
line4 = ax4_twin.plot(congestion['t'], congestion['throughput'], 'r--', linewidth=1.5, alpha=0.5, label='Congestion (Throughput)')
ax4_twin.set_ylabel('Throughput (msg/s)', fontsize=12, fontweight='bold', color='blue')
ax4_twin.tick_params(axis='y', labelcolor='blue')

# Combined legend
lines = line1 + line2 + line3 + line4
labels = [l.get_label() for l in lines]
ax4.legend(lines, labels, fontsize=9, loc='upper left')

ax4.set_title('재전송은 폭증하지만 Throughput은 유지 (TCP의 투명한 재전송)', fontsize=13, fontweight='bold')
ax4.grid(True, alpha=0.3)

fig.suptitle('재전송 증가 vs Throughput 유지의 역설: TCP는 성공했지만 사용자는 실패', 
             fontsize=16, fontweight='bold', y=0.995)

plt.savefig('results/retrans_throughput_paradox.png', dpi=300, bbox_inches='tight')
print("\n✅ Saved: results/retrans_throughput_paradox.png")

plt.savefig('results/retrans_throughput_paradox.pdf', bbox_inches='tight')
print("✅ Saved: results/retrans_throughput_paradox.pdf")

print("\n" + "=" * 80)
print("✅ Analysis Complete!")
print("=" * 80)
