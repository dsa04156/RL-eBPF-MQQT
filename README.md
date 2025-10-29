**프로젝트 개요**
- 본 저장소는 eBPF로 수집한 커널 신호(RTT, 재전송, 송/수신 버퍼 사용)를 이용해 MQTT 발행자의 전송률(rate)과 배치 크기(batch)를 동적으로 제어하여 꼬리 지연(tail latency)을 낮추는 시스템입니다.
- 핵심 제어 에이전트는 `bpf/eda_rl.py`이며, 섀도우(shadow)와 온라인(online) 모드를 지원하고, 규칙 기반(rule) 또는 Torch 모델(torch) 백엔드로 동작합니다. 제어 명령은 MQTT 토픽을 통해 퍼블리셔로 전달됩니다.
- 관련 배경과 성능 결과는 석사 논문 PDF `KNUthesisformat (2).pdf`에 포함되어 있습니다.

**주요 기능**
- eBPF 수집: TCP 경로에서 per-flow `srtt_us`, `retrans`, `sk_wmem_queued`/`sk_rmem_alloc` 수집 후 집계 (`bpf/eda_rl.py:186` 등).
- MQTT 연동: 서브스크라이버 지연 메트릭 수신(`eda/latency`), 퍼블리셔 제어 명령 발행(`control/room1`) (`bpf/eda_rl.py:46`, `bpf/eda_rl.py:47`, `bpf/eda_rl.py:297`).
- RL 제어: 상태·행동·보상 정의와 안전 가드(스텝 제한, 쿨다운, 혼잡 시 가속 억제, 처리량 바닥선 등) 포함 (`bpf/eda_rl.py:328`, `bpf/eda_rl.py:487`, `bpf/eda_rl.py:806`).
- 실행 모드: `RL_MODE=shadow|online`로 섀도우 로깅 또는 실제 적용 선택 (`bpf/eda_rl.py:51`, `bpf/eda_rl.py:1141`).
- Gym 환경: `USE_GYM_ENV=1` 시 실시간 환경(`MQTTRLGymEnv`)으로 감쌈 (`bpf/eda_rl.py:651`, `bpf/eda_rl.py:1147`).
- 자동 튜닝(옵션): 보상 가중치/감속 한계 등 팔(arms)을 평가·교대하는 간단한 epsilon-greedy 튜너 (`bpf/eda_rl.py:120` 이후, `bpf/eda_rl.py:1187`).

**아키텍처**
- 커널: eBPF(BCC)로 `tcp_sendmsg`, `tcp_rcv_established`, `tcp:tcp_retransmit_skb`에 프로브 연결해 맵에 누적 후 사용자 공간에서 집계/평활 (`bpf/eda_rl.py:1091`).
- 에이전트: 관측 상태(커널 신호+정책 맥락)를 기반으로 d_rate(±20%), d_batch(±1)를 산출 후 쉴드(스텝 제한/쿨다운 등)로 클램프 (`bpf/eda_rl.py:404`, `bpf/eda_rl.py:719`).
- MQTT: 서브스크라이버 지연 메트릭 수신(`METRICS_TOPIC=eda/latency`) → 보상/가드 계산 → 퍼블리셔 제어 토픽(`CONTROL_TOPIC=control/room1`)으로 `{throttle,batch}` 발행.

**요구 사항**
- OS/커널: BPF 가능 커널(예: Ubuntu 24.04, Linux 6.8) 권장.
- Python 3.8+: `bcc`, `paho-mqtt`, `numpy` (+ 선택: `gymnasium`, `torch`).
- MQTT 브로커(예: EMQX)와 퍼블리셔/서브스크라이버 테스트 클라이언트.

**빠른 시작**
- 섀도우 수집(로깅만):
  - `USE_GYM_ENV=1 RL_MODE=shadow RL_LOG_PATH=logs/eda_rl.jsonl python3 bpf/eda_rl.py`
- 온라인 제어(규칙 기반):
  - `USE_GYM_ENV=1 RL_MODE=online RL_BACKEND=rule python3 bpf/eda_rl.py`
- 온라인 제어(Torch 모델):
  - `USE_GYM_ENV=1 RL_MODE=online RL_BACKEND=torch RL_MODEL_PATH=models/bc_kernel_only.pt python3 bpf/eda_rl.py`

**MQTT 토픽/포트**
- 브로커: `MQTT_HOST`, `MQTT_PORT` (`bpf/eda_rl.py:43`, `bpf/eda_rl.py:44`).
- 메트릭 구독: `METRICS_TOPIC` 기본 `eda/latency` (`bpf/eda_rl.py:46`).
- 제어 발행: `CONTROL_TOPIC` 기본 `control/room1` (`bpf/eda_rl.py:47`).
- eBPF 필터 포트: `MQTT_TRACK_PORT` 기본 `MQTT_PORT` (`bpf/eda_rl.py:105`).

**환경변수 요약(발췌)**
- 실행/모드: `RL_MODE=shadow|online`, `EDA_RL=1`, `USE_GYM_ENV=1` (`bpf/eda_rl.py:50`, `bpf/eda_rl.py:1147`).
- 백엔드: `RL_BACKEND=rule|torch`, `RL_MODEL_PATH=...` (`bpf/eda_rl.py:108`, `bpf/eda_rl.py:109`).
- 로깅: `RL_LOG_PATH=logs/eda_rl.jsonl`, `EDA_RL_VERBOSE=0|1` (`bpf/eda_rl.py:52`, `bpf/eda_rl.py:149`).
- SLO/윈도우: `SLO_P99_MS`, `INTERVAL_S`, `EWMA_ALPHA` (`bpf/eda_rl.py:53`, `bpf/eda_rl.py:78`, `bpf/eda_rl.py:79`).
- 가드/제한: `MAX_STEP_FRAC`, `MAX_DECEL_FRAC`, `COOLDOWN_SEC`, `THROUGHPUT_MIN_FLOOR`, `DECEL_HOLD_SEC`, `CLAMP_ACCEL_ON_CONGESTION=1` (`bpf/eda_rl.py:101`, `bpf/eda_rl.py:62`, `bpf/eda_rl.py:102`, `bpf/eda_rl.py:64`, `bpf/eda_rl.py:66`, `bpf/eda_rl.py:842`).
- 초기값/범위: `INIT_RATE`, `INIT_BATCH`, `R_MIN..R_MAX`, `B_MIN..B_MAX` (`bpf/eda_rl.py:93`, `bpf/eda_rl.py:94`, `bpf/eda_rl.py:97`).

**상태·행동·보상(RL)**
- 상태 s: `[rtt_norm, snd_norm, rcv_norm, retrans, queue, rate_norm, batch_norm, last_d_rate, last_d_batch]` (`bpf/eda_rl.py:330`).
- 행동 a: `d_rate ∈ [-0.2,0.2]`, `d_batch ∈ {-1,0,1}` (`bpf/eda_rl.py:713`).
- 보상 r: 앱 메트릭 기반 또는 커널 대리지표 기반 혼합식(처리량 보너스/패널티 + 대기열/RTT/재전송 패널티) (`bpf/eda_rl.py:363`).
- 쉴드: 최대 스텝/쿨다운/연속 감속 홀드 등 안전 적용 (`bpf/eda_rl.py:404`).

**로그/데이터 스키마(JSONL)**
- 각 스텝: `{"ts", "mode", "backend", "s", "a_raw", "a", "r", "s_next", "metrics", "kernel", "applied", "cmds", "metrics_fresh_sec"}` (`docs/paper_methodology.md:61`).
- 샘플 로그: `results/eda_log.jsonl`.

**동적 네트워크 시나리오(netem)**
- 시간가변 혼잡 재현 스크립트: `bench/netem_dynamic.sh`.
- 사용 예: `sudo IF=eth0 PHASE_DUR=30 CYCLES=1 bash bench/netem_dynamic.sh` (`bench/netem_dynamic.sh:4`).

**대표 결과(논문 요약)**
- 테스트베드(Ubuntu 24.04, Linux 6.8, EMQX/Paho, netem)에서 제안 기법이 무제어 대비 꼬리 지연을 크게 감소.
- 앱 p99 중앙값: 55.9 s → 0.48 s, 커널 RTT p99: 1.89 s → 0.78 s, 처리량은 유사(≈171.7 → 158.9 msg/s) 유지. 상세는 `KNUthesisformat (2).pdf` 요약/결과 참조.

**주의/제한**
- 프로덕션 적용 시 가드 설정 필수(감속 한계, 바닥선, 쿨다운 등)를 적절히 조정.
- `USE_GYM_ENV=1`이 기본이며, `gymnasium`이 없으면 레거시 루프로 자동 폴백(`bpf/eda_rl.py:1147`).
- Torch 백엔드는 모델 파일(TorchScript/PT) 필요하며, 실패 시 규칙 기반으로 폴백.

**참고 문서**
- 방법론/재현 절차: `docs/paper_methodology.md`.
- 에이전트 구현: `bpf/eda_rl.py`.
- 논문 PDF(배경/설계/실험): `KNUthesisformat (2).pdf`.
