#!/usr/bin/env python3
"""
RL 처리량 최적화 가이드
"""

print("🎯 RL Throughput 최적화 전략")
print("=" * 80)

print("""
현재 상태:
  - EMQX: 181.7 msg/s (하지만 P99=50초)
  - RL:    92.6 msg/s (P99=866ms)
  - 목표: 120-150 msg/s 유지하면서 P99 < 2초

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📋 방법 1: Reward 함수 튜닝 (가장 쉬움)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

현재 설정:
  SLO_P99_MS = 300            # P99 목표
  THROUGHPUT_TARGET = 250     # 처리량 목표
  THROUGHPUT_BONUS_WEIGHT = 0.1

변경 제안:
  SLO_P99_MS = 1000           # P99 목표를 1초로 완화
  THROUGHPUT_TARGET = 150     # 현실적 목표
  THROUGHPUT_BONUS_WEIGHT = 0.3  # 처리량 가중치 증가

실행 방법:
  export SLO_P99_MS=1000
  export THROUGHPUT_TARGET=150
  export THROUGHPUT_BONUS_WEIGHT=0.3
  sudo USE_GYM_ENV=1 RL_MODE=online RL_BACKEND=torch \
    RL_MODEL_PATH=models/bc_kernel_only.pt \
    python3 bpf/eda_rl.py

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📋 방법 2: Shield 제약 완화 (중간 난이도)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

현재 설정 (매우 보수적):
  MAX_STEP_FRAC = 0.2         # 한 번에 최대 20% 변경
  COOLDOWN_SEC = 2.0          # 2초 쿨다운
  DECEL_HOLD_SEC = 4.0        # 감속 후 4초 대기

변경 제안:
  MAX_STEP_FRAC = 0.3         # 30%까지 허용 (더 빠른 반응)
  COOLDOWN_SEC = 1.5          # 1.5초로 단축
  DECEL_HOLD_SEC = 3.0        # 3초로 단축

실행 방법:
  export MAX_STEP_FRAC=0.3
  export COOLDOWN_SEC=1.5
  export DECEL_HOLD_SEC=3.0
  sudo USE_GYM_ENV=1 RL_MODE=online RL_BACKEND=torch \
    RL_MODEL_PATH=models/bc_kernel_only.pt \
    python3 bpf/eda_rl.py

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📋 방법 3: 혼잡 감지 임계값 조정 (중간 난이도)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

현재 설정 (매우 민감):
  TH_SND_RATIO = 0.1          # snd_ratio 0.1 이상이면 경고
  HI_RTT_US = 10000000        # RTT 10초 이상이면 높음

변경 제안:
  TH_SND_RATIO = 0.2          # 0.2까지 허용 (더 공격적)
  HI_RTT_US = 20000000        # 20초로 완화

코드 수정 필요:
  bpf/eda_rl.py 라인 ~65-70 수정

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📋 방법 4: 새로운 모델 학습 (가장 효과적, 시간 소요)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

현재 문제:
  - 기존 모델은 P99=300ms 목표로 학습됨
  - 너무 보수적으로 rate를 낮춤

해결책:
  1. Shadow 모드로 더 다양한 데이터 수집
     - 네트워크 조건 다양화: 1Mbit, 2Mbit, 5Mbit
     - 혼잡도 다양화: 0%, 1%, 2%, 5% loss

  2. Reward 재정의하여 BC 재학습
     - P99 < 1000ms로 완화
     - Throughput 가중치 증가

실행 예시:
  # 1. 다양한 조건에서 데이터 수집
  for RATE in 2Mbit 5Mbit 10Mbit; do
    for LOSS in 1% 2% 5%; do
      sudo tc qdisc replace dev lo root netem rate $RATE delay 50ms loss $LOSS
      sudo EDA_OBSERVE=1 RL_MODE=shadow RL_BACKEND=rule \
        RL_LOG_PATH=logs/shadow_${RATE}_${LOSS}.jsonl \
        SLO_P99_MS=1000 THROUGHPUT_TARGET=150 \
        python3 bpf/eda_rl.py
    done
  done

  # 2. 데이터 병합 및 학습
  python3 rl/prep_dataset.py --input "logs/shadow_*.jsonl" --output dataset_aggressive.npz
  python3 rl/train_bc.py --data dataset_aggressive.npz --out models/bc_aggressive.pt

  # 3. 새 모델로 실행
  sudo USE_GYM_ENV=1 RL_MODE=online RL_BACKEND=torch \
    RL_MODEL_PATH=models/bc_aggressive.pt \
    python3 bpf/eda_rl.py

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📋 방법 5: Rule-based Hybrid 모드 (빠른 테스트)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Torch 모델 대신 rule 기반으로 더 공격적 설정:
  export SLO_P99_MS=1000
  export THROUGHPUT_TARGET=150
  export THROUGHPUT_BONUS_WEIGHT=0.3
  sudo USE_GYM_ENV=1 RL_MODE=online RL_BACKEND=rule \
    python3 bpf/eda_rl.py

Rule은 다음 논리로 동작:
  - snd_ratio < 0.2 && no retrans → 가속 (+10%)
  - snd_ratio > 0.3 || retrans → 감속 (-10%)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎯 추천 순서
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1️⃣ 먼저 방법 1 + 2 조합 (환경변수만 변경, 즉시 테스트 가능)
   예상 결과: 120-140 msg/s, P99 < 1.5초

2️⃣ 효과 부족하면 방법 3 (코드 수정)
   예상 결과: 140-160 msg/s, P99 < 2초

3️⃣ 최적화가 필요하면 방법 4 (새 모델 학습)
   예상 결과: 150-180 msg/s, P99 < 2초

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")

print("\n💡 지금 바로 실행해볼 명령어 (방법 1+2 조합):")
print("=" * 80)
print("""
sudo SLO_P99_MS=1000 \\
     THROUGHPUT_TARGET=150 \\
     THROUGHPUT_BONUS_WEIGHT=0.3 \\
     MAX_STEP_FRAC=0.3 \\
     COOLDOWN_SEC=1.5 \\
     DECEL_HOLD_SEC=3.0 \\
     USE_GYM_ENV=1 RL_MODE=online RL_BACKEND=torch \\
     RL_MODEL_PATH=models/bc_kernel_only.pt \\
     RL_LOG_PATH=logs/rl_optimized.jsonl \\
     MQTT_HOST=127.0.0.1 MQTT_PORT=23232 \\
     python3 bpf/eda_rl.py

실행 후 비교:
  python3 compare_throughput_tradeoff.py  # 기존 로그와 비교
""")

print("\n⚠️  주의사항:")
print("  - P99가 너무 높아지면 다시 파라미터 조정")
print("  - snd_ratio > 0.5 빈발하면 너무 공격적임")
print("  - Goodput 기준으로 평가 (단순 throughput X)")
