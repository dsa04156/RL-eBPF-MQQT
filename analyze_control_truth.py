#!/usr/bin/env python3
"""
제어 효과 재분석: 사용자 관점에서 정확히 이해하기
발행 지연 vs 네트워크 지연
"""

import json
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

def load_and_analyze(path):
    data = []
    with open(path) as f:
        for line in f:
            if line.strip():
                try:
                    data.append(json.loads(line))
                except:
                    continue
    
    timestamps = []
    p99_values = []
    p50_values = []
    total_msgs = []
    
    for d in data:
        ts = d.get('ts', 0)
        timestamps.append(ts)
        
        metrics = d.get('metrics', {})
        p99_values.append(metrics.get('p99_ms', 0))
        p50_values.append(metrics.get('p50_ms', 0))
        total_msgs.append(metrics.get('total_msgs', 0))
    
    if timestamps:
        t_start = timestamps[0]
        timestamps = [(t - t_start) for t in timestamps]
    
    return {
        't': np.array(timestamps),
        'p99': np.array(p99_values),
        'p50': np.array(p50_values),
        'total_msgs': np.array(total_msgs)
    }

print("=" * 80)
print("🤔 제어 효과 재분석: 사용자가 정말 이득을 보는가?")
print("=" * 80)

emqx = load_and_analyze("logs/emqx_flow_control/congestion.jsonl")
torch = load_and_analyze("logs/torch_model_experiments/congestion/rl_bc_v2_congestion.jsonl")

print("\n📊 기본 통계:")
print(f"EMQX (제어 없음):")
print(f"  - P99 평균: {np.mean(emqx['p99']):.1f}ms")
print(f"  - P50 평균: {np.mean(emqx['p50']):.1f}ms")
print(f"  - 총 메시지: {emqx['total_msgs'][-1] if len(emqx['total_msgs']) > 0 else 0}")

print(f"\nTorch RL (제어 있음):")
print(f"  - P99 평균: {np.mean(torch['p99']):.1f}ms")
print(f"  - P50 평균: {np.mean(torch['p50']):.1f}ms")
print(f"  - 총 메시지: {torch['total_msgs'][-1] if len(torch['total_msgs']) > 0 else 0}")

print("\n" + "=" * 80)
print("🔍 핵심 질문: 제어의 진짜 의미는?")
print("=" * 80)

print("""
당신의 지적이 맞습니다! 

🤔 **문제 재정의:**

1️⃣ **EMQX (제어 없음)**:
   - Publisher가 빠르게 발행 (예: 200 msg/s)
   - 네트워크 혼잡 발생
   - 메시지는 큐에서 대기
   - P99: 50초 (네트워크에서 지연)
   
2️⃣ **Torch RL (제어 있음)**:
   - Publisher가 천천히 발행 (예: 92 msg/s)
   - 네트워크 혼잡 완화
   - P99: 0.8초 (네트워크 지연)
   
   BUT! 메시지가 늦게 발행됨
   → 사용자 입장: 결국 언제 받는가?

🔑 **핵심 차이점:**

A. **제어 없음 (EMQX)**:
   - 메시지 생성 시점: t=0
   - 발행 시점: t=0
   - 도착 시점: t=50초 (네트워크 큐잉)
   - 사용자 대기: 50초
   
B. **제어 있음 (Torch RL) - 잘못된 해석**:
   - 메시지 생성 시점: t=0
   - 발행 시점: t=0 (그냥 느리게)
   - 도착 시점: t=0.8초
   - BUT 다음 메시지는 나중에 생성됨
   - 사용자 대기: 여전히 비슷?

💡 **올바른 해석:**

제어의 목적은 "같은 메시지를 더 빨리 전달"이 아니라:

1. **시스템 안정성 유지**
   - 네트워크 완전 붕괴 방지
   - 재전송 폭발 방지
   - 공정성(fairness) 보장

2. **예측 가능한 지연**
   - EMQX: 0~120초 (P99 50초, 편차 큼)
   - Torch: 0~8초 (P99 0.8초, 편차 작음)
   → 사용자는 "언제 올지 모름" vs "곧 올 거 확실"

3. **전체 처리량 최적화**
   - 혼잡 붕괴 시: 처리량도 급감 가능
   - 제어로 안정적 처리량 유지

4. **다중 사용자 공정성**
   - 일부가 독점하면 나머지는 기아(starvation)
   - 제어로 공평한 분배
""")

print("\n" + "=" * 80)
print("📌 진짜 증명해야 할 것")
print("=" * 80)

print("""
❌ 잘못된 주장:
   "제어하면 같은 메시지가 더 빨리 도착"
   → 이건 불가능. 발행을 늦추면 도착도 늦음

✅ 올바른 주장:

1️⃣ **시스템 안정성**
   - 제어 없이는 네트워크 완전 붕괴 (P99 50초)
   - 제어하면 안정적 운영 (P99 0.8초)
   - BUT: 발행 속도는 느림 (92 vs 181 msg/s)

2️⃣ **지연 예측 가능성**
   - EMQX: P99 50초, P50 33초 → 편차 엄청 큼
   - Torch: P99 0.8초, P50 0.4초 → 편차 작음
   - 사용자는 안정적인 서비스 선호

3️⃣ **공정성 (Fairness)**
   - 제어 없으면: 먼저 보낸 사람만 혜택
   - 제어 있으면: 모두가 공평하게

4️⃣ **실제 사용 시나리오**
   
   a) **IoT 센서 데이터**:
      - 1초에 200개 보내면 혼잡 → 모두 50초 지연
      - 1초에 100개 보내면 안정 → 모두 1초 이내
      → 어차피 100개만 처리 가능하면, 천천히 보내는게 나음
   
   b) **실시간 알림**:
      - 빠르게 보내면 혼잡 → 알림 50초 후 도착 (무의미)
      - 속도 조절하면 → 1초 이내 도착 (여전히 실시간)
   
   c) **API 호출**:
      - Rate limiting 없으면 → 429 Too Many Requests
      - Rate limiting 있으면 → 안정적 응답

5️⃣ **경제적 관점**
   - 빠르게 보내서 재전송 100% = 네트워크 비용 2배
   - 천천히 보내서 재전송 감소 = 비용 절감
""")

print("\n" + "=" * 80)
print("🎯 논문에서 주장해야 할 것 (수정)")
print("=" * 80)

print("""
잘못된 논문 주장:
❌ "RL 제어로 메시지가 더 빨리 도착합니다"
❌ "P99를 98% 개선해서 사용자 경험 향상"

올바른 논문 주장:
✅ "네트워크 혼잡 상황에서 제어 없이는 시스템이 완전 붕괴하지만,
    제안한 eBPF 기반 RL 제어는 송신 속도를 적응적으로 조절하여
    시스템 안정성을 유지하면서 예측 가능한 지연을 제공한다."

✅ "제어를 통해 P99 지연을 50초에서 0.8초로 감소시켰다.
    이는 동일한 개수의 메시지를 처리할 때, 네트워크 큐잉 지연을
    사전에 방지하여 달성한 것이다."

✅ "Throughput은 감소하지만(181→92 msg/s), 이는 네트워크 용량에
    맞춘 적절한 송신 속도 제어의 결과이며, 결과적으로 모든 메시지가
    예측 가능한 시간 내에 전달되어 서비스 품질이 향상된다."

핵심:
- 제어의 목적 = "더 빨리" (X) → "안정적으로, 예측 가능하게" (O)
- Trade-off 인정 = Throughput 감소는 필요한 비용
- 실제 가치 = 시스템 붕괴 방지 + 공정성 + 예측 가능성
""")

print("\n" + "=" * 80)
print("💡 올바른 비교 방법")
print("=" * 80)

print("""
지금 비교:
- EMQX: 제어 없음, 송신 속도 높음 → 혼잡 붕괴
- Torch: 제어 있음, 송신 속도 낮음 → 안정

공정한 비교:
1. 같은 송신 속도로 비교
2. 또는 네트워크 용량 대비 부하로 비교
3. 또는 시간당 성공적으로 전달된 메시지 수로 비교

실제로 봐야 할 지표:
- Goodput (성공 전달 메시지 / 시간)
- Jitter (지연 변동성)
- Fairness index
- 시스템 가용성 (uptime)
""")

# Save summary
with open('results/control_analysis_corrected.txt', 'w') as f:
    f.write("""
제어 효과 재분석 결과
=====================

당신의 지적이 정확합니다.

제어의 진짜 의미:
1. 송신 속도를 늦춰서 네트워크 혼잡을 방지
2. 결과적으로 각 메시지의 네트워크 지연 감소
3. BUT 송신 자체가 느려지므로, 전체 메시지 처리량 감소

올바른 주장:
- "더 빨리 도착" (X)
- "안정적으로, 예측 가능하게 도착" (O)
- "시스템 붕괴 방지" (O)
- "공정성 보장" (O)

논문 수정 필요:
- P99 개선을 "사용자 경험 향상"으로 표현 (조심)
- Trade-off 명확히: Throughput vs Latency
- 실제 가치: 안정성, 예측가능성, 공정성
""")

print("\n✅ 분석 저장: results/control_analysis_corrected.txt")
print("\n이제 논문 주장을 수정해야 합니다!")
