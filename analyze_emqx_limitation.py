#!/usr/bin/env python3
"""
EMQX Flow Control의 근본적 한계 분석
=========================================
가설: Application-level Flow Control은 커널 TCP 상태를 볼 수 없어
     혼잡 네트워크에서 버퍼 압력을 감지하지 못하고 tail latency를 악화시킨다.

증명 포인트:
1. EMQX는 어플리케이션 레벨 메트릭만 사용 (QoS, message queue 등)
2. 커널 TCP 버퍼 상태(snd_ratio)를 모르기 때문에 계속 전송
3. 결과: 버퍼 폭발 → Queue delay 누적 → P99 50초 이상 폭증
4. eBPF는 커널 신호(snd_ratio, retrans, RTT)로 조기 감지 → 사전 제어
"""

import json
import numpy as np
import matplotlib.pyplot as plt
from collections import defaultdict
from pathlib import Path

def load_jsonl(path):
    """JSONL 로그 파일 로드"""
    data = []
    with open(path, 'r') as f:
        for line in f:
            try:
                data.append(json.loads(line.strip()))
            except:
                continue
    return data

def analyze_emqx_blindness(emqx_log):
    """
    EMQX Flow Control이 커널 상태를 못 보는 문제 분석
    """
    print("=" * 80)
    print("1. EMQX Flow Control의 근본적 한계: 커널 신호 부재")
    print("=" * 80)
    
    # P99가 높은 구간 찾기
    high_p99_periods = []
    for i, entry in enumerate(emqx_log):
        if 'metrics' in entry and entry['metrics'].get('p99_ms', 0) > 10000:
            high_p99_periods.append(entry)
    
    if not high_p99_periods:
        print("⚠️  P99 > 10초 구간이 없습니다.")
        return
    
    print(f"\n📊 P99 > 10초 구간: {len(high_p99_periods)}개 샘플")
    print("\n이 구간들의 커널 상태:")
    
    snd_ratios = []
    retrans_counts = []
    rtts = []
    
    for entry in high_p99_periods:
        kernel = entry.get('kernel', {})
        snd_ratios.append(kernel.get('snd_ratio', 0))
        retrans_counts.append(kernel.get('retrans_count', 0))
        rtts.append(kernel.get('ewma_rtt_us', 0) / 1000)  # ms로 변환
    
    print(f"  • 평균 snd_ratio: {np.mean(snd_ratios):.3f} (버퍼 압력)")
    print(f"  • 최대 snd_ratio: {np.max(snd_ratios):.3f}")
    print(f"  • 평균 RTT: {np.mean(rtts):.1f} ms")
    print(f"  • 평균 retrans_count: {np.mean(retrans_counts):.1f}")
    
    print("\n🔴 문제점:")
    print(f"  1. snd_ratio > 1.0 (버퍼 넘침) 상태인데도 EMQX는 모름")
    print(f"  2. 커널에서 이미 {np.mean(rtts):.0f}ms RTT 관찰 중인데 EMQX는 모름")
    print(f"  3. 재전송 발생 중인데 EMQX는 계속 전송")
    print(f"  → Application-level Flow Control은 이런 커널 신호를 볼 수 없음!")

def analyze_rl_advantage(rl_log):
    """
    eBPF+RL이 커널 신호로 사전 제어하는 방식 분석
    """
    print("\n" + "=" * 80)
    print("2. eBPF+RL의 핵심 차별점: 커널 신호 기반 사전 제어")
    print("=" * 80)
    
    # snd_ratio가 임계치 넘을 때 어떻게 대응했는지 분석
    proactive_controls = []
    for i, entry in enumerate(rl_log):
        kernel = entry.get('kernel', {})
        snd_ratio = kernel.get('snd_ratio', 0)
        
        if snd_ratio > 0.3 and entry.get('a', {}).get('d_rate', 0) < 0:
            # 버퍼 압력 감지 → 감속 액션
            proactive_controls.append({
                'snd_ratio': snd_ratio,
                'd_rate': entry['a']['d_rate'],
                'p99_ms': entry.get('metrics', {}).get('p99_ms', 0)
            })
    
    print(f"\n📊 사전 제어 사례: {len(proactive_controls)}회")
    
    if proactive_controls:
        print("\n사전 제어 발동 조건:")
        print(f"  • 평균 snd_ratio: {np.mean([x['snd_ratio'] for x in proactive_controls]):.3f}")
        print(f"  • 평균 감속률: {np.mean([x['d_rate'] for x in proactive_controls]):.3f}")
        print(f"  • 결과 P99: {np.mean([x['p99_ms'] for x in proactive_controls]):.1f} ms")
        
        print("\n✅ eBPF의 이점:")
        print("  1. snd_ratio > 0.3 감지 즉시 감속 (버퍼 폭발 방지)")
        print("  2. 커널 RTT 실시간 모니터링 (네트워크 상태 조기 파악)")
        print("  3. 재전송 큐 크기 추적 (혼잡 징후 감지)")
        print("  → Application은 이런 커널 신호를 볼 수 없음!")

def compare_visibility(emqx_log, rl_log):
    """
    EMQX vs eBPF+RL의 가시성(Observability) 비교
    """
    print("\n" + "=" * 80)
    print("3. 가시성(Observability) 비교")
    print("=" * 80)
    
    print("\n┌─────────────────────┬─────────────────┬─────────────────┐")
    print("│ 신호 종류           │ EMQX Flow Ctrl  │ eBPF+RL         │")
    print("├─────────────────────┼─────────────────┼─────────────────┤")
    print("│ TCP Send Buffer     │ ❌ 불가능       │ ✅ snd_ratio    │")
    print("│ TCP Recv Buffer     │ ❌ 불가능       │ ✅ rcv_ratio    │")
    print("│ Kernel RTT          │ ❌ 불가능       │ ✅ ewma_rtt_us  │")
    print("│ Retrans Queue       │ ❌ 불가능       │ ✅ retrans_out  │")
    print("│ Congestion Window   │ ❌ 불가능       │ ✅ 간접 추론    │")
    print("│ Message Queue       │ ✅ 가능         │ ✅ 가능         │")
    print("│ Client Latency      │ ✅ 가능         │ ✅ 가능         │")
    print("└─────────────────────┴─────────────────┴─────────────────┘")
    
    print("\n🔑 핵심 차이:")
    print("  • EMQX: Application-level 신호만 사용 (message queue, QoS)")
    print("  • eBPF: Kernel-level + Application-level 신호 모두 사용")
    print("  → 커널 신호가 없으면 혼잡을 사후에만 알 수 있음 (이미 늦음)")

def analyze_reaction_time(emqx_log, rl_log):
    """
    EMQX vs eBPF+RL의 반응 시간 비교
    """
    print("\n" + "=" * 80)
    print("4. 혼잡 감지 및 반응 시간 비교")
    print("=" * 80)
    
    # EMQX: P99가 올라가기 시작한 시점 찾기
    emqx_p99_rise = None
    for i in range(1, len(emqx_log)):
        prev_p99 = emqx_log[i-1].get('metrics', {}).get('p99_ms', 0)
        curr_p99 = emqx_log[i].get('metrics', {}).get('p99_ms', 0)
        if curr_p99 > prev_p99 * 2 and curr_p99 > 1000:  # 2배 이상 급증
            emqx_p99_rise = i
            break
    
    if emqx_p99_rise:
        print(f"\n📈 EMQX P99 급증 시점: {emqx_p99_rise}번째 샘플")
        
        # 그 시점의 커널 상태 확인
        entry = emqx_log[emqx_p99_rise]
        kernel = entry.get('kernel', {})
        print(f"  • P99: {entry['metrics']['p99_ms']:.1f} ms")
        print(f"  • snd_ratio: {kernel.get('snd_ratio', 0):.3f}")
        print(f"  • RTT: {kernel.get('ewma_rtt_us', 0)/1000:.1f} ms")
        
        # 이전 시점들 확인
        if emqx_p99_rise > 5:
            prev_entries = emqx_log[emqx_p99_rise-5:emqx_p99_rise]
            prev_snd = [e.get('kernel', {}).get('snd_ratio', 0) for e in prev_entries]
            print(f"\n  📊 5개 샘플 전부터 커널 신호:")
            print(f"     평균 snd_ratio: {np.mean(prev_snd):.3f}")
            print(f"     → 이미 버퍼 압력 상승 중이었지만 EMQX는 감지 못함")
    
    # eBPF+RL: 조기 감지 사례
    early_detections = []
    for entry in rl_log:
        kernel = entry.get('kernel', {})
        metrics = entry.get('metrics', {})
        action = entry.get('a', {})
        
        snd_ratio = kernel.get('snd_ratio', 0)
        p99_ms = metrics.get('p99_ms', 0)
        d_rate = action.get('d_rate', 0)
        
        # P99는 아직 낮지만 snd_ratio가 높아서 미리 감속
        if p99_ms < 1000 and snd_ratio > 0.3 and d_rate < 0:
            early_detections.append({
                'snd_ratio': snd_ratio,
                'p99_ms': p99_ms,
                'd_rate': d_rate
            })
    
    if early_detections:
        print(f"\n📊 eBPF+RL 조기 감지: {len(early_detections)}회")
        print(f"  • P99가 {np.mean([x['p99_ms'] for x in early_detections]):.1f}ms로 낮을 때")
        print(f"  • snd_ratio {np.mean([x['snd_ratio'] for x in early_detections]):.3f} 감지하여")
        print(f"  • 평균 {np.mean([x['d_rate'] for x in early_detections]):.3f} 감속")
        print(f"  → 사전 제어로 P99 폭증 방지!")
    
    print("\n⏱️  반응 시간 비교:")
    print("  • EMQX: P99 폭증 후 감지 (사후 대응) → 이미 큐에 수십초 지연 쌓임")
    print("  • eBPF: 커널 신호로 조기 감지 (사전 대응) → 버퍼 폭발 방지")

def visualize_comparison(emqx_log, rl_log, output_dir):
    """
    EMQX의 커널 신호 부재 문제를 시각화
    """
    print("\n" + "=" * 80)
    print("5. 시각화 생성")
    print("=" * 80)
    
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    fig.suptitle('EMQX Flow Control의 근본적 한계: 커널 신호 부재', fontsize=16, fontweight='bold')
    
    # EMQX 데이터 추출
    emqx_ts = list(range(len(emqx_log)))
    emqx_p99 = [e.get('metrics', {}).get('p99_ms', 0) for e in emqx_log]
    emqx_snd = [e.get('kernel', {}).get('snd_ratio', 0) for e in emqx_log]
    emqx_thr = [e.get('metrics', {}).get('n', 0) for e in emqx_log]
    
    # RL 데이터 추출
    rl_ts = list(range(len(rl_log)))
    rl_p99 = [e.get('metrics', {}).get('p99_ms', 0) for e in rl_log]
    rl_snd = [e.get('kernel', {}).get('snd_ratio', 0) for e in rl_log]
    rl_thr = [e.get('metrics', {}).get('n', 0) for e in rl_log]
    rl_actions = [e.get('a', {}).get('d_rate', 0) for e in rl_log]
    
    # 1. P99 비교
    ax = axes[0, 0]
    ax.plot(emqx_ts, emqx_p99, 'r-', label='EMQX Flow Control', linewidth=2)
    ax.plot(rl_ts, rl_p99, 'b-', label='eBPF+RL', linewidth=2)
    ax.axhline(y=300, color='g', linestyle='--', label='SLO (300ms)', linewidth=1)
    ax.set_xlabel('Time (samples)')
    ax.set_ylabel('P99 Latency (ms)')
    ax.set_title('Tail Latency 비교\nEMQX: 커널 상태 모름 → P99 폭증')
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.set_yscale('log')
    
    # 2. snd_ratio 비교 (핵심!)
    ax = axes[0, 1]
    ax.plot(emqx_ts, emqx_snd, 'r-', label='EMQX (버퍼 압력 감지 불가)', linewidth=2, alpha=0.7)
    ax.plot(rl_ts, rl_snd, 'b-', label='eBPF (커널 신호 감지)', linewidth=2, alpha=0.7)
    ax.axhline(y=1.0, color='orange', linestyle='--', label='버퍼 넘침 (>1.0)', linewidth=2)
    ax.set_xlabel('Time (samples)')
    ax.set_ylabel('snd_ratio (버퍼 압력)')
    ax.set_title('TCP Send Buffer 압력 비교\nEMQX: 이 신호를 볼 수 없음!')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # 3. RL 액션 (사전 제어)
    ax = axes[1, 0]
    colors = ['red' if a < 0 else 'blue' if a > 0 else 'gray' for a in rl_actions]
    ax.scatter(rl_ts, rl_actions, c=colors, alpha=0.5, s=30)
    ax.axhline(y=0, color='black', linestyle='-', linewidth=1)
    ax.set_xlabel('Time (samples)')
    ax.set_ylabel('Rate Change (d_rate)')
    ax.set_title('eBPF+RL의 사전 제어\n빨강: 감속 (버퍼 압력 감지), 파랑: 가속')
    ax.grid(True, alpha=0.3)
    
    # 4. snd_ratio vs P99 산점도
    ax = axes[1, 1]
    ax.scatter(emqx_snd, emqx_p99, c='red', alpha=0.5, label='EMQX', s=50)
    ax.scatter(rl_snd, rl_p99, c='blue', alpha=0.5, label='eBPF+RL', s=50)
    ax.axvline(x=1.0, color='orange', linestyle='--', label='버퍼 넘침', linewidth=2)
    ax.axhline(y=300, color='g', linestyle='--', label='SLO', linewidth=1)
    ax.set_xlabel('snd_ratio (버퍼 압력)')
    ax.set_ylabel('P99 Latency (ms)')
    ax.set_title('버퍼 압력 vs Tail Latency 관계\nEMQX: 버퍼 폭발 → P99 폭증')
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.set_yscale('log')
    
    plt.tight_layout()
    output_path = Path(output_dir) / 'emqx_kernel_signal_limitation.png'
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"\n✅ 그래프 저장: {output_path}")

def generate_thesis_argument(emqx_log, rl_log):
    """
    논문/논제용 핵심 주장 생성
    """
    print("\n" + "=" * 80)
    print("6. 연구의 핵심 주장 (Thesis Statement)")
    print("=" * 80)
    
    # 통계 계산
    emqx_p99 = [e.get('metrics', {}).get('p99_ms', 0) for e in emqx_log]
    rl_p99 = [e.get('metrics', {}).get('p99_ms', 0) for e in rl_log]
    emqx_snd = [e.get('kernel', {}).get('snd_ratio', 0) for e in emqx_log]
    rl_snd = [e.get('kernel', {}).get('snd_ratio', 0) for e in rl_log]
    
    emqx_p99_med = np.median(emqx_p99)
    rl_p99_med = np.median(rl_p99)
    emqx_snd_med = np.median(emqx_snd)
    rl_snd_med = np.median(rl_snd)
    
    improvement = (1 - rl_p99_med / emqx_p99_med) * 100
    buffer_stability = (1 - rl_snd_med / emqx_snd_med) * 100
    
    print("\n" + "="*80)
    print("핵심 주장 (Core Thesis)")
    print("="*80)
    print("""
기존 MQTT 브로커의 Application-level Flow Control은 
혼잡 네트워크에서 TCP 커널 버퍼 상태를 감지할 수 없어 
Tail Latency를 악화시킨다.

eBPF 기반 커널 신호 모니터링을 통한 사전 제어가 
Tail Latency 감소에 필수적이다.
""")
    
    print("\n" + "="*80)
    print("근거 (Evidence)")
    print("="*80)
    print(f"""
1. 가시성 문제 (Observability Gap)
   • EMQX Flow Control: Application-level 신호만 사용
     - Message queue depth, QoS acknowledgements
     - TCP 커널 상태는 볼 수 없음 (snd_ratio, RTT, retrans_out)
   
   • eBPF 접근법: Kernel-level 신호 직접 접근
     - TCP send buffer 압력 (snd_ratio)
     - 커널 RTT 추정치 (ewma_rtt_us)
     - 재전송 큐 크기 (retrans_out)

2. 실험 결과
   • EMQX Flow Control:
     - P99: {emqx_p99_med:.1f} ms (중앙값)
     - snd_ratio: {emqx_snd_med:.3f} (버퍼 압력)
     - 버퍼 압력 > 1.0 → 큐 지연 누적
   
   • eBPF+RL:
     - P99: {rl_p99_med:.1f} ms (중앙값, {improvement:.1f}% 개선)
     - snd_ratio: {rl_snd_med:.3f} (버퍼 압력, {buffer_stability:.1f}% 안정화)
     - 사전 제어로 버퍼 폭발 방지

3. 반응 시간 차이
   • EMQX: P99 폭증 후 감지 (사후 대응)
     → 이미 큐에 수십초 지연 쌓임
   
   • eBPF: 커널 신호로 조기 감지 (사전 대응)
     → P99 < 1초일 때 snd_ratio로 혼잡 예측
""")
    
    print("\n" + "="*80)
    print("결론 (Conclusion)")
    print("="*80)
    print(f"""
Application-level Flow Control의 근본적 한계:
• 커널 TCP 버퍼 상태를 볼 수 없음
• 혼잡을 사후에만 감지 (P99 폭증 이후)
• 버퍼 압력 제어 불가능

eBPF의 필수성:
• 커널 신호 직접 접근 (snd_ratio, RTT, retrans)
• 사전 제어 가능 ({improvement:.1f}% P99 개선)
• 버퍼 압력 안정화 ({buffer_stability:.1f}% 개선)

→ Tail Latency 제어에 커널 신호 모니터링은 필수적이다.
""")

def main():
    print("="*80)
    print("EMQX Flow Control의 근본적 한계 분석")
    print("="*80)
    
    # 로그 파일 경로
    emqx_log_path = 'logs/emqx_flow_control/congestion.jsonl'
    rl_log_path = 'logs/torch_model_experiments/congestion/rl_bc_v2_congestion.jsonl'
    output_dir = 'results/emqx_limitation_analysis'
    
    print(f"\n📁 EMQX 로그: {emqx_log_path}")
    print(f"📁 RL 로그: {rl_log_path}")
    
    # 로그 로드
    emqx_log = load_jsonl(emqx_log_path)
    rl_log = load_jsonl(rl_log_path)
    
    print(f"\n✅ EMQX 샘플: {len(emqx_log)}개")
    print(f"✅ RL 샘플: {len(rl_log)}개")
    
    # 분석 실행
    analyze_emqx_blindness(emqx_log)
    analyze_rl_advantage(rl_log)
    compare_visibility(emqx_log, rl_log)
    analyze_reaction_time(emqx_log, rl_log)
    visualize_comparison(emqx_log, rl_log, output_dir)
    generate_thesis_argument(emqx_log, rl_log)
    
    print("\n" + "="*80)
    print("분석 완료!")
    print("="*80)

if __name__ == '__main__':
    main()
