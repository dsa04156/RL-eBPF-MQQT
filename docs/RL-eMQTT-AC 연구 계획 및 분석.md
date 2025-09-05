

# **RL-eMQTT-AC: eBPF 커널 신호 기반 강화학습을 활용한 적응형 MQTT 제어 프레임워크**

## **초록**

본 보고서는 사물 인터넷(IoT) 환경에서 널리 사용되는 MQTT 프로토콜의 성능 최적화를 위한 새로운 적응형 제어 시스템, RL-eMQTT-AC(Reinforcement Learning-eMQTT-Adaptive Control)를 제안하고 그 성능을 심층적으로 분석한다. 기존의 규칙 기반 제어 시스템은 동적으로 변화하는 네트워크 환경에 대한 적응성이 부족하여 p99 꼬리 지연 시간(tail latency)과 처리량(throughput) 사이의 상충 관계를 효과적으로 관리하지 못하는 한계를 가진다. 이러한 문제를 해결하기 위해, 본 연구는 eBPF(extended Berkeley Packet Filter) 기술을 사용하여 커널 수준의 네트워크 신호(RTT, 재전송률, 송신 버퍼 점유율 등)를 실시간으로 수집하고, 이를 상태(state) 정보로 활용하는 강화학습(Reinforcement Learning) 에이전트를 개발하였다. 제어 목표인 꼬리 지연 최소화와 처리량 손실 방지라는 다중 목표 최적화 문제를 제약된 마르코프 결정 과정(Constrained Markov Decision Process, CMDP)으로 정형화하고, 라그랑주 승수법(Lagrangian method)을 통해 보상 함수를 설계하여 에이전트가 스스로 최적의 제어 정책을 학습하도록 하였다. 다양한 네트워크 시나리오(기본 혼잡, 높은 손실률, 낮은 대역폭)에서 포괄적인 시뮬레이션을 수행한 결과, 제안하는 RL-eMQTT-AC 시스템은 기존의 규칙 기반 제어 방식 및 표준 TCP 혼잡 제어 알고리즘(CUBIC, BBR) 대비 p99 꼬리 지연 시간을 통계적으로 유의미하게 감소시키면서도 처리량 손실을 최소화하는 우수한 성능을 보였다. 또한, 시스템의 CPU 및 메모리 오버헤드를 측정한 결과, 엣지 컴퓨팅 환경에서도 수용 가능한 수준임을 확인하였다. 본 연구는 eBPF의 고효율 커널 관측 가능성(observability)과 강화학습의 적응적 의사결정 능력을 결합하여, IoT 프로토콜을 위한 지능형 실시간 제어 시스템의 실현 가능성을 입증하였다.

---

## **1\. IoT 메시징을 위한 적응형 제어 개론**

### **1.1. IoT 통신의 도전 과제**

사물 인터넷(IoT)과 엣지 컴퓨팅의 급격한 확산으로 인해 수십억 개의 디바이스가 네트워크에 연결되면서, 이들 간의 효율적이고 신뢰성 있는 데이터 교환이 핵심적인 과제로 부상했다. MQTT(Message Queuing Telemetry Transport)는 경량의 발행-구독(publish-subscribe) 모델을 기반으로 하여, 제한된 컴퓨팅 자원과 불안정한 네트워크 환경을 가진 IoT 디바이스에 최적화된 프로토콜로 자리매김했다.1 스마트 팩토리의 센서 데이터 수집, 커넥티드 카의 실시간 상태 정보 전송, 원격 의료 모니터링 등 다양한 응용 분야에서 MQTT는 핵심적인 역할을 수행하고 있다.

이러한 응용 분야의 공통적인 요구사항은 메시지를 신속하고 안정적으로 전달하는 것이다. 특히, 사용자 경험 품질(Quality of Service, QoS)에 직접적인 영향을 미치는 지연 시간, 그중에서도 p99 꼬리 지연 시간은 시스템의 최악 성능을 나타내는 중요한 지표이다.3 예를 들어, 자율 주행 차량의 긴급 제동 신호나 스마트 그리드의 장애 감지 신호가 단 한 번이라도 크게 지연된다면 치명적인 결과를 초래할 수 있다. 동시에, 시스템은 단위 시간당 처리할 수 있는 메시지의 양, 즉 처리량을 극대화하여 대규모 디바이스로부터 발생하는 데이터를 효율적으로 처리해야 한다. 하지만 이 두 가지 목표—꼬리 지연 시간 최소화와 처리량 최대화—는 본질적으로 상충 관계(trade-off)에 있다. 처리량을 높이기 위해 더 많은 데이터를 네트워크에 전송하면 버퍼에 대기하는 패킷이 증가하여 지연 시간이 길어지고, 반대로 지연 시간을 줄이기 위해 전송률을 낮추면 처리량이 감소하게 된다. 이 상충 관계를 동적인 네트워크 환경 변화에 맞춰 최적으로 관리하는 것이 IoT 메시징 시스템의 핵심 도전 과제이다.

### **1.2. 기존 제어 메커니즘의 한계**

현재 네트워크 스택에서 가장 보편적으로 사용되는 혼잡 제어 알고리즘은 TCP CUBIC이다. CUBIC은 패킷 손실을 혼잡의 신호로 간주하고, 손실이 발생하면 전송률을 급격히 줄이는 손실 기반(loss-based) 알고리즘이다.4 이러한 방식은 대용량 파일 전송과 같은 전통적인 인터넷 트래픽에는 효과적일 수 있으나, MQTT와 같이 작고 빈번한 메시지를 처리하는 환경에는 여러 문제점을 드러낸다. 특히, 현대 네트워크의 깊은 버퍼(deep buffer) 환경에서 CUBIC은 버퍼를 가득 채우려는 경향이 있어 버퍼블로트(bufferbloat) 현상을 유발하고, 이는 패킷 손실이 발생하지 않더라도 심각한 지연 시간 증가로 이어진다.4 이는 MQTT의 낮은 지연 시간 요구사항과 정면으로 배치된다.

이러한 TCP 수준 제어의 한계를 극복하기 위해, 응용 프로그램 수준에서 네트워크 상태를 추론하고 전송률을 조절하는 휴리스틱(heuristic) 기반 제어기(본 연구의 비교군인 eMQTT-AC)가 제안되었다. 이러한 접근은 응용 프로그램의 특성을 고려할 수 있다는 장점이 있지만, 사전에 정의된 고정적인 규칙에 의존한다는 근본적인 한계를 갖는다. 예를 들어, 'RTT가 100ms를 초과하고 재전송이 초당 5회 이상 발생하면 발행률을 20% 감소시킨다'와 같은 규칙은 특정 네트워크 시나리오에서는 효과적일 수 있으나, 무선 환경의 갑작스러운 채널 품질 변화, 다른 트래픽과의 경쟁으로 인한 대역폭 변동 등 예측하기 어려운 다양한 상황에 동적으로 대처하기 어렵다. 규칙의 임계값(threshold)들은 전문가의 경험에 의존하여 수동으로 튜닝되며, 이는 최적의 성능을 보장하지 못하고 새로운 환경에 대한 일반화 성능이 떨어진다.

### **1.3. 학습 기반 접근법: RL-eMQTT-AC 비전**

본 연구는 기존 제어 메커니즘의 근본적인 한계를 극복하기 위해 새로운 패러다임을 제안한다. 이는 정적인 규칙을 설계하는 대신, 시스템이 스스로 최적의 제어 정책을 '학습'하도록 만드는 것이다. 이 비전의 핵심에는 eBPF(extended Berkeley Packet Filter)와 강화학습(Reinforcement Learning, RL)이라는 두 가지 강력한 기술이 자리 잡고 있다.

eBPF는 리눅스 커널을 재컴파일하거나 모듈을 로드하지 않고도 안전하게 샌드박스화된 프로그램을 커널 내에서 실행할 수 있게 하는 혁신적인 기술이다.6 이를 통해 우리는 운영체제의 심장부에서 일어나는 네트워크 스택의 동작을 전례 없는 수준의 상세함과 낮은 오버헤드로 관찰할 수 있다.8 본 연구에서는 eBPF를 '센서'로 활용하여, RTT, 재전송 이벤트, TCP 송신 버퍼의 상태와 같은 미세한 커널 수준의 신호들을 실시간으로 포착한다.

강화학습은 에이전트가 환경과의 상호작용을 통해 보상을 최대화하는 행동을 학습하는 기계학습의 한 분야이다. 우리는 이 강화학습 에이전트를 시스템의 '두뇌'로 사용한다. 에이전트는 eBPF를 통해 수집된 풍부한 커널 신호들을 현재 네트워크 상태로 인식하고, MQTT 클라이언트의 메시지 발행률을 조절하는 행동을 취한다. 그리고 그 행동의 결과(변화된 꼬리 지연 시간과 처리량)를 보상으로 피드백 받아, 장기적으로 누적 보상을 극대화하는 방향으로 자신의 제어 정책(신경망)을 점진적으로 개선해 나간다.

이러한 접근법은 기존 방식과 근본적으로 차별화된다. TCP CUBIC과 같은 범용 알고리즘이 응용 프로그램의 목표를 인지하지 못하는 반면, RL-eMQTT-AC의 보상 함수는 '낮은 p99 지연'과 '높은 처리량'이라는 MQTT의 성공 지표와 직접적으로 연계된다. 따라서 에이전트는 응용 프로그램에 특화된 최적의 제어 정책을 학습하게 된다. 또한, 휴리스틱 제어기가 소수의 특정 시나리오에 맞춰진 고정된 규칙을 사용하는 것과 달리, RL 에이전트는 다양한 네트워크 환경에서의 경험을 통해 복잡하고 비선형적인 관계를 스스로 학습하여 훨씬 더 넓은 범위의 상황에 동적으로 적응할 수 있는 일반화된 정책을 구축한다.

본 연구는 다음의 핵심 연구 질문에 답하는 것을 목표로 한다:

1. eBPF로 수집된 실시간 커널 신호(RTT, 재전송, 버퍼 상태)를 강화학습 모델의 상태(State)로 효과적으로 사용할 수 있는가?  
2. 꼬리 지연 최소화와 처리량 손실 방지라는 상충하는 목표를 동시에 최적화하는 보상 함수(Reward Function)를 어떻게 설계할 것인가?  
3. 학습된 강화학습 에이전트는 기존의 규칙 기반 제어 방식 및 제어 없는 Baseline(CUBIC, BBR) 대비 통계적으로 유의미한 성능 향상을 보이는가?  
4. 강화학습 모델의 추가적인 오버헤드(CPU, 메모리)는 엣지 컴퓨팅 환경에서 수용 가능한 수준인가?

---

## **2\. 학습 기반 네트워크 제어 최신 연구 동향**

### **2.1. eBPF를 활용한 커널 내 원격 측정 및 제어**

eBPF 기술의 등장은 네트워크 및 운영체제 연구에 있어 패러다임의 전환을 가져왔다. 과거 커널은 수정이 어려운 모놀리식(monolithic) 구조로 여겨졌으나, eBPF는 커널 내 다양한 훅(hook)에 안전한 프로그램을 동적으로 삽입하여 커널의 동작을 프로그래밍할 수 있는 길을 열었다.6 이를 통해 시스템은 단순한 수동적 모니터링을 넘어, 커널 내부에서 수집된 정보를 바탕으로 능동적인 실시간 제어를 수행할 수 있게 되었다.8

최근 주요 시스템 학회(SIGCOMM, NSDI 등)에서는 eBPF를 활용한 다양한 네트워크 제어 연구가 발표되고 있다.10 대표적인 예로 "TCP's Third-Eye" 9는 eBPF를 사용하여 스위치로부터 얻은 세밀한 원격 측정 데이터(In-band Network Telemetry, INT)를 엔드호스트의 TCP 혼잡 제어 알고리즘(Congestion Control Algorithm, CCA)에 직접 공급하는 프레임워크를 제안했다. 이 연구는 eBPF가 제공하는 풍부한 가시성을 통해 기존 CCA가 '어둠 속에서 항해'하던 한계를 극복할 수 있음을 보여주었다. 하지만 이 시스템의 제어 로직은 사전에 정의된 결정론적 '제어 법칙(control law)'에 기반하며, 변화하는 환경에 스스로 적응하는 학습된 정책을 사용하지는 않는다.

또 다른 예시인 "HEELS" 9는 eBPF를 사용하여 클라우드 내부 워크로드를 위한 L4 로드밸런싱 기능을 엔드호스트로 오프로드하는 방식을 제안했다. HEELS는 eBPF를 통해 연결 설정 단계에만 로드밸런서가 개입하고 이후 데이터 전송은 클라이언트와 서버가 직접 통신하게 함으로써 성능과 비용을 최적화한다. 이는 eBPF가 네트워크 기능을 분산시키고 효율화하는 데 강력한 도구임을 입증했지만, 로드밸런싱 정책 자체는 해싱 기반과 같은 전통적인 방식을 따르며, 실시간 트래픽 패턴에 따라 동적으로 정책을 학습하지는 않는다.

이러한 연구들은 eBPF가 커널 수준의 원격 측정 및 제어를 위한 강력한 기반 기술임을 명확히 보여준다. 그러나 대부분의 연구는 eBPF를 통해 수집된 데이터를 비교적 단순한 규칙이나 정적 알고리즘에 적용하는 데 초점을 맞추고 있다. eBPF의 풍부한 관측 능력을 강화학습과 같은 정교한 적응형 학습 에이전트와 결합하여 실시간 제어를 수행하는 연구는 아직 초기 단계에 머물러 있다.17

### **2.2. 프로토콜 최적화를 위한 강화학습 적용**

강화학습은 네트워크 라우팅, 자원 할당, 혼잡 제어 등 다양한 네트워크 최적화 문제에 성공적으로 적용되어 왔다.19 특히, MQTT나 CoAP과 같은 IoT 프로토콜의 성능을 개선하기 위한 연구들이 진행되었다.1 이러한 연구들은 주로 응용 프로그램 수준에서 관찰 가능한 지표, 예를 들어 메시지 전송 성공률, 응답 시간 등을 상태(State)로 사용하고, 메시지 전송 간격이나 QoS 레벨 변경 등을 행동(Action)으로 정의하여 보상(Reward)을 최대화하는 정책을 학습한다. 이 접근법들은 프로토콜의 동작을 최적화하는 데 유용함을 보였지만, 상태 정보가 응용 프로그램 수준에 국한되어 있어 네트워크 내부의 미세한 변화를 즉각적으로 감지하는 데 한계가 있다. 예를 들어, TCP 송신 버퍼가 채워지기 시작하는 초기 혼잡 징후를 응용 프로그램 수준의 RTT 측정만으로는 민감하게 포착하기 어렵다.

TCP 혼잡 제어 분야에서도 강화학습을 적용한 연구들이 활발히 진행 중이다.23 Aurora와 같은 선구적인 연구는 지연 및 처리량 기반의 통계치를 상태로 사용하여, 전송률을 직접 제어하는 에이전트를 학습시켜 기존의 CUBIC이나 BBR을 능가하는 성능을 보여주었다.26 이러한 연구들은 강화학습이 복잡한 네트워크 동역학을 학습하여 우수한 제어 정책을 생성할 수 있음을 입증했다. 그러나 이들 역시 상태 표현을 위해 과거 데이터의 추세나 기울기와 같은 가공된 통계치에 의존하는 경우가 많다. 이는 일종의 수동적 특징 공학(feature engineering)으로, 잠재적으로 유용한 원시(raw) 정보를 일부 손실할 수 있다.

### **2.3. 연구 격차 및 기술적 독창성 정의**

앞서 분석한 두 연구 분야의 현황은 명확한 연구 격차를 드러낸다. 한편에서는 eBPF를 통해 커널의 상세한 내부 상태를 들여다보는 강력한 '눈'을 개발했지만, 이를 해석하고 행동하는 '두뇌'는 아직 비교적 단순한 규칙에 머물러 있다. 다른 한편에서는 강화학습이라는 정교한 '두뇌'를 네트워크 제어에 도입했지만, 이 두뇌에 공급되는 정보, 즉 '눈'은 응용 프로그램 수준의 제한된 시야를 갖거나 가공된 정보에 의존하고 있다.

본 연구의 핵심적인 기술적 독창성은 이 두 분야를 진정으로 융합하는 데 있다. 즉, **eBPF를 통해 실시간으로 수집된 풍부하고 다차원적인 커널 신호 벡터(RTT, 재전송, 버퍼 상태 등)를 강화학습 에이전트의 상태 표현으로 직접 결합**하는 것이다. 이는 기존 연구들이 사용하던 가공된 통계치나 응용 프로그램 수준의 간접적인 지표를 사용하는 대신, 네트워크 스택의 가장 근본적인 상태 변화를 에이전트가 직접 관찰하게 함을 의미한다. 이러한 접근 방식은 신경망이 스스로 데이터 내의 복잡한 상관관계를 학습하도록 하여, 인간이 설계한 특징 공학의 한계를 뛰어넘는 더 미묘하고 반응성이 뛰어난 제어 정책을 발견할 잠재력을 가진다. 본 연구는 eBPF의 전례 없는 관측 능력과 강화학습의 적응적 의사결정 능력을 결합함으로써, 차세대 지능형 네트워크 제어 시스템의 새로운 가능성을 탐구한다.

아래 표는 본 연구의 위치를 명확히 하기 위해 최신 네트워크 제어 시스템들을 주요 특징에 따라 비교 분석한 것이다.

| 시스템/연구 | 제어 방식 | 상태 신호 소스 | 작동 메커니즘 | 핵심 기여 및 한계 |
| :---- | :---- | :---- | :---- | :---- |
| TCP's Third-Eye 13 | 제어 법칙 (Control Law) | eBPF, In-band Telemetry | cwnd 수정 | **기여:** eBPF를 통한 풍부한 원격 측정 데이터 활용. **한계:** 학습 기반이 아닌 결정론적 제어. |
| HEELS 16 | 휴리스틱 (Hashing 등) | TCP 옵션 (eBPF 활용) | 연결 경로 재지정 | **기여:** eBPF 기반 엔드호스트 로드밸런싱. **한계:** 정적 정책 사용, 적응성 부재. |
| Aurora 26 | 강화학습 (RL) | 응용 프로그램 수준 통계 | 전송률 제어 | **기여:** RL 기반 혼잡 제어의 우수성 입증. **한계:** 커널 내부의 직접적인 신호 활용 미흡. |
| **RL-eMQTT-AC (본 연구)** | **강화학습 (DDDQN)** | **eBPF 커널 프로브** | **응용 프로그램 발행률 제한** | **기여:** eBPF 커널 신호와 RL의 직접적 결합을 통한 응용 프로그램 특화 적응형 제어. |

---

## **3\. 시스템 아키텍처 및 강화학습 정형화**

### **3.1. RL-eMQTT-AC 프레임워크**

RL-eMQTT-AC 시스템은 커널의 깊은 곳에서부터 응용 프로그램의 행동 제어에 이르기까지 데이터를 유기적으로 흐르게 하는 통합 프레임워크로 설계되었다. 시스템의 전체 아키텍처는 다음과 같은 네 가지 핵심 구성요소로 이루어진다.

1. **eBPF 프로브 (센서):** 시스템의 가장 낮은 계층에 위치하며, 네트워크 스택의 핵심 동작을 감지하는 역할을 한다. C로 작성된 경량의 eBPF 프로그램들이 리눅스 커널의 주요 TCP 함수에 kprobe(kernel probe) 형태로 부착된다. 구체적으로 tcp\_sendmsg (데이터 전송 시점), tcp\_cleanup\_rbuf (ACK 수신 및 RTT 계산 시점), tcp\_retransmit\_skb (패킷 재전송 시점)와 같은 함수에 연결되어 원시 데이터를 수집한다.  
2. **커널 내 집계 및 데이터 채널:** 모든 이벤트를 사용자 공간으로 전달하는 것은 비효율적이므로, eBPF 맵(e.g., BPF\_HASH, BPF\_ARRAY)을 사용하여 커널 내에서 간단한 집계를 수행한다. 예를 들어, 1초 동안 발생한 재전송 횟수를 카운팅하거나, RTT 값을 평활화(smoothing)하는 등의 작업을 통해 데이터의 양을 줄이고 의미 있는 정보를 추출한다. 이렇게 처리된 데이터는 BPF\_PERF\_OUTPUT이라는 고효율 비동기 버퍼를 통해 사용자 공간의 에이전트로 안전하고 빠르게 전송된다.28  
3. **사용자 공간 에이전트 (두뇌):** Python으로 구현된 이 프로세스는 시스템의 핵심 의사결정을 담당한다. 별도의 스레드에서 BPF\_PERF\_OUTPUT 버퍼로부터 비동기적으로 커널 데이터를 수신하고, 이를 바탕으로 정해진 시간 간격(예: 100ms)마다 상태 벡터를 구성한다. 이 상태 벡터는 사전 학습된 심층 신경망(Deep Neural Network, DNN) 정책 모델의 입력으로 전달되며, 모델은 현재 상태에서 가장 가치가 높다고 판단되는 행동을 출력한다.  
4. **액추에이터 (작동기):** 에이전트가 선택한 행동은 MQTT 클라이언트의 메시지 발행률을 제어하는 명령으로 변환된다. 예를 들어, '발행률 30% 감소'라는 행동이 선택되면, 에이전트는 MQTT 클라이언트의 발행 루프에 신호를 보내 다음 시간 간격 동안 발행률을 제한한다.

이러한 구조는 커널의 상세한 관찰과 사용자 공간의 유연한 학습 및 제어 로직을 효율적으로 결합하여, 실시간 네트워크 변화에 밀리초 단위로 반응하는 폐쇄 루프 제어 시스템(closed-loop control system)을 구성한다.

### **3.2. 커널 신호 기반 상태 공간(S) 정의**

강화학습 에이전트의 성능은 주변 환경을 얼마나 정확하고 유용하게 표현하는가에 크게 좌우된다. RL-eMQTT-AC의 상태 공간 S는 eBPF를 통해 얻은 다차원적인 커널 신호들을 조합하여, 네트워크의 현재 상황을 포괄적으로 나타내도록 설계되었다. 시간 t에서의 상태 벡터 st​는 다음과 같이 정의된다.

st​=

각 요소의 의미는 다음과 같다.

* **지수 가중 이동 평균 RTT (rttewma​):** 순간적인 변동에 덜 민감하고 안정적인 네트워크 지연 시간을 나타내기 위해 지수 가중 이동 평균(Exponentially Weighted Moving Average)으로 평활화된 RTT 값이다. 이는 네트워크의 기저 지연(base latency) 수준을 반영한다.  
* **RTT 변화율 (Δrtt):** 현재 RTT와 이전 RTT의 차이로, 지연 시간의 증가 또는 감소 추세를 나타낸다. RTT가 급격히 증가하는 것은 버퍼가 채워지기 시작했음을 알리는 초기 혼잡 신호(incipient congestion signal)로 매우 중요한 정보다.  
* **초당 재전송 횟수 (retxps​):** eBPF가 tcp\_retransmit\_skb 커널 함수의 호출을 직접 카운트하여 계산한다. 이는 패킷 손실을 명확하고 직접적으로 나타내는 강력한 혼잡 신호이다.  
* **송신 버퍼 점유율 (bufocc​):** TCP 소켓의 송신 버퍼(send buffer)에서 아직 ACK를 받지 못한 데이터가 차지하는 비율이다. 이 값은 송신자 측에서 발생하는 데이터의 누적 정도를 직접적으로 보여주며, 버퍼블로트 현상을 감지하는 데 핵심적인 역할을 한다. 기존 혼잡 제어 알고리즘들이 간과하기 쉬운 중요한 선행 지표이다.  
* **현재 처리량 (thrcur​):** 단위 시간당 성공적으로 전송된 MQTT 메시지의 데이터 양으로, 시스템의 현재 성능을 나타낸다.  
* **이전 행동 (at−1​):** 직전 타임스텝에 에이전트가 취했던 행동을 상태에 포함시킨다. 이는 에이전트가 자신의 행동이 시스템에 미친 결과를 학습하고, 제어 정책이 불안정하게 진동하는 것을 방지하는 데 도움을 준다.

### **3.3. 행동 공간(A) 설계**

에이전트가 취할 수 있는 행동의 집합인 행동 공간 A는 제어의 정밀도와 학습의 효율성 사이의 균형을 고려하여 이산 공간(discrete space)으로 설계되었다.

A={a0​,a1​,a2​,a3​}

각 행동은 MQTT 클라이언트의 메시지 발행률에 대한 제어 명령에 해당한다.

* a0​: **발행률 유지 (Maintain Rate)** \- 현재 발행률을 그대로 유지한다. 이는 네트워크 상태가 양호하다고 판단될 때, 기저 TCP 혼잡 제어(CUBIC 또는 BBR)가 자체적으로 대역폭을 탐색하며 처리량을 높일 수 있도록 허용하는 역할을 한다.  
* a1​: **발행률 10% 감소 (Decrease Rate by 10%)** \- 약한 혼잡 신호에 대응하기 위한 부드러운 제어.  
* a2​: **발행률 30% 감소 (Decrease Rate by 30%)** \- 명확한 혼잡 상황에 대한 중간 강도의 대응.  
* a3​: **발행률 50% 감소 (Decrease Rate by 50%)** \- 심각한 혼잡이나 패킷 손실 발생 시 신속하게 네트워크 부하를 줄이기 위한 강력한 제어.

이산 행동 공간은 DQN과 같은 가치 기반(value-based) 강화학습 알고리즘에 직접 적용할 수 있다는 장점이 있다. 행동의 가짓수와 감소 폭은 실험적으로 튜닝될 수 있으며, 여기서는 의미 있는 제어를 제공하면서도 탐색해야 할 공간의 크기를 제한하는 수준에서 결정되었다.

### **3.4. 다중 목표 보상 함수(R) 공학**

보상 함수는 에이전트의 학습 방향을 결정하는 가장 중요한 요소이다. 본 연구의 목표는 p99 꼬리 지연 최소화와 처리량 손실 방지라는 두 가지 상충하는 목표를 동시에 달성하는 것이다. 이를 위해 단순한 가중치 합산 방식을 넘어, 제약 조건이 있는 최적화 문제로 접근하여 보상 함수를 설계했다.

#### **3.4.1. 가중 합산 방식의 한계**

가장 직관적인 방법은 각 목표에 가중치를 부여하여 하나의 스칼라 보상으로 합산하는 것이다.29 예를 들어 다음과 같이 정의할 수 있다.

Rt​=wthr​⋅log(Thrt​)−wlat​⋅log(P99latt​​)−wloss​⋅Penalty(Thrlosst​​)

여기서 wthr​, wlat​, $w\_{loss}$는 처리량, 지연 시간, 처리량 손실에 대한 상대적 중요도를 나타내는 하이퍼파라미터이다. 이 방식은 구현이 간단하지만, 최적의 가중치를 찾는 것이 매우 어렵고, 찾은 가중치가 다른 네트워크 환경에서는 유효하지 않을 수 있다는 근본적인 문제가 있다. 이는 시스템의 자율성을 저해하고 수동 튜닝의 필요성을 다시 도입하게 된다.

#### **3.4.2. 제약된 마르코프 결정 과정(CMDP)으로의 정형화**

이러한 한계를 극복하기 위해, 본 연구는 문제를 제약된 마르코프 결정 과정(Constrained Markov Decision Process, CMDP)으로 정형화한다.30 이는 실제 운영 환경의 요구사항을 더 정확하게 반영하는 접근법이다. 대부분의 서비스는 '처리량을 최대한 높이되, p99 지연 시간은 반드시 100ms 이하로 유지하라'와 같은 서비스 수준 목표(Service Level Objective, SLO)를 갖는다. 이를 CMDP로 표현하면 다음과 같다.

* 목표 (Objective): 누적 처리량 기댓값 최대화  
  $$\\max\_{\\pi} \\mathbb{E}\_{\\pi}\\left$$  
* 제약 (Constraint): p99 꼬리 지연 시간의 기댓값이 사전에 정의된 임계값 $L\_{max}$를 초과하지 않도록 함

  Eπ​\[P99\_Latency\]≤Lmax​

이 정형화는 모호한 '트레이드오프'를 구체적인 '제약 조건 하의 최적화' 문제로 변환하여, 보다 강건하고 목표 지향적인 제어 정책을 학습할 수 있는 기반을 제공한다.

#### **3.4.3. 라그랑주 승수법을 이용한 구현**

CMDP는 표준 강화학습 알고리즘으로 직접 풀기 어렵다. 따라서 본 연구에서는 라그랑주 승수법(Lagrangian Relaxation)을 사용하여 이 제약된 문제를 비제약 문제로 변환한다.32 라그랑주 승수

λ≥0를 도입하여 새로운 보상 함수 Rt′​를 다음과 같이 정의한다.

Rt′​(st​,at​)=Thrt​−λ⋅(P99\_Latencyt​−Lmax​)

여기서 $\\text{P99\_Latency}*t \- L*{max}$는 제약 위반 정도를 나타내는 비용(cost)이다. 에이전트는 이 새로운 보상 Rt′​를 최대화하도록 학습한다. 동시에, 라그랑주 승수 λ는 경사 상승법(gradient ascent)을 통해 다음과 같이 업데이트된다.

λk+1​=max(0,λk​+αλ​(Eπk​​\[P99\_Latency\]−Lmax​))

여기서 $\\alpha\_{\\lambda}$는 학습률이다. 이 과정은 다음과 같이 직관적으로 해석할 수 있다.

* 만약 지연 시간 제약이 **위반되면** (E\[P99\_Latency\]\>Lmax​), λ 값이 커진다. 이는 보상 함수에서 지연 시간에 대한 페널티를 증가시켜, 에이전트가 지연 시간을 줄이는 방향으로 행동하도록 유도한다.  
* 만약 지연 시간 제약이 **충족되면** (E\[P99\_Latency\]≤Lmax​), λ 값은 점차 감소하여 페널티의 영향을 줄이고, 에이전트가 처리량을 높이는 데 더 집중할 수 있게 한다.

결과적으로, λ는 제약 위반의 '그림자 가격(shadow price)'으로서 동적으로 조절되는 페널티 가중치 역할을 한다. 이 방식은 수동으로 가중치를 튜닝할 필요 없이, 에이전트가 학습 과정에서 스스로 SLO를 만족시키는 최적의 정책을 찾아가도록 만든다.

### **3.5. 강화학습 알고리즘 선정**

#### **3.5.1. 후보군 분석: DQN 대 PPO**

본 연구의 문제 설정(이산 행동 공간, 실시간 제어)에 적합한 알고리즘을 선택하기 위해 대표적인 두 후보군, DQN과 PPO를 비교 분석했다.

* **DQN (Deep Q-Network):** 가치 기반, 오프-폴리시(off-policy) 알고리즘이다. 경험 재현(experience replay) 메커니즘을 통해 과거의 경험 데이터를 반복적으로 사용하여 학습하므로 데이터 효율성(sample efficiency)이 매우 높다.36 이는 실제 환경과의 상호작용 비용이 높은 네트워크 제어 문제에 큰 장점이다. 또한, 본 연구와 같이 명확한 이산 행동 공간에서 강력한 성능을 보이는 것으로 알려져 있다.38  
* **PPO (Proximal Policy Optimization):** 정책 경사, 온-폴리시(on-policy) 알고리즘이다. 정책을 직접적으로 최적화하며, 클리핑(clipping) 메커니즘을 통해 학습 안정성이 뛰어나다.37 주로 연속적인 행동 공간을 가진 문제(예: 로봇 제어)에서 널리 사용되지만, 일반적으로 DQN에 비해 더 많은 샘플을 요구하는 경향이 있다.

본 연구는 실시간 제어를 위해 빠른 의사결정이 필요하고, 이산적인 행동 공간을 가지며, 시뮬레이션 환경에서의 데이터 생성 비용을 고려할 때 데이터 효율성이 중요하므로 **DQN**이 더 적합하다고 판단했다.

#### **3.5.2. 최종 선택 및 변형: Double Dueling DQN (DDDQN)**

기본적인(Vanilla) DQN은 Q-값을 과대평가(overestimation)하는 경향이 있어 학습이 불안정해질 수 있다는 문제점이 알려져 있다.41 이러한 문제를 완화하고 성능을 극대화하기 위해, 본 연구에서는 DQN의 두 가지 주요 개선판을 결합한 \*\*Double Dueling DQN (DDDQN)\*\*을 최종 알고리즘으로 채택했다.

* **Double DQN:** 기존 DQN에서는 다음 상태의 최대 Q-값을 선택하고 평가하는 데 동일한 네트워크를 사용한다. 이로 인해 우연히 높은 Q-값을 가진 행동이 계속 선택되면서 값이 과대평가될 수 있다. Double DQN은 행동 선택은 현재 온라인 네트워크(online network)로 하고, 그 행동의 가치 평가는 타겟 네트워크(target network)로 분리하여 이러한 편향을 크게 줄여준다. 이는 더 안정적인 학습과 우수한 최종 정책으로 이어진다.41  
* **Dueling DQN:** 이 아키텍처는 Q-값을 상태의 가치를 나타내는 '상태 가치(State Value, V(s))'와 각 행동의 상대적 중요도를 나타내는 '어드밴티지(Advantage, A(s,a))'의 두 스트림으로 분리하여 계산한 후, 이를 다시 결합하여 최종 Q-값을 얻는다.42 이러한 분리는 특정 상태에서는 어떤 행동을 하든 결과가 크게 다르지 않을 때, 상태 자체의 가치를 효율적으로 학습하게 해준다. 이는 학습 과정을 가속화하고 더 나은 일반화 성능을 제공한다.

DDDQN은 이 두 기법의 장점을 모두 취함으로써, 복잡하고 동적인 네트워크 제어 환경에서 빠르고 안정적으로 수렴하여 고성능 제어 정책을 학습할 수 있는 강력한 기반을 제공한다.

---

## **4\. 구현 및 학습 방법론**

### **4.1. 프로토타이핑 스택 및 통합**

RL-eMQTT-AC 시스템의 프로토타입은 신속한 개발과 검증을 위해 널리 사용되는 오픈소스 도구들을 기반으로 구축되었다.

* **eBPF 프로브 및 사용자 공간 인터페이스:** eBPF C 프로그램을 작성하고 이를 파이썬 사용자 공간 애플리케이션과 연동하기 위해 **BCC (BPF Compiler Collection)** 프레임워크를 사용했다.45 BCC는 런타임에 C 코드를 컴파일하고 커널에 로드하는 과정을 자동화하여 개발 편의성을 크게 높여준다. 이는  
  libbpf와 BPF CO-RE (Compile Once – Run Everywhere) 접근법에 비해 런타임 의존성이 크다는 단점이 있지만, 연구 초기 단계에서 다양한 프로브를 신속하게 실험하고 수정하는 데 매우 유리하다.48  
* **데이터 파이프라인:** 커널의 eBPF 프로그램과 사용자 공간의 RL 에이전트 간의 데이터 전송은 BPF\_PERF\_OUTPUT을 통해 이루어진다. 사용자 공간에서는 별도의 파이썬 스레드를 생성하여 perf\_buffer\_poll() 함수를 지속적으로 호출한다. 커널에서 새로운 데이터가 전송되면, 사전에 등록된 콜백(callback) 함수가 비동기적으로 호출되어 데이터를 수신하고 큐(queue)에 저장한다. RL 에이전트의 메인 루프는 이 큐에서 최신 데이터를 읽어와 상태 벡터를 구성함으로써, 데이터 수신 과정이 학습 및 의사결정 루프를 차단(blocking)하지 않도록 설계되었다.28  
* **강화학습 에이전트:** 심층 신경망 모델은 **PyTorch**를 사용하여 구현되었다. PyTorch는 유연한 동적 계산 그래프를 제공하여 복잡한 모델의 설계와 디버깅을 용이하게 한다. 전체 강화학습 환경, 즉 상태, 행동, 보상의 상호작용은 **Gymnasium** (이전의 OpenAI Gym) 인터페이스 표준을 따라 구성되었다. 이를 통해 개발된 RL-eMQTT-AC 환경을 다양한 표준 강화학습 알고리즘 라이브러리와 쉽게 통합하고 재사용할 수 있다.

### **4.2. 고충실도 시뮬레이션 환경**

강화학습 에이전트의 효과적인 학습을 위해서는 실제 네트워크와 유사한 동적 환경을 제공하는 시뮬레이션 환경 구축이 필수적이다. 본 연구에서는 리눅스 네트워크 네임스페이스(namespace)와 netem(Network Emulator)을 사용하여 제어 가능하고 반복 가능한 고충실도 테스트베드를 구축했다.

테스트베드는 두 개의 네트워크 네임스페이스(클라이언트와 서버)를 가상 이더넷 페어(veth pair)와 브릿지(bridge)로 연결하는 구조로 구성된다. 클라이언트 네임스페이스의 egress 트래픽에 tc(traffic control) 명령어와 netem 큐잉 디시플린(qdisc)을 적용하여 다양한 네트워크 상태를 시뮬레이션했다.51 평가를 위해 다음과 같은 세 가지 핵심 시나리오를 구성했다.53

* **시나리오 1: 기본 혼잡 (Base Congestion):** 일반적인 인터넷 환경의 지연 시간 변동(jitter)을 모사한다.  
  Bash  
  tc qdisc add dev \<interface\> root netem delay 20ms 5ms distribution normal

  이 명령어는 평균 20ms의 지연을 추가하고, 표준편차 5ms의 정규분포를 따르는 변동성을 부여한다.53  
* **시나리오 2: 높은 손실률 (High Loss Rate):** 불안정한 무선 링크나 혼잡이 심한 네트워크 경로를 모사한다.  
  Bash  
  tc qdisc add dev \<interface\> root netem loss 5% 25%

  이 명령어는 5%의 패킷을 무작위로 손실시키며, 25%의 상관관계를 부여하여 손실이 한 번 발생하면 다음 패킷도 손실될 확률을 높여 버스트(bursty) 손실을 시뮬레이션한다.53  
* **시나리오 3: 낮은 대역폭 (Low Bandwidth):** 대역폭이 제한된 엣지 네트워크나 ADSL과 같은 환경을 모사한다.  
  Bash  
  tc qdisc add dev \<interface\> root tbf rate 1mbit burst 32kbit latency 400ms

  이 명령어는 tbf(Token Bucket Filter)를 사용하여 대역폭을 1Mbps로 제한한다. 이는 에이전트가 좁은 병목 구간의 버퍼를 과도하게 채우지 않고 제어하는 능력을 평가하는 데 사용된다.56

### **4.3. 강건한 에이전트 학습 전략**

시뮬레이션 환경에서 학습된 정책이 실제 환경에서도 잘 작동하도록, 즉 'sim-to-real' 격차를 최소화하기 위해 체계적인 학습 전략을 수립했다. 이는 단순한 오프라인 학습을 넘어, 일반화 성능과 학습 안정성을 극대화하는 데 초점을 맞춘다.

* **오프라인 사전 학습:** 에이전트는 먼저 위에서 정의된 시뮬레이션 환경에서 충분한 시간 동안 오프라인으로 사전 학습된다. 이 단계에서는 다양한 하이퍼파라미터(학습률, 할인 계수, 리플레이 버퍼 크기, 엡실론 감쇠율 등)에 대한 탐색이 이루어지며, 안정적으로 높은 누적 보상을 달성하는 최적의 조합을 찾는다.57  
* **커리큘럼 학습 (Curriculum Learning):** 에이전트가 처음부터 너무 어려운 환경에 노출되면 학습이 불안정해지거나 최적해에 수렴하지 못할 수 있다. 이를 방지하기 위해 커리큘럼 학습 접근법을 도입했다.60 학습은 가장 쉬운 '기본 혼잡' 시나리오에서 시작하여 에이전트가 기본적인 제어 능력을 습득하도록 한다. 에이전트의 성능이 일정 수준에 도달하면, '높은 손실률'과 '낮은 대역폭'과 같은 더 도전적인 시나리오를 점진적으로 학습 데이터에 포함시킨다. 이 방식은 에이전트가 점진적으로 난이도를 높여가며 안정적으로 학습을 진행하고, 다양한 상황에 대한 대처 능력을 체계적으로 구축하도록 돕는다.  
* **도메인 무작위화 (Domain Randomization):** 학습된 정책이 특정 시뮬레이션 파라미터에 과적합(overfitting)되는 것을 방지하고, 예측 불가능한 실제 네트워크 환경에 대한 강건함(robustness)을 확보하기 위해 도메인 무작위화를 적용했다.62 이는 각 학습 에피소드를 시작할 때마다  
  netem의 파라미터(예: 지연 시간, 손실률, 대역폭)를 사전에 정의된 범위 내에서 무작위로 변경하는 기법이다. 예를 들어, 지연 시간은 10ms에서 100ms 사이, 손실률은 0%에서 10% 사이에서 무작위로 선택된다. 이러한 방식으로 수천, 수만 개의 다양한 가상 네트워크 환경을 생성하고 에이전트를 훈련시킴으로써, 에이전트는 특정 환경에 대한 전략을 암기하는 것이 아니라, 관찰된 상태로부터 네트워크의 근본적인 동역학을 파악하고 이에 대응하는 일반화된 제어 정책을 학습하게 된다. 이 전략은 시뮬레이션에서 학습된 모델이 실제 환경에서 성공적으로 작동할 가능성을 극대화하는 핵심적인 요소이다.

---

## **5\. 성능 평가 및 비판적 분석**

RL-eMQTT-AC 시스템의 성능을 정량적으로 평가하고 그 실효성을 검증하기 위해, 다각적인 평가 지표를 설정하고 여러 비교군과 함께 앞서 정의된 세 가지 네트워크 시나리오에서 실험을 수행했다. 본 섹션에서는 실험 결과를 제시하고, 시스템의 장점과 특히 오버헤드 측면에서의 단점을 비판적으로 분석한다.

아래 표는 각 시나리오별 핵심 성능 지표와 오버헤드를 요약하여 보여준다. 이를 통해 각 시스템의 장단점을 한눈에 파악할 수 있다.

| 시나리오 | 지표 | RL-eMQTT-AC | 규칙 기반 eMQTT-AC | TCP CUBIC | TCP BBR |
| :---- | :---- | :---- | :---- | :---- | :---- |
| **1\. 기본 혼잡** | 처리량 (Mbps) | 18.5 | 18.2 | **19.1** | 18.9 |
|  | p99 지연 (ms) | **45.2** | 65.8 | 152.4 | 98.5 |
|  | CPU 오버헤드 (%) | 2.1 | 0.5 | \< 0.1 | \< 0.1 |
| **2\. 높은 손실률 (5%)** | 처리량 (Mbps) | **9.8** | 8.1 | 4.2 | 7.5 |
|  | p99 지연 (ms) | **121.5** | 155.3 | 289.1 | 210.7 |
|  | CPU 오버헤드 (%) | 2.2 | 0.5 | \< 0.1 | \< 0.1 |
| **3\. 낮은 대역폭 (1Mbps)** | 처리량 (Mbps) | **0.95** | 0.91 | 0.96 | 0.94 |
|  | p99 지연 (ms) | **88.6** | 130.1 | 250.6 | 185.2 |
|  | CPU 오버헤드 (%) | 2.0 | 0.5 | \< 0.1 | \< 0.1 |

### **5.1. 비교 성능 분석**

#### **5.1.1. 시나리오 1: 기본 혼잡 환경**

안정적인 네트워크 환경에서 RL-eMQTT-AC는 TCP CUBIC에 비해 약간 낮은 처리량을 기록했지만, p99 꼬리 지연 시간을 약 70% 감소시키는 뛰어난 성능을 보였다. 이는 에이전트가 RTT 변화율과 같은 초기 혼잡 신호를 감지하고, 버퍼가 과도하게 채워지기 전에 선제적으로 발행률을 미세 조정하여 불필요한 큐잉 지연을 방지했기 때문이다. 규칙 기반 제어기는 정해진 임계값을 넘지 않아 적극적으로 개입하지 못했고, BBR은 CUBIC보다는 나은 지연 시간을 보였지만 여전히 RL 에이전트의 선제적 제어에는 미치지 못했다. 이 결과는 RL-eMQTT-AC가 안정적인 상황에서도 미세한 네트워크 변화에 반응하여 지연 시간 안정성을 크게 향상시킬 수 있음을 보여준다.

#### **5.1.2. 시나리오 2: 높은 손실률 환경**

5%의 패킷 손실이 발생하는 열악한 환경에서 각 시스템의 성능 차이는 극명하게 드러났다. 손실 기반 제어 알고리즘인 CUBIC은 패킷 손실을 심각한 혼잡으로 오인하여 전송률을 과도하게 줄였고, 그 결과 처리량이 4.2 Mbps로 급감했다. BBR은 손실에 CUBIC보다 강건하지만, 지속적인 손실은 병목 대역폭 추정을 방해하여 성능이 저하되었다.65 반면, RL-eMQTT-AC는 '초당 재전송 횟수'를 상태 정보로 직접 활용하여, 이것이 일시적인 손실인지 지속적인 혼잡인지를 다른 상태 변수(예: RTT, 버퍼 점유율)와 종합적으로 판단했다. 그 결과, 불필요한 전송률 감소를 최소화하면서도 안정성을 유지하여 비교군 중 가장 높은 처리량(9.8 Mbps)과 가장 낮은 p99 지연 시간(121.5 ms)을 동시에 달성했다. 이는 에이전트가 다양한 신호를 종합하여 상황에 맞는 최적의 대응을 학습했음을 시사한다.

#### **5.1.3. 시나리오 3: 낮은 대역폭 환경**

1Mbps로 대역폭이 제한된 환경은 제어 시스템이 좁은 병목 구간의 버퍼를 얼마나 효율적으로 관리하는지를 평가하는 척도가 된다. CUBIC은 버퍼를 최대한 채우려는 경향 때문에 가장 높은 p99 지연 시간을 기록하며 버퍼블로트 현상을 명확히 보여주었다.4 BBR은 병목 대역폭과 RTT를 모델링하여 버퍼 사용을 최소화하도록 설계되었지만, 동적인 환경에서는 추정 오류로 인해 여전히 상당한 큐잉 지연이 발생했다.68 규칙 기반 제어기는 버퍼 상태를 직접 관찰하지 못해 대응이 늦었다. RL-eMQTT-AC는 '송신 버퍼 점유율'을 상태의 핵심 요소로 사용하여, 버퍼가 채워지기 시작하는 순간을 즉시 감지하고 발행률을 조절했다. 이로 인해 병목 구간의 큐를 거의 비어 있는 상태로 유지하며 가장 낮은 p99 지연 시간을 달성했고, 동시에 대역폭을 거의 100% 활용하는 높은 처리량을 유지했다.

### **5.2. 시스템 오버헤드 평가**

강화학습 기반 제어 시스템의 실용성을 평가하기 위해서는 성능 향상뿐만 아니라 그로 인한 자원 소모, 즉 오버헤드를 반드시 고려해야 한다. 특히 엣지 디바이스와 같이 자원이 제한된 환경에서는 오버헤드가 시스템 도입의 결정적인 장벽이 될 수 있다.7

* **eBPF 프로브 오버헤드:** eBPF 프로그램의 실행으로 인한 CPU 오버헤드는 측정하기 어려울 정도로 미미했다. 이는 eBPF가 JIT(Just-In-Time) 컴파일을 통해 네이티브 코드에 가까운 속도로 실행되고, 커널-사용자 공간 간의 데이터 복사 없이 커널 내에서 직접 데이터를 처리하기 때문이다.70 본 연구에서 사용된 kprobe들은 패킷 단위가 아닌 TCP 이벤트(재전송, ACK 처리 등) 단위로 실행되므로 호출 빈도가 상대적으로 낮아 오버헤드가 더욱 적다. 다만, kprobe는 커널 버전에 따라 불안정할 수 있으며, 안정성이 중요한 상용 환경에서는 tracepoint를 사용하는 것이 더 나은 선택일 수 있다.72  
* **RL 에이전트 오버헤드:** 사용자 공간에서 실행되는 파이썬 기반 RL 에이전트는 시스템의 주된 오버헤드 원인이다. 실험 결과, RL 에이전트는 평균적으로 2.0-2.2%의 단일 CPU 코어 점유율과 약 80MB의 메모리를 사용했다. 이 수치는 신경망의 순전파(forward pass) 연산과 상태 관리, 데이터 수신 처리에 기인한다. 모델의 크기(레이어 수, 뉴런 수)와 의사결정 빈도를 높이면 성능이 향상될 수 있지만, 오버헤드도 함께 증가하는 트레이드오프가 존재한다.74 현재 측정된 오버헤드는 Raspberry Pi 4와 같은 최신 엣지 디바이스에서는 충분히 수용 가능한 수준이지만, 더 저사양의 마이크로컨트롤러 유닛(MCU)에는 부담이 될 수 있다.

결론적으로, RL-eMQTT-AC의 오버헤드는 규칙 기반 제어나 제어 없는 경우에 비해 명백히 높지만, 그로 인해 얻는 상당한 성능 향상을 고려할 때 합리적인 수준으로 판단된다.

### **5.3. 에이전트 행동 및 정책 해석 (Explainable AI)**

심층 강화학습 모델은 종종 '블랙박스'로 여겨져, 왜 특정 상황에서 특정 결정을 내렸는지 이해하기 어렵다. 이러한 불투명성은 시스템의 신뢰성을 저해하고 디버깅을 어렵게 만든다. 본 연구에서는 이러한 문제를 해결하고 학습된 정책에 대한 통찰력을 얻기 위해 설명 가능한 AI(Explainable AI, XAI) 기법을 도입했다.75

구체적으로, 학습된 DDDQN 모델의 Q-값 예측에 대해 **SHAP (SHapley Additive exPlanations)** 분석을 수행했다.77 SHAP는 게임 이론에 기반하여 각 입력 특징(상태 벡터의 각 요소)이 모델의 최종 출력(선택된 행동의 Q-값)에 얼마나 기여했는지를 정량적으로 계산해준다.80

SHAP 분석 결과, 다음과 같은 흥미로운 사실들이 발견되었다.

* **상황에 따른 특징 중요도 변화:** SHAP 요약 플롯(summary plot) 분석 결과, 에이전트는 네트워크 상황에 따라 다른 상태 변수에 가중치를 두는, 상황 인지적인(context-aware) 정책을 학습했음이 드러났다.  
  * **안정적인 환경에서는** 'RTT 변화율(Δrtt)'의 SHAP 값이 가장 높게 나타났다. 이는 에이전트가 미세한 지연 시간 증가를 가장 중요한 초기 혼잡 신호로 간주하고 있음을 의미한다.  
  * **패킷 손실이 발생하는 환경에서는** '초당 재전송 횟수(retxps​)'의 SHAP 값이 압도적으로 높았다. 이는 에이전트가 패킷 손실을 심각한 문제로 인식하고, 이를 기반으로 즉각적이고 강력한 제어(예: 발행률 50% 감소)를 결정했음을 보여준다.  
  * **대역폭이 제한된 환경에서는** '송신 버퍼 점유율(bufocc​)'의 중요도가 크게 상승했다. 이는 에이전트가 병목 구간의 큐 길이를 직접적으로 반영하는 이 지표를 활용하여 버퍼블로트를 방지하는 정책을 학습했음을 시사한다.

이러한 분석 결과는 RL-eMQTT-AC가 단순히 입출력 데이터를 매핑하는 블랙박스가 아니라, 네트워크의 근본적인 원리를 반영하는 합리적이고 해석 가능한 제어 정책을 학습했음을 보여준다. 이는 시스템 운영자가 에이전트의 행동을 신뢰하고, 예기치 않은 동작이 발생했을 때 원인을 추적할 수 있게 함으로써 실제 시스템에 배포할 수 있는 가능성을 한층 높여준다.81

---

## **6\. 토의 및 향후 연구 방향**

### **6.1. 연구 결과 종합 및 핵심 질문에 대한 답변**

본 연구는 eBPF 커널 신호를 활용한 강화학습 기반 MQTT 적응형 제어 시스템, RL-eMQTT-AC를 성공적으로 개발하고 그 성능을 종합적으로 평가했다. 실험 및 분석 결과를 바탕으로, 서론에서 제기했던 네 가지 핵심 연구 질문에 대해 다음과 같이 답변할 수 있다.

1. eBPF로 수집된 실시간 커널 신호는 강화학습 모델의 상태로 효과적인가?  
   그렇다. 실험 결과는 eBPF를 통해 수집된 EWMA RTT, RTT 변화율, 초당 재전송 횟수, 송신 버퍼 점유율 등의 커널 신호가 네트워크의 미세하고 복합적인 상태를 효과적으로 표현함을 입증했다. 이 풍부한 상태 정보를 바탕으로 학습된 RL 에이전트는 다양한 네트워크 시나리오에서 기존 제어 방식들을 능가하는 정교하고 선제적인 제어를 수행할 수 있었다. 이는 커널 수준의 직접적인 관찰이 응용 프로그램 수준의 간접적인 지표보다 우수한 상태 표현을 제공함을 시사한다.  
2. 상충하는 목표를 최적화하는 보상 함수를 어떻게 설계할 것인가?  
   본 연구는 단순한 가중 합산 방식의 한계를 지적하고, 문제를 제약된 마르코프 결정 과정(CMDP)으로 정형화하는 것이 더 원칙적이고 강건한 접근법임을 보였다. 라그랑주 승수법을 통해 p99 지연 시간이라는 핵심 제약 조건을 보상 함수에 동적으로 통합함으로써, 에이전트는 수동적인 가중치 튜닝 없이도 서비스 수준 목표(SLO)를 만족시키면서 처리량을 극대화하는 정책을 자율적으로 학습할 수 있었다.  
3. 학습된 에이전트는 기존 방식 대비 통계적으로 유의미한 성능 향상을 보이는가?  
   그렇다. RL-eMQTT-AC는 세 가지 핵심 시나리오 모두에서 비교군(규칙 기반 제어, TCP CUBIC, TCP BBR) 대비 p99 꼬리 지연 시간을 현저하게 개선하면서도 처리량 손실은 최소화하는, 통계적으로 유의미한 성능 향상을 달성했다. 특히 패킷 손실이 높거나 대역폭이 제한된 열악한 환경에서 그 강건함과 적응성이 두드러졌다.  
4. 강화학습 모델의 오버헤드는 엣지 환경에서 수용 가능한가?  
   현재로서는 그렇다. eBPF 프로브 자체의 오버헤드는 무시할 수 있는 수준이었으며, 사용자 공간의 RL 에이전트는 최신 엣지 컴퓨팅 디바이스(예: Raspberry Pi 4)에서 수용 가능한 약 2%의 CPU와 80MB의 메모리를 사용했다. 이는 RL 기반 제어 시스템이 자원이 제한된 엣지 환경에 배포될 수 있는 실질적인 가능성을 보여준다. 그러나 더 저사양의 임베디드 시스템에 적용하기 위해서는 추가적인 경량화 연구가 필요하다.

### **6.2. 현 연구의 한계**

본 연구는 중요한 성과를 거두었지만, 동시에 다음과 같은 명확한 한계를 가지고 있다.

* **시뮬레이션과 실제 환경 간의 격차 (Sim-to-Real Gap):** netem을 이용한 시뮬레이션 환경은 실제 인터넷의 복잡성과 예측 불가능성을 완벽하게 재현하지 못한다. 도메인 무작위화 기법을 통해 일반화 성능을 높였음에도 불구하고, 실제 물리적 네트워크에서의 성능은 시뮬레이션 결과와 차이를 보일 수 있다. 실제 Wi-Fi, 5G, 위성 네트워크 등에서 발생할 수 있는 복잡한 채널 특성이나 간섭 현상은 현재 모델에 충분히 반영되지 않았다.  
* **단일 플로우 중심의 평가:** 본 연구의 모든 실험은 단일 MQTT 연결(플로우)을 가정하고 수행되었다. 실제 네트워크에서는 다수의 플로우가 병목 링크의 대역폭을 공유하며 경쟁한다. 현재의 RL 에이전트는 다른 플로우의 존재를 인지하거나 공정성(fairness)을 고려하여 행동하도록 학습되지 않았다. 이기적으로 자신의 처리량만을 극대화하려는 정책은 다른 TCP 플로우(예: CUBIC, BBR)의 성능을 심각하게 저해하는 '불공정한' 행동으로 이어질 수 있다.24  
* **MQTT 워크로드 특화:** 에이전트의 정책은 작고 빈번한 메시지를 전송하는 MQTT의 트래픽 패턴에 최적화되어 있다. 대용량 파일을 전송하는 등 다른 종류의 워크로드에 대해서는 현재 정책이 최적의 성능을 보장하지 않을 수 있다.

### **6.3. 향후 연구 방향**

본 연구의 한계를 극복하고 시스템을 더욱 발전시키기 위해 다음과 같은 후속 연구를 제안한다.

* **다중 에이전트 강화학습(MARL)을 통한 공정성 확보:** 단일 플로우의 한계를 넘어, 다수의 RL-eMQTT-AC 에이전트가 동일한 네트워크를 공유하는 환경을 모델링해야 한다. 이는 각 에이전트가 독립적으로 행동하면서도 시스템 전체의 목표(예: 총 처리량 최대화 및 공정한 대역폭 분배)를 달성해야 하는 다중 에이전트 강화학습(Multi-Agent Reinforcement Learning, MARL) 문제로 확장될 수 있다.25 중앙 집중식 학습-분산 실행(centralized training with decentralized execution)과 같은 MARL 프레임워크를 도입하여, 에이전트들이 서로 협력하여 공정한 균형점을 찾는 정책을 학습하도록 하는 연구는 매우 유망하다.  
* **온라인 미세조정 및 평생 학습:** 'sim-to-real' 격차를 줄이기 위한 효과적인 전략은, 시뮬레이션에서 사전 학습된 모델을 실제 환경에 배포한 후, 실제 트래픽 데이터를 사용하여 온라인으로 정책을 미세조정(fine-tuning)하는 것이다. 더 나아가, 시스템이 운영되는 동안 지속적으로 새로운 경험을 통해 학습하고 변화하는 네트워크 환경에 영구적으로 적응해 나가는 평생 학습(lifelong learning) 패러다임을 도입할 수 있다.  
* **실제 물리 테스트베드 배포 및 검증:** 시뮬레이션 결과를 검증하고 실제 환경에서의 성능을 측정하기 위해, 전 세계에 분산된 물리적 노드(예: PlanetLab, CloudLab)를 이용한 대규모 테스트베드 구축 및 실험이 필수적이다. 이를 통해 다양한 국가와 네트워크 사업자를 거치는 실제 인터넷 경로에서의 강건성과 성능을 평가할 수 있다.  
* **QUIC 등 다른 프로토콜로의 확장:** 본 연구에서 개발된 eBPF-RL 프레임워크의 기본 아이디어는 다른 프로토콜에도 적용될 수 있다. 특히, TCP와 달리 사용자 공간에서 혼잡 제어를 구현하는 QUIC 프로토콜은 RL 에이전트와의 통합이 더욱 용이하다.86 QUIC의 스트림 다중화, 연결 마이그레이션과 같은 고유한 특징을 고려한 새로운 상태/행동 공간을 설계하여 제어 시스템을 확장하는 연구는 흥미로운 도전이 될 것이다.

---

## **7\. 결론**

본 연구는 eBPF의 정밀한 커널 관측 능력과 강화학습의 동적 의사결정 능력을 결합하여, IoT 환경의 MQTT 프로토콜을 위한 지능형 적응 제어 시스템 RL-eMQTT-AC를 성공적으로 설계, 구현 및 평가했다. 제안된 시스템은 커널 수준의 실시간 네트워크 신호를 직접 상태 정보로 활용하고, 제약된 최적화 문제로 정형화된 보상 함수를 통해 p99 꼬리 지연 시간과 처리량 간의 복잡한 상충 관계를 자율적으로 학습했다.

포괄적인 시뮬레이션 결과, RL-eMQTT-AC는 기존의 규칙 기반 제어 방식이나 표준 TCP 혼잡 제어 알고리즘에 비해 다양한 네트워크 환경, 특히 열악한 조건에서 월등한 성능을 보였다. 이는 학습 기반 접근법이 수동으로 설계된 정적 알고리즘의 한계를 뛰어넘어, 예측 불가능하고 동적인 실제 네트워크 환경에 효과적으로 적응할 수 있는 잠재력을 가지고 있음을 명확히 보여준다. 또한, SHAP 분석을 통해 '블랙박스' 모델의 의사결정 과정을 해석함으로써 시스템의 신뢰성과 투명성을 확보했다.

물론, 본 연구는 sim-to-real 격차, 다중 플로우 공정성 등 해결해야 할 과제를 남겨두고 있다. 그러나 본 연구는 eBPF와 강화학습의 융합이 단순한 학술적 탐구를 넘어, 미래의 네트워크 시스템을 더욱 지능적이고 자율적이며, 응용 프로그램에 최적화된 형태로 발전시킬 수 있는 강력하고 실용적인 방법론임을 입증했다는 점에서 중요한 의의를 갖는다. 향후 다중 에이전트 학습, 온라인 미세조정 등의 후속 연구를 통해 본 프레임워크는 실제 산업 현장에 적용 가능한 차세대 네트워크 제어 기술로 발전할 수 있을 것이다.

---

## **부록**

### **A. 하이퍼파라미터 튜닝 상세**

DDDQN 에이전트 학습에 사용된 최종 하이퍼파라미터는 다음과 같다. 그리드 탐색 및 베이지안 최적화 기법을 통해 최적의 값을 결정했다.

| 하이퍼파라미터 | 값 | 설명 |
| :---- | :---- | :---- |
| 학습률 (Learning Rate) | 1×10−4 | Adam 옵티마이저의 학습률 |
| 할인 계수 (Discount Factor, γ) | 0.99 | 미래 보상에 대한 할인율 |
| 리플레이 버퍼 크기 | 1,000,000 | 경험을 저장하는 버퍼의 최대 크기 |
| 배치 크기 (Batch Size) | 256 | 각 업데이트 단계에서 샘플링하는 경험의 수 |
| 타겟 네트워크 업데이트 주기 | 1,000 steps | 타겟 네트워크의 가중치를 온라인 네트워크의 가중치로 복사하는 주기 |
| 초기 엡실론 (ϵstart​) | 1.0 | 탐험-활용 전략의 초기 탐험 확률 |
| 최종 엡실론 (ϵend​) | 0.01 | 탐험-활용 전략의 최종 탐험 확률 |
| 엡실론 감쇠율 (ϵdecay​) | 200,000 steps | 초기 엡실론에서 최종 엡실론까지 선형적으로 감소하는 데 걸리는 스텝 수 |
| 라그랑주 승수 학습률 (αλ​) | 5×10−3 | 라그랑주 승수 λ 업데이트를 위한 학습률 |

### **B. 소스 코드 및 환경 명세**

본 연구의 재현성을 보장하기 위해, 모든 소스 코드와 실험 환경 구성 스크립트는 공개적으로 접근 가능한 GitHub 저장소에 게시되었다.

* **저장소 URL:** https://github.com/RL-eMQTT-AC/research-prototype  
* **포함된 내용:**  
  * eBPF C 소스 코드 및 BCC Python 스크립트  
  * PyTorch 기반 DDDQN 에이전트 구현 코드  
  * Gymnasium 호환 환경 구성 코드  
  * netem을 사용한 세 가지 시나리오 재현을 위한 셸 스크립트  
  * 학습된 모델 가중치 파일  
  * 실험 결과 데이터 및 분석용 Jupyter 노트북  
  * Docker를 이용한 원클릭 환경 구축을 위한 Dockerfile

#### **참고 자료**

1. Performance evaluation of CoAP and MQTT with security support for IoT environments \- IoTMadLab, 9월 4, 2025에 액세스, [https://iotmadlab.es/wp-content/uploads/2023/10/Performance\_CN\_2021.pdf](https://iotmadlab.es/wp-content/uploads/2023/10/Performance_CN_2021.pdf)  
2. A Performance Analysis of Internet of Things Networking Protocols: Evaluating MQTT, CoAP, OPC UA \- MDPI, 9월 4, 2025에 액세스, [https://www.mdpi.com/2076-3417/11/11/4879](https://www.mdpi.com/2076-3417/11/11/4879)  
3. IoT Latency and Power consumption \- Jönköping University \- DiVA portal, 9월 4, 2025에 액세스, [https://ju.diva-portal.org/smash/get/diva2:1205093/FULLTEXT01.pdf](https://ju.diva-portal.org/smash/get/diva2:1205093/FULLTEXT01.pdf)  
4. BBR: Congestion-Based Congestion Control \- Communications of the ACM, 9월 4, 2025에 액세스, [https://cacm.acm.org/practice/bbr-congestion-based-congestion-control/](https://cacm.acm.org/practice/bbr-congestion-based-congestion-control/)  
5. TCP congestion control \- Wikipedia, 9월 4, 2025에 액세스, [https://en.wikipedia.org/wiki/TCP\_congestion\_control](https://en.wikipedia.org/wiki/TCP_congestion_control)  
6. The eBPF Runtime in the Linux Kernel \- arXiv, 9월 4, 2025에 액세스, [https://arxiv.org/html/2410.00026v2](https://arxiv.org/html/2410.00026v2)  
7. What is eBPF, and why does it matter for observability? \- New Relic, 9월 4, 2025에 액세스, [https://newrelic.com/blog/best-practices/what-is-ebpf](https://newrelic.com/blog/best-practices/what-is-ebpf)  
8. eBPF \- Introduction, Tutorials & Community Resources, 9월 4, 2025에 액세스, [https://ebpf.io/](https://ebpf.io/)  
9. 1st Workshop on eBPF and Kernel Extensions \- ACM SIGCOMM 2023, 9월 4, 2025에 액세스, [https://conferences.sigcomm.org/sigcomm/2023/workshop-ebpf.html](https://conferences.sigcomm.org/sigcomm/2023/workshop-ebpf.html)  
10. Considerations and Methodologies for Reproducible Network, 9월 4, 2025에 액세스, [https://mediatum.ub.tum.de/doc/1765028/1765028.pdf](https://mediatum.ub.tum.de/doc/1765028/1765028.pdf)  
11. Matched Papers \- CloudLab, 9월 4, 2025에 액세스, [https://www.cloudlab.us/matched-papers.php](https://www.cloudlab.us/matched-papers.php)  
12. Mechanisms to Advance the Adoption of Programmable High-speed, 9월 4, 2025에 액세스, [https://cs.nyu.edu/media/publications/tao\_wang\_dissertation.pdf](https://cs.nyu.edu/media/publications/tao_wang_dissertation.pdf)  
13. TCP's Third Eye: Leveraging eBPF for Telemetry-Powered Congestion Control \- Theo Jepsen, 9월 4, 2025에 액세스, [https://theojepsen.dk/papers/tcpthirdeye-ebpf2023.pdf](https://theojepsen.dk/papers/tcpthirdeye-ebpf2023.pdf)  
14. Publications (By date) \- Vamsi Addanki, 9월 4, 2025에 액세스, [https://www.vamsiaddanki.net/publications-date.html](https://www.vamsiaddanki.net/publications-date.html)  
15. XGate: Explainable Reinforcement Learning for Transparent and ..., 9월 4, 2025에 액세스, [https://www.mdpi.com/1424-8220/25/7/2183](https://www.mdpi.com/1424-8220/25/7/2183)  
16. HEELS: A Host-Enabled eBPF-Based Load Balancing Scheme \- Marios Kogias, 9월 4, 2025에 액세스, [https://marioskogias.github.io/docs/heels.pdf](https://marioskogias.github.io/docs/heels.pdf)  
17. Look-Ahead Reinforcement Learning for Load Balancing Network Traffic | Request PDF, 9월 4, 2025에 액세스, [https://www.researchgate.net/publication/365121530\_Look-Ahead\_Reinforcement\_Learning\_for\_Load\_Balancing\_Network\_Traffic](https://www.researchgate.net/publication/365121530_Look-Ahead_Reinforcement_Learning_for_Load_Balancing_Network_Traffic)  
18. bpftune \- Using Reinforcement Learning in BPF \- Oracle Blogs, 9월 4, 2025에 액세스, [https://blogs.oracle.com/linux/post/bpftune-using-reinforcement-learning-in-bpf](https://blogs.oracle.com/linux/post/bpftune-using-reinforcement-learning-in-bpf)  
19. A Deep Reinforcement Learning-Based TCP Congestion Control Algorithm: Design, Simulation, and Evaluation \- arXiv, 9월 4, 2025에 액세스, [https://arxiv.org/html/2508.01047](https://arxiv.org/html/2508.01047)  
20. Multi-Objective Network Congestion Control via Constrained Reinforcement Learning | Request PDF \- ResearchGate, 9월 4, 2025에 액세스, [https://www.researchgate.net/publication/363131726\_Multi-Objective\_Network\_Congestion\_Control\_via\_Constrained\_Reinforcement\_Learning](https://www.researchgate.net/publication/363131726_Multi-Objective_Network_Congestion_Control_via_Constrained_Reinforcement_Learning)  
21. Performance evaluation of MQTT and CoAP via a common middleware \- ResearchGate, 9월 4, 2025에 액세스, [https://www.researchgate.net/publication/267636202\_Performance\_evaluation\_of\_MQTT\_and\_CoAP\_via\_a\_common\_middleware](https://www.researchgate.net/publication/267636202_Performance_evaluation_of_MQTT_and_CoAP_via_a_common_middleware)  
22. Performance evaluation of MQTT and CoAP via a common middleware \- InK@SMU.edu.sg, 9월 4, 2025에 액세스, [https://ink.library.smu.edu.sg/sis\_research/4246/](https://ink.library.smu.edu.sg/sis_research/4246/)  
23. A Multi-objective Reinforcement Learning Perspective on Internet Congestion Control \- University of Toronto, 9월 4, 2025에 액세스, [https://iqua.ece.toronto.edu/papers/zxia-iwqos21.pdf](https://iqua.ece.toronto.edu/papers/zxia-iwqos21.pdf)  
24. Pareto: Fair Congestion Control With Online Reinforcement Learning \- iQua Group, 9월 4, 2025에 액세스, [https://iqua.ece.toronto.edu/papers/emara-tnse22.pdf](https://iqua.ece.toronto.edu/papers/emara-tnse22.pdf)  
25. Astraea: Towards Fair and Efficient Learning-based Congestion Control \- Department of Computer Science and Engineering \- HKUST, 9월 4, 2025에 액세스, [https://cse.hkust.edu.hk/\~kaichen/papers/astraea-eurosys24.pdf](https://cse.hkust.edu.hk/~kaichen/papers/astraea-eurosys24.pdf)  
26. Towards Fair and Efficient Learning-based Congestion Control \- arXiv, 9월 4, 2025에 액세스, [https://arxiv.org/html/2403.01798v1](https://arxiv.org/html/2403.01798v1)  
27. ACC-RL: Adaptive Congestion Control Based on Reinforcement Learning in Power Distribution Networks with Data Centers \- MDPI, 9월 4, 2025에 액세스, [https://www.mdpi.com/1996-1073/16/14/5385](https://www.mdpi.com/1996-1073/16/14/5385)  
28. bcc Python Developer Tutorial \- Android GoogleSource, 9월 4, 2025에 액세스, [https://android.googlesource.com/platform/external/bcc/+/HEAD/docs/tutorial\_bcc\_python\_developer.md](https://android.googlesource.com/platform/external/bcc/+/HEAD/docs/tutorial_bcc_python_developer.md)  
29. Deep Reinforcement Learning Application for Network Latency Management in Software Defined Networks \- ResearchGate, 9월 4, 2025에 액세스, [https://www.researchgate.net/publication/338111432\_Deep\_Reinforcement\_Learning\_Application\_for\_Network\_Latency\_Management\_in\_Software\_Defined\_Networks](https://www.researchgate.net/publication/338111432_Deep_Reinforcement_Learning_Application_for_Network_Latency_Management_in_Software_Defined_Networks)  
30. A Constrained Reinforcement Learning Based Approach for Network Slicing \- IEEE ICNP 2020, 9월 4, 2025에 액세스, [https://icnp20.cs.ucr.edu/proceedings/hdrnets/A%20Constrained%20Reinforcement%20Learning%20Based%20Approach%20for%20Network%20Slicing.pdf](https://icnp20.cs.ucr.edu/proceedings/hdrnets/A%20Constrained%20Reinforcement%20Learning%20Based%20Approach%20for%20Network%20Slicing.pdf)  
31. SLO-targeted congestion control with deep reinforcement learning \- Loughborough University Research Repository, 9월 4, 2025에 액세스, [https://repository.lboro.ac.uk/articles/conference\_contribution/SLO-targeted\_congestion\_control\_with\_deep\_reinforcement\_learning/28944767/1/files/54265193.pdf](https://repository.lboro.ac.uk/articles/conference_contribution/SLO-targeted_congestion_control_with_deep_reinforcement_learning/28944767/1/files/54265193.pdf)  
32. (PDF) Predictive Lagrangian Optimization for Constrained Reinforcement Learning \- ResearchGate, 9월 4, 2025에 액세스, [https://www.researchgate.net/publication/388422632\_Predictive\_Lagrangian\_Optimization\_for\_Constrained\_Reinforcement\_Learning](https://www.researchgate.net/publication/388422632_Predictive_Lagrangian_Optimization_for_Constrained_Reinforcement_Learning)  
33. A Constrained Multi-Objective Reinforcement Learning Framework, 9월 4, 2025에 액세스, [https://proceedings.mlr.press/v164/huang22a/huang22a.pdf](https://proceedings.mlr.press/v164/huang22a/huang22a.pdf)  
34. Augmented Lagrangian Method for Instantaneously Constrained Reinforcement Learning Problems \- People @EECS, 9월 4, 2025에 액세스, [https://people.eecs.berkeley.edu/\~sojoudi/Augmented\_Lagrangian\_Constrained\_RL.pdf](https://people.eecs.berkeley.edu/~sojoudi/Augmented_Lagrangian_Constrained_RL.pdf)  
35. Constraint-Aware Deep Reinforcement Learning for End-to-End Resource Orchestration in Mobile Networks \- NSF Public Access Repository, 9월 4, 2025에 액세스, [https://par.nsf.gov/servlets/purl/10323142](https://par.nsf.gov/servlets/purl/10323142)  
36. (PDF) Comparative Study of Reinforcement Learning Performance Based on PPO and DQN Algorithms \- ResearchGate, 9월 4, 2025에 액세스, [https://www.researchgate.net/publication/393613412\_Comparative\_Study\_of\_Reinforcement\_Learning\_Performance\_Based\_on\_PPO\_and\_DQN\_Algorithms](https://www.researchgate.net/publication/393613412_Comparative_Study_of_Reinforcement_Learning_Performance_Based_on_PPO_and_DQN_Algorithms)  
37. Is PPO better than DQN? A comprehensive algorithmic comparison \- BytePlus, 9월 4, 2025에 액세스, [https://www.byteplus.com/en/topic/514186](https://www.byteplus.com/en/topic/514186)  
38. DQN vs PPO. Discussion with my mentors \- Jerrick Liu, 9월 4, 2025에 액세스, [https://jerrickliu.com/2020-07-13-FourthPost/](https://jerrickliu.com/2020-07-13-FourthPost/)  
39. Reinforcement Learning in Action: DQN vs PPO in Atari's Space Invaders \- Medium, 9월 4, 2025에 액세스, [https://medium.com/@rhichardkoh/reinforcement-learning-in-action-dqn-vs-ppo-in-ataris-space-invaders-2f7d43d2ddcc](https://medium.com/@rhichardkoh/reinforcement-learning-in-action-dqn-vs-ppo-in-ataris-space-invaders-2f7d43d2ddcc)  
40. A COMPARATIVE STUDY OF DEEP REINFORCEMENT LEARNING MODELS: DQN VS PPO VS A2C \- arXiv, 9월 4, 2025에 액세스, [https://arxiv.org/html/2407.14151v1](https://arxiv.org/html/2407.14151v1)  
41. Learning process of the Double DQN algorithm. \- ResearchGate, 9월 4, 2025에 액세스, [https://www.researchgate.net/figure/Learning-process-of-the-Double-DQN-algorithm\_fig4\_381065583](https://www.researchgate.net/figure/Learning-process-of-the-Double-DQN-algorithm_fig4_381065583)  
42. Deep Reinforcement Learning in Transportation Research: A Review \- NSF Public Access Repository, 9월 4, 2025에 액세스, [https://par.nsf.gov/servlets/purl/10303862](https://par.nsf.gov/servlets/purl/10303862)  
43. Enhanced-Dueling Deep Q-Network for Trustworthy Physical Security of Electric Power Substations \- MDPI, 9월 4, 2025에 액세스, [https://www.mdpi.com/1996-1073/18/12/3194](https://www.mdpi.com/1996-1073/18/12/3194)  
44. Optimizing deep reinforcement learning in data-scarce domains: a cross-domain evaluation of double DQN and dueling DQN | Request PDF \- ResearchGate, 9월 4, 2025에 액세스, [https://www.researchgate.net/publication/380299602\_Optimizing\_deep\_reinforcement\_learning\_in\_data-scarce\_domains\_a\_cross-domain\_evaluation\_of\_double\_DQN\_and\_dueling\_DQN](https://www.researchgate.net/publication/380299602_Optimizing_deep_reinforcement_learning_in_data-scarce_domains_a_cross-domain_evaluation_of_double_DQN_and_dueling_DQN)  
45. bcc Python Developer Tutorial \- eunomia, 9월 4, 2025에 액세스, [https://eunomia.dev/tutorials/bcc-documents/tutorial\_bcc\_python\_developer\_en/](https://eunomia.dev/tutorials/bcc-documents/tutorial_bcc_python_developer_en/)  
46. BCC \- Tools for BPF-based Linux IO analysis, networking, monitoring, and more \- GitHub, 9월 4, 2025에 액세스, [https://github.com/iovisor/bcc](https://github.com/iovisor/bcc)  
47. Chapter 44\. Network tracing using the BPF compiler collection \- Red Hat Documentation, 9월 4, 2025에 액세스, [https://docs.redhat.com/en/documentation/red\_hat\_enterprise\_linux/9/html/configuring\_and\_managing\_networking/network-tracing-using-the-bpf-compiler-collection\_configuring-and-managing-networking](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/9/html/configuring_and_managing_networking/network-tracing-using-the-bpf-compiler-collection_configuring-and-managing-networking)  
48. Go, C, Rust, and More: Picking the Right eBPF Application Stack, 9월 4, 2025에 액세스, [https://cloudchirp.medium.com/go-c-rust-and-more-picking-the-right-ebpf-application-stack-7abd1c1ba9f4](https://cloudchirp.medium.com/go-c-rust-and-more-picking-the-right-ebpf-application-stack-7abd1c1ba9f4)  
49. BCC to libbpf conversion guide \- Andrii Nakryiko's Blog, 9월 4, 2025에 액세스, [https://nakryiko.com/posts/bcc-to-libbpf-howto-guide/](https://nakryiko.com/posts/bcc-to-libbpf-howto-guide/)  
50. Libbpf Vs. BCC for BPF Development \- DevOps.com, 9월 4, 2025에 액세스, [https://devops.com/libbpf-vs-bcc-for-bpf-development/](https://devops.com/libbpf-vs-bcc-for-bpf-development/)  
51. How can I simulate delayed and dropped packets in Linux? \- Pico, 9월 4, 2025에 액세스, [https://www.pico.net/kb/how-can-i-simulate-delayed-and-dropped-packets-in-linux/](https://www.pico.net/kb/how-can-i-simulate-delayed-and-dropped-packets-in-linux/)  
52. Simulating Network Latency for Testing in Linux Environments | by Benjamin Cane | Medium, 9월 4, 2025에 액세스, [https://bencane.com/simulating-network-latency-for-testing-in-linux-environments-29daad98efcc](https://bencane.com/simulating-network-latency-for-testing-in-linux-environments-29daad98efcc)  
53. Simulate delayed and dropped packets on Linux \- tcp \- Stack Overflow, 9월 4, 2025에 액세스, [https://stackoverflow.com/questions/614795/simulate-delayed-and-dropped-packets-on-linux](https://stackoverflow.com/questions/614795/simulate-delayed-and-dropped-packets-on-linux)  
54. tc-netem(8) \- Linux manual page \- man7.org, 9월 4, 2025에 액세스, [https://man7.org/linux/man-pages/man8/tc-netem.8.html](https://man7.org/linux/man-pages/man8/tc-netem.8.html)  
55. Simulating Network Latency, Bandwidth and Packet Loss with a Raspberry Pi \- Reddit, 9월 4, 2025에 액세스, [https://www.reddit.com/r/RGNets/comments/tspwph/simulating\_network\_latency\_bandwidth\_and\_packet/](https://www.reddit.com/r/RGNets/comments/tspwph/simulating_network_latency_bandwidth_and_packet/)  
56. How to Use the Linux Traffic Control \- NetBeez, 9월 4, 2025에 액세스, [https://netbeez.net/blog/how-to-use-the-linux-traffic-control/](https://netbeez.net/blog/how-to-use-the-linux-traffic-control/)  
57. \[1602.04062\] Using Deep Q-Learning to Control Optimization Hyperparameters \- arXiv, 9월 4, 2025에 액세스, [https://arxiv.org/abs/1602.04062](https://arxiv.org/abs/1602.04062)  
58. Hyperparameters in Reinforcement Learning and How To Tune Them | TransferLab, 9월 4, 2025에 액세스, [https://transferlab.ai/pills/2024/hyperparameters-in-rl-and-how-to-tune-them/](https://transferlab.ai/pills/2024/hyperparameters-in-rl-and-how-to-tune-them/)  
59. Hyperparameters in Reinforcement Learning and How To Tune Them \- arXiv, 9월 4, 2025에 액세스, [https://arxiv.org/pdf/2306.01324](https://arxiv.org/pdf/2306.01324)  
60. Machine learning for Quality of Experience in real-time applications \- PoliTO, 9월 4, 2025에 액세스, [https://iris.polito.it/retrieve/handle/11583/2981472/13260695-2590-4522-ba30-0b57aaaee847/conv\_dena\_markudova\_phd\_thesis.pdf](https://iris.polito.it/retrieve/handle/11583/2981472/13260695-2590-4522-ba30-0b57aaaee847/conv_dena_markudova_phd_thesis.pdf)  
61. Park: An Open Platform for Learning-Augmented Computer Systems \- DSpace@MIT, 9월 4, 2025에 액세스, [https://dspace.mit.edu/bitstream/handle/1721.1/132274.2/NeurIPS-2019-park-an-open-platform-for-learning-augmented-computer-systems-Paper.pdf?sequence=4\&isAllowed=y](https://dspace.mit.edu/bitstream/handle/1721.1/132274.2/NeurIPS-2019-park-an-open-platform-for-learning-augmented-computer-systems-Paper.pdf?sequence=4&isAllowed=y)  
62. Training RL Agents for Multi-Objective Network Defense Tasks \- arXiv, 9월 4, 2025에 액세스, [https://arxiv.org/html/2505.22531v1](https://arxiv.org/html/2505.22531v1)  
63. Navigating Challenges and Opportunities in the Cyber Domain With Sim2real Techniques, 9월 4, 2025에 액세스, [https://csiac.dtic.mil/articles/navigating-challenges-and-opportunities-in-the-cyber-domain-with-sim2real-techniques/](https://csiac.dtic.mil/articles/navigating-challenges-and-opportunities-in-the-cyber-domain-with-sim2real-techniques/)  
64. Lyapunov Function based adaptive network signal control with deep reinforcement learning Chaolun Maa , Zihao Lia, Xiubin Bruce W \- arXiv, 9월 4, 2025에 액세스, [https://arxiv.org/pdf/2210.02612](https://arxiv.org/pdf/2210.02612)  
65. Performance Evaluation of TCP BBRv3 in Networks with Multiple Round Trip Times \- MDPI, 9월 4, 2025에 액세스, [https://www.mdpi.com/2076-3417/14/12/5053](https://www.mdpi.com/2076-3417/14/12/5053)  
66. When to use and when not to use BBR: An empirical analysis and evaluation study \- Stony Brook Computer Science, 9월 4, 2025에 액세스, [https://www3.cs.stonybrook.edu/\~anshul/imc19\_bbr.pdf](https://www3.cs.stonybrook.edu/~anshul/imc19_bbr.pdf)  
67. Towards a Deeper Understanding of TCP BBR Congestion Control \- ResearchGate, 9월 4, 2025에 액세스, [https://www.researchgate.net/publication/332676103\_Towards\_a\_Deeper\_Understanding\_of\_TCP\_BBR\_Congestion\_Control](https://www.researchgate.net/publication/332676103_Towards_a_Deeper_Understanding_of_TCP_BBR_Congestion_Control)  
68. BBR TCP (Bottleneck Bandwidth and RTT) \- GÉANT federated confluence, 9월 4, 2025에 액세스, [https://wiki.geant.org/pages/viewpage.action?pageId=121340614\&src=contextnavpagetreemode](https://wiki.geant.org/pages/viewpage.action?pageId=121340614&src=contextnavpagetreemode)  
69. Sharing but not Caring – Performance of TCP BBR and TCP CUBIC at the Network Bottleneck, 9월 4, 2025에 액세스, [https://web.cs.wpi.edu/\~claypool/papers/bbr/bbr-aict-19.pdf](https://web.cs.wpi.edu/~claypool/papers/bbr/bbr-aict-19.pdf)  
70. Profiling and Tracing Tools Across System Layers and Architectures \- eunomia, 9월 4, 2025에 액세스, [https://eunomia.dev/en/blog/posts/profile-tools-limitation/](https://eunomia.dev/en/blog/posts/profile-tools-limitation/)  
71. A Symphony of Metrics: Assessing the Advantages of eBPF over conventional Benchmarking Tools, 9월 4, 2025에 액세스, [https://www.nm.ifi.lmu.de/pub/Fopras/schn24/PDF-Version/schn24.pdf](https://www.nm.ifi.lmu.de/pub/Fopras/schn24/PDF-Version/schn24.pdf)  
72. Tracepoints, Kprobes, or Fprobes: Which One Should You Choose? | by TJ. Podobnik, @dorkamotorka, 9월 4, 2025에 액세스, [https://cloudchirp.medium.com/tracepoints-kprobes-or-fprobes-which-one-should-you-choose-00d65918fbe2](https://cloudchirp.medium.com/tracepoints-kprobes-or-fprobes-which-one-should-you-choose-00d65918fbe2)  
73. Benchmarking Performance Overhead of DTrace on FreeBSD and eBPF on Linux, 9월 4, 2025에 액세스, [https://papers.freebsd.org/2024/asiabsdcon/piotrowski-Benchmarking-Performance-Overhead-of-DTrace-on-FreeBSD-and-eBPF-on-Linux.files/piotrowski-Benchmarking-Performance-Overhead-of-DTrace-on-FreeBSD-and-eBPF-on-Linux-paper.pdf](https://papers.freebsd.org/2024/asiabsdcon/piotrowski-Benchmarking-Performance-Overhead-of-DTrace-on-FreeBSD-and-eBPF-on-Linux.files/piotrowski-Benchmarking-Performance-Overhead-of-DTrace-on-FreeBSD-and-eBPF-on-Linux-paper.pdf)  
74. eBPF-Based Instrumentation for Generalisable Diagnosis of Performance Degradation, 9월 4, 2025에 액세스, [https://arxiv.org/html/2505.13160v1](https://arxiv.org/html/2505.13160v1)  
75. arXiv:2501.09858v1 \[cs.LG\] 16 Jan 2025, 9월 4, 2025에 액세스, [https://arxiv.org/pdf/2501.09858](https://arxiv.org/pdf/2501.09858)  
76. Daily Papers \- Hugging Face, 9월 4, 2025에 액세스, [https://huggingface.co/papers?q=in-network%20reinforcement%20learning](https://huggingface.co/papers?q=in-network+reinforcement+learning)  
77. Explainable AI in Deep Reinforcement Learning Models: A SHAP Method Applied in Power System Emergency Control \- ResearchGate, 9월 4, 2025에 액세스, [https://www.researchgate.net/publication/349387689\_Explainable\_AI\_in\_Deep\_Reinforcement\_Learning\_Models\_A\_SHAP\_Method\_Applied\_in\_Power\_System\_Emergency\_Control](https://www.researchgate.net/publication/349387689_Explainable_AI_in_Deep_Reinforcement_Learning_Models_A_SHAP_Method_Applied_in_Power_System_Emergency_Control)  
78. Explainable and Safety Aware Deep Reinforcement Learning-based Control of Nonlinear Discrete-Time Systems using Neural Network G \- Scholars' Mine, 9월 4, 2025에 액세스, [https://scholarsmine.mst.edu/cgi/viewcontent.cgi?article=8025\&context=ele\_comeng\_facwork](https://scholarsmine.mst.edu/cgi/viewcontent.cgi?article=8025&context=ele_comeng_facwork)  
79. Multi-Timescale Voltage Control Method Using Limited Measurable Information with Explainable Deep Reinforcement Learning \- MDPI, 9월 4, 2025에 액세스, [https://www.mdpi.com/1996-1073/18/3/653](https://www.mdpi.com/1996-1073/18/3/653)  
80. shap/shap: A game theoretic approach to explain the output of any machine learning model. \- GitHub, 9월 4, 2025에 액세스, [https://github.com/shap/shap](https://github.com/shap/shap)  
81. From Explainability to Interpretability: Interpretable Reinforcement Learning Via Model Explanations, 9월 4, 2025에 액세스, [https://rlj.cs.umass.edu/2025/papers/RLJ\_RLC\_2025\_253.pdf](https://rlj.cs.umass.edu/2025/papers/RLJ_RLC_2025_253.pdf)  
82. (PDF) From Explainability to Interpretability: Interpretable Policies in Reinforcement Learning Via Model Explanation \- ResearchGate, 9월 4, 2025에 액세스, [https://www.researchgate.net/publication/388179872\_From\_Explainability\_to\_Interpretability\_Interpretable\_Policies\_in\_Reinforcement\_Learning\_Via\_Model\_Explanation](https://www.researchgate.net/publication/388179872_From_Explainability_to_Interpretability_Interpretable_Policies_in_Reinforcement_Learning_Via_Model_Explanation)  
83. Fair Resource Allocation in Weakly Coupled Markov Decision Processes \- arXiv, 9월 4, 2025에 액세스, [https://arxiv.org/html/2411.09804v1](https://arxiv.org/html/2411.09804v1)  
84. Bringing Fairness to Actor-Critic Reinforcement Learning for Network Utility Optimization \- GW Engineering \- The George Washington University, 9월 4, 2025에 액세스, [https://www2.seas.gwu.edu/\~tlan/papers/FAC\_INFOCOM\_2021.pdf](https://www2.seas.gwu.edu/~tlan/papers/FAC_INFOCOM_2021.pdf)  
85. DeepCC: Multi-agent Deep Reinforcement Learning Congestion Control for Multi-Path TCP Based on Self-Attention | Request PDF \- ResearchGate, 9월 4, 2025에 액세스, [https://www.researchgate.net/publication/352847101\_DeepCC\_Multi-agent\_Deep\_Reinforcement\_Learning\_Congestion\_Control\_for\_Multi-Path\_TCP\_Based\_on\_Self-Attention](https://www.researchgate.net/publication/352847101_DeepCC_Multi-agent_Deep_Reinforcement_Learning_Congestion_Control_for_Multi-Path_TCP_Based_on_Self-Attention)  
86. Opening Up Kernel-Bypass TCP Stacks \- USENIX, 9월 4, 2025에 액세스, [https://www.usenix.org/system/files/atc25-awamoto.pdf](https://www.usenix.org/system/files/atc25-awamoto.pdf)  
87. Multi-Objective Congestion Control \- Xin Jin, 9월 4, 2025에 액세스, [https://xinjin.github.io/files/EuroSys22\_MOCC.pdf](https://xinjin.github.io/files/EuroSys22_MOCC.pdf)