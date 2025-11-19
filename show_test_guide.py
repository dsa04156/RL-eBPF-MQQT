#!/usr/bin/env python3
"""
간단한 테스트: retrans_count 필드가 제대로 기록되는지 확인
EMQX 없이 로컬에서 간단히 테스트
"""
print("""
🧪 retrans_count 필드 테스트 가이드
====================================

수정 내용:
  ✅ total_retrans_delta 변수 추가
  ✅ kernel 딕셔너리에 "retrans_count" 필드 추가
  ✅ 이제 boolean이 아닌 실제 재전송 횟수 기록

테스트 방법 (3가지):

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
방법 1: 간단한 30초 테스트 (추천)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. EMQX 시작:
   sudo systemctl start emqx

2. Publisher & Subscriber 시작:
   python3 clients/mqtt_publisher.py &
   python3 clients/mqtt_subscriber.py &

3. 네트워크 혼잡 조건 적용:
   sudo tc qdisc add dev lo root netem delay 100ms loss 5%

4. eBPF Agent 실행 (30초):
   sudo python3 bpf/eda_rl.py > logs/test_retrans.jsonl 2>&1 &
   sleep 30
   sudo pkill -f eda_rl.py

5. 결과 확인:
   grep "retrans_count" logs/test_retrans.jsonl | python3 -m json.tool

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
방법 2: 자동 테스트 스크립트 (가장 간단)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

bash test_retrans_count.sh

→ 자동으로 모든 과정 실행 및 검증

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
방법 3: 전체 실험 (EMQX vs Torch 비교)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

A. EMQX 무제어 실험:
   sudo bash bench/netem_on.sh
   # Publisher & Subscriber 시작
   # eda_rl.py를 shadow mode로 실행 (관측만)
   RL_MODE=shadow python3 bpf/eda_rl.py > logs/emqx_new_congestion.jsonl

B. Torch RL 제어 실험:
   sudo bash bench/netem_on.sh
   # Publisher & Subscriber 시작
   # eda_rl.py를 online mode로 실행
   RL_MODE=online RL_BACKEND=torch python3 bpf/eda_rl.py > logs/torch_new_congestion.jsonl

C. 비교 분석:
   python3 << 'PYEOF'
import json
import numpy as np

# EMQX
emqx_retrans = []
with open('logs/emqx_new_congestion.jsonl') as f:
    for line in f:
        data = json.loads(line)
        if 'kernel' in data:
            emqx_retrans.append(data['kernel'].get('retrans_count', 0))

# Torch
torch_retrans = []
with open('logs/torch_new_congestion.jsonl') as f:
    for line in f:
        data = json.loads(line)
        if 'kernel' in data:
            torch_retrans.append(data['kernel'].get('retrans_count', 0))

print(f"EMQX 총 재전송: {sum(emqx_retrans):,} 회")
print(f"Torch 총 재전송: {sum(torch_retrans):,} 회")
print(f"감소율: {(1-sum(torch_retrans)/sum(emqx_retrans))*100:.1f}%")
PYEOF

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

기대 결과:

  EMQX (무제어):
    총 재전송: 1,234 회
    평균: 12.5 회/interval
    
  Torch RL (제어):
    총 재전송: 123 회
    평균: 1.2 회/interval
    
  → 90% 감소! ✅

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

문제 해결:

  Q: retrans_count가 0만 나옴
  A: 네트워크 혼잡이 없음. tc netem으로 loss/delay 추가

  Q: 필드가 아예 없음
  A: eda_rl.py 수정이 제대로 안됨. 파일 확인

  Q: Python 에러
  A: sudo로 실행 필요 (eBPF 권한)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")

print("\n어떤 방법으로 테스트하시겠습니까?")
print("1) 자동 테스트 스크립트 실행: bash test_retrans_count.sh")
print("2) 수동 단계별 실행: 위 가이드 참고")
print("3) 전체 실험: EMQX vs Torch 비교")
