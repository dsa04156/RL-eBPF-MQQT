# eda.py 코드에 PPO 적용하기

## 기존 eda.py의 동작 이해하기

eda.py 에이전트는 eBPF를 이용해 **MQTT 포트(23232)**의 TCP 연결 상태를 모니터링하고, RTT, 재전송 횟수, 송수신 버퍼 사용량 등의 **네트워크 신호**를 주기적으로 수집합니다. 이 스크립트는 **이벤트 드리븐 에이전트**로서, 수집된 신호를 기반으로 현재 **혼잡 상태(congested)**인지 여부를 판단하고, 혼잡이 감지되면 **MQTT 제어 메시지**를 발행하여 퍼블리셔의 송신 속도를 조절(throttle)하거나 배치 크기(batch size)를 변경하는 등의 조치를 취합니다. 예를 들어, 평균 RTT(ewma_rtt_us)가 임계치 이상으로 높고 패킷 재전송이 발생하면 혼잡 상태로 간주하여 **발행 속도를 감소**시키고(throttle), QoS 수준을 낮추며(qos=0), 메시지를 모아 보낸다(batch 전송) 등의 명령을 보냅니다. 반대로 RTT가 충분히 낮아지고 재전송이 없으면 혼잡이 해소된 것으로 보고, **원래 설정으로 복귀**하는 release 명령을 보냅니다. 이 모든 논리는 **고정 임계값과 히스테리시스** (상/하한 임계 및 유지 시간) 기반의 수동 설계된 휴리스틱에 의해 동작합니다.

이 접근 방식은 비교적 **단순하고 예측 가능**하지만, 네트워크 환경이 동적으로 변하거나 임계값 설정이 부정확한 경우 최적의 성능을 보장하기 어렵습니다. **PPO와 같은 강화학습** 기법을 적용하면 이러한 다중 신호를 보다 **지능적으로 결합**하여, 사람이 정한 규칙 대신 **데이터로부터 학습된 정책**으로 혼잡 시점과 제어 강도를 결정할 수 있습니다. 다음 섹션에서는 PPO를 eda.py에 통합하는 방법과 그에 따른 고려사항을 자세히 설명합니다.

## PPO 적용의 필요성과 기대 효과

기존의 임계치 기반 **혼잡 제어 알고리즘**은 간단하지만, 네트워크 조건 변화에 대한 **적응성**이 부족할 수 있습니다. 잘못 설정된 임계값은 과잉 제어(너무 자주 throttle) 또는 부족한 제어(혼잡 방치)를 초래할 수 있습니다. **Proximal Policy Optimization (PPO)**과 같은 **심층 강화학습** 알고리즘을 이용하면, 에이전트가 **경험을 통해 최적의 제어 전략**을 학습할 수 있습니다[\[1\]](https://baychin.medium.com/proximal-policy-optimization-ppo-from-control-systems-to-bioengineering-applications-3ff73bba4762#:~:text=PPO%20is%20a%20popular%20RL,critic%20method%2C%20meaning). PPO는 **actor-critic 구조**를 사용하는 최신 RL 알고리즘으로, 정책 갱신 시 변화 폭을 제한(clipping)하여 학습의 안정성을 높인 것이 특징입니다[\[1\]](https://baychin.medium.com/proximal-policy-optimization-ppo-from-control-systems-to-bioengineering-applications-3ff73bba4762#:~:text=PPO%20is%20a%20popular%20RL,critic%20method%2C%20meaning). 이를 eda.py에 적용하면 다음과 같은 기대 효과가 있습니다:

- **다중 신호의 통합 판단**: PPO 에이전트는 RTT, 재전송, 버퍼 사용량 등 여러 지표를 **동시에 고려**하여 사람이 정의한 공식을 넘는 **비선형 결합**이나 가중치를 학습할 수 있습니다. 이를 통해 특정 신호에만 의존하는 편향된 판단을 줄이고, **총체적인 네트워크 상태**에 대한 최적 대응이 가능해집니다.
- **동적인 임계값 조정**: 강화학습 에이전트는 **환경 변화에 따라** 행동을 계속 조정하며 학습하기 때문에, 고정 임계값이 아닌 **적응형 임계 정책**을 내재적으로 갖추게 됩니다. 예를 들어 트래픽 패턴이나 링크 용량 변화에 따라 **스스로 혼잡 판단 기준을 조절**하여 일관된 성능을 낼 수 있습니다.
- **성능 향상**: 잘 학습된 PPO 기반 제어는 **기존 휴리스틱보다 높은 처리량과 낮은 지연**을 달성할 잠재력이 있습니다. 실제로 QUIC 프로토콜에 PPO 에이전트를 도입하여 혼잡제어를 수행한 연구(PBQ)에서는, PPO 에이전트가 네트워크 상태를 바탕으로 **혼잡 윈도우 크기**를 동적으로 결정함으로써 기존 Cubic이나 BBR 기반 알고리즘보다 **더 높은 처리량과 더 낮은 RTT**를 얻었다고 보고되었습니다[\[2\]](https://pmc.ncbi.nlm.nih.gov/articles/PMC9955954/#:~:text=scenarios,better%20performance%20in%20both%20throughput). 마찬가지로, 데이터센터 네트워크 혼잡제어에 RL을 적용한 ACC-RL 연구에서는 **전송률(throughput)**, **RTT**, **큐 길이** 등을 보상 신호로 설계하여 PPO 기반 정책을 훈련한 결과, **기존 규칙 기반 알고리즘**(TIMELY, DCQCN, HPCC 등) 대비 **공정성, 링크 활용도, 처리량이 개선**되는 결과를 보였습니다[\[3\]](https://www.mdpi.com/1996-1073/16/14/5385#:~:text=power%20distribution%20networks,RL)[\[4\]](https://www.mdpi.com/1996-1073/16/14/5385#:~:text=network%20environments,fairness%2C%20link%20utilization%2C%20and%20throughput).
- **복잡한 조건에서의 안정성**: 휴리스틱 규칙은 사람이 예상한 시나리오에서는 잘 동작하지만, 상정하지 못한 복잡한 트래픽 패턴에서는 비효율적일 수 있습니다. PPO 에이전트는 훈련 데이터에 나타난 다양한 상황에 대응하도록 **일반화된 정책**을 형성하기 때문에, 잠재적으로 예기치 않은 상황에서도 **안정적인 제어**를 수행할 수 있습니다. (물론 RL 정책도 훈련 범위를 벗어난 상황에서는 성능 보장이 어렵기에, 실제 적용 전 **충분한 시나리오로 학습 및 검증**해야 합니다.)

요약하면, PPO를 적용함으로써 eda.py 에이전트는 **고정 규칙 기반**에서 **데이터 주도 학습 기반**으로 전환되어, 환경 변화에 **적응적**이고 **최적화된 혼잡 제어 정책**을 구현할 수 있습니다.

## 강화학습 문제로의 정식화 (환경, 상태, 행동, 보상)

PPO를 eda.py에 적용하려면 먼저 현재 문제를 강화학습의 틀(환경 Environment, 상태 State, 행동 Action, 보상 Reward)으로 정식화해야 합니다. 이는 PPO 에이전트가 무엇을 **관측**하고 어떤 **행동을 선택**하며, 그에 따라 **어떤 보상**을 받을지를 정의하는 단계입니다.

- **환경 (Environment)**: 에이전트가 작동하는 환경은 **네트워크 혼잡 제어 시나리오**입니다. 이 환경은 매 타임스텝마다 네트워크 상태(예: RTT, 버퍼 점유율 등)를 에이전트에게 제공하고, 에이전트의 제어 명령(예: throttle 속도 변경)이 네트워크 성능에 영향을 줍니다. 실제 물리적 환경(운영 중인 네트워크)을 직접 학습에 사용할 수도 있지만, 안전하고 효율적인 훈련을 위해 **시뮬레이션 환경**을 구축하는 것이 일반적입니다. 예를 들어, NS-3와 OpenAI Gym을 연동한 **ns3-gym** 같은 프레임워크를 사용하면 네트워크를 가상으로 시뮬레이션하여 RL 훈련을 진행할 수 있습니다. 또는 자체적으로 **간소화된 네트워크 모델**을 만들어, 일정 대역폭과 지연을 갖는 링크에서 **패킷 큐잉 동작**을 모사함으로써 훈련 환경을 구성할 수도 있습니다. 환경은 에이전트가 취한 행동에 따라 RTT나 패킷 손실률이 어떻게 변하는지 **모델링 역할**을 합니다.
- **상태 (State)**: 에이전트가 관측하는 상태는 eda.py가 수집하는 **네트워크 성능 지표들**로 구성됩니다. 주요 상태 특징(feature)으로는:
- **RTT 관련**: 현재 평균 RTT (예: ewma_rtt_us 값을 ms 단위로 스케일링) 또는 최근 RTT 샘플들의 이동평균. RTT 값은 **네트워크 혼잡의 정도**를 나타내는 핵심 신호입니다.
- **재전송 발생 여부**: 최근 간격(INTERVAL_S) 동안 **재전송 패킷 수** (retrans_delta) 또는 0/1 플래그 (재전송 발생 여부). 패킷 손실/재전송은 강한 혼잡 신호이므로 상태에 포함합니다.
- **송신/수신 버퍼 사용률**: sndbuf와 rcvbuf를 **최대 버퍼 크기**(TH_SNDBUF, TH_RCVBUF)로 나눈 **상대 사용률** (snd_ratio, rcv_ratio). 이는 송수신 큐의 압력 수준을 나타내며 혼잡 시 크게 상승합니다.
- **이전 행동**: (선택 사항) 직전 타임스텝에 에이전트가 취한 제어 행동을 상태에 포함할 수 있습니다. 이는 환경이 부분적으로 관측 가능하거나(Partial observability) **이력에 따라 다른 대응**이 필요한 경우 도움이 됩니다. 예를 들어, 직전에 이미 throttle을 건 상태인지에 따라 이번에 추가 제어를 할지 말지가 달라질 수 있으므로, 이전 행동 정보를 상태로 제공하면 PPO 에이전트가 히스테리시스 같은 메커니즘을 스스로 학습할 수 있습니다.
- **기타 신호**: 필요에 따라 패킷 전송률, 세션 수 등 추가적인 정보를 상태로 확장할 수 있습니다. 그러나 초기에는 **중요한 핵심 지표들만 선택**하여 상태 공간을 너무 복잡하지 않게 유지하는 것이 좋습니다.

상태 벡터의 각 항목은 **적절한 정규화** 또는 스케일링이 필요합니다. 예를 들어 RTT는 수만 마이크로초 단위이므로 몇 만 단위의 숫자를 그대로 신경망에 넣기보다는 **0~1 사이로 정규화**하거나, 로그 스케일 등을 사용하는 것이 학습에 유리합니다. 버퍼 사용률 등 이미 0~1 범위인 값들은 그대로 사용할 수 있습니다. 이러한 상태는 매 시간 간격(예: 2초)마다 업데이트되어 **PPO 에이전트에 입력**으로 주어집니다.

- **행동 (Action)**: 에이전트의 행동은 곧 **MQTT를 통해 퍼블리셔에게 내리는 제어 명령**입니다. eda.py에서는 혼잡 상태에 따라 throttle (발행 주기 조정), batch (배치 전송 크기), qos (QoS 레벨) 세 가지 매개변수를 제어합니다. PPO 정책이 직접 이 값을 출력하도록 여러 가지 방식으로 행동 공간을 정의할 수 있습니다:
- **이산형 행동 공간**: 몇 가지 **정해진 모드** 중 선택하도록 정의합니다. 예를 들어, 0 = 제어 없음(기본 상태 복귀), 1 = 보통 수준 제어(중간 throttle과 기본 batch), 2 = 강한 제어(최대 throttle 적용, batch 두 배, QoS0 강하)와 같이 **3가지 이산 행동**으로 설정할 수 있습니다. 이렇게 하면 PPO의 정책 네트워크가 3개의 행동 중 하나를 선택하며, eda.py는 그에 대응하는 사전 정의된 명령 세트를 발행합니다. 현재 코드의 휴리스틱도 기본적으로 **Stable (해제)**, **Moderate**, **Severe** 3단계로 행동을 구분하고 있으므로 이산형으로 표현하기 적합합니다.
- **연속형 행동 공간**: 행동을 하나의 연속값이나 다차원 연속 벡터로 정의할 수도 있습니다. 예를 들어 에이전트가 **throttle 빈도**를 1~10 Hz 범위의 연속값으로 출력하고, **batch 크기 배수**(예: 1x ~ 2x)나 QoS 레벨(0 또는 1를 연속 출력 후 반올림) 등을 함께 출력하도록 할 수 있습니다. 연속형 출력은 세밀한 제어가 가능하다는 장점이 있지만, **동시 조절 변수**가 많아지면 학습 난이도가 올라가므로 신중한 설계가 필요합니다. 초기 단계에서는 이산형으로 간략화한 후, 성능 향상이 기대되면 연속형으로 확장하는 것을 권장합니다.
- **멀티-디스크리트/멀티-Continuous**: OpenAI Gym에서는 여러 개의 행동 공간을 조합한 MultiDiscrete 혹은 MultiContinuous 공간도 지원합니다. 이를 이용하면 예를 들어 \[throttle모드, qos모드\] 처럼 두 개의 행동을 한 번에 선택할 수도 있습니다. 하지만 이 또한 문제를 복잡하게 만들 수 있으므로, 우선은 단일 행동으로 표현하는 방법(위의 이산형 등)을 고려합니다.

**행동 매핑**은 에이전트 출력과 실제 제어 명령을 연결하는 부분입니다. 예를 들어, 행동=2 (강한 제어)가 선택되면 eda.py는 {"cmd": "throttle", "rate": 1}, {"cmd": "batch", "size": 10}, {"cmd": "qos", "level": 0} 등의 MQTT 메시지를 순차적으로 퍼블리셔에게 보내 현재 퍼블리싱 속도를 크게 낮추고 품질을 낮추도록 합니다. 행동=1 (보통 제어)일 경우 rate=5, batch=5, qos=1(변경없음) 정도로 하고, 행동=0이면 {"cmd": "release", "defaults": {...}} 메시지를 보내 모든 설정을 기본값으로 풀도록 매핑할 수 있습니다. 이처럼 **PPO 행동 -> 제어명령 세트**를 명시적으로 정의해두면, PPO 출력값을 바로 기존 eda.py 제어 로직에 통합할 수 있습니다.

- **보상 (Reward)**: 보상 설계는 강화학습 성능의 **성패를 좌우**하는 핵심 요소입니다. 에이전트가 궁극적으로 **최적화하려는 목표**를 수치화해서 제공해야 하기 때문입니다. 본 문제의 이상적인 목표는 **네트워크 혼잡을 최소화하면서도 데이터 전송률(처리량)을 최대화**하는 것입니다. 이를 고려한 보상 설계 방안은 다음과 같습니다:
- **RTT 기반 보상**: RTT는 혼잡으로 인한 지연을 보여주는 지표이므로, RTT가 낮을수록 보상을 높게 주고 높을수록 패널티를 부여합니다. 예를 들어 간단히 reward_RTT = - (현재 RTT / 기준_RTT) 형태로 줄 수 있습니다. 기준_RTT는 혼잡이 없는 상태의 평균 RTT (예: 50ms)로 정하여, RTT가 50ms일 때 -1, 100ms일 때 -2 등의 **음의 보상**이 주어지게끔 합니다. 이렇게 하면 에이전트는 RTT를 줄이는 방향으로 학습하게 됩니다. (RTT 대신 RTT 증가분이나 RTT/기준비율의 로그 값을 사용하는 등 변형도 가능함)
- **재전송/손실 패널티**: 재전송 발생이나 패킷 손실은 심각한 혼잡의 신호이므로, 이 이벤트가 발생하면 추가적인 큰 패널티를 주어야 합니다. 예를 들어 해당 간격에 재전송이 1회라도 있었다면 -5의 보상을 더 깎는 식으로 설정합니다. 이렇게 하면 에이전트는 **패킷 손실을 피하도록 행동**을 학습하게 됩니다.
- **처리량(Throughput) 보상**: RTT나 손실을 줄이는 것만 목표로 두면 에이전트는 극단적으로 **전송률을 낮춰버리는** 방향으로 갈 위험이 있습니다. 따라서 **데이터 전송량** 자체에 대한 보상도 포함해야 합니다. 만약 환경에서 매 간격마다 전송된 바이트/패킷 수를 얻을 수 있다면, 이를 정규화하여 보상에 넣습니다. 예를 들어 reward_tp = + (송신한 패킷 수 / 최대가능패킷수) 와 같이, 더 많은 데이터를 보내면 보상이 증가하도록 합니다. eda.py 코드 자체에서는 퍼블리셔가 얼마나 보냈는지를 직접 측정하지 않지만, **대신 throttle 레이트**나 **batch 크기** 등을 이용해 **간접적인 처리량** 추정을 할 수 있습니다. 예컨대 현재 rate 설정 / 최대 rate를 처리량 기여도로 보고 보상에 포함할 수 있습니다. 또는 훈련 환경을 시뮬레이션할 때 명시적으로 **실제 전송된 데이터양**을 추적하도록 구현하면 확실한 처리량 보상이 가능합니다.
- **행동 비용**: 필요에 따라 에이전트의 행동 변화에 비용을 부여할 수도 있습니다. 너무 잦은 제어 명령 변경은 시스템에 부담이 될 수 있으므로, 매 타임스텝마다 행동이 바뀌면 작은 마이너스 보상을 주고, 연속으로 같은 행동을 유지하면 보상을 약간 높게 준다든지 하는 방식입니다. 이렇게 하면 에이전트가 **불필요한 빈번한 제어를 삼가고 안정적인 정책**을 취하도록 유도할 수 있습니다. (이 부분은 꼭 필수는 아니며, 상황에 따라 조정합니다.)

보상 함수를 종합하면 예를 들어 다음과 같은 형태가 될 수 있습니다:

여기서 $w_{\\text{tp}}, w_{\\text{rtt}}, w_{\\text{loss}}$는 각 항목의 가중치입니다 (적절한 값은 실험적으로 결정). 예를 들어 처리량 가중치 1, RTT 가중치 2, 손실 가중치 5 등으로 설정하면 손실을 매우 강하게 억제하면서도 RTT 개선보다 처리량 유지에 조금 더 비중을 두는 식의 정책을 학습시킬 수 있습니다. 실제 ACC-RL 연구에서도 **전송률(throughput)**을 높게 유지하면서 **큐 지연(RTT)**은 낮추는 단일 목표 함수를 설계하여, **최적 전송률을 유지하면서도 패킷이 큐에 쌓이지 않도록** 보상 설계를 하였다고 보고하고 있습니다[\[5\]](https://www.mdpi.com/1996-1073/16/14/5385#:~:text=,at%20the%20best%20possible%20level). 중요한 것은 보상이 에이전트에게 원하는 방향성을 제대로 심어주는 것입니다. 보상 설계 후에는 시뮬레이션을 통해 **의도한 대로 에이전트가 움직이는지** 검증하고, 필요하다면 보상 함수를 조정해야 합니다.

## PPO 에이전트 훈련 단계

문제를 정식화했다면, 이제 **PPO 에이전트를 학습(train)**시켜야 합니다. 일반적으로는 다음과 같은 순서로 진행됩니다:

1. **강화학습 환경 구현**: 앞서 정의한 상태, 행동, 보상 구조를 실제로 코드로 구현합니다. Python의 gym.Env 클래스를 상속하여 커스텀 환경을 만들 수 있습니다. 이 환경의 reset() 메서드는 **초기 상태**를 설정하고 반환하며, step(action) 메서드는 주어진 행동을 환경에 적용하고 **다음 상태, 보상, 종료여부, 부가정보**를 반환하게 됩니다.
2. 만약 **시뮬레이터**를 사용한다면, step()에서 NS-3 등의 시뮬레이터와 연동하여 네트워크를 한 스텝 진행시키고 결과 메트릭을 읽어오는 방식이 될 것입니다.
3. 간소화된 모델을 사용할 경우, step() 안에 현재 행동(throttle 등)이 적용됐을 때 RTT와 패킷 손실이 어떻게 변할지를 계산하는 **수식 or 간단한 큐 모델**을 구현합니다. 예를 들어, 가용대역폭과 현재 보내는 속도를 비교해 **큐에 쌓이는 데이터량**을 추정하고, 그로부터 RTT 증가분을 계산하거나 임계치를 넘으면 패킷 드롭이 발생했다고 가정하는 식입니다. 정확한 모델링이 어렵다면, 과거의 실제 데이터(예: 혼잡 발생 시 RTT 패턴)를 활용해 **확률적/경험적 모델**을 세울 수도 있습니다. 중요한 것은 에이전트가 학습하는 동안 **다양한 상황**을 겪어볼 수 있도록 환경에 랜덤성을 부여하는 것입니다. 예를 들어 최대 대역폭이나 백그라운드 트래픽을 에피소드마다 다르게 주거나, RTT 기본값을 다르게 설정하여 **일반화된 정책**을 학습시킵니다.
4. 환경 구현 시 **에피소드 종결 조건**도 정해야 합니다. 네트워크 제어 문제는 이론상 계속 진행되는 작업이지만, 학습을 위해서는 에피소드를 일정 길이로 끊어주는 것이 보통입니다. 예컨대 **N초간 (혹은 N번 스텝)** 시뮬레이션을 돌리면 한 에피소드를 끝내고 환경을 리셋합니다. 또는 혼잡이 장시간 지속되어 일정 기준 이상 누적 보상이 나쁘면 에피소드를 조기 종료시킬 수도 있습니다. 에피소드 길이는 학습 안정성에 영향을 주는 하이퍼파라미터이며, 너무 짧으면 장기 효과 학습이 어렵고 너무 길면 학습이 느려질 수 있습니다.
5. **PPO 알고리즘으로 학습**: Python의 RL 라이브러리인 **Stable-Baselines3 (SB3)**를 사용하면 PPO 구현을 쉽게 활용할 수 있습니다. SB3의 PPO 클래스를 이용해 학습을 시작하기 전에, 위에서 만든 환경을 벡터화하거나(Wrappers 사용) 상태/행동 공간에 맞게 잘 동작하는지 체크합니다.
6. SB3 사용 예시:  

- import stable_baselines3 as sb3  
    from stable_baselines3.ppo import PPO  
    model = PPO("MlpPolicy", env, learning_rate=3e-4, gamma=0.99,  
    n_steps=2048, batch_size=64, n_epochs=10,  
    clip_range=0.2, gae_lambda=0.95, verbose=1)  
    model.learn(total_timesteps=100000)
- 위 코드에서는 다층퍼셉트론 정책("MlpPolicy")과 함께 PPO 에이전트를 초기화하고, 하이퍼파라미터(학습률, 할인율 등)를 지정한 뒤 100,000 스텝 만큼 학습시킵니다. 학습 도중 에이전트는 환경과 상호작용하면서 **상태-행동-보상** 데이터를 쌓고, 일정 스텝마다 이를 가지고 정책 신경망을 업데이트합니다. PPO는 on-policy 알고리즘이므로, 에이전트가 최신 정책으로 얻은 데이터만을 가지고 반복적으로 학습합니다[\[1\]](https://baychin.medium.com/proximal-policy-optimization-ppo-from-control-systems-to-bioengineering-applications-3ff73bba4762#:~:text=PPO%20is%20a%20popular%20RL,critic%20method%2C%20meaning). 또한 클리핑과 GAE(Generalized Advantage Estimation) 등을 내부적으로 사용하여 학습을 안정화시킵니다.

1. **보상 모니터링 및 튜닝**: 학습 과정에서 **에피소드 당 총보상**이 꾸준히 상승하는지 모니터링해야 합니다. SB3에서는 TensorBoard를 통해 학습曲선을 시각화할 수 있습니다. 만약 보상 함수가 의도와 다르게 설정되어 있다면, 에이전트의 행동이 이상하게 학습되거나 보상이 정체될 수 있습니다. 이를테면 RTT를 너무 강조한 나머지 에이전트가 지나치게 전송을 억제하는 식으로 학습된다면, 처리량 보상 비중을 높여주거나 해야 합니다. **하이퍼파라미터 튜닝** 또한 중요합니다. PPO의 learning_rate, gamma(할인율), clip_range, entropy_coefficient 등은 성능에 영향을 주므로 Optuna 등의 툴로 자동 탐색하거나 경험적으로 조정해야 할 수 있습니다[\[6\]](https://baychin.medium.com/proximal-policy-optimization-ppo-from-control-systems-to-bioengineering-applications-3ff73bba4762#:~:text=1,define%20ranges%20for%20critical%20hyperparameters)[\[7\]](https://baychin.medium.com/proximal-policy-optimization-ppo-from-control-systems-to-bioengineering-applications-3ff73bba4762#:~:text=range). 예를 들어 gamma는 보통 0.99 정도로 하되, 네트워크 제어처럼 **장기 성과**가 중요하다면 약간 높이는 것을 고려합니다. entropy_coefficient는 탐험(Exploration) 강도를 조절하므로, 초기 학습에는 어느 정도 부여하여 다양한 정책을 시도하게 하고, 나중에는 줄이는 식의 전략도 있습니다.
2. **학습 결과 평가**: 충분히 학습이 진행되면, 최적화된 정책이 얻어졌는지 **평가**합니다. 시뮬레이션 환경에서 여러 에피소드를 실행해 **평균 누적보상**, **평균 RTT/처리량** 등을 측정합니다[\[8\]](https://baychin.medium.com/proximal-policy-optimization-ppo-from-control-systems-to-bioengineering-applications-3ff73bba4762#:~:text=3,is%20returned%20to%20evaluate%20effectiveness)[\[9\]](https://baychin.medium.com/proximal-policy-optimization-ppo-from-control-systems-to-bioengineering-applications-3ff73bba4762#:~:text=,predict%28obs%2C%20deterministic%3DTrue). 정책이 휴리스틱보다 개선되었는지, 혹은 특정 시나리오에서 실패하지 않는지 등을 검증합니다. 필요하다면 훈련을 더 하거나, 상태/보상 설계를 손보고 다시 훈련해야 합니다.
3. **모델 저장**: 성능이 만족스러운 정책이 얻어지면 model.save("eda_ppo_policy.zip") 등으로 모델을 저장합니다. 이렇게 저장된 정책은 나중에 실제 eda.py 코드에 임포트되어 사용될 것입니다.
4. **온라인 학습 vs 오프라인 적용**: 학습은 가능하면 **시뮬레이션 or 테스트베드** 환경에서 완료하는 것이 좋습니다. 훈련 중에는 에이전트가 미완성 정책으로 **여러 시행착오를 겪기 때문에**, 이를 실제 운영망에 적용하면 성능 저하나 패킷 손실을 초래할 수 있습니다. 대신 모의 환경에서 충분히 학습한 후, **완성된 정책만 운영 환경에 배치**하는 방식을 권장합니다. 이후 운영 중 정책의 성능이 떨어지면, 그때 발생한 트래픽 패턴 데이터를 수집하여 **정책을 추가로 재학습(fine-tuning)**하거나, 새로운 환경 조건에 맞춰 **주기적으로 정책을 업데이트**하는 식으로 관리하면 됩니다. 일부 연구는 운영 환경에서 **온라인 학습**을 시도하기도 하지만[\[10\]](https://www.mdpi.com/1996-1073/16/14/5385#:~:text=PPO%3A%20It%20is%20an%20RL,for%20easier%20implementation%20and%20greater)[\[11\]](https://www.mdpi.com/1996-1073/16/14/5385#:~:text=Meanwhile%2C%20we%20found%20that%20the,TIMELY%20is%20unable%20to%20accomplish), 이는 매우 신중한 접근이 필요하며 예기치 않은 exploration으로 인한 장애를 감수해야 합니다. 그러므로 여기서는 **오프라인 학습 -> 온라인 적용**을 기본 가정으로 합니다.

## eda.py 코드에 PPO 통합하기

훈련된 PPO 모델을 eda.py에 적용하려면, 기존의 임계값 기반 분기 로직을 **정책 모델 호출로 대체**해야 합니다. 아래는 통합에 필요한 주요 수정 사항 및 단계입니다:

1. **의존성 추가**: PPO 모델을 불러오기 위해 필요한 라이브러리를 임포트합니다. 예를 들어 SB3를 사용했다면 from stable_baselines3 import PPO를 추가하고, 혹은 PyTorch로 직접 구현했다면 torch와 모델 클래스 정의가 필요합니다. 또한 훈련된 모델 파일(eda_ppo_policy.zip 등)을 어플리케이션에 포함시켜야 합니다 (또는 사전에 경로에 다운로드/설치).
2. **모델 로드**: 스크립트 시작 시 학습된 PPO 정책 모델을 로드해야 합니다. SB3의 경우 model = PPO.load("eda_ppo_policy.zip")처럼 호출하면 되고, 만약 별도 신경망 클래스라면 model.load_state_dict(torch.load("...")) 등의 방법으로 가중치를 불러옵니다. 모델 로드가 성공하면 log를 남겨 확인할 수 있습니다. 로딩 위치는 main() 진입 전에 하거나, main() 내부에서 BPF 설정 직후 하는 것이 좋습니다. 예를 들어:  

- \# PPO 모델 로드  
    model = PPO.load("eda_ppo_policy.zip")  
    model_policy = model.policy # (SB3의 경우 .policy로 액세스 가능)  
    print("\[OK\] PPO policy loaded")
- 와 같이 합니다. 만약 모델 크기가 크다면 로드 시간도 고려해야 하지만, 일반적인 MLP 몇층 정도는 순식간입니다.

1. **상태 준비**: eda.py의 주 loop에서 매 주기마다 수집한 메트릭을 이제 **상태 벡터**로 변환해야 합니다. 기존 코드에서는 각 flow의 RTT, buf, retrans를 처리한 후 최종적으로 avg_rtt_ms, had_retrans, snd_ratio, rcv_ratio 등을 계산했습니다. 이 부분에서 PPO 정책 입력으로 사용할 상태 리스트/배열을 구성합니다. 예를 들어:

- state = \[  
    ewma_rtt_us / 100000.0, # RTT: 정규화 (예: 100ms -> 1.0)  
    snd_ratio, # 송신 버퍼 비율 (0~1)  
    rcv_ratio, # 수신 버퍼 비율 (0~1)  
    1.0 if had_retrans else 0.0, # 재전송 발생여부 (0 또는 1)  
    last_action_idx # 이전 행동 (예: 0,1,2 중 하나를 float로)  
    \]
- 위와 같이 현재 측정값들을 **모델 학습 당시와 동일한 방식**으로 전처리/정규화하여 배열 형태로 준비합니다. 학습 때와 입력 특성이 동일해야 올바른 정책 동작을 기대할 수 있으므로, 학습에 사용한 상태 구성과 스케일을 정확히 재현해야 합니다. (예: 학습 때 RTT를 100ms로 나누었다면 여기서도 동일하게 나눔) last_action_idx는 이전 타임스텝에 선택한 행동을 저장해두었다가 사용하는 것으로, 에이전트에 이전 결정 상황을 알려주려는 의도입니다. 만약 학습 시에 이전 행동을 상태로 안 썼다면 굳이 넣을 필요 없습니다.

1. **PPO 정책으로 행동 결정**: 이제 준비된 상태를 PPO 모델에 넣고 행동을 얻습니다. SB3의 경우 action, _ = model.predict(state, deterministic=True)를 호출하면 현재 상태에서 모델이 선택하는 행동을 얻을 수 있습니다. (deterministic=True로 두면 탐험 없이 **가장 높은 확률의 행동**을 선택합니다. 운영 시에는 결정론적으로 하는 것이 보통이며, 학습 시에는 False로 해서 exploration을 허용했을 것입니다.) 반환된 action은 이산형으로 설정했다면 int 값 (예: 0,1,2 중 하나)이 되고, 연속형이면 ndarray로 나옵니다. 이 값을 우리 로직에서 해석하여 대응하는 제어명령을 생성합니다:

- action_idx = int(action)  
    if action_idx == 0:  
    \# Release (stable) mode  
    cmd = {"cmd": "release", "defaults": {"rate": -1, "batch": -1, "qos": 1}}  
    \# 혼잡 해제: 기본값 복귀 (rate, batch -1은 약속된 기본설정 의미)  
    if last_action_idx != 0:  
    cli.publish(CONTROL_TOPIC, json.dumps(cmd), qos=1)  
    last_action_idx = 0  
    print(f"\[PPO\] Stable: releasing control to defaults", flush=True)  
    elif action_idx == 1:  
    \# Moderate control mode  
    cmds = \[  
    {"cmd": "throttle", "rate": CTRL_THROTTLE_RATE}, # 예: 5 Hz  
    {"cmd": "batch", "size": max(1, CTRL_BATCH_SIZE)} # 예: 기본 배치 5  
    \# QoS는 변경하지 않음 (1 유지)  
    \]  
    if last_action_idx != 1:  
    for c in cmds:  
    cli.publish(CONTROL_TOPIC, json.dumps(c), qos=1)  
    last_action_idx = 1  
    print(f"\[PPO\] Moderate congestion control: rate={CTRL_THROTTLE_RATE}, batch={CTRL_BATCH_SIZE}", flush=True)  
    elif action_idx == 2:  
    \# Severe control mode  
    cmds = \[  
    {"cmd": "throttle", "rate": max(1, int(CTRL_THROTTLE_RATE/1))}, # 예: 1 Hz  
    {"cmd": "batch", "size": max(1, int(CTRL_BATCH_SIZE\*2))}, # 예: 배치 10  
    {"cmd": "qos", "level": 0}  
    \]  
    if last_action_idx != 2:  
    for c in cmds:  
    cli.publish(CONTROL_TOPIC, json.dumps(c), qos=1)  
    last_action_idx = 2  
    print(f"\[PPO\] Severe congestion control: rate=1, batch={CTRL_BATCH_SIZE\*2}, qos=0", flush=True)
- 위 코드는 **모범적인 예시**로, PPO 행동을 기존 moderate/severe 릴리스 로직에 대응시킨 것입니다. 핵심은 **직전에 보낸 명령과 같은 명령을 반복해서 보내지 않도록** last_action_idx를 체크하는 부분입니다. 이렇게 해야 불필요하게 같은 제어 명령을 매 주기마다 퍼블리셔에 보내지 않고, 행동이 변할 때만 한번씩 전송합니다. (물론, 필요하다면 일정 시간마다 동일 설정을 리마인드하기 위해 주기적으로 보내도록 할 수도 있습니다.) 또한, CONTROL_MIN_SEC(쿨다운)도 여전히 적용할 수 있습니다. 예를 들어 행동이 바뀌었더라도 직전 명령 후 너무 이른 시점이면 send를 지연시키는 식으로 안전장치를 둘 수 있습니다. 이러한 제한은 PPO 정책이 경솔하게 출력을 바꾸는 것을 조금 완충해주는 역할도 합니다. 다만, 이상적으로는 PPO 에이전트 자체가 **잔여효과**나 **히스테리시스**를 학습하여 출력을 불안정하게 내지 않도록 훈련되겠지만, 현실에서는 약간의 보조 로직이 도움이 될 수 있습니다.

1. **혼잡 판단 로직 대체**: 기존 코드에서 want_on, want_off 등의 조건으로 혼잡 여부를 판단하고 congested 플래그를 업데이트하던 부분은 더 이상 필요하지 않을 것입니다. PPO 에이전트의 정책이 그 역할을 대신하기 때문입니다. 따라서 해당 조건문들과 히스테리시스 타이머 (on_since, off_since 등) 관련 코드를 제거하거나 비활성화하고, 오로지 PPO의 결정 (action_idx)에 따라 제어 여부를 판단하도록 변경합니다. 예를 들어 congested 불리언 대신 action_idx 값이 0 (release)이냐 아니냐로 상태를 간주할 수도 있습니다. 그러나 congested 변수를 완전히 없애지 않고, **모니터링용**으로는 유지할 수 있습니다 (예: "PPO가 판단한 현재 모드가 혼잡(1,2)인지 안정(0)인지"를 congested로 표시). 이 경우 congested = (action_idx != 0)처럼 세팅하면 될 것입니다.
2. **로그와 모니터링**: PPO를 적용한 후에도 운영 중 **로깅**은 중요합니다. 기존에 JSON으로 출력하던 RTT, retrans 등 라인은 그대로 두어, 나중에 PPO 정책의 행동과 성능을 분석할 근거로 삼습니다. 추가로 PPO의 결정(action_idx)도 로그에 포함하는 것이 좋습니다. 예를 들어:

- line\["ppo_action"\] = int(action_idx)  
    print(json.dumps(line), flush=True)
- 와 같이 JSON 라인에 현재 행동을 기록하면, 나중에 RTT 추이와 PPO 액션의 상관관계를 분석해볼 수 있습니다. 또한, 필요시 PPO 입력 상태벡터도 로그에 남겨 디버깅할 수 있습니다 (정규화에 문제가 없었는지 등 확인용).

이상의 변경을 마치면, eda.py는 더 이상 하드코딩된 임계값을 사용하지 않고 **PPO 모델의 인퍼런스 결과에 따라 네트워크 제어 명령**을 발행하게 됩니다. 배포 전 최종적으로 실제 환경에서 **테스트 모드**로 동작시켜 보는 것이 좋습니다. 예를 들어 MQTT 제어 메시지를 실제 퍼블리셔에 보내지 않고 로그로만 찍게 한 뒤, PPO 에이전트가 합리적인 결정을 내리는지 (너무 자주 throttle을 걸지 않는지, 혼잡이 생겼을 때 적절히 행동하는지) 관찰합니다. 테스트 결과가 양호하면 퍼블리셔와 연동하여 **실제 제어**를 수행해봅니다. 초기에는 PPO 정책이 어느 정도 보수적으로 작동하는지 확인하고, 필요한 경우 **안전장치**를 추가합니다. 예를 들어 RTT가 일정 임계 이상 길어지면 PPO와 무관하게 강제 throttle을 거는 **fallback**을 구현하거나, 반대로 RTT가 매우 낮고 여유로울 때는 PPO 결정과 무관하게 release하도록 하는 조건 등을 넣어 **안전망**을 마련할 수 있습니다. (이렇게 하면 PPO가 혹시 학습이 미흡해도 치명적 실수를 하는 것을 막아줍니다.)

## 고려사항 및 향후 개선

- **훈련-운영 환경 차이**: 시뮬레이터로 훈련한 PPO 정책이 실제 네트워크 환경에서도 잘 통할지는 장담할 수 없습니다. 시뮬레이션 모델의 한계로 현실의 복잡성을 완전히 재현하지 못하기 때문입니다. 이를 완화하기 위해 훈련시 **다양한 트래픽 패턴과 네트워크 조건**을 포함하거나, 부분적으로 **실제 데이터로부터 환경을 보정**하는 노력이 필요합니다. 운영 중 일정 기간 PPO 정책의 행동과 성능을 관찰하여, 문제가 발견되면 추가 학습이나 파라미터 조정을 해야 합니다.
- **부분 관찰 문제**: 에이전트는 RTT, 버퍼 등 일부 지표만 볼 수 있고 **완전한 네트워크 상태**(예: 실제 잔여 대역폭이나 큐 잔량 등)는 직접 관찰 못할 수 있습니다. 이런 경우 PPO와 같은 모델프리 RL은 학습이 어려울 수 있습니다[\[10\]](https://www.mdpi.com/1996-1073/16/14/5385#:~:text=PPO%3A%20It%20is%20an%20RL,for%20easier%20implementation%20and%20greater). ACC-RL 등의 연구에서는 이를 POMDP로 모델링하고 **LSTM 기반 정책**이나 **deterministic policy gradient** 등으로 해결을 모색합니다[\[12\]](https://www.mdpi.com/1996-1073/16/14/5385#:~:text=To%20solve%20the%20above%20problem%2C,to%20obtain%20the%20superior%20value)[\[13\]](https://www.mdpi.com/1996-1073/16/14/5385#:~:text=network%20traffic%2C%20and%20balance%20the,contributions%20are%20summarized%20as%20follows). 우리 적용에서는 상황이 복잡해질 경우, 정책에 **과거 몇 단계의 상태를 함께 입력**하거나 (프레임 스택), SB3의 RecurrentPPO를 사용해 LSTM 폴리시를 학습시키는 것을 고려할 수 있습니다. 다만, 처음에는 관측가능한 변수들로도 충분히 성능 향상을 낼 수 있는지 실험해보고, 부족할 때 도입해도 늦지 않습니다.
- **연속적 학습과 탐험**: 일단 학습된 모델을 적용한 후에는 기본적으로 **탐험(exploration)** 없이 결정론적으로 행동합니다. 시간이 지남에 따라 네트워크 상황이 변하면 정책 성능이 저하될 수 있는데, 이를 자동으로 개선하려면 **온라인 학습**을 재개해야 합니다. 하지만 운영 중 임의 탐험은 위험하므로, 비교적 안전한 범위에서만 미세 탐색을 하거나, 주기적으로 새로운 로그 데이터를 모아 **오프라인 재학습**하는 방식을 고려합니다. 예를 들어 월단위로 정책을 업데이트하거나, CI/CD 파이프라인에 RL 재학습을 포함시켜 지속적으로 정책을 개선할 수 있습니다.
- **복수 흐름에 대한 확장**: eda.py는 현재 단일 MQTT 포트(23232)에 대한 관찰에 맞춰져 있지만, 만약 여러 연결/세션을 동시에 관리해야 한다면 RL 상태나 행동도 확장되어야 합니다. PPO 에이전트가 **여러 흐름의 지표를 모두 관찰**하여 일괄적인 행동을 낼 수도 있고, 아니면 **흐름별 개별 에이전트**를 두는 멀티에이전트 설정도 가능합니다[\[14\]](https://arxiv.org/html/2405.11956v1#:~:text=PET%3A%20Multi,Computer%20Networks%2C%20200%3A108515). 본문의 PPO 통합은 단일 제어 대상 (하나의 퍼블리셔/토픽)에 중점을 두었으나, 향후 스케일 확장 시 이러한 구조 개편도 고려해야 합니다.

## 결론

기존 eda.py의 휴리스틱 혼잡 제어를 **PPO 강화학습 정책**으로 대체하면, 네트워크 혼잡 감지 및 제어가 **고정 임계값** 기반에서 **학습된 최적 정책** 기반으로 향상될 수 있습니다. 이를 위해 상태, 행동, 보상을 신중히 정의하고, 시뮬레이션 환경에서 충분한 훈련을 거쳐 안정된 PPO 모델을 얻은 후, 해당 정책을 eda.py에 통합하는 과정을 거쳤습니다. PPO 에이전트는 다양한 신호를 바탕으로 사람이 짠 규칙보다 **정교한 의사결정**을 수행하며, 결과적으로 **높은 처리율과 안정된 RTT 달성**을 목표로 합니다[\[2\]](https://pmc.ncbi.nlm.nih.gov/articles/PMC9955954/#:~:text=scenarios,better%20performance%20in%20both%20throughput). 실제 연구 사례들도 이러한 접근의 유효성을 보여주고 있으며[\[2\]](https://pmc.ncbi.nlm.nih.gov/articles/PMC9955954/#:~:text=scenarios,better%20performance%20in%20both%20throughput)[\[4\]](https://www.mdpi.com/1996-1073/16/14/5385#:~:text=network%20environments,fairness%2C%20link%20utilization%2C%20and%20throughput), 우리의 구현 역시 올바른 환경 설정과 학습을 통해 개선된 성능을 얻을 것으로 기대됩니다.

마지막으로, 강화학습 기반 제어는 초기 도입 시 충분한 테스트와 안전장치가 필요하며, **정책 학습에 대한 모니터링과 재훈련 체계**가 뒷받침될 때 비로소 실효성을 가집니다. 적절히 운영한다면 PPO를 적용한 eda.py 에이전트는 시간에 따라 변화하는 네트워크 환경에 스스로 적응하면서, **최적의 MQTT 전송 속도 제어 전략**을 지속적으로 구현해낼 것입니다.

[\[1\]](https://baychin.medium.com/proximal-policy-optimization-ppo-from-control-systems-to-bioengineering-applications-3ff73bba4762#:~:text=PPO%20is%20a%20popular%20RL,critic%20method%2C%20meaning) [\[6\]](https://baychin.medium.com/proximal-policy-optimization-ppo-from-control-systems-to-bioengineering-applications-3ff73bba4762#:~:text=1,define%20ranges%20for%20critical%20hyperparameters) [\[7\]](https://baychin.medium.com/proximal-policy-optimization-ppo-from-control-systems-to-bioengineering-applications-3ff73bba4762#:~:text=range) [\[8\]](https://baychin.medium.com/proximal-policy-optimization-ppo-from-control-systems-to-bioengineering-applications-3ff73bba4762#:~:text=3,is%20returned%20to%20evaluate%20effectiveness) [\[9\]](https://baychin.medium.com/proximal-policy-optimization-ppo-from-control-systems-to-bioengineering-applications-3ff73bba4762#:~:text=,predict%28obs%2C%20deterministic%3DTrue) Proximal Policy Optimization (PPO): From Control Systems to Bioengineering Applications | by Bay Chin | Medium

<https://baychin.medium.com/proximal-policy-optimization-ppo-from-control-systems-to-bioengineering-applications-3ff73bba4762>

[\[2\]](https://pmc.ncbi.nlm.nih.gov/articles/PMC9955954/#:~:text=scenarios,better%20performance%20in%20both%20throughput) PBQ-Enhanced QUIC: QUIC with Deep Reinforcement Learning Congestion Control Mechanism - PMC

<https://pmc.ncbi.nlm.nih.gov/articles/PMC9955954/>

[\[3\]](https://www.mdpi.com/1996-1073/16/14/5385#:~:text=power%20distribution%20networks,RL) [\[4\]](https://www.mdpi.com/1996-1073/16/14/5385#:~:text=network%20environments,fairness%2C%20link%20utilization%2C%20and%20throughput) [\[5\]](https://www.mdpi.com/1996-1073/16/14/5385#:~:text=,at%20the%20best%20possible%20level) [\[10\]](https://www.mdpi.com/1996-1073/16/14/5385#:~:text=PPO%3A%20It%20is%20an%20RL,for%20easier%20implementation%20and%20greater) [\[11\]](https://www.mdpi.com/1996-1073/16/14/5385#:~:text=Meanwhile%2C%20we%20found%20that%20the,TIMELY%20is%20unable%20to%20accomplish) [\[12\]](https://www.mdpi.com/1996-1073/16/14/5385#:~:text=To%20solve%20the%20above%20problem%2C,to%20obtain%20the%20superior%20value) [\[13\]](https://www.mdpi.com/1996-1073/16/14/5385#:~:text=network%20traffic%2C%20and%20balance%20the,contributions%20are%20summarized%20as%20follows) ACC-RL: Adaptive Congestion Control Based on Reinforcement Learning in Power Distribution Networks with Data Centers

<https://www.mdpi.com/1996-1073/16/14/5385>

[\[14\]](https://arxiv.org/html/2405.11956v1#:~:text=PET%3A%20Multi,Computer%20Networks%2C%20200%3A108515) PET: Multi-agent Independent PPO-based Automatic ECN Tuning ...

<https://arxiv.org/html/2405.11956v1>