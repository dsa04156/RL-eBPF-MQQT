# MQTT eBPF-RL 연구 개요 및 로드맵

## 1. 연구 배경과 목적
- **목표**: MQTT 퍼블리셔 트래픽이 다양한 네트워크 환경(지연, 손실, 대역폭 제한)에서 SLA 수준의 지연을 유지하도록 퍼블리셔 전송률·배치 크기를 자동 제어하는 강화학습 기반 정책을 개발한다.
- **핵심 질문**
  1. eBPF 기반 커널 신호(TCP RTT, 버퍼 사용량, 재전송 수)가 MQTT 레이어 메트릭(p50/p95/p99 지연, 처리량)과 결합됐을 때 혼잡 상황을 얼마나 정확히 감지할 수 있는가?
  2. Rule 기반 임계값 제어 대비 RL 정책이 지연·처리량 트레이드오프에서 어떤 개선을 보이는가?
  3. Shadow 모드 데이터만으로 학습한 정책을 온라인 모드에서 안전하게 적용하기 위한 쉴드/페일세이프 설계는 어떻게 해야 하는가?

## 2. 시스템 구성
### 2.1 데이터 수집 파이프라인
- **메인 스크립트**: `bpf/eda_rl.py`
  - eBPF BPF_HASH(`stats`)로 MQTT 관련 TCP 소켓의 `srtt_us`, `sndbuf`, `rcvbuf`, `retrans` 집계.
  - MQTT subscriber가 발행하는 `eda/latency` 토픽에서 윈도우별 latency 통계 수신.
  - 수집한 신호를 기반으로 2초(기본)마다 상태(state), 행동(action), 보상(reward)을 평가해 JSONL 로그(`logs/eda_rl.jsonl`)에 기록.

### 2.2 네트워크/워크로드 환경
- **퍼블리셔/서브스크라이버**: Docker Compose(`publisher-compose.yml`, `subscriber-compose.yml`)로 스케일·RATE·PAYLOAD 조정.
- **네트워크 변조**: `bench/netem_dynamic.sh`가 delay/loss 조합을 순환 적용하며 다양한 조건 생성.
- **MQTT 브로커**: EMQX (192.168.0.1:23232) 기준.

### 2.3 상태·행동·보상 정의
- **상태 벡터 `s ∈ ℝ^9`**
  1. `rtt_norm`: EWMA RTT / SLO(기본 10초) → 0~10 클램프
  2. `snd_norm`: `tanh(snd_ratio / 2)`
  3. `rcv_norm`: `tanh(rcv_ratio / 2)`
  4. `retrans_flag`: 재전송 발생 여부 (0/1)
  5. `queue_pressure`: `tanh(max(snd_ratio, rcv_ratio) / 2)` → 연속 혼잡도 지표
  6. `rate_norm`: 현재 퍼블리셔 rate / `R_MAX`
  7. `batch_norm`: 현재 퍼블리셔 batch / `B_MAX`
  8. `last_d_rate`: 직전 행동의 d_rate (클램프)
  9. `last_d_batch`: 직전 행동의 d_batch (클램프)
- **행동 `a`**
  - `d_rate`: 연속값(약 ±0.2) – 퍼블리셔 레이트를 상대적으로 조정.
  - `d_batch`: {-1, 0, +1} – 퍼블리셔 배치 크기를 증감.
  - 실제 적용 시 `Shield`가 `MAX_STEP_FRAC`, `COOLDOWN_SEC`, `R_MIN/R_MAX`, `B_MIN/B_MAX`로 안전 범위 유지.
- **보상 `r`**
  - 메인 항: `-(p99 - SLO)/SLO` (초과 시 패널티).
  - throughput 보너스: `0.2 * clamp(throughput/1000, 0, 1)`.
  - p99 미수신 시 대체: RTT·버퍼 기반 패널티.
  - 추가 안정화: p99 개선 시 `delta_bonus` 적용.

### 2.4 로그 포맷 예시
```json
{
  "ts": 1757997551.2995,
  "mode": "shadow",
  "backend": "rule",
  "s": [...],
  "a": {"d_rate": -0.1, "d_batch": 1},
  "r": -9.95,
  "metrics": {"p50_ms": 45654.1, "p95_ms": 57677.5, "p99_ms": 60171.5, ...},
  "kernel": {"ewma_rtt_us": 1_447_640, "snd_ratio": 4.18, "congestion_score": 0.97, ...},
  "applied": false,
  "cmds": []
}
```

## 3. 현재 진행 상황 정리
1. **RuleAgent 업그레이드**: 기존 이진 혼잡 임계 대신 `queue_pressure`와 RTT, 재전송을 연속적으로 조합하여 `d_rate`/`d_batch`를 출력하도록 개선.
2. **Shadow 데이터 수집**: 퍼블리셔 부하(RATE, PAYLOAD, 스케일)·netem 조건을 바꿔가며 정상/혼잡 샘플을 동시에 축적 중. 현재 로그는 수백~수천 건 수준이며, 혼잡 구간(큐 압력 0.6~0.97)과 정상 구간(0.0~0.03)이 모두 포함되도록 조정하고 있음.
3. **전처리 스크립트 개선**: `rl/prep_dataset.py`에서 `tqdm` optional import 처리로 의존성 없이 실행 가능.
4. **문서/실험 계획화**: 본 문서를 시작으로 연구 전반의 절차, 메트릭, 평가 시나리오를 명문화.

## 4. 데이터 수집 전략 세부화
- **샘플링 주기**: 기본 `INTERVAL_S=2.0`, 데이터가 필요할 때 `INTERVAL_S=0.5~1.0`으로 단축.
- **부하 패턴**
  - 퍼블리셔 스케일: 5 → 10 → 20 → 10 → 5 순환으로 상태 다양화.
  - RATE: (10, 30, 50), PAYLOAD_BYTES: (0, 256, 512) 조합 실험.
  - netem: Delay(10/30/70/100ms) × Loss(0/0.5/1/2/5%).
- **세션 메타데이터 기록**: 각 run마다 시간, netem 설정, 퍼블리셔 설정, INTERVAL_S, 모드(shadow/online)를 CSV 혹은 JSON으로 별도 저장 (`logs/run_meta.json`).
- **용량 관리**: 1일 이상 수집 시 `logs/archive/`로 이전 및 압축. 학습에 사용한 로그 버전(`eda_rl_runYYYYMMDDHH.jsonl`) 식으로 명명.
- **샘플 목표**: 최소 5만 건 이상. 정상:혼잡 비율이 6:4 정도가 되도록 주기적으로 부하를 조절.

## 5. 학습 및 평가 로드맵
### 5.1 단계별 절차
1. **행동 복제(Behavioral Cloning)**
   - 데이터셋: `rl/prep_dataset.py logs/eda_rl.jsonl --out logs/eda_dataset_runX.npz`
   - 모델 후보: 2~3층 MLP(ReLU) / LayerNorm / Dropout 적용. 손실은 `L = MSE(d_rate) + λ * CE(d_batch)`;
     λ는 1.0~2.0 범위 탐색.
   - 학습 로그 및 검증은 `results/bc_runX/`에 저장.
2. **오프라인 RL (선택)**
   - CQL or IQL 적용, reward scale 조정을 위해 normalize/clipping 수행.
   - offline dataset 품질 확인: reward None 제거, state-action coverage 평가.
3. **온라인 파인튜닝**
   - `RL_BACKEND=torch`, `RL_MODEL_PATH=...`로 shadow 검증 → `RL_MODE=online` 전환.
   - 안전장치: `Shield` 유지, 행동이 유효하지 않을 경우 RuleAgent fallback.
   - 모델 업데이트 시 keep-last policy 저장(`models/policy_v{n}.pt`).
4. **지속적 학습 루프**
   - 온라인 로그를 다시 전처리해 replay buffer 확장.
   - 주기적으로 파라미터 재학습/검증.

### 5.2 평가 지표
- **SLA 만족도**: `p99_ms <= SLO` 비율, 평균 초과량.
- **처리량 유지율**: 수집 기간 동안 throughput 평균/표준편차.
- **제어 안정성**: 적용된 throttle/batch 명령 수, rate 변화량의 절대합.
- **네트워크 지표**: EWMA RTT, 재전송 카운트, queue_pressure 분포.
- **기저 정책 대비 개선율**: RuleAgent, BC, (추후) RL 정책을 동일 시나리오에서 실행해 지표 비교.
- **안전성**: 온라인 모드에서 fallback이 발동한 경우 수, 쉴드가 차단한 비율.

### 5.3 실험 시나리오
| 시나리오 | 설명 | 기대 포인트 |
| --- | --- | --- |
| A. 정상→혼잡→정상 | netem delay/loss를 단계적으로 상승 후 하강 | 정책이 상황 변화에 빠르게 적응하는지 |
| B. 부하 급증 | 퍼블리셔 수 5→20으로 증가, netem 중간 | rate 감속이 적시에 일어나는지 |
| C. 손실 위주 | 손실률 0→5% 상승, delay는 중간 | 재전송 신호 반응, queue_pressure 민감도 |
| D. 주기적 스파이크 | netem이 30초 주기로 극단값을 삽입 | 정책의 안정성과 탐색-활용 균형 |

## 6. 운영 및 자동화 계획
- **스케줄링**: cron 또는 tmux 세션으로 장기 수집 실행, bash 스크립트로 환경변수 세트 자동화.
- **메트릭 대시보드**: 간단한 Python notebook 또는 Grafana로 `p99`, `throughput`, `queue_pressure`, `d_rate` 분포 시각화.
- **데이터 검증**: 로그 라인 수, reward None 비율, state NaN 여부를 자동 체크.
- **버전 관리**: 모델(`models/`), 데이터셋(`logs/eda_dataset_*.npz`), 실험 로그(`results/`)에 공통 prefix와 메타데이터 JSON 첨부.
- **안전 장치**: 온라인 모드 전환 시 `MAX_STEP_FRAC`, `COOLDOWN_SEC`을 보수적으로 잡고 점진적으로 완화.

## 7. 향후 연구 과제
- **정책 표현력 향상**: 상태에 순환 특성을 반영하기 위해 RNN/LSTM 또는 attention 기반 모델 검토.
- **멀티 액션 확장**: QoS 변경, 퍼블리셔 수 동적 조정 등 추가 액션 도입 가능성 평가.
- **전송 프로토콜 다양화**: MQTT 외 CoAP, HTTP/2 환경에서의 일반화 여부 탐구.
- **이론적 분석**: queue_pressure와 실제 큐 길이의 상관관계, reward 설계 민감도 분석.
- **논문 초안 연계**: `docs/내논문.pdf`에 본 계획을 반영하고, 실험 결과 챕터에 시나리오별 지표 표준화.

## 8. 실행 명령어 모음
```bash
# Shadow 수집 (기본 주기)
sudo RL_MODE=shadow RL_BACKEND=rule RL_LOG_PATH=logs/eda_rl.jsonl \
     MQTT_HOST=192.168.0.1 MQTT_PORT=23232 CONTROL_TOPIC=control/room1 \
     METRICS_TOPIC=eda/latency python3 bpf/eda_rl.py >/dev/null 2>&1 &

# Shadow 수집 (샘플링 0.5초)
sudo INTERVAL_S=0.5 RL_MODE=shadow RL_BACKEND=rule RL_LOG_PATH=logs/eda_rl_fast.jsonl \
     MQTT_HOST=192.168.0.1 MQTT_PORT=23232 CONTROL_TOPIC=control/room1 \
     METRICS_TOPIC=eda/latency python3 bpf/eda_rl.py >/dev/null 2>&1 &

# 데이터셋 생성
python3 rl/prep_dataset.py logs/eda_rl.jsonl --out logs/eda_dataset_runX.npz

# 행동 복제 학습 예시
python3 rl/train_bc.py --data logs/eda_dataset_runX.npz --out models/bc_runX.pt \
    --epochs 50 --hidden 128 128 --lr 1e-3

# 학습 모델로 shadow 검증
sudo RL_MODE=shadow RL_BACKEND=torch RL_MODEL_PATH=models/bc_runX.pt \
     RL_LOG_PATH=logs/eda_rl_bc_shadow.jsonl python3 bpf/eda_rl.py &

# 온라인 모드 시험 (보수적 설정)
sudo RL_MODE=online RL_BACKEND=torch RL_MODEL_PATH=models/bc_runX.pt \
     MAX_STEP_FRAC=0.1 COOLDOWN_SEC=5.0 python3 bpf/eda_rl.py &
```

## 9. 방법론 요약 (논문용 기술)
### 9.1 시스템 개요
- *목표*: MQTT publish 스루풋을 유지하면서 tail latency (p99) 초과를 최소화하는 adaptive rate control.
- *아키텍처*: (1) eBPF 모듈이 커널 TCP 소켓 신호를 수집, (2) MQTT subscriber가 사용자 레벨 메트릭을 발행, (3) RL 에이전트가 상태를 구성해 행동(`d_rate`, `d_batch`)을 산출, (4) Shadow 모드에서 정책 데이터를 축적 후 Online 모드에서 쉴드를 통해 명령을 적용.

### 9.2 데이터 수집 및 상태 구성
- **커널 계층 수집**: `BPF_HASH(stats)`에 (src,dst,port)별 `srtt_us`, `sndbuf`, `rcvbuf`, `retrans`를 저장. `EWMA` 업데이트는 `r_t = r_{t-1} + α (cur - r_{t-1})`, `α = EWMA_ALPHA`.
- **MQTT 계층 수집**: `eda/latency` 토픽에서 윈도우 집계 `{p50, p95, p99, n, window_sec}` 수신.
- **상태 벡터** `s_t` 정의:
  
  \[
  s_t = [\phi_{rtt}(\tilde{r}_t), \phi_{buf}(snd_t), \phi_{buf}(rcv_t), \mathbb{1}_{ret_t}, \phi_{buf}(\max(snd_t,rcv_t)), \frac{rate_t}{R_{max}}, \frac{batch_t}{B_{max}}, \mathrm{clip}(d\_rate_{t-1}), \mathrm{clip}(d\_batch_{t-1})]
  \]

  - `\tilde{r}_t`: EWMA RTT (μs), `\phi_{rtt}(x) = \min(x / (SLO_{p99} · 10^3), 10)`
  - `snd_t = sndbuf/TH_SNDBUF`, `rcv_t = rcvbuf/TH_RCVBUF`, `\phi_{buf}(x) = \tanh(x/2)`
  - `\mathbb{1}_{ret_t}`: 최근 interval에서 재전송 발생 여부
  - 마지막 두 항은 직전 행동의 잔기억으로, 행동 변화 제약에 활용

### 9.3 보상 함수
- 메트릭이 존재할 때는 tail latency 중심 보상:
  
  \[
  r_t = -2 \cdot \max\left(0, \frac{p99_t - SLO_{p99}}{SLO_{p99}}\right) + 0.2 \cdot \mathrm{clip}\left(\frac{throughput_t}{1000}, 0, 1\right) + \beta \cdot \max\left(0, \frac{p99_{t-1} - p99_t}{p99_{t-1}}\right)
  \]
  
  여기서 `throughput_t = n_t / window_sec`, `β = 0.5`는 안정화 가중치.
- 메트릭이 지연되는 경우 대리지표 사용:
  
  \[
  r_t = - \left( \phi_{rtt}(\tilde{r}_t) + 0.5 · \max(\phi_{buf}(snd_t), \phi_{buf}(rcv_t)) \right)
  \]
- Reward는 shadow/online 공통으로 로그에 저장되며, 학습 시 reward=None 샘플은 제거.

### 9.4 정책 학습 절차
1. **Shadow 데이터 축적**: 다양한 부하 조건 하에서 `(s_t, a_t, r_t, s_{t+1})`를 확보.
2. **행동 복제(BC)**: 수집된 `(s_t, a_t)`를 지도학습으로 근사해 초기 정책 `\pi_{BC}` 획득.
   - `d_rate` 회귀: `L_{rate} = \|\pi_{BC}^{rate}(s_t) - d\_rate_t\|_2^2`
   - `d_batch` 분류: `L_{batch} = \mathrm{CE}(\pi_{BC}^{batch}(s_t), d\_batch_t)`
   - 총 손실: `L = L_{rate} + λ L_{batch}` (`λ≈1`)
3. **오프라인 RL (선택)**: BC 모델을 warm start로 사용해 CQL/IQL 등으로 reward 기반 fine-tuning.
4. **온라인 적용**: `RL_MODE=online`에서 `Shield`로 안전성을 보장하면서 정책을 적용, 추가 데이터를 replay buffer에 축적해 지속 개선.

### 9.5 Shield 및 안전 제어
- **Rate 제한**: `d_rate`는 `|d_rate| ≤ MAX_STEP_FRAC`로 클램프, 실제 적용되는 새 rate는 `r' = clip(r_t (1 + d_rate), R_MIN, R_MAX)`.
- **Batch 제한**: `b' = clip(b_t + d_batch, B_MIN, B_MAX)`.
- **Cooldown**: 마지막 적용 시점 이후 `COOLDOWN_SEC`이 지나야 새로운 명령을 발행.
- **Fallback 전략**: 온라인 모드에서 예외 발생 시 RuleAgent 기본 정책으로 즉시 복구.

### 9.6 실험 프로토콜
- 각 시나리오에서 다음 순서를 준수:
  1. Shadow 로그 수집 (RuleAgent)
  2. 데이터 전처리 → BC 학습 → Shadow 검증
  3. Online 모드로 정책 적용, 동일 시나리오 재실행
  4. 결과 비교: (Rule vs BC vs RL) Tail latency, throughput, 제어 빈도
- 결과는 평균 ±95% 신뢰구간 형태로 표/그래프 제시.

---
본 문서는 현재 진행 중인 로그 수집/학습 파이프라인을 기준으로 작성되었으며, 실험 진행에 따라 지속 업데이트 예정이다.
