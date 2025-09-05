#!/usr/bin/env python3
#!/usr/bin/env python3
# rl_eda.py - PPO 기반 RL-EDA (원본 eda.py 기반)
# 실제 eBPF 데이터로 PPO 훈련 및 MQTT 제어

import gymnasium as gym
import numpy as np
import json
import time
import os
import sys
from collections import deque
from statistics import mean
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback

# eBPF 관련 임포트 (원본 eda.py에서)
from bcc import BPF
from socket import inet_ntop, AF_INET, ntohs
import struct
from paho.mqtt import client as mqtt
# 기존 eda.py를 확장하여 rule-based 제어를 PPO로 대체

import gymnasium as gym  # gym -> gymnasium으로 변경
import numpy as np
import torch
import torch.nn as nn
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.env_util import make_vec_env
import json
import time
import os
import sys
from collections import deque
from statistics import mean
from bcc import BPF
from socket import inet_ntop, AF_INET, ntohs
import struct
from paho.mqtt import client as mqtt

# 기존 eda.py의 환경변수들
MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "23232"))
CONTROL_TOPIC = os.getenv("CONTROL_TOPIC", "control/room1")
INTERVAL_S = float(os.getenv("INTERVAL_S", "2.0"))

# RL 관련 환경변수 - VirtualBox 환경 고려
RL_MODE = os.getenv("RL_MODE", "train")  # "train" or "inference"
MODEL_PATH = os.getenv("MODEL_PATH", "/home/sslab/mqtt-ebpf-edge/models/ppo_mqtt_eda")
TOTAL_TIMESTEPS = int(os.getenv("TOTAL_TIMESTEPS", "10000"))  # 작게 시작 (50000 -> 10000)
TRAINING_EPISODES = int(os.getenv("TRAINING_EPISODES", "200"))  # 작게 시작 (1000 -> 200)

# 수정된 BPF 프로그램 - tracepoint 문제 해결
BPF_PROGRAM = r"""
#include <uapi/linux/ptrace.h>
#include <net/sock.h>
#include <net/inet_sock.h>
#include <linux/tcp.h>
#include <linux/skbuff.h>

struct key_t {
    __u32 saddr;
    __u32 daddr;
    __u16 sport;
    __u16 dport;
};

struct val_t {
    __u64 retrans;     // 누적 재전송
    __u32 srtt_us;     // 최근 RTT(마이크로초, 커널 내부*8에서 보정하여 저장)
    __u32 sndbuf;      // 송신 큐 바이트(sk_wmem_queued)
    __u32 rcvbuf;      // 수신 큐 바이트(sk_rmem_alloc)
};

BPF_HASH(stats, struct key_t, struct val_t, 16384);

static __always_inline int is_mqtt_port(__u16 p_be) {
    __u16 p = bpf_ntohs(p_be);
    return p == 23232; // MQTT
}

static __always_inline int fill_key(struct sock *sk, struct key_t *key) {
    struct inet_sock *inet = (struct inet_sock *)sk;
    if (!inet) return 0;
    // MQTT 소켓만 추적
    if (!(is_mqtt_port(inet->inet_sport) || is_mqtt_port(inet->inet_dport))) return 0;

    key->saddr = inet->inet_saddr;
    key->daddr = inet->inet_daddr;
    key->sport = inet->inet_sport; // big-endian 저장
    key->dport = inet->inet_dport;
    return 1;
}

// ① kprobe로 재전송 추적 (tracepoint 대신)
int kprobe__tcp_retransmit_skb(struct pt_regs *ctx, struct sock *sk, struct sk_buff *skb, int segs) {
    if (!sk) return 0;

    struct key_t k = {};
    if (!fill_key(sk, &k)) return 0;

    struct val_t zero = {};
    struct val_t *v = stats.lookup_or_init(&k, &zero);
    if (v) {
        __sync_fetch_and_add(&v->retrans, 1);
    }
    return 0;
}

// ② 송신 호출 시 sndbuf 샘플링
int kprobe__tcp_sendmsg(struct pt_regs *ctx, struct sock *sk, struct msghdr *msg, size_t size) {
    if (!sk) return 0;
    struct key_t k = {};
    if (!fill_key(sk, &k)) return 0;

    __u32 wmem = 0;
    bpf_probe_read_kernel(&wmem, sizeof(wmem), &sk->sk_wmem_queued);

    struct val_t zero = {};
    struct val_t *v = stats.lookup_or_init(&k, &zero);
    if (v) { v->sndbuf = wmem; }
    return 0;
}

// ③ 수신 경로에서 RTT/rcvbuf 샘플링
int kprobe__tcp_rcv_established(struct pt_regs *ctx, struct sock *sk, struct sk_buff *skb,
                                const struct tcphdr *th, unsigned int len) {
    if (!sk) return 0;
    struct key_t k = {};
    if (!fill_key(sk, &k)) return 0;

    struct tcp_sock *tp = (struct tcp_sock *)sk;
    __u32 srtt = 0;
    bpf_probe_read_kernel(&srtt, sizeof(srtt), &tp->srtt_us);
    if (srtt) srtt >>= 3; // 마이크로초(us)

    __u32 rmem = 0;
    bpf_probe_read_kernel(&rmem, sizeof(rmem), &sk->sk_rmem_alloc);

    struct val_t zero = {};
    struct val_t *v = stats.lookup_or_init(&k, &zero);
    if (v) { v->srtt_us = srtt; v->rcvbuf = rmem; }
    return 0;
}
""";

def ntoa(x):
    try:
        return inet_ntop(AF_INET, struct.pack("!I", x))
    except Exception:
        return inet_ntop(AF_INET, struct.pack("I", x))

def key_to_str(k):
    saddr = ntoa(k[0]); daddr = ntoa(k[1])
    sport = ntohs(k[2]); dport = ntohs(k[3])
    return f"{saddr}:{sport}->{daddr}:{dport}"

class MQTTeBPFEnv(gym.Env):
    """MQTT-eBPF 성능 최적화를 위한 강화학습 환경"""
    
    def __init__(self):
        super().__init__()
        
        # 상태 공간: [rtt_norm, retrans_flag, sndbuf_ratio, rcvbuf_ratio, last_action]
        # 문서에 따라 5차원으로 설정
        self.observation_space = gym.spaces.Box(
            low=0.0, high=1.0, shape=(5,), dtype=np.float32
        )
        
        # 액션 공간: 이산형 3개 모드 (문서의 권장사항)
        # 0 = Stable (제어 없음/해제), 1 = Moderate (보통 제어), 2 = Severe (강한 제어)
        self.action_space = gym.spaces.Discrete(3)
        
        # 메트릭 히스토리
        self.metrics_history = deque(maxlen=50)
        self.reward_history = deque(maxlen=20)
        
        # 정규화를 위한 기준값들 (문서 기반)
        self.max_rtt = 100000  # 100ms (us) - 문서에서 기준 RTT로 제시
        self.max_buffer = 256 * 1024  # 256KB - 기존 eda.py의 TH_SNDBUF/RCVBUF
        
        # 베이스라인 성능 (기존 결과 기반)
        self.baseline_rtt_ms = 60.0  # 혼잡 없는 상태의 평균 RTT
        self.baseline_throughput = 250  # msg/s
        
        # 상태 추적
        self.last_action = 0  # 이전 행동 저장
        self.episode_steps = 0
        self.max_episode_steps = 100
        
    def reset(self):
        """환경 리셋"""
        self.metrics_history.clear()
        self.reward_history.clear()
        self.episode_steps = 0
        self.last_action = 0  # Stable 모드로 시작
        return self._get_observation()
    
    def _get_observation(self):
        """현재 상태 관찰 - 문서에 따라 5차원으로 구성"""
        if not self.metrics_history:
            # 초기 중립 상태: [rtt_norm, retrans_flag, sndbuf_ratio, rcvbuf_ratio, last_action]
            return np.array([0.6, 0.0, 0.3, 0.3, 0.0], dtype=np.float32)
        
        recent = self.metrics_history[-1]
        
        # RTT 정규화 (0~1) - 문서: ewma_rtt_us / 100000.0
        rtt_norm = min(recent.get('ewma_rtt_us', 60000) / self.max_rtt, 1.0)
        
        # 재전송 발생 여부 (0 또는 1) - 문서: 1.0 if had_retrans else 0.0
        retrans_flag = 1.0 if recent.get('had_retrans', False) else 0.0
        
        # 버퍼 사용률 (0~1)
        sndbuf_ratio = min(recent.get('snd_ratio', 0.3), 1.0)
        rcvbuf_ratio = min(recent.get('rcv_ratio', 0.3), 1.0)
        
        # 이전 행동 (0,1,2를 float로) - 문서에서 제안한 이전 행동 포함
        last_action_norm = float(self.last_action) / 2.0  # 0,1,2 -> 0,0.5,1
        
        return np.array([rtt_norm, retrans_flag, sndbuf_ratio, rcvbuf_ratio, 
                        last_action_norm], dtype=np.float32)
    
    def step(self, action):
        """액션 실행 및 보상 계산 - 이산형 액션 (0=Stable, 1=Moderate, 2=Severe)"""
        self.episode_steps += 1
        action_idx = int(action)  # 이산형 액션
        
        # 문서에 따른 이산형 액션 매핑
        commands = []
        
        if action_idx == 0:  # Stable (제어 해제)
            commands.append({"cmd": "release", "defaults": {"rate": -1, "batch": -1, "qos": 1}})
            action_name = "STABLE"
            
        elif action_idx == 1:  # Moderate (보통 제어)
            commands.append({"cmd": "throttle", "rate": 5})  # 기본 CTRL_THROTTLE_RATE
            commands.append({"cmd": "batch", "size": 5})     # 기본 CTRL_BATCH_SIZE
            # QoS는 변경하지 않음
            action_name = "MODERATE"
            
        elif action_idx == 2:  # Severe (강한 제어)
            commands.append({"cmd": "throttle", "rate": 1})  # 최대 제한
            commands.append({"cmd": "batch", "size": 10})    # 배치 크기 증가
            commands.append({"cmd": "qos", "level": 0})      # 낮은 QoS
            action_name = "SEVERE"
        
        # 제어 명령 저장
        self.last_commands = commands
        self.last_action = action_idx
        
        # 액션 적용 후 짧은 대기 (시스템 반응 시간)
        time.sleep(0.5)
        
        # 보상 계산
        reward = self._calculate_reward()
        self.reward_history.append(reward)
        
        # 다음 상태
        next_obs = self._get_observation()
        
        # 에피소드 종료 조건
        done = self._is_done()
        
        info = {
            "action_name": action_name,
            "action_idx": action_idx,
            "commands": commands,
            "reward_components": self._get_reward_components(),
            "episode_steps": self.episode_steps
        }
        
        return next_obs, reward, done, info
    
    def _calculate_reward(self):
        """문서 기반 다목적 보상 함수 - 실제 메트릭에 맞게 조정"""
        if len(self.metrics_history) < 2:
            return 0.0
        
        current = self.metrics_history[-1]
        previous = self.metrics_history[-2]
        
        # 1. RTT 기반 보상 (문서: reward_RTT = -(현재 RTT / 기준_RTT))
        current_rtt_ms = current.get('avg_rtt_ms', self.baseline_rtt_ms)
        rtt_reward = -(current_rtt_ms / self.baseline_rtt_ms)  # RTT가 낮을수록 높은 보상
        
        # 2. 재전송/손실 페널티 (문서: 재전송 1회당 -5)
        retrans_penalty = -5.0 if current.get('had_retrans', False) else 0.0
        
        # 3. 처리량 보상 (문서: reward_tp = +(송신량 / 최대가능량))
        # 간접적으로 현재 설정을 기반으로 추정
        estimated_throughput = current.get('throughput', self.baseline_throughput)
        throughput_reward = estimated_throughput / self.baseline_throughput
        
        # 4. 버퍼 압박 페널티
        max_buffer_ratio = max(current.get('snd_ratio', 0), current.get('rcv_ratio', 0))
        buffer_penalty = -(max_buffer_ratio ** 2) * 2  # 제곱으로 급격한 페널티
        
        # 5. 행동 일관성 보상 (너무 잦은 변경 방지)
        action_consistency = 0.1 if self.last_action == current.get('action_idx', 0) else -0.1
        
        # 문서의 가중치 예시: w_tp=1, w_rtt=2, w_loss=5
        total_reward = (
            throughput_reward * 1.0 +      # 처리량 (가중치 1)
            rtt_reward * 2.0 +             # RTT (가중치 2) 
            retrans_penalty * 1.0 +        # 재전송 페널티 (이미 -5로 큰 값)
            buffer_penalty * 0.5 +         # 버퍼 페널티
            action_consistency * 0.2       # 행동 일관성
        )
        
        return float(total_reward)
    
    def _get_reward_components(self):
        """보상 구성 요소 분석용"""
        if len(self.metrics_history) < 2:
            return {}
        
        current = self.metrics_history[-1]
        return {
            "rtt_ms": current.get('avg_rtt_ms', 0),
            "throughput": current.get('throughput', 0),
            "retrans_rate": current.get('retrans_rate', 0),
            "snd_ratio": current.get('snd_ratio', 0),
            "rcv_ratio": current.get('rcv_ratio', 0),
            "episode_steps": self.episode_steps
        }
    
    def _is_done(self):
        """에피소드 종료 조건"""
        # 최대 스텝 수 도달
        if self.episode_steps >= self.max_episode_steps:
            return True
        
        # 성능이 너무 나빠진 경우
        if self.metrics_history:
            current = self.metrics_history[-1]
            if current.get('avg_rtt_ms', 60) > 200:  # 200ms 초과
                return True
            if current.get('throughput', 250) < 50:  # 50 msg/s 미만
                return True
        
        return False
    
    def update_metrics(self, metrics):
        """외부에서 메트릭 업데이트"""
        self.metrics_history.append(metrics)


class RLEDAAgent:
    """PPO 기반 강화학습 EDA 에이전트"""
    
    def __init__(self):
        # eBPF 설정
        self.bpf = BPF(text=BPF_PROGRAM)
        print("[OK] eBPF loaded (MQTT:23232; RL-Enhanced)", flush=True)
        
        # MQTT 클라이언트
        self.mqtt_client = self._setup_mqtt()
        
        # 강화학습 환경
        self.env = MQTTeBPFEnv()
        
        # PPO 모델
        self.model = None
        self.is_training = (RL_MODE == "train")
        
        # 기존 EDA 상태 변수들
        self.prev_totals = {}
        self.last_ctrl_ts = 0.0
        self.ewma_rtt_us = None
        self.rtt_window = deque(maxlen=200)
        
        # 모델 저장 디렉토리 생성
        os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
        
    def _setup_mqtt(self):
        """MQTT 클라이언트 설정"""
        client = mqtt.Client(client_id="rl-eda-agent")
        try:
            client.connect(MQTT_HOST, MQTT_PORT, 60)
            client.loop_start()
            print(f"[OK] MQTT connected to {MQTT_HOST}:{MQTT_PORT}", flush=True)
        except Exception as e:
            print(f"[ERROR] MQTT connection failed: {e}", flush=True)
        return client
    
    def publish_control(self, commands):
        """제어 명령들 발행"""
        try:
            for cmd in commands:
                self.mqtt_client.publish(
                    CONTROL_TOPIC, 
                    payload=json.dumps(cmd), 
                    qos=1
                )
        except Exception as e:
            print(f"[ERROR] MQTT publish failed: {e}", flush=True)
    
    def train_model(self):
        """PPO 모델 훈련"""
        print(f"[TRAIN] PPO 훈련 시작 (timesteps: {TOTAL_TIMESTEPS})", flush=True)
        
        # PPO 모델 생성 - VirtualBox/CPU 환경 최적화
        self.model = PPO(
            "MlpPolicy",
            self.env,
            verbose=1,
            learning_rate=3e-4,
            n_steps=512,        # 작은 배치 (기본 2048 -> 512)
            batch_size=32,      # 작은 배치 크기 (기본 64 -> 32)
            n_epochs=4,         # 적은 epoch (기본 10 -> 4)
            gamma=0.99,
            gae_lambda=0.95,
            clip_range=0.2,
            ent_coef=0.01,
            vf_coef=0.5,
            max_grad_norm=0.5,
            device="cpu",       # 명시적으로 CPU 사용
            tensorboard_log=f"{os.path.dirname(MODEL_PATH)}/tensorboard/"
        )
        
        # 콜백 설정
        callback = TrainingCallback()
        
        # 훈련 실행
        self.model.learn(
            total_timesteps=TOTAL_TIMESTEPS,
            callback=callback
        )
        
        # 모델 저장
        self.model.save(MODEL_PATH)
        print(f"[OK] 모델 저장됨: {MODEL_PATH}", flush=True)
    
    def load_model(self):
        """훈련된 모델 로드"""
        try:
            self.model = PPO.load(MODEL_PATH)
            print(f"[OK] 모델 로드됨: {MODEL_PATH}", flush=True)
            return True
        except Exception as e:
            print(f"[ERROR] 모델 로드 실패: {e}", flush=True)
            return False
    
    def collect_ebpf_metrics(self):
        """eBPF에서 메트릭 수집 - 기존 eda.py 로직 활용"""
        now = time.time()
        table = self.bpf.get_table("stats")
        
        snapshot = {}
        rtt_ms_list = []
        had_retrans = False
        max_sndbuf = 0
        max_rcvbuf = 0
        total_retrans = 0
        
        # 기존 eda.py와 동일한 로직
        for k, v in table.items():
            key = (k.saddr, k.daddr, k.sport, k.dport)
            snapshot[key] = int(v.retrans)
            
            rtt_ms = float(v.srtt_us) / 1000.0
            sndbuf = int(v.sndbuf)
            rcvbuf = int(v.rcvbuf)
            retrans_total = int(v.retrans)
            retrans_delta = max(0, retrans_total - self.prev_totals.get(key, 0))
            
            rtt_ms_list.append(rtt_ms)
            if retrans_delta > 0:
                had_retrans = True
                total_retrans += retrans_delta
            if sndbuf > max_sndbuf: max_sndbuf = sndbuf
            if rcvbuf > max_rcvbuf: max_rcvbuf = rcvbuf
            
            # 기존 eda.py처럼 개별 플로우 로그
            line = {
                "ts": now,
                "flow": key_to_str(key),
                "interval_s": INTERVAL_S,
                "rtt_ms": round(rtt_ms, 2),
                "retrans_delta": retrans_delta,
                "sndbuf": sndbuf,
                "rcvbuf": rcvbuf
            }
            print(json.dumps(line), flush=True)
        
        # EWMA RTT 계산 (기존 eda.py 로직)
        if rtt_ms_list:
            avg_rtt_ms = mean(rtt_ms_list)
            cur_rtt_us = int(avg_rtt_ms * 1000)
            
            if self.ewma_rtt_us is None:
                self.ewma_rtt_us = cur_rtt_us
            else:
                # 기존 eda.py의 EWMA_ALPHA = 0.3 사용
                self.ewma_rtt_us = int(self.ewma_rtt_us + 0.3 * (cur_rtt_us - self.ewma_rtt_us))
        else:
            avg_rtt_ms = self.baseline_rtt_ms
            cur_rtt_us = int(avg_rtt_ms * 1000)
        
        # 처리량 추정 (기존 eda.py는 직접 측정하지 않으므로 간접 추정)
        num_flows = len(rtt_ms_list)
        # RTT가 낮고 플로우가 많을수록 높은 처리량으로 추정
        estimated_throughput = max(50, num_flows * 100 / max(1, avg_rtt_ms / 30))
        
        # 버퍼 사용률 (기존 eda.py 임계값 사용)
        TH_SNDBUF = 256 * 1024  # 기존 eda.py 기본값
        TH_RCVBUF = 256 * 1024
        snd_ratio = max_sndbuf / max(1, TH_SNDBUF)
        rcv_ratio = max_rcvbuf / max(1, TH_RCVBUF)
        
        metrics = {
            "timestamp": now,
            "avg_rtt_ms": avg_rtt_ms,
            "ewma_rtt_us": self.ewma_rtt_us,
            "had_retrans": had_retrans,
            "total_retrans": total_retrans,
            "max_sndbuf": max_sndbuf,
            "max_rcvbuf": max_rcvbuf,
            "snd_ratio": snd_ratio,
            "rcv_ratio": rcv_ratio,
            "throughput": estimated_throughput,
            "num_flows": num_flows
        }
        
        self.prev_totals = snapshot
        return metrics
    
    def run(self):
        """메인 실행 루프"""
        print(f"[START] RL-EDA Agent ({RL_MODE} mode)", flush=True)
        
        if self.is_training:
            # 훈련 모드
            self.train_model()
            return
        else:
            # 추론 모드
            if not self.load_model():
                print("[ERROR] 모델 로드 실패. 훈련된 모델이 필요합니다.", flush=True)
                return
        
        # 환경 초기화
        obs = self.env.reset()
        episode_count = 0
        step_count = 0
        
        print("[START] 추론 모드 실행", flush=True)
        
        while True:
            try:
                time.sleep(INTERVAL_S)
                
                # eBPF에서 메트릭 수집
                metrics = self.collect_ebpf_metrics()
                
                # 환경에 메트릭 업데이트
                self.env.update_metrics(metrics)
                
                # PPO 모델로 액션 예측
                action, _states = self.model.predict(obs, deterministic=True)
                
                # 액션 실행
                obs, reward, done, info = self.env.step(action)
                
                # 제어 명령 발행
                if hasattr(self.env, 'last_commands'):
                    self.publish_control(self.env.last_commands)
                
                # 로깅
                log_data = {
                    "timestamp": time.time(),
                    "episode": episode_count,
                    "step": step_count,
                    "action": action.tolist(),
                    "reward": float(reward),
                    "metrics": metrics,
                    "control_info": info,
                    "observation": obs.tolist()
                }
                
                print(json.dumps(log_data), flush=True)
                
                step_count += 1
                
                # 에피소드 종료 처리
                if done:
                    print(f"[EPISODE] {episode_count} 종료 (steps: {step_count})", flush=True)
                    obs = self.env.reset()
                    episode_count += 1
                    step_count = 0
                
            except KeyboardInterrupt:
                print("[STOP] 사용자 종료", flush=True)
                break
            except Exception as e:
                print(f"[ERROR] 실행 중 오류: {e}", flush=True)
                time.sleep(5)  # 오류 후 잠시 대기


class TrainingCallback(BaseCallback):
    """훈련 진행 상황 모니터링"""
    
    def __init__(self):
        super().__init__()
        self.episode_rewards = []
        self.episode_lengths = []
        
    def _on_step(self) -> bool:
        # 에피소드 완료시 통계 저장
        if self.locals.get('dones', [False])[0]:
            episode_reward = self.locals.get('episode_rewards', [0])[0]
            episode_length = self.locals.get('episode_lengths', [0])[0]
            
            self.episode_rewards.append(episode_reward)
            self.episode_lengths.append(episode_length)
            
            # 최근 10 에피소드 평균
            if len(self.episode_rewards) >= 10:
                avg_reward = np.mean(self.episode_rewards[-10:])
                avg_length = np.mean(self.episode_lengths[-10:])
                
                print(f"[TRAIN] Episode {len(self.episode_rewards)}: "
                      f"Avg Reward: {avg_reward:.3f}, Avg Length: {avg_length:.1f}")
        
        return True


if __name__ == "__main__":
    try:
        agent = RLEDAAgent()
        agent.run()
    except KeyboardInterrupt:
        print("\n[EXIT] 프로그램 종료")
        sys.exit(0)
    except Exception as e:
        print(f"[FATAL] {e}")
        sys.exit(1)
