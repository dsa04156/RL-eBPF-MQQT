# MQTT eBPF 기반 네트워크 제어: 방법론과 실험 계획 (Paper-Ready)

본 문서는 본 저장소(mqtt-ebpf-edge)의 실험을 논문 수준으로 재현 가능하게 정리한 방법론과 실험 계획서입니다. 시스템 구성, 신호, 강화학습 정식화, 안전 가드, 실행 모드, 데이터 스키마, 학습 파이프라인, 평가 지표, 실험 시나리오, 통계 처리, 재현 절차를 상세히 기술합니다.

## 1. 문제 정의와 목표
- 대상: MQTT 퍼블리셔/서브스크라이버 워크로드의 네트워크 경로(커널 TCP 스택)에서 관측되는 혼잡 징후를 eBPF로 수집하고, 이를 이용해 퍼블리셔 측 전송률(throttle)과 배치 크기(batch)를 동적으로 제어.
- 1차 목표: 처리량(target throughput) 유지.
- 2차 목표: 꼬리 지연(p95/p99) 억제 및 변동성 축소.
- 제약: 온라인 안전성(급격한 감속/가속 방지, 신선하지 않은 메트릭 무시, 혼잡 시 가속 억제 등).

## 2. 시스템 개요
- 커널 신호 수집: BCC/eBPF로 `tcp_sendmsg`, `tcp_rcv_established` 경로에서 per-flow EWMA RTT, 재전송 유무, send/rcv 버퍼 사용량을 수집(`bpf/eda_rl.py` 내 BPF_PROGRAM).
- 메트릭 수집: 서브스크라이버가 30s 윈도우의 p50/p95/p99 및 메시지 건수 `n`, `window_sec`를 MQTT 토픽으로 보고.
- 제어 경로: 에이전트가 {rate, batch} 명령을 퍼블리셔 제어 토픽으로 발행.
- 실행 모드: `RL_MODE=shadow | online` (섀도우는 로깅만, 온라인은 실제 적용).
- 로그: `(s, a_raw, a, r, s_next, metrics, kernel, applied, cmds, metrics_fresh_sec)`를 JSONL로 기록.

## 3. 상태·행동·보상 (RL 정식화)
- 상태 `s` (길이 9)
  1. `rtt_norm` = `ewma_rtt_us / (SLO_P99_MS*1000)` 클램프(<=10)
  2. `snd_norm` = `tanh(snd_ratio/2)`
  3. `rcv_norm` = `tanh(rcv_ratio/2)`
  4. `retrans_flag` ∈ {0,1}
  5. `queue_pressure` = `tanh(max(snd,rcv)/2)` (0~1)
  6. `rate_norm` = `current_rate / R_MAX`
  7. `batch_norm` = `current_batch / B_MAX`
  8. `last_d_rate`
  9. `last_d_batch`
- 행동 `a`
  - `d_rate` ∈ [-0.2, +0.2] (비율), `d_batch` ∈ {-1, 0, +1} (한 스텝 변화)
- 보상 `r`
  - 앱 메트릭 사용 시: `-(2*over_slo(p99)) + 0.2*clip(throughput/1000) + Δp99 개선 보너스`
  - 커널 대리지표: `rtt_norm`, `queue_pressure`, `snd/rcv_penalty`, `retrans_penalty`, `low_queue_bonus` 등 조합 (상세 구현: `compute_reward`)
- 처리량 정의: `throughput = metrics.n / metrics.window_sec`

## 4. 안전 가드(Shield)와 정책 가이드라인
- 최대 스텝 제한: `|Δrate| ≤ MAX_STEP_FRAC`, 감속은 별도 한계 `MAX_DECEL_FRAC`.
- 쿨다운: `COOLDOWN_SEC` 내 추가 변경 차단.
- 혼잡 시 가속 금지: `CLAMP_ACCEL_ON_CONGESTION=1`이면 `d_rate>0` 무효화.
- 처리량 바닥선: `THROUGHPUT_MIN_FLOOR` 미만이면 추가 감속 금지.
- 감속 후 안정화 대기: `DECEL_HOLD_SEC`와 `DECEL_P99_WAIT_*` 조건 만족 전 추가 감속 금지.
- 회복 바이어스: `RECOVERY_THR_FLOOR` 미만이고 큐/RTT 낮으면 최소 가속 보장.

## 5. 실행 모드와 Gym 환경
- 레거시 루프 또는 Gymnasium 래퍼(`MQTTRLGymEnv`) 사용.
- `USE_GYM_ENV=1`이면 환경을 통해 step/reset 구동, 아니면 기존 루프 유지.
- 조용한 수집: `EDA_RL_VERBOSE=0` 기본값으로 터미널 출력 억제, 로그만 기록.

### 주요 환경변수(발췌)
- `RL_MODE=shadow|online`, `RL_BACKEND=rule|torch`, `RL_LOG_PATH`,
  `THROUGHPUT_TARGET`, `THROUGHPUT_MIN_FLOOR`, `MAX_DECEL_FRAC`, `DECEL_HOLD_SEC`,
  `SLO_P99_MS`, `INTERVAL_S`, `USE_GYM_ENV`, `EDA_RL_VERBOSE`.

## 6. 데이터 스키마(JSONL)
각 줄은 하나의 전이 기록 또는 per-flow 측정:
```json
{
  "ts": <float>,
  "mode": "shadow|online",
  "backend": "rule|torch",
  "s": [...],
  "a_raw": {"d_rate": <float>, "d_batch": <int>},
  "a": {"d_rate": <float>, "d_batch": <int>},
  "r": <float|null>,
  "s_next": [...],
  "metrics": {"p50_ms":..., "p95_ms":..., "p99_ms":..., "n":..., "window_sec":..., "total_msgs":...},
  "kernel": {"ewma_rtt_us":..., "snd_ratio":..., "rcv_ratio":..., "had_retrans":..., "congested":..., "congestion_score":...},
  "applied": <bool>,
  "cmds": [{"cmd":"throttle","rate":...},{"cmd":"batch","size":...}],
  "metrics_fresh_sec": <float>
}
```
권장 필터: `metrics_fresh_sec <= max(10, 1.5*window_sec)`인 샘플 우선 사용.

## 7. 수집·학습·온라인 절차
### 7.1 섀도우 수집(권장)
```bash
EDA_RL_VERBOSE=0 USE_GYM_ENV=1 RL_MODE=shadow RL_LOG_PATH=logs/eda_rl.jsonl \
  INTERVAL_S=1.0 python3 bpf/eda_rl.py
```

### 7.2 데이터셋 전처리(Behavior Cloning용)
```bash
python3 rl/prep_dataset.py logs/eda_rl.jsonl --out models/dataset_kernel_only.npz --min_len 1000
# 실제 적용 샘플만 사용하려면 --use_applied_only 추가
```

### 7.3 BC 학습 및 TorchScript 내보내기
```bash
python3 rl/train_bc.py --data models/dataset_kernel_only.npz \
  --out models/bc_kernel_only.pt --epochs 30
```

### 7.4 온라인 적용(안전 가드 유지)
```bash
USE_GYM_ENV=1 RL_MODE=online RL_BACKEND=torch \
  RL_MODEL_PATH=models/bc_kernel_only.pt EDA_RL_VERBOSE=0 \
  THROUGHPUT_MIN_FLOOR=120 CLAMP_ACCEL_ON_CONGESTION=1 \
  python3 bpf/eda_rl.py
```

## 8. 네트워크 시나리오 설계(netem)
시간가변 혼잡을 재현해 RL의 이점(복구·안정성)을 검증합니다.

### 8.1 지연만 증가(베이스라인)
```bash
sudo tc qdisc replace dev <if> root netem delay 80ms 10ms distribution normal
```

### 8.2 지연+손실+대역폭 제한
```bash
sudo tc qdisc replace dev <if> root handle 1: netem delay 80ms loss 1% jitter 20ms
sudo tc qdisc add dev <if> parent 1:1 handle 10: tbf rate 5mbit burst 32kbit latency 400ms
```

### 8.3 시간가변 프로파일(30s 단계 전환)
동적 혼잡을 자동으로 재현하는 스크립트를 제공합니다.
```bash
# 인터페이스 확인
ip route get <브로커IP>

# 1회 사이클(각 단계 30s): NONE → DELAY_LOSS → RATE_LIMIT → SEVERE → NONE
sudo IF=eth0 PHASE_DUR=30 CYCLES=1 bash bench/netem_dynamic.sh

# 더 길게 반복
sudo IF=eth0 PHASE_DUR=45 CYCLES=3 bash bench/netem_dynamic.sh

# 종료/중단 시 qdisc 자동 제거(trap)
```
단계별 적용 값은 환경변수로 조정 가능(RATE, LOSS_PCT, DELAY_MS, JITTER_MS). 스크립트는 최신 커널의 `netem rate`를 사용합니다.

검증 체크리스트: `ip route get <브로커IP>`로 경로 확인 후 해당 인터페이스에 `tc qdisc show dev <if>` 결과가 반영되었는지 확인.

## 9. 평가 지표와 통계 처리
- 처리량(msg/s): `n/window_sec`의 시계열 평균과 10/90 백분위.
- 앱 레벨 지연: p50/p95/p99의 중앙값/평균/95th/99th.
- 커널 RTT: p50/p90/p95/p99, 평균/표준편차, min/max.
- 적용 강도: `applied` 카운트, 제어 스텝 크기 분포.
- 복구 시간: 혼잡→정상 전환 시 `p99`가 임계치 이하로 돌아오는 시간.
- SLA 위반율: `p99 > SLO_P99_MS` 비율.
- 통계: 부트스트랩(1k resamples)로 평균/중앙값의 95% CI 보고 권장.

### 9.1 자동 비교 스크립트
```bash
# Rule vs Observe vs RL(torch) 비교 예시
python3 bench/compare_logs_1.py \
  logs/eda_rl.jsonl results/eda_observe_run2.jsonl results/eda_our_run_final.jsonl
```
출력: 각 로그의 커널 RTT 요약, 처리량, 앱 pxx 스냅샷 통계(중앙값/95th/99th).

### 9.2 동적 시나리오 A/B 절차
```bash
# (1) 동적 netem 적용
sudo IF=eth0 PHASE_DUR=30 CYCLES=2 bash bench/netem_dynamic.sh &  # 백그라운드

# (2) rule 온라인 실행(로그 분리)
USE_GYM_ENV=1 RL_MODE=online RL_BACKEND=rule \
  RL_LOG_PATH=logs/rl/dyn_rule.jsonl python3 bpf/eda_rl.py

# (3) torch 온라인 실행(같은 프로파일 반복)
USE_GYM_ENV=1 RL_MODE=online RL_BACKEND=torch \
  RL_MODEL_PATH=models/bc_kernel_only.pt \
  RL_LOG_PATH=logs/rl/dyn_torch.jsonl python3 bpf/eda_rl.py

# (4) 결과 비교
python3 bench/compare_logs_1.py logs/rl/dyn_rule.jsonl logs/rl/dyn_torch.jsonl
```

## 10. 대표 결과(예시)
실제 저장소 로그 비교(요약):

- 온라인 제어(`eda_rl.jsonl`, backend=rule):
  - 처리량 평균 ≈ 158.9 msg/s
  - 앱 p99 중앙값 ≈ 0.48 s
  - 커널 RTT p95/p99 ≈ 0.52/0.78 s
- 관찰(`eda_observe_run2.jsonl`, 적용 없음):
  - 처리량 유사(≈159.8 msg/s)이나 앱 p99 중앙값 ≈ 22.7 s로 테일 급등
  - 커널 RTT p95/p99 ≈ 1.84/2.39 s

해석: “처리량 동급 유지” 조건에서 제어 유무가 꼬리 지연에 미치는 영향이 크며, 시간가변/가혹한 netem 하에서는 RL 백엔드가 rule 대비 추가 이득을 보일 가능성이 높다.

## 11. 어블레이션과 민감도 분석
- 가드 제거 테스트: `THROUGHPUT_MIN_FLOOR=0`, `CLAMP_ACCEL_ON_CONGESTION=0` 등.
- 윈도우 변화: subscriber `window_sec` 10/30/60s.
- 보상 구성 요소 제거/가중치 변동: `THROUGHPUT_*_WEIGHT`.

## 12. 재현 환경
- OS/커널: 실험 시 커널 버전, BCC/BPF 툴체인 명시.
- Python: 3.8+, `gymnasium>=0.29`, `numpy>=1.23`, `bcc`, `paho-mqtt`.
- 하드웨어: CPU/메모리, 네트워크 인터페이스 사양.
- 고정 시드: (학습 시) `torch.manual_seed`, 환경 시드.

## 13. 윤리·제한·위협요인
- 실제 프로덕션 경로 적용 시, 안전 가드 미설정은 QoS 과도 저하를 야기할 수 있음.
- netem은 현실 전체를 대변하지 않음(무선/모바일/중간 큐잉 정책 등).
- 계측 지연과 윈도우 설정이 보상에 반영되는 시간차 유의.

## 부록 A. 자주 쓰는 명령어
```bash
# 섀도우 수집
EDA_RL_VERBOSE=0 USE_GYM_ENV=1 RL_MODE=shadow python3 bpf/eda_rl.py

# 온라인(rule)
USE_GYM_ENV=1 RL_MODE=online RL_BACKEND=rule python3 bpf/eda_rl.py

# 온라인(torch)
USE_GYM_ENV=1 RL_MODE=online RL_BACKEND=torch RL_MODEL_PATH=models/bc_kernel_only.pt \
  python3 bpf/eda_rl.py

# 로그 비교
python3 bench/compare_logs_1.py logs/eda_rl.jsonl results/eda_observe_run2.jsonl
```

---
문의/보완 사항이 있으면 이 문서를 업데이트하여 최신 실험 설정과 결과를 반영하세요.
