# EDA-RL 커널 기반 강화학습 방법론

본 문서는 `mqtt-ebpf-edge` 프로젝트에서 EDA-RL(Extended Data Agent Reinforcement Learning)을 커널 지표만으로 동작시키기 위해 적용한 전체 절차를 정리한 것이다. 기존 `eda.py` 룰 기반 제어와 `eda_rl.py`에 혼재되어 있던 애플리케이션 메트릭 의존성을 제거하고, eBPF로 수집한 커널 신호만으로 tail latency를 제어하는 방법을 단계별로 설명한다.

## 1. 시스템 구성 개요

- **데이터 경로**: MQTT Publisher → Broker → Subscriber. 실험 단계에서는 subscriber가 latency 통계를 발행하지만, 커널-only 모드에서는 이 값 없이도 RL이 동작하도록 설계한다.
- **관측 레이어**: eBPF 프로그램(`bpf/eda_rl.py`)이 TCP 소켓에서 EWMA RTT, 송신/수신 버퍼 점유율, 재전송 횟수 등을 수집하여 유저 공간 에이전트에 전달한다.
- **RL 에이전트**: PyTorch 기반 정책(`TorchAgent`) 또는 기본 룰 기반 정책(`RuleAgent`). 상태를 받아 `d_rate`, `d_batch`를 출력하고, `Shield`가 안전 범위로 클램프한 뒤 MQTT 제어 토픽으로 throttle/batch 명령을 발행한다.

## 2. 상태(State) 설계

`make_state` 함수에서 생성하는 상태 벡터는 다음 9개 항목으로 구성된다.

| index | 이름 | 설명 |
|------:|:-----|:-----|
| 0 | `rtt_norm` | EWMA RTT / SLO를 0~10으로 클램프 |
| 1 | `snd_norm` | 송신 버퍼 비율을 `tanh(snd_ratio/2)`로 스케일 |
| 2 | `rcv_norm` | 수신 버퍼 비율을 동일 방식으로 스케일 |
| 3 | `retr_norm` | 재전송 발생 여부 (0 또는 1) |
| 4 | `cong_norm` | `compute_queue_pressure`로 계산한 혼잡도 |
| 5 | `rate_norm` | 현재 퍼블리셔 rate / `R_MAX` |
| 6 | `batch_norm` | 현재 배치 크기 / `B_MAX` |
| 7 | `last_d_rate` | 직전 행동의 비정규화된 `d_rate` |
| 8 | `last_d_batch` | 직전 행동의 `d_batch` |

## 3. 행동(Action)

- `d_rate ∈ [-0.2, 0.2]`: 퍼블리셔 rate를 비율로 증감. 혼잡 시 -0.2로 최대 감속을 사용한다.
- `d_batch ∈ {-1, 0, +1}`: 배치 크기를 한 단계 늘리거나 줄인다.

`Shield.clamp`가 최소 ±1 스텝 이상의 변화가 실제 정수 rate/batch에 반영되도록 보정한다.

## 4. 보상(Reward) 설계

커널-only 모드에서 reward는 다음 요소로 구성된다. throughput을 직접 측정할 수 있는 경우(`USE_APP_METRICS=1`)에는 동일 보상 구조에서 throughput 항이 활성화된다.

```
rtt_norm    = min(EWMA_RTT_us / (SLO * 1000), 10)
queue_pen   = queue_pressure
snd_pen     = tanh(max(0, snd_ratio - 0.4))
rcv_pen     = tanh(max(0, rcv_ratio - 0.4))
retrans_pen = 1.0 if had_retrans else 0.0
throughput_pen = max(0, (THROUGHPUT_TARGET - throughput) / THROUGHPUT_TARGET)

penalty = 2.0*rtt_norm + 1.4*queue_pen + 0.9*snd_pen + 0.7*rcv_pen +
          0.7*retrans_pen + 1.5*throughput_pen

rate_norm       = clamp(current_rate / INIT_RATE, 0, 2)
low_queue_bonus = 1 - queue_pressure
bonus = 0.5*rate_norm + 0.2*low_queue_bonus + (0.1 if throughput ≥ target else 0)

reward = -penalty + bonus
```

- `THROUGHPUT_TARGET` 기본값을 45 msg/s로 설정하여 baseline과 유사한 처리량을 유지하도록 유도한다.
- penalty 항목은 tail(quadratic RTT, queue, 재전송) 감소에 우선순위를 두고, throughput이 목표보다 낮으면 추가 패널티가 적용된다.

## 5. 쉴드(Shield) 조정

- `MAX_STEP_FRAC`, `COOLDOWN_SEC`, `R_MAX`, `B_MAX`를 환경 변수로 조절해 감속 강도와 회복 속도를 제어한다.
- 정수 반올림으로 명령이 사라지지 않도록 `floor/ceil`을 사용해 최소 ±1 스텝 변화가 보장되도록 수정했다.
- `CLAMP_ACCEL_ON_CONGESTION=1`으로 혼잡 상태에서 양의 `d_rate`를 차단하고, 감속 후 일정 시간 가속을 제한한다.

## 6. 데이터 수집 및 학습 루프

1. **로그 수집**: `USE_APP_METRICS=0` 모드로 에이전트를 실행해 `logs/kernel_only/eda_rl_kernel_*.jsonl` 형태로 저장한다.
2. **로그 병합**: `cat logs/kernel_only/eda_rl_kernel_*.jsonl > logs/kernel_only/eda_rl_kernel_merged.jsonl`
3. **데이터셋 생성**: `python3 rl/prep_dataset.py logs/kernel_only/eda_rl_kernel_merged.jsonl --out logs/kernel_only/dataset_kernel_only.npz`
4. **BC 학습**: `python3 rl/train_bc.py --data logs/kernel_only/dataset_kernel_only.npz --out models/bc_kernel_only.pt --epochs 120 --bs 512 --lr 5e-4`
5. **(선택) RL fine-tuning**: PPO/SAC 등으로 커널 보상을 이용한 정책 경사 학습.
6. **재배포**: 새 모델을 `RL_MODEL_PATH`로 지정해 에이전트를 재실행.

## 7. 평가 방법

- **커널 지표**: EWMA RTT, queue pressure, 송신/수신 버퍼 비율, 재전송 발생률, reward 추이를 모니터링한다.
- **애플리케이션 지표**: subscriber가 정상 동작할 경우 p99 및 throughput을 baseline과 비교한다. 동일 throughput 구간(예: 40±5 msg/s)을 필터링해 tail을 비교하는 것이 공정하다.
- **혼잡 구간 분석**: 혼잡 조건(예: `ewma_rtt_us > 70,000` 또는 `queue_pressure > 0.6`) 이후 구간의 p99·throughput을 따로 추려 비교한다.

## 8. 재현 절차 요약

```bash
sudo pkill -f bpf/eda_rl.py || true
cat logs/kernel_only/eda_rl_kernel_*.jsonl > logs/kernel_only/eda_rl_kernel_merged.jsonl
python3 rl/prep_dataset.py logs/kernel_only/eda_rl_kernel_merged.jsonl \
    --out logs/kernel_only/dataset_kernel_only.npz
source ~/myenv/bin/activate
python3 rl/train_bc.py --data logs/kernel_only/dataset_kernel_only.npz \
    --out models/bc_kernel_only.pt --epochs 120 --bs 512 --lr 5e-4
LOG_TS=$(date +%Y%m%d_%H%M%S)
sudo -E USE_APP_METRICS=0 THROUGHPUT_TARGET=45 RL_MODE=online RL_BACKEND=torch \
    RL_MODEL_PATH=$(pwd)/models/bc_kernel_only.pt \
    RL_LOG_PATH=$(pwd)/logs/kernel_only/eda_rl_kernel_${LOG_TS}.jsonl \
    MQTT_HOST=$BROKER MQTT_PORT=$PORT \
    CONTROL_TOPIC=control/room1 METRICS_TOPIC=eda/latency \
    /usr/bin/python3 bpf/eda_rl.py \
    > logs/kernel_only/eda_rl_kernel_${LOG_TS}.out 2>&1 &
```

## 9. 향후 작업

- throughput 가중치를 추가 조정해 baseline throughput(≈40 msg/s)을 유지하면서 tail을 더 낮추도록 반복 실험.
- 커널 지표와 tail 사이의 상관 관계를 분석하여 reward 설계를 최적화.
- PPO·SAC 같은 RL 알고리즘으로 BC 정책을 초기화한 뒤 online fine-tuning.

