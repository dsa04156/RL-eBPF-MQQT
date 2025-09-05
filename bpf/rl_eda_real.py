#!/usr/bin/env python3
# rl_eda_real.py - 실제 eBPF 데이터 기반 PPO RL-EDA
# 원본 eda.py의 eBPF 수집 + PPO 제어 결합

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

# ====== 환경변수 ======
# RL 모드 설정
RL_MODE = os.getenv("RL_MODE", "train")  # train, inference, collect
MODEL_PATH = os.getenv("MODEL_PATH", "/home/sslab/mqtt-ebpf-edge/models/ppo_mqtt_eda_real")
TOTAL_TIMESTEPS = int(os.getenv("TOTAL_TIMESTEPS", "5000"))

# MQTT 설정 (원본과 동일)
MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "23232"))
CONTROL_TOPIC = os.getenv("CONTROL_TOPIC", "control/room1")
OBSERVE = os.getenv("EDA_OBSERVE", "0") == "1"   # 1이면 관찰 전용

# 기본 임계값들 (원본과 동일)
TH_RTT_US  = int(os.getenv("TH_RTT_US",  "60000"))
TH_RETRANS = int(os.getenv("TH_RETRANS", "1"))
TH_SNDBUF  = int(os.getenv("TH_SNDBUF",  str(256*1024)))
TH_RCVBUF  = int(os.getenv("TH_RCVBUF",  str(256*1024)))

# 히스테리시스 / 홀드타임
HI_RTT_US  = int(os.getenv("HI_RTT_US",  "70000"))
LO_RTT_US  = int(os.getenv("LO_RTT_US",  "50000"))
T_HOLD_ON  = float(os.getenv("T_HOLD_ON",  "0.8"))
T_HOLD_OFF = float(os.getenv("T_HOLD_OFF", "1.5"))

# 평활화
EWMA_ALPHA = float(os.getenv("EWMA_ALPHA", "0.3"))

# sndbuf 사용률 기준
SND_RATIO_HI = float(os.getenv("SND_RATIO_HI", "0.85"))
SND_RATIO_LO = float(os.getenv("SND_RATIO_LO", "0.60"))

# 수집/제어 주기
INTERVAL_S       = float(os.getenv("INTERVAL_S", "2.0"))
CONTROL_MIN_SEC  = float(os.getenv("CONTROL_MIN_SEC", "2.0"))

# 제어 명령 파라미터
CTRL_THROTTLE_RATE = int(os.getenv("CTRL_RATE", "5"))
CTRL_BATCH_SIZE    = int(os.getenv("CTRL_BATCH", "5"))

# 적응형 임계(옵션)
USE_ADAPTIVE = os.getenv("USE_ADAPTIVE", "0") == "1"
ADAPT_WIN    = int(os.getenv("ADAPT_WIN", "200"))
MIN_RTT_HARD = 40_000
MAX_HI_CAP   = 120_000

# eBPF 프로그램 (원본 eda.py와 동일)
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

// ① 재전송 발생 시 누적 카운트 증가
TRACEPOINT_PROBE(tcp, tcp_retransmit_skb) {
    struct sock *sk = (struct sock *)args->skaddr;
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

# 유틸리티 함수들 (원본과 동일)
def ntoa(x):
    try:
        return inet_ntop(AF_INET, struct.pack("!I", x))
    except Exception:
        return inet_ntop(AF_INET, struct.pack("I", x))

def key_to_str(k):
    saddr = ntoa(k[0]); daddr = ntoa(k[1])
    sport = ntohs(k[2]); dport = ntohs(k[3])
    return f"{saddr}:{sport}->{daddr}:{dport}"

def make_mqtt():
    cli = mqtt.Client(client_id="rl-eda-agent")
    cli.connect(MQTT_HOST, MQTT_PORT, 60)
    cli.loop_start()
    return cli

class MQTTeBPFEnv(gym.Env):
    """실제 eBPF 데이터 기반 MQTT 제어 환경"""
    
    def __init__(self):
        super().__init__()
        
        # 상태 공간: [rtt_norm, retrans_flag, sndbuf_ratio, rcvbuf_ratio, last_action]
        self.observation_space = gym.spaces.Box(
            low=0.0, high=1.0, shape=(5,), dtype=np.float32
        )
        
        # 액션 공간: 이산형 3개 모드
        self.action_space = gym.spaces.Discrete(3)
        
        # eBPF 및 MQTT 설정
        print("[INIT] eBPF 프로그램 로딩...")
        self.bpf = BPF(text=BPF_PROGRAM)
        print("[OK] eBPF loaded (MQTT:23232)")
        
        self.mqtt_client = make_mqtt()
        
        # 상태 관리
        self.prev_totals = {}           # flow별 누적 재전송 스냅샷
        self.last_ctrl_ts = 0.0         # 제어 쿨다운
        self.ewma_rtt_us = None
        self.rtt_window = deque(maxlen=ADAPT_WIN)
        self.metrics_history = deque(maxlen=50)
        self.last_action = 0
        self.episode_steps = 0
        self.max_episode_steps = 100
        
        # 베이스라인 메트릭
        self.baseline_rtt_ms = 60.0
        self.baseline_throughput = 250
        
    def reset(self, seed=None, options=None):
        if seed is not None:
            np.random.seed(seed)
            
        # 상태 초기화
        self.prev_totals.clear()
        self.metrics_history.clear()
        self.last_action = 0
        self.episode_steps = 0
        self.ewma_rtt_us = None
        self.rtt_window.clear()
        
        # 초기 관측
        initial_metrics = self._collect_ebpf_metrics()
        self.metrics_history.append(initial_metrics)
        
        return self._get_observation(), {}
    
    def _collect_ebpf_metrics(self):
        """eBPF에서 실제 네트워크 메트릭 수집"""
        now = time.time()
        table = self.bpf.get_table("stats")
        
        snapshot = {}
        rtt_ms_list = []
        had_retrans = False
        max_sndbuf = 0
        max_rcvbuf = 0
        
        for k, v in table.items():
            key = (k.saddr, k.daddr, k.sport, k.dport)
            snapshot[key] = int(v.retrans)
            
            rtt_ms = float(v.srtt_us) / 1000.0
            if rtt_ms > 0:
                rtt_ms_list.append(rtt_ms)
                self.rtt_window.append(int(v.srtt_us))  # int로 변환
            
            if key in self.prev_totals:
                delta_retrans = snapshot[key] - self.prev_totals[key]
                if delta_retrans > 0:
                    had_retrans = True
            
            max_sndbuf = max(max_sndbuf, int(v.sndbuf))  # int로 변환
            max_rcvbuf = max(max_rcvbuf, int(v.rcvbuf))  # int로 변환
        
        self.prev_totals = snapshot.copy()
        
        # EWMA RTT 계산
        avg_rtt_ms = mean(rtt_ms_list) if rtt_ms_list else 0.0
        if avg_rtt_ms > 0:
            if self.ewma_rtt_us is None:
                self.ewma_rtt_us = avg_rtt_ms * 1000
            else:
                self.ewma_rtt_us = (EWMA_ALPHA * avg_rtt_ms * 1000 + 
                                  (1 - EWMA_ALPHA) * self.ewma_rtt_us)
        
        # 버퍼 사용률 계산
        snd_ratio = min(max_sndbuf / TH_SNDBUF, 1.0) if max_sndbuf > 0 else 0.0
        rcv_ratio = min(max_rcvbuf / TH_RCVBUF, 1.0) if max_rcvbuf > 0 else 0.0
        
        # 가상 처리량 계산 (RTT 기반)
        if avg_rtt_ms > 0:
            throughput = self.baseline_throughput * (self.baseline_rtt_ms / avg_rtt_ms)
        else:
            throughput = self.baseline_throughput
        
        return {
            "timestamp": float(now),  # float로 변환
            "avg_rtt_ms": float(avg_rtt_ms),  # float로 변환
            "ewma_rtt_us": float(self.ewma_rtt_us or 0),  # float로 변환
            "had_retrans": bool(had_retrans),  # bool로 변환
            "snd_ratio": float(snd_ratio),  # float로 변환
            "rcv_ratio": float(rcv_ratio),  # float로 변환
            "throughput": float(throughput),  # float로 변환
            "max_sndbuf": int(max_sndbuf),  # int로 명시
            "max_rcvbuf": int(max_rcvbuf),  # int로 명시
            "flow_count": int(len(rtt_ms_list))  # int로 명시
        }
    
    def _get_observation(self):
        if not self.metrics_history:
            return np.array([0.6, 0.0, 0.3, 0.3, 0.0], dtype=np.float32)
        
        recent = self.metrics_history[-1]
        
        # RTT 정규화 (0-200ms → 0-1)
        rtt_norm = min(recent.get('avg_rtt_ms', 60) / 200.0, 1.0)
        
        # 재전송 플래그
        retrans_flag = 1.0 if recent.get('had_retrans', False) else 0.0
        
        # 버퍼 사용률
        sndbuf_ratio = recent.get('snd_ratio', 0.3)
        rcvbuf_ratio = recent.get('rcv_ratio', 0.3)
        
        # 이전 액션 정규화
        last_action_norm = float(self.last_action) / 2.0
        
        return np.array([rtt_norm, retrans_flag, sndbuf_ratio, rcvbuf_ratio, 
                        last_action_norm], dtype=np.float32)
    
    def step(self, action):
        self.episode_steps += 1
        action_idx = int(action)
        
        # 제어 명령 실행 (OBSERVE=0일 때만)
        if not OBSERVE:
            self._execute_control_action(action_idx)
        
        # 다음 측정까지 대기
        time.sleep(INTERVAL_S)
        
        # 새로운 메트릭 수집
        metrics = self._collect_ebpf_metrics()
        self.metrics_history.append(metrics)
        
        # 보상 계산
        reward = self._calculate_reward()
        
        # 에피소드 종료 조건
        done = (self.episode_steps >= self.max_episode_steps or 
                metrics.get('avg_rtt_ms', 0) > 200)  # 200ms 초과시 종료
        
        self.last_action = action_idx
        
        info = {
            "action_name": ["STABLE", "MODERATE", "SEVERE"][action_idx],
            "metrics": metrics,
            "flow_count": metrics.get('flow_count', 0)
        }
        
        return self._get_observation(), reward, done, False, info
    
    def _execute_control_action(self, action_idx):
        """MQTT 제어 명령 발행"""
        now = time.time()
        
        # 쿨다운 체크
        if now - self.last_ctrl_ts < CONTROL_MIN_SEC:
            return
        
        if action_idx == 0:  # Stable - 제어 해제
            cmd = {
                "cmd": "release",
                "defaults": {"rate": -1, "batch": -1, "qos": 1}
            }
        elif action_idx == 1:  # Moderate - 보통 제어
            cmd = {
                "cmd": "throttle",
                "rate": CTRL_THROTTLE_RATE,
                "batch": CTRL_BATCH_SIZE
            }
        else:  # Severe - 강한 제어
            cmd = {
                "cmd": "throttle", 
                "rate": max(1, CTRL_THROTTLE_RATE // 2),
                "batch": CTRL_BATCH_SIZE * 2,
                "qos": 0
            }
        
        try:
            self.mqtt_client.publish(CONTROL_TOPIC, json.dumps(cmd))
            self.last_ctrl_ts = now
            print(f"[CTRL] {['STABLE', 'MODERATE', 'SEVERE'][action_idx]}: {cmd}")
        except Exception as e:
            print(f"[ERROR] MQTT publish failed: {e}")
    
    def _calculate_reward(self):
        if len(self.metrics_history) < 2:
            return 0.0
        
        current = self.metrics_history[-1]
        
        # RTT 기반 보상 (-2 ~ +2)
        current_rtt_ms = current.get('avg_rtt_ms', self.baseline_rtt_ms)
        if current_rtt_ms > 0:
            rtt_reward = -(current_rtt_ms / self.baseline_rtt_ms - 1.0) * 2
        else:
            rtt_reward = 0.0
        
        # 재전송 페널티
        retrans_penalty = -5.0 if current.get('had_retrans', False) else 0.0
        
        # 처리량 보상
        throughput = current.get('throughput', self.baseline_throughput)
        throughput_reward = (throughput / self.baseline_throughput - 1.0) * 2
        
        # 버퍼 사용률 페널티
        max_buffer_ratio = max(current.get('snd_ratio', 0), current.get('rcv_ratio', 0))
        buffer_penalty = -(max_buffer_ratio ** 2) * 2
        
        # 연결 수 보너스 (활성 플로우가 많을수록 좋음)
        flow_bonus = min(current.get('flow_count', 0) / 10.0, 1.0)
        
        total_reward = (
            rtt_reward * 2.0 +
            throughput_reward * 1.5 +
            retrans_penalty * 1.0 +
            buffer_penalty * 0.5 +
            flow_bonus * 0.3
        )
        
        return float(total_reward)
    
    def close(self):
        if hasattr(self, 'mqtt_client'):
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()

class RLEDAAgent:
    """실제 eBPF 기반 PPO 에이전트"""
    
    def __init__(self):
        self.env = MQTTeBPFEnv()
        self.model = None
        self.is_training = (RL_MODE == "train")
        
        # 모델 저장 디렉토리 생성
        os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    
    def train_model(self):
        print(f"[TRAIN] 실제 eBPF PPO 훈련 시작 (timesteps: {TOTAL_TIMESTEPS})")
        
        self.model = PPO(
            "MlpPolicy",
            self.env,
            verbose=1,
            learning_rate=3e-4,
            n_steps=64,       # 실제 환경은 느리므로 작게
            batch_size=16,    # 작은 배치
            n_epochs=4,
            gamma=0.99,
            gae_lambda=0.95,
            clip_range=0.2,
            ent_coef=0.01,
            device="cpu"
        )
        
        # 훈련 실행
        self.model.learn(total_timesteps=TOTAL_TIMESTEPS)
        
        # 모델 저장
        self.model.save(MODEL_PATH)
        print(f"[OK] 모델 저장됨: {MODEL_PATH}")
    
    def load_model(self):
        try:
            self.model = PPO.load(MODEL_PATH)
            print(f"[OK] 모델 로드됨: {MODEL_PATH}")
            return True
        except Exception as e:
            print(f"[ERROR] 모델 로드 실패: {e}")
            return False
    
    def run_inference(self):
        """추론 모드 실행"""
        print("[START] 실제 eBPF 추론 모드")
        
        obs, _ = self.env.reset()
        episode_count = 0
        
        try:
            while True:
                action, _ = self.model.predict(obs, deterministic=True)
                obs, reward, done, _, info = self.env.step(action)
                
                # 로깅
                log_data = {
                    "step": self.env.episode_steps,
                    "action": info["action_name"],
                    "reward": float(reward),
                    "metrics": info["metrics"],
                    "flow_count": info["flow_count"]
                }
                print(json.dumps(log_data))
                
                if done:
                    print(f"[EPISODE] 종료 (step: {self.env.episode_steps})")
                    obs, _ = self.env.reset()
                    episode_count += 1
                    
        except KeyboardInterrupt:
            print("[STOP] 사용자 중단")
        finally:
            self.env.close()
    
    def collect_data(self):
        """데이터 수집 모드 (훈련용 데이터 생성)"""
        print("[COLLECT] 데이터 수집 모드")
        
        obs, _ = self.env.reset()
        
        try:
            for step in range(100):  # 100 스텝 수집
                # 랜덤 액션
                action = self.env.action_space.sample()
                obs, reward, done, _, info = self.env.step(action)
                
                # 데이터 로깅 (타입 변환)
                log_data = {
                    "step": int(step),
                    "action": int(action),
                    "action_name": str(info["action_name"]),
                    "reward": float(reward),
                    "obs": [float(x) for x in obs.tolist()],
                    "metrics": info["metrics"],  # 이미 타입 변환됨
                    "flow_count": int(info["flow_count"])
                }
                print(json.dumps(log_data))
                
                if done:
                    obs, _ = self.env.reset()
                    
        except KeyboardInterrupt:
            print("[STOP] 데이터 수집 중단")
        finally:
            self.env.close()
    
    def run(self):
        if self.is_training:
            self.train_model()
        elif RL_MODE == "collect":
            self.collect_data()
        else:
            if self.load_model():
                self.run_inference()
            else:
                print("[ERROR] 훈련된 모델이 없습니다. train 모드로 실행하세요.")

if __name__ == "__main__":
    print(f"[START] RL-EDA 실제 환경 ({RL_MODE} 모드)")
    
    try:
        agent = RLEDAAgent()
        agent.run()
    except Exception as e:
        print(f"[ERROR] 실행 오류: {e}")
        import traceback
        traceback.print_exc()
    
    print("[END] RL-EDA 종료")
