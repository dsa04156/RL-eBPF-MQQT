# PPO (Proximal Policy Optimization) 강화학습 가이드

## 🚨 중요: BC vs PPO

이 프로젝트는 **RL 기반 MQTT 제어**를 위한 것으로, 두 가지 학습 방법을 지원합니다:

### 1. Behavior Cloning (BC) - `train_bc.py`

- **방식**: 지도학습 (Supervised Learning)
- **데이터**: Shadow 모드에서 수집한 rule-based 정책의 행동 모방
- **장점**: 빠른 학습, 안정적
- **단점**: rule 정책보다 나아지기 어려움

### 2. PPO (Proximal Policy Optimization) - `train_ppo.py` ⭐

- **방식**: 진짜 강화학습 (Reinforcement Learning)
- **데이터**: 환경과의 상호작용을 통한 reward 기반 학습
- **장점**: 최적 정책 탐색 가능, rule보다 성능 향상 가능
- **단점**: 학습 시간 오래 걸림, 불안정할 수 있음

---

## PPO 학습 워크플로우

### Step 1: Shadow 모드로 trajectory 데이터 수집

```bash
# 다양한 네트워크 조건에서 데이터 수집
for i in {1..10}; do
  echo "=== Run $i ==="

  # 동적 네트워크 조건 적용
  sudo bash bench/netem_dynamic.sh &

  # Shadow 모드로 RL 에이전트 실행
  USE_GYM_ENV=1 RL_MODE=shadow RL_BACKEND=rule \
    RL_LOG_PATH=logs/ppo_shadow_run${i}.jsonl \
    python3 bpf/eda_rl.py

  # 30초 대기
  sleep 30

  # netem 종료
  sudo tc qdisc del dev eth0 root 2>/dev/null
done
```

### Step 2: PPO 학습

```bash
# 수집한 로그로 PPO 학습
python3 rl/train_ppo.py \
  --log logs/ppo_shadow_run1.jsonl \
  --out models/ppo_model.pt \
  --episodes 100 \
  --epochs 4 \
  --batch_size 256 \
  --lr 3e-4 \
  --gamma 0.99 \
  --clip_epsilon 0.2
```

**주요 하이퍼파라미터:**

- `--episodes`: 학습 에피소드 수 (더 많을수록 좋지만 시간 오래 걸림)
- `--epochs`: 각 업데이트당 PPO epoch 수 (보통 4~10)
- `--batch_size`: 미니배치 크기
- `--lr`: Learning rate (기본 3e-4)
- `--gamma`: Discount factor (미래 보상 가중치, 0.95~0.99)
- `--clip_epsilon`: PPO clip 범위 (0.1~0.3)

### Step 3: 학습된 모델로 온라인 제어

```bash
# PPO 모델로 실제 제어
USE_GYM_ENV=1 RL_MODE=online RL_BACKEND=torch \
  RL_MODEL_PATH=models/ppo_model.pt \
  python3 bpf/eda_rl.py
```

---

## PPO vs BC 비교 실험

### 실험 1: BC 기준선

```bash
# BC 모델 학습
python3 rl/prep_dataset.py --input logs/shadow_data.jsonl --output dataset.npz
python3 rl/train_bc.py --data dataset.npz --out models/bc_model.pt

# BC 모델 테스트
USE_GYM_ENV=1 RL_MODE=online RL_BACKEND=torch \
  RL_MODEL_PATH=models/bc_model.pt \
  RL_LOG_PATH=logs/test_bc.jsonl \
  python3 bpf/eda_rl.py
```

### 실험 2: PPO 강화학습

```bash
# PPO 모델 학습
python3 rl/train_ppo.py --log logs/shadow_data.jsonl --out models/ppo_model.pt

# PPO 모델 테스트
USE_GYM_ENV=1 RL_MODE=online RL_BACKEND=torch \
  RL_MODEL_PATH=models/ppo_model.pt \
  RL_LOG_PATH=logs/test_ppo.jsonl \
  python3 bpf/eda_rl.py
```

### 실험 3: 결과 비교

```bash
# 성능 분석
python3 bench/analyze_ppo_results.py \
  --baseline logs/test_bc.jsonl \
  --ppo logs/test_ppo.jsonl
```

---

## 고급 기능

### Multi-episode 데이터로 학습

```bash
# 여러 로그 파일 병합
cat logs/ppo_shadow_run*.jsonl > logs/ppo_merged.jsonl

# 병합된 데이터로 학습
python3 rl/train_ppo.py \
  --log logs/ppo_merged.jsonl \
  --out models/ppo_model_v2.pt \
  --episodes 500
```

### 학습 곡선 시각화

```bash
# PPO 학습 과정 시각화
python3 bench/visualize_rl_training.py \
  --log logs/test_ppo.jsonl \
  --output-dir results/ppo_analysis
```

---

## 트러블슈팅

### 문제 1: "No valid trajectory data found"

- **원인**: Shadow 로그에 s, a, r, s_next가 없음
- **해결**: `RL_MODE=shadow` 확인, 충분한 시간 실행

### 문제 2: PPO 학습이 수렴 안함

- **원인**: Learning rate 너무 높거나 낮음
- **해결**: `--lr 1e-4` 시도, `--clip_epsilon 0.1` 감소

### 문제 3: Value loss가 계속 증가

- **원인**: Reward scale 문제
- **해결**: `SLO_P99_MS`, `THROUGHPUT_TARGET` 환경변수 조정

### 문제 4: 학습은 되는데 실제 제어 시 성능 떨어짐

- **원인**: Train/test 분포 차이
- **해결**: 다양한 네트워크 조건에서 데이터 수집

---

## 논문 작성 시 언급할 점

✅ **이제 해야 할 것:**

1. ✅ PPO 구현 완료
2. ✅ BC vs PPO 비교 실험
3. ✅ "우리는 PPO를 사용했다" 명시

❌ **이전 문제:**

- BC만 있어서 "지도학습 모방"에 불과
- RL 논문인데 실제 RL이 없었음

📊 **결과 섹션 구조:**

1. Baseline (No control)
2. Rule-based control
3. BC (Behavior Cloning) - rule 모방
4. **PPO (Reinforcement Learning)** ⭐ - 진짜 RL
5. Ablation studies

---

## 참고 자료

- PPO 원본 논문: https://arxiv.org/abs/1707.06347
- Spinning Up PPO: https://spinningup.openai.com/en/latest/algorithms/ppo.html
- 프로젝트 Copilot Instructions: `.github/copilot-instructions.md`
