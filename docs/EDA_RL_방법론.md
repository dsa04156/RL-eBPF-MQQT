### **1. eMQTT-AC 시스템 아키텍처 (Proposed System Architecture)**

eMQTT-AC 시스템은 크게 **eBPF 기반 데이터 평면(eBPF-based Data Plane)**과 **강화학습 기반 제어 평면(RL-based Control Plane)**의 두 가지 핵심 요소로 구성된다. 데이터 평면은 커널 공간에서 실제 MQTT 패킷을 처리하는 역할을 담당하며, 제어 평면은 사용자 공간에서 데이터 평면의 동작을 지능적으로 제어하는 정책을 수립한다. 두 평면은 eBPF 맵(eBPF Maps)이라는 효율적인 커널-사용자 공간 공유 메모리 메커니즘을 통해 상호작용한다.

**1.1. 전체 구성도**

*   *<그림 1: eMQTT-AC 전체 시스템 아키텍처. 네트워크 인터페이스(NIC)에서 수신된 패킷이 TC Ingress Hook에서 eBPF 프로그램에 의해 처리되고, eBPF 맵을 통해 사용자 공간의 RL 에이전트와 상태 및 정책을 주고받는 과정을 보여주는 다이어그램>*

**1.2. eBPF 기반 데이터 평면 (in Kernel Space)**

데이터 평면은 MQTT 브로커가 설치된 엣지 서버의 커널 공간에서 동작하며, 네트워크 인터페이스 카드(NIC)에 도달하는 모든 패킷을 MQTT 애플리케이션보다 먼저 검사하고 처리한다. 이를 위해 리눅스 TC(Traffic Control) 서브시스템의 Ingress Hook에 eBPF 프로그램을 연결(attach)한다. TC Hook은 XDP(eXpress Data Path)에 비해 다소 느리지만, 완전한 형태의 네트워크 패킷 정보(sk_buff)에 접근할 수 있어 TCP 기반의 MQTT 프로토콜을 파싱하기에 더 적합하다.

데이터 평면의 주요 구성 요소는 다음과 같다.

*   **패킷 파서 (Packet Parser):** TC Ingress Hook으로 들어온 `sk_buff` 구조체로부터 IP 및 TCP 헤더를 분석하여 MQTT 패킷을 식별한다. 식별된 MQTT 패킷에 대해서는 `CONNECT`, `PUBLISH`, `SUBSCRIBE` 등의 명령어 타입, 토픽 이름, QoS 레벨, 페이로드 크기 등의 핵심 정보를 추출한다.
*   **상태 수집기 (State Collector):** eBPF 프로그램 내에서 패킷의 흐름을 추적하고, 관련 통계를 eBPF 맵에 실시간으로 기록한다.
    *   `flow_metrics_map`: (해시 맵) 5-tuple(출발지/목적지 IP/Port, 프로토콜)을 키로 하여 패킷 수, 바이트, 마지막 도착 시간 등의 흐름 정보를 저장한다.
    *   `topic_stats_map`: (해시 맵) 토픽 이름의 해시값을 키로 하여, 해당 토픽의 메시지 도착률, 평균 크기 등을 저장한다.
    *   이러한 정보는 사용자 공간의 RL 에이전트가 '상태'를 인지하는 데 사용된다.
*   **패킷 제어기 (Packet Controller):** RL 에이전트가 수립한 정책에 따라 실제 패킷 처리 액션을 수행한다.
    *   `policy_map`: (해시 맵) 제어 대상(예: 토픽 해시)을 키로, 제어 값(예: 0~100 사이의 샘플링 비율)을 값으로 저장하는 맵. 이 맵은 사용자 공간의 RL 에이전트에 의해 주기적으로 업데이트된다.
    *   eBPF 프로그램은 `PUBLISH` 메시지를 파싱한 후, 해당 토픽이 `policy_map`에 있는지 확인한다. 만약 존재한다면, 맵에 저장된 샘플링 비율에 따라 확률적으로 해당 패킷을 `TC_ACT_OK` (전달) 또는 `TC_ACT_SHOT` (폐기) 처분한다. 이를 통해 브로커에 도달하는 트래픽의 양을 동적으로 조절한다.
*   **이벤트 통지기 (Event Notifier):** 커널에서 발생한 중요 이벤트나 수집된 통계 정보를 사용자 공간으로 비동기적으로 전달한다. 최신 커널에서 제공하는 `BPF_MAP_TYPE_RINGBUF`를 사용하여, 락(lock-free) 없이 안전하고 효율적으로 데이터를 전송한다. 예를 들어, 새로운 토픽이 발견되거나 특정 토픽의 트래픽이 급증하는 이벤트를 RL 에이전트에게 즉시 알릴 수 있다.

**1.3. 강화학습 기반 제어 평면 (in User Space)**

제어 평면은 일반적인 파이썬 애플리케이션으로 사용자 공간에서 실행된다. BCC(BPF Compiler Collection) 또는 libbpf-python과 같은 라이브러리를 사용하여 eBPF 프로그램을 커널에 로드하고, eBPF 맵을 읽고 쓰는 방식으로 데이터 평면과 상호작용한다.

*   **상태 관찰자 (State Observer):** 주기적으로(예: 매 1초) 데이터 평면의 eBPF 맵들(`flow_metrics_map`, `topic_stats_map` 등)을 읽고, `RINGBUF`로부터 전달된 이벤트들을 수신한다. 수집된 원시 데이터(raw data)를 정규화하고 조합하여 강화학습 에이전트가 사용할 수 있는 형태의 상태 벡터(state vector) `S_t`를 생성한다. 또한, MQTT 브로커의 상태(CPU, 메모리 사용량)를 `/proc` 파일시스템 등을 통해 직접 조회하여 상태 벡터에 포함시킨다.
*   **RL 에이전트 (Actor-Critic Agent):** 제어 평면의 핵심 두뇌. PPO 알고리즘을 기반으로 구현되며, 정책을 결정하는 액터(Actor) 신경망과 상태의 가치를 평가하는 크리틱(Critic) 신경망으로 구성된다.
    *   에이전트는 상태 관찰자로부터 상태 벡터 `S_t`를 입력받는다.
    *   액터 네트워크는 이 상태를 바탕으로 최적의 행동 `A_t` (예: 토픽 'A'의 샘플링 비율 80%, 토픽 'B'의 샘플링 비율 50%)를 결정한다.
    *   크리틱 네트워크는 현재 상태 `S_t`가 얼마나 '좋은지'를 평가하는 가치 `V(S_t)`를 출력하며, 이는 액터 네트워크의 학습을 돕는 데 사용된다.
*   **정책 적용기 (Policy Applier):** RL 에이전트가 결정한 행동 `A_t`를 실제 eBPF가 이해할 수 있는 정책으로 변환하여 `policy_map`에 기록한다. 예를 들어, 에이전트가 "토픽 'factory/robot/1/status'의 샘플링 비율을 75%로 설정하라"는 행동을 출력하면, 정책 적용기는 해당 토픽 이름을 해싱하여 키로 사용하고, 값 75를 `policy_map`에 업데이트한다. 이 순간부터 커널의 패킷 제어기는 새로운 샘플링 비율에 따라 동작하게 된다.
*   **보상 계산기 (Reward Calculator):** 시스템의 목표를 달성했는지 측정하는 보상(reward) `R_t`를 계산한다. 이를 위해 구독자(subscriber) 클라이언트로부터 실제 종단 간 지연 시간을 측정하거나, 상태 관찰자가 수집한 처리량, 패킷 손실률, CPU 사용량 등의 지표를 조합하여 보상 함수를 통해 최종 보상 값을 산출한다. 이 보상 값은 RL 에이전트가 더 나은 정책을 학습하는 데 결정적인 역할을 한다.

---

### **2. 강화학습 문제 공식화 (Markov Decision Process)**
    *   **상태 (State, S):** 에이전트가 최적의 결정을 내리기 위해 관찰하는 정보의 집합.
        *   네트워크 상태: `(수신 메시지 비율, 발행/구독 토픽 분포, 평균 메시지 크기, 네트워크 큐 길이)`
        *   브로커 상태: `(CPU 사용률, 메모리 점유율, 처리 지연 시간)`
        *   eBPF 통계: `(패킷 폐기율, 패킷 전달률)`
    *   **행동 (Action, A):** 각 상태에서 에이전트가 취할 수 있는 제어 행위.
        *   이산적(Discrete) 또는 연속적(Continuous) 행동 공간 정의
        *   예시: `(전체 메시지 샘플링 비율 조정, 특정 토픽에 대한 샘플링 비율 조정, QoS 레벨 강등)`
    *   **보상 (Reward, R):** 특정 행동을 취했을 때 얻는 즉각적인 피드백. 시스템 목표(지연 최소화, 처리량 최대화)를 반영하도록 설계.
        *   `Reward = w1 * (1 / End-to-End Latency) + w2 * Throughput - w3 * Drop Rate - w4 * CPU Usage`
        *   가중치(w1, w2, w3, w4)는 시스템의 목표 우선순위에 따라 조정

### **3. 강화학습 알고리즘: 모방학습(BC) 및 PPO (Reinforcement Learning Algorithm: Behavioral Cloning & PPO)**
    *   **1단계: 모방학습(Behavioral Cloning, BC)을 통한 정책 초기화**
        *   목적: 불안정한 탐험(exploration)으로 인한 초기 시스템 성능 저하를 방지하고, 안정적인 정책으로 학습을 시작하기 위함.
        *   데이터 수집: 숙련된 전문가(또는 잘 정의된 규칙 기반 시스템)의 제어 로그(`상태-행동` 쌍)를 수집. (`logs/kernel_only/`의 데이터 활용)
        *   학습: 수집된 데이터를 지도학습(Supervised Learning) 방식으로 학습하여 초기 정책 신경망(`model_bc.pt`)을 생성.
    *   **2단계: PPO(Proximal Policy Optimization)를 이용한 온라인 정책 미세조정**
        *   PPO 선택 이유: 데이터 효율성이 높고, 정책 업데이트의 변동성이 적어 안정적인 학습이 가능. Actor-Critic 구조를 통해 정책과 상태 가치를 동시에 학습.
        *   학습 과정:
            1. BC로 초기화된 정책을 이용해 실제 환경과 상호작용하며 `(s, a, r, s')` 궤적(trajectory) 수집
            2. 수집된 데이터를 이용해 어드밴티지(Advantage) `A(s, a)` 계산
            3. 클리핑(Clipping)을 이용한 목적 함수(Objective Function)를 통해 정책(Actor) 및 가치(Critic) 신경망을 업데이트
            4. 1~3 과정 반복

### **4. 정책 및 가치 신경망 모델 구조 (Policy and Value Neural Network Model Architecture)**
    *   입력층: 3절에서 정의된 상태(State) 벡터
    *   은닉층: 다층 퍼셉트론(Multi-Layer Perceptron, MLP) 구조 (예: 2-3개의 은닉층, ReLU 활성화 함수)
    *   출력층:
        *   정책망(Actor): 행동 공간의 확률 분포 (예: Categorical 또는 Beta 분포)
        *   가치망(Critic): 현재 상태의 가치(Scalar 값)

### **5. 학습 및 평가 (Training and Evaluation)**
    *   **실험 환경:**
        *   MQTT 브로커, 발행자(Publisher), 구독자(Subscriber)로 구성된 테스트베드
        *   네트워크 상태 에뮬레이션: `netem`과 같은 도구를 사용하여 다양한 네트워크 지연 및 대역폭 시나리오 재현
    *   **평가 지표:**
        *   종단 간 메시지 지연 시간 (End-to-End Latency)
        *   초당 처리량 (Throughput)
        *   메시지 손실률 (Message Loss Rate)
        *   브로커 및 클라이언트의 CPU/메모리 사용량
    *   **비교 대상(Baselines):**
        *   기본 MQTT 브로커 (제어 없음)
        *   정적 규칙 기반 필터링 시스템
        *   모방학습(BC)만 적용한 에이전트

### **6. eBPF를 이용한 제어 메커니즘 구현**
    *   eBPF C 코드: TC/XDP hook에서 실행될 패킷 처리 로직 작성
    *   Python 사용자 공간 코드: `BCC` 또는 `libbpf-python` 라이브러리를 사용하여 eBPF 프로그램을 커널에 로드하고, eBPF 맵을 통해 RL 에이전트와 통신하는 방법 기술
    *   상태 정보 공유: 커널의 eBPF 프로그램이 `bpf_perf_event_output` 또는 링 버퍼(Ring Buffer)를 통해 상태 정보를 사용자 공간으로 전달하는 메커니즘
    *   정책 업데이트: 사용자 공간의 RL 에이전트가 eBPF 맵의 특정 키 값을 업데이트하면, 커널의 eBPF 프로그램이 이 값을 읽어 제어 정책을 갱신하는 방식
