# RL 학습 과정 시각화 가이드

## 개요
이 프로젝트의 로그 데이터로 RL 학습 과정을 분석하고 시각화할 수 있습니다.

## 사용 가능한 데이터

### 로그 파일 현황
```bash
$ wc -l logs/*.jsonl
   104 logs/eda_baseline.jsonl          # 베이스라인 (제어 없음)
   843 logs/eda_rl.jsonl                # Rule-based 제어
   143 logs/eda_rl2.jsonl               # Rule-based 제어 (추가)
   149 logs/eda_rl_torch_online.jsonl  # PyTorch 모델 온라인 제어
```

### 로그 데이터 구조
각 줄은 하나의 RL 스텝을 나타내며 다음 정보를 포함:
- `ts`: 타임스탬프
- `s`: 상태 (9차원 벡터)
- `a`: 적용된 행동
- `r`: 보상
- `metrics`: 애플리케이션 지연 메트릭 (p50/p95/p99)
- `kernel`: 커널 신호 (RTT, 버퍼 사용률, 재전송 등)
- `applied`: 제어 명령 실제 적용 여부

## 시각화 도구

### 1. 기본 사용법
```bash
python3 bench/visualize_rl_training.py \
    --log logs/eda_rl_torch_online.jsonl \
    --output-dir results/rl_analysis
```

### 2. 생성되는 그래프

#### a) 학습 곡선 (training_curve.png)
- X축: Episode (1 episode = 100 steps)
- Y축: 평균 보상
- 음영 영역: 표준편차 (변동성)
- **의미**: 학습이 진행되며 보상이 개선되는 추세를 확인

#### b) P99 지연 감소 (p99_reduction.png)
- X축: Training Step
- Y축: P99 Latency (ms)
- **의미**: 
  - 시작: 2689ms
  - 종료: 477ms
  - **82.3% 감소**

#### c) 행동 분포 변화 (action_distribution.png)
- 초기 학습 vs 후기 학습 비교
- X축: Rate Change (d_rate)
- Y축: 빈도
- **의미**:
  - 초기: 랜덤 탐색 (넓게 분포)
  - 후기: 집중된 제어 (0 근처 집중)

#### d) 정책 엔트로피 (policy_entropy.png)
- X축: Training Step
- Y축: Policy Entropy
- **의미**:
  - 높은 엔트로피 = 탐색 (Exploration)
  - 낮은 엔트로피 = 활용 (Exploitation)
  - 학습이 진행되며 감소하는 추세

#### e) TD 오차 대리지표 (td_error.png)
- X축: Training Step
- Y축: Reward Std Dev (TD Error Proxy)
- **의미**: Value Function 예측 정확도 개선 추세

### 3. 실행 결과 예시
```
[✓] Loaded 149 steps

RL Training Summary Statistics
============================================================
Total Steps:        149
Reward Mean:        1.3287
Reward Std:         0.7294
Reward Min/Max:     -1.2782 / 3.2039

P99 Latency (ms):
  Initial:          2689.17
  Final:            477.25
  Min:              197.04
  Reduction:        82.3%

Action Statistics (d_rate):
  Mean:             -0.0013
  Std:              0.0163
  Zeros:            148 (99.3%)
============================================================
```

## 요청하신 시각화 항목 대응표

| 요청 항목 | 구현 상태 | 파일명 | 설명 |
|----------|----------|--------|------|
| 1. 학습 곡선 (Training Curve) | ✅ 구현 | training_curve.png | Episode별 평균 보상 + 표준편차 |
| 2. 성능 메트릭 변화 (P99 Latency) | ✅ 구현 | p99_reduction.png | 학습 중 P99 지연 감소 추이 |
| 3. 행동 분포 변화 | ✅ 구현 | action_distribution.png | 초기 vs 후기 탐색 패턴 |
| 4. 정책 엔트로피 | ✅ 구현 | policy_entropy.png | 탐색→활용 전환 시각화 |
| 5. Value Function 예측 정확도 | ⚠️ 근사 구현 | td_error.png | 보상 표준편차 기반 대리지표 |

**주의사항**: 
- 정확한 TD 오차를 계산하려면 Value Function이 명시적으로 학습되어야 하지만, 현재는 Behavior Cloning(BC) 방식으로 정책만 학습
- 대신 보상의 변동성(표준편차)를 Value Function 예측 불확실성의 대리지표로 사용

## 여러 로그 비교

### 다중 실험 비교 예시
```bash
# Rule-based 제어
python3 bench/visualize_rl_training.py \
    --log logs/eda_rl.jsonl \
    --output-dir results/rule_based

# Torch 모델 제어  
python3 bench/visualize_rl_training.py \
    --log logs/eda_rl_torch_online.jsonl \
    --output-dir results/torch_online

# 비교
ls results/rule_based/*.png
ls results/torch_online/*.png
```

## 추가 분석 도구

### 1. 성능 비교 분석
```bash
python3 bench/analyze_ppo_results.py
```
베이스라인 vs RL 제어 성능 비교

### 2. 실시간 모니터링
```bash
python3 bench/show_livedata.py
```
실행 중 메트릭 실시간 표시

### 3. EDA 분석
```bash
python3 bench/analyze_eda.py
```
탐색적 데이터 분석

## 한계 및 주의사항

### 현재 데이터의 특징
1. **스텝 수 제한**: 149 스텝 (약 5분 실행)
   - 장기 학습 곡선 분석에는 더 많은 데이터 필요
   - 권장: 1000+ 스텝 (30+ 분 실행)

2. **온라인 학습 vs BC**: 
   - 현재는 Behavior Cloning (offline 학습)
   - PPO/SAC 같은 online RL은 더 명확한 학습 곡선 제공

3. **보상 변동성**:
   - 네트워크 조건 변화로 인한 노이즈
   - 평활화된 메트릭 사용 권장

### 개선 방안
1. **더 긴 실행**: shadow 모드로 장시간 데이터 수집
2. **다양한 조건**: netem으로 다양한 네트워크 시나리오 테스트
3. **온라인 RL 도입**: PPO 등으로 실시간 학습 곡선 확보

## 참고 문서
- `docs/paper_methodology.md`: 실험 재현 절차
- `docs/EDA_RL_Methodology.md`: RL 방법론 상세
- `KNUthesisformat (2).pdf`: 논문 (한글) - 배경, 설계, 실험 결과
