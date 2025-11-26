#!/usr/bin/env python3
# eda_rl.py — eBPF 커널 신호 + RL 섀도우/온라인 제어 에이전트
# - Subscriber가 보내는 eda/latency(p50/p95/p99, n, window_sec)를 수신해 보상 계산
# - Publisher 제어 토픽(control/room1)에 throttle/batch/qos 명령 발행
# - RL_MODE=shadow: 행동은 적용하지 않고 (s,a,r,s')만 로깅
# - RL_MODE=online : 에이전트 행동을 쉴드로 클램프 후 실제 적용
#
# 필요 패키지: bcc, paho-mqtt, (옵션)torch

# PyTorch + eBPF 호환성을 위한 환경 최적화 (Intel/Netflix 방식)
import os
os.environ['PYTORCH_DISABLE_CUDA_MALLOC_CACHE'] = '1'
os.environ['OMP_NUM_THREADS'] = '1'
os.environ['MKL_NUM_THREADS'] = '1'
os.environ['NUMEXPR_NUM_THREADS'] = '1'
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['CUDA_VISIBLE_DEVICES'] = ''
os.environ['KMP_AFFINITY'] = 'granularity=fine,compact,1,0'
os.environ['KMP_BLOCKTIME'] = '1'

import sys, time, json, struct, math
from typing import Optional, Tuple

import numpy as np

try:
    import gymnasium as gym
    from gymnasium import spaces
except Exception:  # gymnasium is optional for legacy deployments
    gym = None
    spaces = None
from socket import inet_ntop, AF_INET, ntohs
from statistics import mean
from collections import deque
from pathlib import Path

from bcc import BPF
from paho.mqtt import client as mqtt
import threading
# =========================
# 환경변수
# =========================
MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "23232"))
DATA_TOPIC  = os.getenv("SUB_TOPIC", "bench/foo1")       # 추적 포트/필터와 일치용
METRICS_TOPIC = os.getenv("METRICS_TOPIC", "eda/latency") # subscriber 보고 토픽
CONTROL_TOPIC = os.getenv("CONTROL_TOPIC", "control/room1")

# RL
EDA_RL   = os.getenv("EDA_RL", "1") == "1"
RL_MODE  = os.getenv("RL_MODE", "shadow")  # 'shadow' | 'online'
RL_LOG_PATH = os.getenv("RL_LOG_PATH", "./logs/eda_rl.jsonl")
SLO_P99_MS  = float(os.getenv("SLO_P99_MS", "10000"))  # 예: 10초
USE_APP_METRICS = os.getenv("USE_APP_METRICS", "0") == "1"
THROUGHPUT_TARGET = float(os.getenv("THROUGHPUT_TARGET", "45.0"))
THROUGHPUT_BONUS_WEIGHT = float(os.getenv("THROUGHPUT_BONUS_WEIGHT", "0.0"))
THROUGHPUT_PENALTY_WEIGHT = float(os.getenv("THROUGHPUT_PENALTY_WEIGHT", "1.2"))
# 감속 폭 비대칭 캡(음수쪽 최대 스텝 비율)
MAX_DECEL_FRAC = float(os.getenv("MAX_DECEL_FRAC", os.getenv("MAX_STEP_FRAC", "0.2")))
# 처리량 하한 가드(이 값 미만이면 감속 금지)
THROUGHPUT_MIN_FLOOR = float(os.getenv("THROUGHPUT_MIN_FLOOR", "0.0"))
# 연속 감속 홀드(음수 조치 후 추가 감속까지 최소 대기 초)
DECEL_HOLD_SEC = float(os.getenv("DECEL_HOLD_SEC", "1.0"))
# 감속 이후 p99 안정화 대기 조건
DECEL_P99_WAIT_DROP_FRAC = float(os.getenv("DECEL_P99_WAIT_DROP_FRAC", "0.15"))  # 직전 대비 최소 하락 비율
DECEL_P99_WAIT_ABS_MS = float(os.getenv("DECEL_P99_WAIT_ABS_MS", "0"))          # 절대 임계(0이면 비활성)
# 저처리량 회복 모드(throughput이 바닥을 크게 하회할 때 가속 바이어스)
RECOVERY_THR_FLOOR = float(os.getenv("RECOVERY_THR_FLOOR", "0.0"))
RECOVERY_MAX_PUSH = float(os.getenv("RECOVERY_MAX_PUSH", "0.10"))  # d_rate 상향 한계
ACTION_HOLD_SEC = float(os.getenv("ACTION_HOLD_SEC", "0.0"))
# 절대 처리량 보너스(타깃 비율 외에 순수 msg/s에 대한 보너스)
THROUGHPUT_ABS_WEIGHT = float(os.getenv("THROUGHPUT_ABS_WEIGHT", "0.3"))
THROUGHPUT_ABS_SCALE  = float(os.getenv("THROUGHPUT_ABS_SCALE",  "100.0"))  # msg/s 기준 스케일
P99_PENALTY_WEIGHT = float(os.getenv("P99_PENALTY_WEIGHT", "6.0"))
ACCEL_P99_GUARD_FRAC = float(os.getenv("ACCEL_P99_GUARD_FRAC", "0.05"))
P99_TREND_MIN_MS = float(os.getenv("P99_TREND_MIN_MS", "5000"))
HARD_DECEL_FRAC = float(os.getenv("HARD_DECEL_FRAC", "0.2"))
P99_ACCEL_BLOCK_MS = float(os.getenv("P99_ACCEL_BLOCK_MS", "5000"))
P99_ACCEL_BLOCK_COUNT = int(os.getenv("P99_ACCEL_BLOCK_COUNT", "3"))
P99_SUSTAIN_DECEL_FRAC = float(os.getenv("P99_SUSTAIN_DECEL_FRAC", "0.05"))
P99_STOP_MS = float(os.getenv("P99_STOP_MS", "20000"))
P99_STOP_COUNT = int(os.getenv("P99_STOP_COUNT", "3"))
P99_STOP_RELEASE_MS = float(os.getenv("P99_STOP_RELEASE_MS", "5000"))

# eBPF 집계/임계/평활
INTERVAL_S  = float(os.getenv("INTERVAL_S", "2.0"))
EWMA_ALPHA  = float(os.getenv("EWMA_ALPHA", "0.3"))
HI_RTT_US   = int(os.getenv("HI_RTT_US",  "70000"))
LO_RTT_US   = int(os.getenv("LO_RTT_US",  "50000"))
TH_RETRANS  = int(os.getenv("TH_RETRANS", "1"))
TH_SNDBUF   = int(os.getenv("TH_SNDBUF",  str(256*1024)))
TH_RCVBUF   = int(os.getenv("TH_RCVBUF",  str(256*1024)))
SND_RATIO_HI= float(os.getenv("SND_RATIO_HI","0.85"))
SND_RATIO_LO= float(os.getenv("SND_RATIO_LO","0.60"))

T_HOLD_ON   = float(os.getenv("T_HOLD_ON",  "0.8"))
T_HOLD_OFF  = float(os.getenv("T_HOLD_OFF", "1.5"))

# 제어/쉴드 파라미터
CONTROL_MIN_SEC = float(os.getenv("CONTROL_MIN_SEC", "2.0"))
INIT_RATE   = int(os.getenv("INIT_RATE", os.getenv("CTRL_RATE","10")))
INIT_BATCH  = int(os.getenv("INIT_BATCH", os.getenv("CTRL_BATCH","1")))
INIT_QOS    = int(os.getenv("INIT_QOS", os.getenv("QOS","1")))

R_MIN = int(os.getenv("R_MIN", "1"))
R_MAX = int(os.getenv("R_MAX", "2000"))
B_MIN = int(os.getenv("B_MIN", "1"))
B_MAX = int(os.getenv("B_MAX", "32"))
MAX_STEP_FRAC = float(os.getenv("MAX_STEP_FRAC", "0.2"))  # |Δrate| <= 20%
COOLDOWN_SEC  = float(os.getenv("COOLDOWN_SEC", "3.0"))

# MQTT 관찰 포트 (eBPF 필터에 주입)
TRACK_PORT = int(os.getenv("MQTT_TRACK_PORT", str(MQTT_PORT)))

# 옵션: Torch 에이전트 경로
RL_BACKEND  = os.getenv("RL_BACKEND", "rule")  # 'rule' | 'torch'
RL_MODEL_PATH = os.getenv("RL_MODEL_PATH", "")

# eBPF 스킵 옵션
SKIP_EBPF = os.getenv("SKIP_EBPF", "0") == "1"

# MQTT 스킵 옵션 (디버깅용)
SKIP_MQTT = os.getenv("SKIP_MQTT", "0") == "1"

# =========================
# (Optional) Online hyper-parameter tuner (contextual bandit)
# =========================
TUNER_ENABLE = os.getenv("TUNER_ENABLE", "0") == "1"
TUNER_EVAL_SEC = float(os.getenv("TUNER_EVAL_SEC", "90"))  # window length to evaluate an arm
TUNER_EPS = float(os.getenv("TUNER_EPS", "0.1"))          # epsilon-greedy exploration

def _parse_float_list(env_name: str, default_csv: str):
    txt = os.getenv(env_name, default_csv)
    out = []
    for t in str(txt).split(','):
        t = t.strip()
        if not t:
            continue
        try:
            out.append(float(t))
        except Exception:
            pass
    return out or [float(x) for x in default_csv.split(',')]

# Candidate grids (kept small for safety)
TUNER_CANDS_BONUS   = _parse_float_list("TUNER_CANDS_BONUS",   "1.8,2.2,2.6,3.0")
TUNER_CANDS_PENALTY = _parse_float_list("TUNER_CANDS_PENALTY", "0.4,0.5,0.6")
TUNER_CANDS_ABS_W   = _parse_float_list("TUNER_CANDS_ABS_W",   "0.6,0.8,1.0")
TUNER_CANDS_ABS_S   = _parse_float_list("TUNER_CANDS_ABS_S",   "80,100,120")
TUNER_CANDS_DECEL   = _parse_float_list("TUNER_CANDS_DECEL",   "0.06,0.08,0.10,0.12")
TUNER_CANDS_HOLD    = _parse_float_list("TUNER_CANDS_HOLD",    "5,10,15")
TUNER_CANDS_FLOOR   = _parse_float_list("TUNER_CANDS_FLOOR",   "120,140,160")

def _to_bool_env(val: str) -> bool:
    return str(val).lower() not in ("0", "false", "no", "off", "")

EDA_RL_VERBOSE = _to_bool_env(os.getenv("EDA_RL_VERBOSE", "0"))

def _emit(*args, **kwargs):
    if not EDA_RL_VERBOSE:
        return
    if "flush" not in kwargs:
        kwargs["flush"] = True
    print(*args, **kwargs)

def _tuner_param_grid():
    combos = []
    for bw in TUNER_CANDS_BONUS:
        for pw in TUNER_CANDS_PENALTY:
            for aw in TUNER_CANDS_ABS_W:
                for ascale in TUNER_CANDS_ABS_S:
                    for dcap in TUNER_CANDS_DECEL:
                        for hold in TUNER_CANDS_HOLD:
                            for floor in TUNER_CANDS_FLOOR:
                                combos.append((bw, pw, aw, ascale, dcap, hold, floor))
    # keep grid reasonable
    return combos[:256]

# =========================
# eBPF 프로그램 (MQTT 포트 필터)
# =========================
BPF_PROGRAM = """
#include <linux/version.h>
#include <uapi/linux/ptrace.h>
#include <linux/tcp.h>
#include <linux/skbuff.h>
#include <net/sock.h>
#include <linux/in.h>   // AF_INET

struct key_t {
    __u32 saddr;   // host order
    __u32 daddr;   // host order
    __u16 sport;   // host order
    __u16 dport;   // big-endian
};

struct val_t {
    __u64 retrans;
    __u32 srtt_us;
    __u32 sndbuf;
    __u32 rcvbuf;
    __u32 retrans_out;  // 현재 재전송 대기 큐 크기
};

BPF_HASH(stats, struct key_t, struct val_t, 16384);

static __always_inline int is_mqtt_port_be(__u16 p_be) {
    __u16 p = bpf_ntohs(p_be);
    return p == /*TRACK_PORT*/ __TRACK_PORT__;
}

static __always_inline int fill_key(struct sock *sk, struct key_t *key) {
    // __sk_common을 통해 안전하게 읽기
    struct sock_common *skc = (struct sock_common *)&sk->__sk_common;

    __u16 family = 0;
    bpf_probe_read_kernel(&family, sizeof(family), &skc->skc_family);
    if (family != AF_INET) return 0;

    __u16 sport_host = 0;
    __be16 dport_be  = 0;
    __u32 saddr_host = 0;
    __u32 daddr_host = 0;

    bpf_probe_read_kernel(&sport_host,  sizeof(sport_host),  &skc->skc_num);         // host
    bpf_probe_read_kernel(&dport_be,    sizeof(dport_be),    &skc->skc_dport);       // be16
    bpf_probe_read_kernel(&saddr_host,  sizeof(saddr_host),  &skc->skc_rcv_saddr);   // host
    bpf_probe_read_kernel(&daddr_host,  sizeof(daddr_host),  &skc->skc_daddr);       // host

    if (!(is_mqtt_port_be(bpf_htons(sport_host)) || is_mqtt_port_be(dport_be))) return 0;

    key->saddr = saddr_host;
    key->daddr = daddr_host;
    key->sport = sport_host;  // host order
    key->dport = dport_be;    // big-endian
    return 1;
}

TRACEPOINT_PROBE(tcp, tcp_retransmit_skb) {
    struct sock *sk = (struct sock *)args->skaddr;
    if (!sk) return 0;
    struct key_t k = {};
    if (!fill_key(sk, &k)) return 0;
    struct val_t zero = {};
    struct val_t *v = stats.lookup_or_init(&k, &zero);
    if (v) { __sync_fetch_and_add(&v->retrans, 1); }
    return 0;
}

int on_tcp_sendmsg(struct pt_regs *ctx, struct sock *sk, struct msghdr *msg, size_t size) {
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

int on_tcp_rcv_established(struct pt_regs *ctx, struct sock *sk) {
    if (!sk) return 0;
    struct key_t k = {};
    if (!fill_key(sk, &k)) return 0;
    struct tcp_sock *tp = (struct tcp_sock *)sk;
    __u32 srtt = 0;
    bpf_probe_read_kernel(&srtt, sizeof(srtt), &tp->srtt_us);
    if (srtt) srtt >>= 3;
    __u32 rmem = 0;
    bpf_probe_read_kernel(&rmem, sizeof(rmem), &sk->sk_rmem_alloc);
    __u32 retrans_out = 0;
    bpf_probe_read_kernel(&retrans_out, sizeof(retrans_out), &tp->retrans_out);
    struct val_t zero = {};
    struct val_t *v = stats.lookup_or_init(&k, &zero);
    if (v) { v->srtt_us = srtt; v->rcvbuf = rmem; v->retrans_out = retrans_out; }
    return 0;
}
"""


# =========================
# MQTT & 메트릭 수신
# =========================
LATEST_METRICS = {"ts": None, "n": None, "window_sec": None, "p50_ms": None, "p95_ms": None, "p99_ms": None, "mean_ms": None, "total_msgs": None}

METRICS_BUFFER = []
METRICS_LOCK = threading.Lock()
def on_metrics(cli, userdata, msg):
    try:
        payload = json.loads(msg.payload)
        # 락을 걸고 리스트에 보고서 추가
        with METRICS_LOCK:
            METRICS_BUFFER.append(payload)
    except Exception as e:
        # 에러 로그가 너무 많이 뜨면 주석 처리 가능
        pass

# 전역 변수 선언 (파일 상단 METRICS_BUFFER 근처에 두세요)
LAST_AGG_TIME = time.time()

def get_aggregated_metrics_and_clear():
    global LAST_AGG_TIME
    
    with METRICS_LOCK:
        if not METRICS_BUFFER:
            # 버퍼가 비었어도 시간은 갱신 (흐름 유지)
            LAST_AGG_TIME = time.time()
            return None

        # 집계 변수 초기화
        max_p99 = 0.0
        max_p95 = 0.0
        max_p50 = 0.0
        total_n = 0.0
        
        # 버퍼 순회 및 집계
        for m in METRICS_BUFFER:
            p99 = float(m.get("p99_ms", 0.0))
            if p99 > max_p99: max_p99 = p99

            p95 = float(m.get("p95_ms", 0.0))
            if p95 > max_p95: max_p95 = p95

            p50 = float(m.get("p50_ms", 0.0))
            if p50 > max_p50: max_p50 = p50

            # 전체 처리량 합산 (모든 Subscriber가 처리한 양)
            total_n += float(m.get("n", 0.0))

        count = len(METRICS_BUFFER)
        METRICS_BUFFER.clear()

        # [핵심 추가] 실제 경과 시간 기반 Throughput (msg/s) 계산
        now = time.time()
        delta_time = now - LAST_AGG_TIME
        if delta_time <= 0.001: delta_time = 1.0 # 0 나누기 방지
        
        # 초당 처리량 = (총 처리 개수) / (지난번 집계 후 경과 시간)
        calculated_thr = total_n / delta_time
        
        # 시간 갱신
        LAST_AGG_TIME = now

        return {
            "p99_ms": max_p99,
            "p95_ms": max_p95,
            "p50_ms": max_p50,
            "n": total_n,           # 이번 구간 총 처리 개수
            "thr": calculated_thr,  # [추가됨] 정확한 msg/s
            "window_sec": delta_time, 
            "cnt": count
        }

def make_mqtt():
    if SKIP_MQTT:
        _emit("[SKIP] MQTT client disabled")
        return None
    try:
        # paho-mqtt 2.0+ 호환
        cli = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="eda-rl-agent")
    except (AttributeError, TypeError):
    # paho-mqtt 1.x 호환
        cli = mqtt.Client(client_id="eda-rl-agent")
    cli.connect(MQTT_HOST, MQTT_PORT, 60)
    cli.loop_start()
    cli.message_callback_add(METRICS_TOPIC, on_metrics)
    cli.subscribe(METRICS_TOPIC, qos=0)
    return cli

# =========================
# 유틸/상태·보상·로깅
# =========================
def ntoa_hostorder(x: int) -> str:
    # host-order 32bit를 그대로 리틀엔디언 패킹
    return inet_ntop(AF_INET, struct.pack("<I", x))

def key_to_str(k):
    saddr = ntoa_hostorder(k[0]); daddr = ntoa_hostorder(k[1])
    sport = int(k[2])        # host order 그대로
    dport = ntohs(k[3])      # big-endian 저장 → ntohs로 보정
    return f"{saddr}:{sport}->{daddr}:{dport}"

def clamp(x, lo, hi): return max(lo, min(hi, x))

def compute_queue_pressure(snd_ratio: float, rcv_ratio: float) -> float:
    import math
    # tanh로 0~1 스케일링 (ratio가 2 이상이면 거의 1 근처)
    return math.tanh(max(snd_ratio, rcv_ratio) / 2.0)


def make_state(ewma_rtt_us, snd_ratio, rcv_ratio, had_retrans, queue_pressure,
               current_rate, current_batch, last_action, metrics=None):
    # 간단 정규화
    # rtt_norm  = clamp((ewma_rtt_us or 0)/100_000.0, 0.0, 5.0)
    rtt_norm = min( (ewma_rtt_us or 0) / (SLO_P99_MS*1000.0), 10.0)
    import math

    # s_norm    = clamp(snd_ratio, 0.0, 5.0)
    # r_norm    = clamp(rcv_ratio, 0.0, 5.0)
    s_norm = min(snd_ratio, 5.0) / 5.0  # 0~1.0 범위로 정규화하되, 5배까지 허용
    r_norm = min(rcv_ratio, 5.0) / 5.0
    retr_norm = 1.0 if had_retrans else 0.0
    cong_norm = clamp(queue_pressure, 0.0, 1.0)
    rate_norm = clamp(current_rate/float(R_MAX), 0.0, 1.0)
    batch_norm= clamp(current_batch/float(B_MAX), 0.0, 1.0)
    drate     = clamp(last_action.get("d_rate", 0.0), -1.0, 1.0)
    # dbatch    = clamp(last_action.get("d_batch", 0), -3, 3)/3.0
    dbatch = 0.0 # Force batch size to be fixed (simplify learning)

    return [rtt_norm, s_norm, r_norm, retr_norm, cong_norm, rate_norm, batch_norm, drate, dbatch]

def compute_throughput(metrics):
    # AGG에서 thr를 넘겨주면 그걸 우선 사용
    if isinstance(metrics, dict):
        if "thr" in metrics and metrics["thr"] is not None:
            return float(metrics["thr"])
    n = metrics.get("n"); win = metrics.get("window_sec")
    if n is None or not win or win <= 0:
        return None
    return float(n)/float(win)



def compute_reward(
    metrics,
    *,
    ewma_rtt_us,
    snd_ratio,
    rcv_ratio,
    queue_pressure,
    had_retrans,
    retrans_count,
    current_rate,
    SLO_p99_ms,  # 시그니처 맞추기용, 내부에서 안 씀
):
    """
    New Reward Policy: Throughput Maximization with Kernel Constraints
    - Goal: Maximize throughput
    - Constraints: Strong penalty for retrans/queue explosion/high RTT
    - P99 is NOT used in reward (only for evaluation/shield)
    """
    import math

    if not isinstance(metrics, dict):
        return 0.0

    # 1) Throughput term (The Protagonist)
    thr = compute_throughput(metrics) or 0.0
    # Reference throughput (approx. normal level)
    # If THROUGHPUT_TARGET is not defined, default to 1500
    target = 1500.0
    if 'THROUGHPUT_TARGET' in globals():
        target = max(globals()['THROUGHPUT_TARGET'], 1.0)
    
    # 1) Throughput term (Main Objective)
    # Logarithmic reward: incentivizes increase but prevents infinite growth
    w_thr = 20.0
    if 'THROUGHPUT_ABS_WEIGHT' in globals():
         w_thr = max(globals()['THROUGHPUT_ABS_WEIGHT'], 1.0)

    thr_ref = target
    r_thr = w_thr * math.log1p(thr / thr_ref)

    # 2) Latency Penalty (Conditional)
    # Only penalize P99 if we have reached the target throughput (1500)
    # This encourages the agent to rush to 1500 first.
    p99 = float(metrics.get("p99_ms") or 0.0)
    if SLO_p99_ms <= 0: SLO_p99_ms = 1.0
    
    r_lat = 0.0
    if thr >= thr_ref:
        # Strict penalty if target reached
        over_slo = max(0.0, p99 - SLO_p99_ms) / SLO_p99_ms
        r_lat = -10.0 * over_slo
    else:
        # Safety net: Penalize if P99 explodes (> 1000ms) even before target
        # This prevents the agent from destroying the network while chasing throughput
        SAFETY_P99_MS = 1000.0
        if p99 > SAFETY_P99_MS:
             over_safety = (p99 - SAFETY_P99_MS) / SAFETY_P99_MS
             r_lat = -10.0 * over_safety

    # 3) Kernel Signals (Safety Net)
    # Only penalize if buffer is actually overflowing (> 1.0)
    r_loss = 0.0 # Loss penalty removed as requested
    r_q = -20.0 * max(snd_ratio - 1.0, 0.0)
    r_rtt = 0.0

    reward = r_thr + r_lat + r_q
    return float(reward)

def log_transition(path, rec):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
# =========================
# 에이전트/쉴드
# =========================
class Shield:
    def __init__(self, r_min, r_max, b_min, b_max, max_step_frac, cooldown, max_decel_frac=None, decel_hold_sec=0.0):
        self.r_min, self.r_max = r_min, r_max
        self.b_min, self.b_max = b_min, b_max
        self.max_step_frac = max_step_frac
        self.cooldown = cooldown
        self.max_decel_frac = max_decel_frac if max_decel_frac is not None else max_step_frac
        self.last_ts = 0.0
        self.decel_hold_sec = float(decel_hold_sec or 0.0)
        self.last_dec_ts = 0.0
    def clamp(self, now, current_rate, current_batch, d_rate_frac, d_batch):
        # 쿨다운
        can_apply = (now - self.last_ts) >= self.cooldown
        # p99_now = None
        # try:
        #     # 전역 변수 LATEST_METRICS에서 현재 지연 시간 확인
        #     metrics = LATEST_METRICS 
        #     p99_now = metrics.get("p99_ms")
        # except:
        #     pass
        # # rate 스텝 제한(음수/양수 비대칭) + 최소 변화(정수 반올림 보정)
        
        # # 목표치(SLO_P99_MS)는 전역변수 사용 (예: 300ms)
        # if p99_now is not None and p99_now > SLO_P99_MS:
        #     # 상황 1: 심각함 (목표치의 2배 초과) -> 강제로 10% 감속
        #     if p99_now > SLO_P99_MS * 2.0:
        #         d_rate_frac = -0.1
        #         if d_batch > 0: d_batch = -1 # 배치도 못 늘리게
        #     # 상황 2: 목표치 초과 -> 강제로 5% 감속 (가속하려 했다면 무시됨)
        #     else:
        #         d_rate_frac = -0.05
        #         if d_batch > 0: d_batch = 0
        lo = -float(self.max_decel_frac)
        hi = float(self.max_step_frac)
        d_rate_frac = clamp(d_rate_frac, lo, hi)
        raw_rate = current_rate * (1.0 + d_rate_frac)
        if d_rate_frac < 0.0:
            new_rate = math.floor(raw_rate)
            if new_rate >= current_rate:
                new_rate = current_rate - 1
        elif d_rate_frac > 0.0:
            new_rate = math.ceil(raw_rate)
            if new_rate <= current_rate:
                new_rate = current_rate + 1
        else:
            new_rate = current_rate
        new_rate = clamp(new_rate, self.r_min, self.r_max)

        # batch도 최소 ±1 스텝 반영
        if d_batch > 0:
            new_batch = current_batch + max(1, d_batch)
        elif d_batch < 0:
            # [수정] 배치가 이미 최솟값인데 더 줄이려고 하면 -> 대신 Rate를 줄여준다 (혼잡 완화 유도)
            if current_batch <= self.b_min:
                # 배치는 그대로 두고, Rate를 강제 감속 (기존 d_rate보다 더 강력하게)
                new_batch = current_batch
                # d_rate가 이미 음수라면 그대로 두고, 양수라면 음수로 뒤집거나 -0.1 정도 추가 감속
                if d_rate_frac > 0:
                    d_rate_frac = -0.1
                else:
                    d_rate_frac -= 0.1
                
                # 재계산된 d_rate_frac으로 new_rate 다시 계산
                raw_rate = current_rate * (1.0 + d_rate_frac)
                new_rate = math.floor(raw_rate)
                if new_rate >= current_rate:
                    new_rate = current_rate - 1
                new_rate = clamp(new_rate, self.r_min, self.r_max)
            else:
                new_batch = current_batch + min(-1, d_batch)
        else:
            new_batch = current_batch
        new_batch = clamp(new_batch, self.b_min, self.b_max)

        # 연속 감속 홀드: 직전 감속 이후 최소 대기시간을 만족해야 추가 감속 허용
        decel_ok = True
        if d_rate_frac < 0.0 and self.decel_hold_sec > 0.0:
            decel_ok = (now - self.last_dec_ts) >= self.decel_hold_sec

        changed = (new_rate != current_rate) or (new_batch != current_batch)
        if can_apply and changed and decel_ok:
            self.last_ts = now
            if d_rate_frac < 0.0:
                self.last_dec_ts = now
        return (can_apply and changed and decel_ok), new_rate, new_batch

class RuleAgent:
    # 연속 지표를 활용해 완만하게 제어. RL은 이 분포를 학습해 자체 임계값을 찾는다.
    def act(self, state, ewma_rtt_us=None, snd_ratio=None, had_retrans=None):
        import math

        rtt_norm = clamp(state[0], 0.0, 10.0)
        snd_norm = clamp(state[1], 0.0, 1.0)
        rcv_norm = clamp(state[2], 0.0, 1.0)
        queue_pressure = clamp(state[4], 0.0, 1.0)
        retrans_flag = 1.0 if (had_retrans or state[3] >= 0.5) else 0.0

        latency_score = math.tanh(rtt_norm)
        buffer_score = queue_pressure
        retrans_score = retrans_flag

        score = 0.5 * latency_score + 0.35 * buffer_score + 0.15 * retrans_score

        if score >= 0.75:
            d_rate = -0.2
        elif score >= 0.5:
            d_rate = -0.1
        elif score <= 0.15:
            d_rate = 0.1
        else:
            d_rate = 0.0

        rate_level = clamp(state[5], 0.0, 1.0)
        
        if rate_level <= 0.2 and score < 0.4 and buffer_score < 0.4 and retrans_flag < 0.5:
            d_rate = max(d_rate, 0.10)

        congested_or_retx = (buffer_score >= 0.6) or retrans_flag >= 0.5
        if congested_or_retx:
            # 혼잡이면 최소 0, 필요 시 -1 로 완화만 허용
            d_batch = 0 if buffer_score >= 0.6 else (-1 if buffer_score <= 0.2 else 0)
        else:
            # 여유 있을 때만 +1
            if buffer_score <= 0.2:
                d_batch = -1
            elif buffer_score <= 0.4:
                d_batch = 0
            else:
                d_batch = +1
        return {"d_rate": d_rate, "d_batch": d_batch}

class TorchAgent:
    def __init__(self, model_path):
        self.model_path = model_path
        self.model = None
        self.torch = None
        self.py = os.environ.get("PYTHON_EXECUTABLE", sys.executable)
        self.force_subproc = os.environ.get("FORCE_TORCH_SUBPROCESS", "0") == "1"

    def _lazy_load_with_env_optimization(self):
        if os.getenv("FORCE_TORCH_SUBPROCESS", "") == "1":
            raise RuntimeError("forced_subprocess")
        import importlib.util
        if importlib.util.find_spec("torch") is None:
            raise RuntimeError("forced_subprocess")
        # 강제로 서브프로세스로만 돌리기 (부모에서 torch import 시도 안 함)
        if self.force_subproc:
            raise RuntimeError("forced_subprocess")

        if self.model is None:
            import torch
            torch.set_num_threads(1)
            torch.set_num_interop_threads(1)
            self.torch = torch
            self.model = torch.jit.load(self.model_path, map_location="cpu")
            self.model.eval()
            _emit(json.dumps({"info":"torch_model_loaded","backend":"env_optimized"}))
            
    def act(self, state, **_):
        try:
            # 환경 최적화 방식 시도
            self._lazy_load_with_env_optimization()
            
            x = self.torch.tensor([state], dtype=self.torch.float32)
            with self.torch.no_grad():
                out = self.model(x)
            
            d_rate = float(out[0,0].item())
            d_batch = int(round(out[0,1].item()))
            d_batch = max(-1, min(1, d_batch))
            d_rate = max(-0.2, min(0.2, d_rate))
            
            return {"d_rate": d_rate, "d_batch": d_batch}
            
        except Exception as e:
            msg = str(e)
            if "forced_subprocess" in msg:
                # 의도된 경로: 경고 대신 정보 레벨로 남긴다
                _emit(json.dumps({"info":"torch_main_skip","reason":"forced_subprocess","fallback":"subprocess"}))
            else:
                _emit(json.dumps({"warn":"env_optimization_failed","fallback":"subprocess","err": msg}))
            return self._subprocess_fallback(state)
    
    def _subprocess_fallback(self, state):
        """프로세스 분리 방식 fallback"""
        try:
            import subprocess, json, os

            code = f"""
import sys, json, os
VERBOSE = os.getenv("EDA_RL_VERBOSE", "0").lower() not in ("0","false","no","off","")
if VERBOSE:
    print("PY:", sys.executable, file=sys.stderr)
try:
    import torch
    if VERBOSE:
        print("TORCH_OK:", torch.__version__, file=sys.stderr)
except Exception as e:
    if VERBOSE:
        print("TORCH_ERR:", repr(e), file=sys.stderr)
    raise
model = torch.jit.load({json.dumps(self.model_path)}, map_location='cpu')
with torch.no_grad():
    x = torch.tensor([json.loads(sys.argv[1])], dtype=torch.float32)
    out = model(x)
    d_rate = float(out[0,0].item())
    d_batch = int(round(out[0,1].item()))
    d_batch = max(-1, min(1, d_batch))
    d_rate = max(-0.2, min(0.2, d_rate))
    print(json.dumps({{"d_rate": d_rate, "d_batch": d_batch}}))
    """
            cmd = [self.py, "-c", code, json.dumps(state)]
            # 환경 그대로 승계(venv path 포함)
            env = os.environ.copy()

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=20, env=env)
            if result.returncode == 0:
                # 어떤 파이썬/torch를 썼는지 stderr로 확인
                if result.stderr.strip():
                    _emit(json.dumps({"subproc_stderr": result.stderr.strip()}))
                return json.loads(result.stdout.strip())
            else:
                raise Exception(f"subprocess failed: {result.stderr}")

        except Exception as e:
            # 최후 fallback: rule-based
            _emit(json.dumps({"warn":"all_torch_methods_failed","fallback":"rule","err":str(e)}))
            congested = state[4] >= 0.5
            if congested:
                return {"d_rate": -0.2, "d_batch": +1}
            else:
                return {"d_rate": 0.0, "d_batch": 0}


if gym is not None:
    class MQTTRLGymEnv(gym.Env):
        """Streaming Gymnasium environment that wraps live MQTT eBPF control loop."""

        metadata = {"render_modes": []}

        def __init__(
            self,
            *,
            bpf_obj,
            mqtt_client,
            shield: Shield,
            mode: str,
            backend: str,
            log_path: str,
            interval_s: float,
            slo_p99_ms: float,
        ):
            super().__init__()
            if spaces is None:
                raise RuntimeError("gymnasium spaces unavailable")

            self.b = bpf_obj
            self.cli = mqtt_client
            self.shield = shield
            self.mode = mode
            self.backend = backend
            self.log_path = log_path
            self.interval_s = interval_s
            self.slo_p99_ms = slo_p99_ms

            # Observation = [rtt_norm, snd_norm, rcv_norm, retrans_flag,
            #                queue, rate, batch, last_d_rate, last_d_batch]
            obs_low = np.array(
                [0.0, 0.0, 0.0, 0.0,
                 0.0, 0.0, 0.0, -1.0, -1.0],
                dtype=np.float32,
            )
            obs_high = np.array(
                [10.0, 1.0, 1.0, 1.0,
                 1.0, 1.2, 1.0, 1.0, 1.0],
                dtype=np.float32,
            )
            self.observation_space = spaces.Box(low=obs_low, high=obs_high, dtype=np.float32)

            # Action = [d_rate_frac in [-0.2,0.2], d_batch_step in {-1,0,1} approximated as [-1,1]]
            self.action_space = spaces.Box(
                low=np.array([-0.2, -1.0], dtype=np.float32),
                high=np.array([0.2, 1.0], dtype=np.float32),
                dtype=np.float32,
            )

            self.prev_totals = {}
            self.ewma_rtt_us: Optional[int] = None
            self.congested = False
            self.on_since: Optional[float] = None
            self.off_since: Optional[float] = time.time()

            self.current_rate = int(INIT_RATE)
            self.current_batch = int(INIT_BATCH)
            self.current_qos = int(INIT_QOS)

            self.last_action = {"d_rate": 0.0, "d_batch": 0}
            self.last_obs: Optional[list] = None
            self.last_info: dict = {}
            self.last_dec_ts = 0.0
            self.last_dec_p99_ms: Optional[float] = None
            self.next_apply_time = 0.0
            self.p99_hist = deque(maxlen=5)
            self.stop_active = False
            self._force_stop_next = False

        # Gym interface -------------------------------------------------
        def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
            super().reset(seed=seed)

            self.prev_totals.clear()
            self.ewma_rtt_us = None
            self.congested = False
            self.on_since = None
            self.off_since = time.time()
            self.current_rate = int(INIT_RATE)
            self.current_batch = int(INIT_BATCH)
            self.current_qos = int(INIT_QOS)
            self.last_action = {"d_rate": 0.0, "d_batch": 0}
            self.last_dec_ts = 0.0
            self.last_dec_p99_ms = None
            self.next_apply_time = 0.0
            self.p99_hist.clear()
            self.stop_active = False
            self._force_stop_next = False

            kernel = self._collect_kernel_snapshot()
            obs = make_state(
                kernel["ewma_rtt_us"],
                kernel["snd_ratio"],
                kernel["rcv_ratio"],
                kernel["had_retrans"],
                kernel["queue_pressure"],
                self.current_rate,
                self.current_batch,
                self.last_action,
                self._metrics_slice(),
            )
            info = self._build_info(kernel, applied=False, cmds=[], reward_valid=False, reward=None,
                                     raw_action={"d_rate": 0.0, "d_batch": 0},
                                     clamped_action={"d_rate": 0.0, "d_batch": 0})

            self.last_obs = obs
            self.last_info = info
            return np.array(obs, dtype=np.float32), info

        def step(self, action):
            if self.last_obs is None:
                raise RuntimeError("Environment used before reset")
            # 1. 10개 Subscriber의 데이터를 모두 모아서 집계 (Max P99, Sum N)
            agg_metrics = get_aggregated_metrics_and_clear()
            
            # 2. 전역 변수 LATEST_METRICS 갱신 (Shield, Reward 계산에 쓰임)
            global LATEST_METRICS
            if agg_metrics is not None:
                LATEST_METRICS = agg_metrics
                self._update_p99_history(LATEST_METRICS.get("p99_ms"))
            else:
                # 데이터가 안 들어왔으면(통신 두절 등), 0으로 초기화하거나 이전 값 유지
                # 여기서는 안전하게 0으로 처리
                pass
            raw_d_rate, raw_d_batch = self._parse_action(action)
            d_rate_frac = float(clamp(raw_d_rate, -MAX_STEP_FRAC, MAX_STEP_FRAC))
            d_batch = int(max(-1, min(1, round(raw_d_batch))))

            # policy shields/gates
            d_rate_frac, d_batch = self._apply_policy_guards(d_rate_frac, d_batch)

            now = time.time()
            if ACTION_HOLD_SEC > 0.0 and now < getattr(self, "next_apply_time", 0.0):
                d_rate_frac = 0.0
                d_batch = 0

            stop_rate = max(0, self.shield.r_min)
            force_stop = getattr(self, "stop_active", False)
            if force_stop:
                can_apply = (self.current_rate != stop_rate)
                new_rate = stop_rate
                new_batch = self.current_batch
            else:
                can_apply, new_rate, new_batch = self.shield.clamp(
                    now,
                    self.current_rate,
                    self.current_batch,
                    d_rate_frac,
                    d_batch,
                )

            applied = False
            applied_cmds = []
            if self.mode == "online" and can_apply and (new_rate != self.current_rate or new_batch != self.current_batch):
                applied = True
                applied_cmds = [
                    {"cmd": "throttle", "rate": int(new_rate)},
                    {"cmd": "batch", "size": int(new_batch)},
                ]
                if self.cli is not None:
                    for c in applied_cmds:
                        self.cli.publish(CONTROL_TOPIC, json.dumps(c), qos=1)
                self.current_rate = int(new_rate)
                self.current_batch = int(new_batch)
                if ACTION_HOLD_SEC > 0.0:
                    self.next_apply_time = now + ACTION_HOLD_SEC
                if d_rate_frac < 0.0:
                    self.last_dec_ts = now
                    try:
                        self.last_dec_p99_ms = float(LATEST_METRICS.get("p99_ms"))
                    except Exception:
                        self.last_dec_p99_ms = None

            # even in shadow mode we record intended adjustments
            self.last_action = {"d_rate": d_rate_frac, "d_batch": d_batch}

            time.sleep(self.interval_s)

            kernel = self._collect_kernel_snapshot()

            reward_valid = True
            reward = self._compute_reward(kernel)
            if reward is None:
                reward_valid = False
                reward = 0.0

            next_state = make_state(
                kernel["ewma_rtt_us"],
                kernel["snd_ratio"],
                kernel["rcv_ratio"],
                kernel["had_retrans"],
                kernel["queue_pressure"],
                self.current_rate,
                self.current_batch,
                self.last_action,
                self._metrics_slice(),
            )

            info = self._build_info(
                kernel,
                applied=applied,
                cmds=applied_cmds,
                reward_valid=reward_valid,
                reward=reward,
                raw_action={"d_rate": raw_d_rate, "d_batch": raw_d_batch},
                clamped_action=self.last_action.copy(),
            )

            rec = {
                "ts": kernel["ts"],
                "mode": self.mode,
                "backend": self.backend,
                "s": self.last_obs,
                "a_raw": {"d_rate": raw_d_rate, "d_batch": raw_d_batch},
                "a": self.last_action.copy(),
                "r": reward if reward_valid else None,
                "s_next": next_state,
                "metrics": info["metrics"],
                "kernel": info["kernel"],
                "applied": applied,
                "cmds": applied_cmds,
            }
            if "metrics_fresh_sec" in info:
                rec["metrics_fresh_sec"] = info["metrics_fresh_sec"]
                
            final_p99 = 0
            if LATEST_METRICS:
                final_p99 = LATEST_METRICS.get("p99_ms", 0)
            
            # 목표치(300ms) 초과 시 개입
            # if final_p99 > SLO_P99_MS:
            #     # 현재 속도의 20%를 강제로 깎음 (최소 5씩 깎음)
            #     cut_amount = max(5, int(self.current_rate * 0.2))
            #     forced_rate = max(1, self.current_rate - cut_amount)
                
            #     # 로그상으로는 감속 안 한 걸로 보여도, 여기서는 무조건 보냄
            #     if forced_rate < self.current_rate:
            #         cmds = [
            #             {"cmd": "throttle", "rate": forced_rate},
            #             # 배치는 건드리지 않음 (변수 통제)
            #         ]
            #         if self.cli is not None:
            #             for c in cmds:
            #                 self.cli.publish(CONTROL_TOPIC, json.dumps(c), qos=1)
                    
            #         # 내부 상태 강제 동기화
            #         self.current_rate = forced_rate
                    
            #         # 로그에 "강제 개입함" 표시
            #         rec["applied"] = True
            #         rec["cmds"] = cmds
            #         # rec["action"]["d_rate"] = -0.2  # 로그 확인용
            #         rec["note"] = "FORCED_DECEL_BY_SHIELD" # 디버깅용 태그

            # ========================================================
            log_transition(self.log_path, rec)

            self.last_obs = next_state
            self.last_info = info

            terminated = False
            truncated = False
            return np.array(next_state, dtype=np.float32), float(reward), terminated, truncated, info

        # Helpers -------------------------------------------------------
        def _parse_action(self, action) -> Tuple[float, float]:
            if isinstance(action, dict):
                return float(action.get("d_rate", 0.0)), float(action.get("d_batch", 0.0))
            arr = np.asarray(action, dtype=np.float32).reshape(-1)
            if arr.size == 0:
                return 0.0, 0.0
            if arr.size == 1:
                return float(arr[0]), 0.0
            return float(arr[0]), float(arr[1])

        def _apply_policy_guards(self, d_rate_frac: float, d_batch: int) -> Tuple[float, int]:
            """
            Safety guard in front of Shield.
            1. Hard Brake: P99 > 1000ms or Buffer > 100% -> Force strong deceleration (-0.5)
            2. Kickstart: Throughput < Floor and Safe -> Force acceleration (+0.05)
            """

            # 최신 앱 메트릭
            metrics = LATEST_METRICS if isinstance(LATEST_METRICS, dict) else {}
            thr_now = compute_throughput(metrics) if metrics else 0.0
            p99 = float(metrics.get("p99_ms") or 0.0)

            p99_trend_up = self._p99_trending_up()
            p99_sustain_high = self._p99_sustained_high()
            self._update_stop_state(p99 if metrics else None)
            force_stop = getattr(self, "stop_active", False)
            self._force_stop_next = force_stop

            # 커널 스냅샷
            k = self._collect_kernel_snapshot()
            snd_ratio = k.get("snd_ratio", 0.0) or 0.0

            if force_stop:
                return 0.0, 0

            # 1) Hard Brake (Emergency Stop)
            if snd_ratio > 1.0:
                d_rate_frac = min(d_rate_frac, -HARD_DECEL_FRAC)
                if d_batch > 0: d_batch = 0
                return d_rate_frac, d_batch

            if p99_trend_up and p99 >= P99_TREND_MIN_MS:
                d_rate_frac = min(d_rate_frac, -HARD_DECEL_FRAC)
                if d_batch > 0: d_batch = 0
                return d_rate_frac, d_batch

            if p99_sustain_high:
                clamp_dec = max(P99_SUSTAIN_DECEL_FRAC, 0.01)
                d_rate_frac = min(d_rate_frac, -clamp_dec)
                if d_batch > 0:
                    d_batch = 0
                return d_rate_frac, d_batch

            # 상승 추세가 없으면 목표 처리량까지는 가속을 허용
            try:
                if thr_now < THROUGHPUT_TARGET and not p99_trend_up:
                    d_rate_frac = max(d_rate_frac, 0.05)
                    if d_batch < 0:
                        d_batch = 0
            except Exception:
                pass

            # p99가 연속 상승 중일 때만 완화(감속) 허용
            if d_rate_frac < 0.0 and not p99_trend_up:
                d_rate_frac = 0.0

            if p99_trend_up and p99 >= P99_TREND_MIN_MS:
                kick = -0.05
                if p99 > max(self.slo_p99_ms, P99_TREND_MIN_MS) * 1.3:
                    kick = -0.1
                d_rate_frac = min(d_rate_frac, kick)
                if d_batch > 0:
                    d_batch = 0

            # 2) Throughput floor (Kickstart)
            # If throughput is too low and latency is safe, force acceleration.
            try:
                if (
                    THROUGHPUT_MIN_FLOOR > 0.0
                    and thr_now < THROUGHPUT_MIN_FLOOR
                ):
                    if p99 < SLO_P99_MS:
                        # Safe to accelerate
                        d_rate_frac = max(d_rate_frac, 0.05)
                    else:
                        # Unsafe, but don't decelerate too much
                        d_rate_frac = max(d_rate_frac, 0.0)
            except Exception:
                pass

            return d_rate_frac, d_batch

        def _update_p99_history(self, p99_val: Optional[float]):
            try:
                if p99_val is None:
                    return
                self.p99_hist.append(float(p99_val))
            except Exception:
                pass

        def _update_stop_state(self, p99_val: Optional[float]):
            try:
                if self.stop_active:
                    if p99_val is not None and p99_val <= P99_STOP_RELEASE_MS:
                        self.stop_active = False
                else:
                    if self._p99_should_stop():
                        self.stop_active = True
            except Exception:
                pass

        def _p99_trending_up(self) -> bool:
            vals = [v for v in self.p99_hist if v is not None]
            if len(vals) < 3:
                return False
            window = vals[-3:]
            # 3 포인트 모두 지정 임계 이상이면서 일관 상승할 때만 true
            if any(v < P99_TREND_MIN_MS for v in window):
                return False
            deltas = [b - a for a, b in zip(window, window[1:])]
            min_step = max(5.0, 0.01 * P99_TREND_MIN_MS)
            return all(d > min_step for d in deltas)

        def _p99_sustained_high(self) -> bool:
            count = max(1, int(P99_ACCEL_BLOCK_COUNT))
            vals = [v for v in self.p99_hist if v is not None]
            if len(vals) < count:
                return False
            window = vals[-count:]
            return all(v is not None and v >= P99_ACCEL_BLOCK_MS for v in window)

        def _p99_should_stop(self) -> bool:
            vals = [v for v in self.p99_hist if v is not None]
            count = max(1, int(P99_STOP_COUNT))
            if len(vals) < count:
                return False
            window = vals[-count:]
            return all(v is not None and v >= P99_STOP_MS for v in window)

        def _collect_kernel_snapshot(self) -> dict:
            now = time.time()
            snapshot = {}
            had_retrans = False
            total_retrans_delta = 0  # 이번 interval의 총 재전송 횟수
            max_retrans_out = 0  # 현재 재전송 대기 큐 최대값
            max_sndbuf = 0
            max_rcvbuf = 0
            rtt_ms_list = []

            if self.b is not None:
                table = self.b.get_table("stats")
                keys = list(table.keys())
                new_totals = {}
                for k in keys:
                    try:
                        v = table[k]
                    except Exception:
                        continue

                    key = (k.saddr, k.daddr, k.sport, k.dport)
                    total_retrans = int(v.retrans)
                    new_totals[key] = total_retrans

                    rtt_ms = float(v.srtt_us) / 1000.0
                    sndbuf = int(v.sndbuf)
                    rcvbuf = int(v.rcvbuf)
                    retrans_out = int(v.retrans_out)  # 현재 재전송 대기 큐
                    retrans_delta = max(0, total_retrans - self.prev_totals.get(key, 0))

                    if rtt_ms > 0:
                        rtt_ms_list.append(rtt_ms)
                    if retrans_delta > 0:
                        had_retrans = True
                        total_retrans_delta += retrans_delta  # 재전송 횟수 누적
                    if retrans_out > max_retrans_out:
                        max_retrans_out = retrans_out  # 재전송 큐 최대값
                    if sndbuf > max_sndbuf:
                        max_sndbuf = sndbuf
                    if rcvbuf > max_rcvbuf:
                        max_rcvbuf = rcvbuf

                    line = {
                        "ts": now,
                        "flow": key_to_str(key),
                        "interval_s": self.interval_s,
                        "rtt_ms": round(rtt_ms, 2),
                        "retrans_delta": retrans_delta,
                        "sndbuf": sndbuf,
                        "rcvbuf": rcvbuf,
                    }
                    _emit(json.dumps(line))

                    # Clear the entry to prevent stale data (Ghost Flows)
                    # Active flows will be re-created by eBPF on next packet
                    try:
                        del table[k]
                    except Exception:
                        pass

                self.prev_totals = new_totals
            else:
                keys = []

            if rtt_ms_list:
                avg_rtt_ms = mean(rtt_ms_list)
                cur_rtt_us = int(avg_rtt_ms * 1000)
                if self.ewma_rtt_us is None:
                    self.ewma_rtt_us = cur_rtt_us
                else:
                    self.ewma_rtt_us = int(self.ewma_rtt_us + EWMA_ALPHA * (cur_rtt_us - self.ewma_rtt_us))
            else:
                avg_rtt_ms = 0.0
                cur_rtt_us = 0
                if self.ewma_rtt_us is None:
                    self.ewma_rtt_us = 0

            snd_ratio = max_sndbuf / max(1, TH_SNDBUF)
            rcv_ratio = max_rcvbuf / max(1, TH_RCVBUF)

            queue_pressure = compute_queue_pressure(snd_ratio, rcv_ratio)
            congested = self._update_congestion(now, had_retrans, snd_ratio, rcv_ratio)

            return {
                "ts": now,
                "ewma_rtt_us": self.ewma_rtt_us,
                "snd_ratio": snd_ratio,
                "rcv_ratio": rcv_ratio,
                "had_retrans": had_retrans,
                "retrans_count": total_retrans_delta,  # 실제 재전송 횟수
                "retrans_queue": max_retrans_out,  # 현재 재전송 대기 큐 크기
                "queue_pressure": queue_pressure,
                "congested": congested,
            }

        def _update_congestion(self, now: float, had_retrans: bool, snd_ratio: float, rcv_ratio: float) -> bool:
            rtt_on = (self.ewma_rtt_us or 0) > HI_RTT_US
            rtt_off = (self.ewma_rtt_us or 0) < LO_RTT_US
            buf_on = (snd_ratio >= SND_RATIO_HI) or (rcv_ratio >= SND_RATIO_HI)
            buf_off = (snd_ratio <= SND_RATIO_LO) and (rcv_ratio <= SND_RATIO_LO)
            ret_on = had_retrans and (TH_RETRANS <= 1)
            ret_off = not had_retrans

            want_on = rtt_on and (buf_on or had_retrans)
            want_off = rtt_off and buf_off and ret_off

            if want_on:
                if self.on_since is None:
                    self.on_since = now
                if (now - self.on_since) >= T_HOLD_ON:
                    self.congested = True
                    self.off_since = None
            else:
                self.on_since = None

            if want_off:
                if self.off_since is None:
                    self.off_since = now
                if (now - self.off_since) >= T_HOLD_OFF:
                    self.congested = False
                    self.on_since = None
            else:
                if not want_off:
                    self.off_since = None

            return self.congested

        def _metrics_slice(self) -> dict:
            keys = ["p50_ms", "p95_ms", "p99_ms", "n", "window_sec", "total_msgs", "thr"]
            return {k: LATEST_METRICS.get(k) for k in keys}

        def _compute_reward(self, kernel: dict) -> Optional[float]:
            if USE_APP_METRICS:
                m_ts = LATEST_METRICS.get("ts")
                m_win = LATEST_METRICS.get("window_sec") or 0
                if m_ts and (kernel["ts"] - float(m_ts)) > max(10.0, 1.5 * float(m_win)):
                    return None

            return compute_reward(
                LATEST_METRICS,
                ewma_rtt_us=kernel["ewma_rtt_us"],
                snd_ratio=kernel["snd_ratio"],
                rcv_ratio=kernel["rcv_ratio"],
                queue_pressure=kernel["queue_pressure"],
                had_retrans=kernel["had_retrans"],
                retrans_count=kernel.get("retrans_count", 0),
                current_rate=self.current_rate,
                SLO_p99_ms=self.slo_p99_ms,
            )

        def _build_info(
            self,
            kernel: dict,
            *,
            applied: bool,
            cmds: list,
            reward_valid: bool,
            reward: Optional[float],
            raw_action: dict,
            clamped_action: dict,
        ) -> dict:
            info = {
                "ts": kernel["ts"],
                "metrics": self._metrics_slice(),
                "kernel": {
                    "ewma_rtt_us": kernel["ewma_rtt_us"],
                    "snd_ratio": kernel["snd_ratio"],
                    "rcv_ratio": kernel["rcv_ratio"],
                    "had_retrans": kernel["had_retrans"],
                    "retrans_count": kernel["retrans_count"],  # 실제 재전송 횟수
                    "retrans_queue": kernel["retrans_queue"],  # 현재 재전송 대기 큐
                    "congested": kernel["congested"],
                    "congestion_score": kernel["queue_pressure"],
                },
                "applied": applied,
                "cmds": cmds,
                "reward_valid": reward_valid,
                "reward": reward,
                "raw_action": raw_action,
                "action": clamped_action,
            }
            try:
                mts = LATEST_METRICS.get("ts")
                mwin = LATEST_METRICS.get("window_sec")
                if mts and mwin:
                    info["metrics_fresh_sec"] = round(kernel["ts"] - float(mts), 3)
            except Exception:
                pass
            return info


def load_agent():
    if RL_BACKEND == "torch" and RL_MODEL_PATH:
        try:
            return TorchAgent(RL_MODEL_PATH), "torch"
        except Exception as e:
            _emit(json.dumps({"warn":"torch_agent_load_failed","err":str(e)}))
    return RuleAgent(), "rule"

# =========================
# 메인
# =========================
def main():
    # eBPF attach
    if SKIP_EBPF:
        b = None
        _emit("[SKIP] eBPF disabled")
    else:
        program = BPF_PROGRAM.replace("__TRACK_PORT__", str(TRACK_PORT))
        b = BPF(text=program, debug=0x4)
        _emit("[OK] eBPF loaded for port {}".format(TRACK_PORT))
        ok_send = ok_rcv = True
        try:
            b.attach_kprobe(event="tcp_sendmsg", fn_name="on_tcp_sendmsg")
        except Exception as e:
            ok_send = False
            _emit(json.dumps({"warn":"attach_kprobe_sendmsg_failed", "err":str(e)}))

        try:
            b.attach_kprobe(event="tcp_rcv_established", fn_name="on_tcp_rcv_established")
        except Exception as e:
            ok_rcv = False
            _emit(json.dumps({"warn":"attach_kprobe_rcv_failed", "err":str(e)}))

        _emit(json.dumps({"kprobe_sendmsg": ok_send, "kprobe_rcv": ok_rcv}))
        # ──────────────────────────────────────────────────────────

        _emit("[OK] eBPF loaded for port {}".format(TRACK_PORT))
    # MQTT
    cli = make_mqtt()

    # 상태 변수
    prev_totals = {}
    ewma_rtt_us = None
    congested = False
    on_since, off_since = None, time.time()
    last_congested_state = False
    last_action = {"d_rate": 0.0, "d_batch": 0}

    # Tuner state
    tuner_grid = _tuner_param_grid() if TUNER_ENABLE else []
    tuner_Q = [0.0 for _ in tuner_grid]
    tuner_N = [0 for _ in tuner_grid]
    tuner_arm = 0 if tuner_grid else None
    tuner_last_switch = time.time()
    # rolling window stats for tuner
    tuner_thr = []
    tuner_p99 = []
    tuner_decel_applied = 0

    # 현재 제어 파라미터(내부 추적; 퍼블리셔가 따라온다고 가정)
    current_rate  = int(INIT_RATE)
    current_batch = int(INIT_BATCH)
    current_qos   = int(INIT_QOS)

    # 에이전트/쉴드
    agent, backend = load_agent()
    shield = Shield(R_MIN, R_MAX, B_MIN, B_MAX, MAX_STEP_FRAC, COOLDOWN_SEC, MAX_DECEL_FRAC, DECEL_HOLD_SEC)

    last_ctrl_ts = 0.0
    total_lines = 0
    # 감속 안정화 관찰을 위한 상태
    last_dec_ts_global = 0.0
    last_dec_p99_ms = None
    next_action_time = 0.0

    use_gym_env = os.getenv("USE_GYM_ENV", "1") == "1"
    if use_gym_env and gym is None:
        _emit(json.dumps({"warn": "gymnasium_not_available", "fallback": "legacy_loop"}))
        use_gym_env = False

    if use_gym_env:
        env = MQTTRLGymEnv(
            bpf_obj=b,
            mqtt_client=cli,
            shield=shield,
            mode=RL_MODE,
            backend=backend,
            log_path=RL_LOG_PATH,
            interval_s=INTERVAL_S,
            slo_p99_ms=SLO_P99_MS,
        )

        obs, info = env.reset()
        while True:
            kernel_info = info.get("kernel", {}) if isinstance(info, dict) else {}
            state_for_agent = obs.tolist() if isinstance(obs, np.ndarray) else list(obs)
            action = agent.act(
                state_for_agent,
                ewma_rtt_us=kernel_info.get("ewma_rtt_us"),
                snd_ratio=kernel_info.get("snd_ratio"),
                had_retrans=kernel_info.get("had_retrans"),
            )

            obs, reward, terminated, truncated, info = env.step(action)

            metrics = info.get("metrics") if isinstance(info, dict) else {}
            if isinstance(metrics, dict):
                n = metrics.get("n"); w = metrics.get("window_sec"); p99 = metrics.get("p99_ms")
                if isinstance(n, (int, float)) and isinstance(w, (int, float)) and w > 0:
                    tuner_thr.append(n / w)
                if isinstance(p99, (int, float)):
                    tuner_p99.append(p99)
            if info.get("applied") and info.get("action", {}).get("d_rate", 0.0) < 0.0:
                tuner_decel_applied += 1

            now = info.get("ts", time.time())
            if TUNER_ENABLE and tuner_grid and (now - tuner_last_switch) >= TUNER_EVAL_SEC:
                thr_mean = float(sum(tuner_thr) / len(tuner_thr)) if tuner_thr else 0.0
                p99_med = float(sorted(tuner_p99)[len(tuner_p99) // 2]) if tuner_p99 else float("inf")
                tgt = max(THROUGHPUT_TARGET, 1.0)
                slo = max(SLO_P99_MS, 1.0)
                thr_score = min(thr_mean / tgt, 1.2)
                tail_pen = max((p99_med / slo), 0.0)
                decel_pen = tuner_decel_applied / max(1, len(tuner_thr))
                alpha, beta, gamma = 1.0, 0.7, 0.3
                score = alpha * thr_score - beta * tail_pen - gamma * decel_pen

                idx = tuner_arm
                if idx is not None:
                    nprev = tuner_N[idx]
                    qprev = tuner_Q[idx]
                    tuner_Q[idx] = (qprev * nprev + score) / (nprev + 1)
                    tuner_N[idx] = nprev + 1

                import random

                if random.random() < TUNER_EPS:
                    next_idx = random.randrange(len(tuner_grid))
                else:
                    best = max(tuner_Q)
                    cands = [i for i, q in enumerate(tuner_Q) if q == best]
                    next_idx = random.choice(cands)

                bw, pw, aw, ascale, dcap, hold, floor = tuner_grid[next_idx]

                globals()['THROUGHPUT_BONUS_WEIGHT'] = float(bw)
                globals()['THROUGHPUT_PENALTY_WEIGHT'] = float(pw)
                globals()['THROUGHPUT_ABS_WEIGHT'] = float(aw)
                globals()['THROUGHPUT_ABS_SCALE'] = float(ascale)
                globals()['MAX_DECEL_FRAC'] = float(dcap)
                globals()['DECEL_HOLD_SEC'] = float(hold)
                globals()['THROUGHPUT_MIN_FLOOR'] = float(floor)

                try:
                    shield.max_decel_frac = float(dcap)
                    shield.decel_hold_sec = float(hold)
                except Exception:
                    pass

                _emit(json.dumps({
                    "tuner": {
                        "ts": now,
                        "arm_idx": next_idx,
                        "params": {"bonus": bw, "penalty": pw, "abs_w": aw, "abs_scale": ascale,
                                    "max_decel_frac": dcap, "decel_hold_sec": hold, "floor": floor},
                        "score": round(score, 4),
                        "thr_mean": round(thr_mean, 2),
                        "p99_med": round(p99_med, 2) if p99_med != float('inf') else None,
                        "decel_applied": tuner_decel_applied,
                        "Q": tuner_Q,
                        "N": tuner_N,
                    }
                }))

                tuner_arm = next_idx
                tuner_last_switch = now
                tuner_thr.clear(); tuner_p99.clear(); tuner_decel_applied = 0

            if terminated or truncated:
                obs, info = env.reset()
                tuner_thr.clear(); tuner_p99.clear(); tuner_decel_applied = 0
            # continue loop (no break)

        return


    while True:
        time.sleep(INTERVAL_S)
        now = time.time()
        if b is None:
            table = {}  # eBPF 비활성: 커널 신호 없음(메트릭만으로 RL 섀도우/온라인은 가능)
        else:
            table = b.get_table("stats")

        # 집계: flow별
        snapshot = {}
        rtt_ms_list = []
        had_retrans = False
        total_retrans_delta = 0  # 이번 interval의 총 재전송 횟수
        max_retrans_out = 0  # 현재 재전송 대기 큐 최대값
        max_sndbuf = 0
        max_rcvbuf = 0
        keys = list(table.keys())

        for k in keys:
            try:
                v = table[k]   # 동시 업데이트 실패 시 예외 → 스킵
            except Exception:
                continue
            key = (k.saddr, k.daddr, k.sport, k.dport)
            snapshot[key] = int(v.retrans)

            rtt_ms = float(v.srtt_us) / 1000.0
            sndbuf = int(v.sndbuf)
            rcvbuf = int(v.rcvbuf)
            retrans_total = int(v.retrans)
            retrans_out = int(v.retrans_out)  # 현재 재전송 대기 큐
            retrans_delta = max(0, retrans_total - prev_totals.get(key, 0))

            if rtt_ms > 0: rtt_ms_list.append(rtt_ms)
            if retrans_delta > 0:
                had_retrans = True
                total_retrans_delta += retrans_delta  # 재전송 횟수 누적
            if retrans_out > max_retrans_out:
                max_retrans_out = retrans_out  # 재전송 큐 최대값
            if sndbuf > max_sndbuf: max_sndbuf = sndbuf
            if rcvbuf > max_rcvbuf: max_rcvbuf = rcvbuf

            # per-flow 로그(기존 파이프와 호환)
            line = {
                "ts": now,
                "flow": key_to_str(key),
                "interval_s": INTERVAL_S,
                "rtt_ms": round(rtt_ms, 2),
                "retrans_delta": retrans_delta,
                "sndbuf": sndbuf,
                "rcvbuf": rcvbuf
            }
            _emit(json.dumps(line))
            total_lines += 1

        # EWMA/비율 계산
        if rtt_ms_list:
            avg_rtt_ms = mean(rtt_ms_list)
            cur_rtt_us = int(avg_rtt_ms * 1000)
            if ewma_rtt_us is None:
                ewma_rtt_us = cur_rtt_us
            else:
                ewma_rtt_us = int(ewma_rtt_us + EWMA_ALPHA * (cur_rtt_us - ewma_rtt_us))
        else:
            avg_rtt_ms = 0.0
            cur_rtt_us = 0
            if ewma_rtt_us is None: ewma_rtt_us = 0

        snd_ratio = max_sndbuf / max(1, TH_SNDBUF)
        rcv_ratio = max_rcvbuf / max(1, TH_RCVBUF)

        # 온/오프 조건 조합 + 히스테리시스
        rtt_on  = (ewma_rtt_us or 0) > HI_RTT_US
        rtt_off = (ewma_rtt_us or 0) < LO_RTT_US
        buf_on  = (snd_ratio >= SND_RATIO_HI) or (rcv_ratio >= SND_RATIO_HI)
        buf_off = (snd_ratio <= SND_RATIO_LO) and (rcv_ratio <= SND_RATIO_LO)
        ret_on  = had_retrans and (TH_RETRANS <= 1)
        ret_off = not had_retrans

        want_on  = rtt_on and (buf_on or had_retrans)
        want_off = rtt_off and buf_off and ret_off

        if want_on:
            if on_since is None: on_since = now
            if (now - on_since) >= T_HOLD_ON:
                congested = True; off_since = None
        else:
            on_since = None

        if want_off:
            if off_since is None: off_since = now
            if (now - off_since) >= T_HOLD_OFF:
                congested = False; on_since = None
        else:
            if not want_off: off_since = None

        # ============== RL 파트 ==============
        if EDA_RL:
            queue_pressure = compute_queue_pressure(snd_ratio, rcv_ratio)
            state = make_state(
                ewma_rtt_us,
                snd_ratio,
                rcv_ratio,
                had_retrans,
                queue_pressure,
                current_rate,
                current_batch,
                last_action,
                LATEST_METRICS if isinstance(LATEST_METRICS, dict) else None,
            )
            # 에이전트 행동 결정(섀도우/온라인 동일)
            act = agent.act(state, ewma_rtt_us=ewma_rtt_us, snd_ratio=snd_ratio, had_retrans=had_retrans)
            # Keep raw (pre-guard) action for diagnostics
            d_rate_frac_raw = float(act.get("d_rate", 0.0))
            d_batch_raw     = int(act.get("d_batch", 0))
            d_rate_frac = d_rate_frac_raw
            d_batch     = d_batch_raw
            # 가드: 혼잡 시 가속(+d_rate) 금지 옵션
            try:
                if congested and os.getenv("CLAMP_ACCEL_ON_CONGESTION", "1") == "1" and d_rate_frac > 0.0:
                    d_rate_frac = 0.0
            except Exception:
                pass
            # 처리량 하한 가드: 현재 throughput이 바닥선 미만이면 추가 감속 금지
            try:
                m = LATEST_METRICS
                n = m.get("n"); w = m.get("window_sec")
                thr = (float(n)/float(w)) if isinstance(n,(int,float)) and isinstance(w,(int,float)) and w>0 else None
                if thr is not None and THROUGHPUT_MIN_FLOOR > 0.0 and thr < THROUGHPUT_MIN_FLOOR and d_rate_frac < 0.0:
                    d_rate_frac = 0.0
            except Exception:
                pass
            # 저처리량 회복 바이어스: thr가 RECOVERY_THR_FLOOR 미만이고 혼잡 신호가 낮으면 최소 가속 보장
            try:
                m = LATEST_METRICS
                n = m.get("n"); w = m.get("window_sec")
                thr = (float(n)/float(w)) if isinstance(n,(int,float)) and isinstance(w,(int,float)) and w>0 else None
                low_queue = (queue_pressure <= 0.2) and (snd_ratio <= 0.3) and (rcv_ratio <= 0.3)
                low_rtt   = (ewma_rtt_us or 0) <= max(LO_RTT_US, 50_000)
                if thr is not None and RECOVERY_THR_FLOOR > 0.0 and thr < RECOVERY_THR_FLOOR and (low_queue or low_rtt):
                    d_rate_frac = max(d_rate_frac, min(RECOVERY_MAX_PUSH, MAX_STEP_FRAC/2.0))
                    # 배치는 완화(너무 크면 -1 권고)
                    if d_batch > 0:
                        d_batch = 0
            except Exception:
                pass
            # 감속 후 p99 안정화 대기: 직전 감속 시점의 p99 대비 충분한 하락이 있을 때까진 추가 감속 금지
            try:
                m = LATEST_METRICS
                p99_now = m.get("p99_ms") if isinstance(m, dict) else None
                abs_thr = DECEL_P99_WAIT_ABS_MS if DECEL_P99_WAIT_ABS_MS > 0 else None
                HARD_GUARD = _to_bool_env(os.getenv("HARD_GUARD_ENABLE", "0"))
                if HARD_GUARD and p99_now is not None and p99_now > SLO_P99_MS * 3.0:
                    # 진짜 완전 망가졌을 때만 세이프티 브레이크
                    d_rate_frac = -0.2
                    if d_batch > 0:
                        d_batch = 0
                # if p99_now is not None and p99_now > SLO_P99_MS:
                #     # 상황 1: 아주 심각함 (목표치의 2배 초과) -> 강제 급브레이크 (-10%)
                #     if p99_now > SLO_P99_MS * 2.0:
                #         d_rate_frac = -0.1
                #         # 배치 크기도 강제로 줄임 (가중치 부여)
                #         if d_batch > -1: d_batch = -1 
                        
                #     # 상황 2: 목표치 초과 -> 완만한 강제 감속 (-5%)
                #     else:
                #         d_rate_frac = -0.05
                #         # 배치는 늘리지 못하게 막음
                #         if d_batch > 0: d_batch = 0
                elif d_rate_frac < 0.0:
                    pass
            except Exception:
                pass
            # compute_reward() 호출 직전
            m_ts  = LATEST_METRICS.get("ts")
            m_win = LATEST_METRICS.get("window_sec") or 0
            # 보상 계산 시, p99는 USE_APP_METRICS가 켜진 경우에만 직접 사용하고
            # 처리량(n/window_sec)은 항상 참조하여 shaping에 활용한다.
            if USE_APP_METRICS and m_ts and (now - m_ts) > max(10.0, 1.5 * m_win):
                reward = None  # 앱 메트릭이 너무 오래된 경우 학습 제외(throughput도 신뢰 어려움)
            else:
                reward = compute_reward(
                    LATEST_METRICS,  # throughput shaping을 위해 항상 전달
                    ewma_rtt_us=ewma_rtt_us,
                    snd_ratio=snd_ratio,
                    rcv_ratio=rcv_ratio,
                    queue_pressure=queue_pressure,
                    had_retrans=had_retrans,
                    current_rate=current_rate,
                    SLO_p99_ms=SLO_P99_MS,
                )


            # 온라인 모드면 적용 (쉴드)
            applied = False; applied_cmds = []
            if RL_MODE == "online":
                can_apply, new_rate, new_batch = shield.clamp(now, current_rate, current_batch, d_rate_frac, d_batch)
                if can_apply and (new_rate != current_rate or new_batch != current_batch):
                    # 제어 발행
                    cmds = [
                        {"cmd":"throttle","rate": int(new_rate)},
                        {"cmd":"batch","size": int(new_batch)}
                    ]
                    if cli is not None:  # MQTT 활성화된 경우만
                        for c in cmds:
                            cli.publish(CONTROL_TOPIC, json.dumps(c), qos=1)
                    current_rate, current_batch = new_rate, new_batch
                    applied = True; applied_cmds = cmds
                    _emit(json.dumps({"ts":now,"applied":True,"rate":current_rate,"batch":current_batch}))
                    # 감속이 실제 적용되었으면 기준 p99를 기록하여 이후 안정화 대기 판단에 사용
                    try:
                        if d_rate_frac < 0.0:
                            last_dec_ts_global = now
                            mm = LATEST_METRICS
                            last_dec_p99_ms = mm.get("p99_ms") if isinstance(mm, dict) else None
                            tuner_decel_applied += 1
                    except Exception:
                        pass

            next_state = make_state(
                ewma_rtt_us,
                snd_ratio,
                rcv_ratio,
                had_retrans,
                queue_pressure,
                current_rate,
                current_batch,
                {"d_rate": d_rate_frac, "d_batch": d_batch},
                LATEST_METRICS if isinstance(LATEST_METRICS, dict) else None,
            )

            # 로그 (s,a,r,s')
            rec = {
                "ts": now, "mode": RL_MODE, "backend": backend,
                "s": state,
                "a_raw": {"d_rate": d_rate_frac_raw, "d_batch": d_batch_raw},
                "a": {"d_rate": d_rate_frac, "d_batch": d_batch},
                "r": reward,
                "s_next": next_state,
                "metrics": {k: LATEST_METRICS.get(k) for k in ["p50_ms","p95_ms","p99_ms","n","window_sec","total_msgs"]},
                "kernel": {"ewma_rtt_us": ewma_rtt_us, "snd_ratio": snd_ratio, "rcv_ratio": rcv_ratio,
                            "had_retrans": had_retrans, "retrans_count": total_retrans_delta,
                            "retrans_queue": max_retrans_out, "congested": congested, "congestion_score": queue_pressure},
                "applied": applied,
                "cmds": applied_cmds
            }
            # metrics freshness (for downstream filtering)
            try:
                mts = LATEST_METRICS.get("ts")
                mwin = LATEST_METRICS.get("window_sec")
                if mts and mwin:
                    rec["metrics_fresh_sec"] = round(now - float(mts), 3)
            except Exception:
                pass
            log_transition(RL_LOG_PATH, rec)
            last_action = {"d_rate": d_rate_frac, "d_batch": d_batch}

            # ---------- Tuner: collect window stats ----------
            try:
                m = LATEST_METRICS
                n = m.get("n"); w = m.get("window_sec"); p99 = m.get("p99_ms")
                if isinstance(n,(int,float)) and isinstance(w,(int,float)) and w>0:
                    tuner_thr.append(n/ w)
                if isinstance(p99,(int,float)):
                    tuner_p99.append(p99)
            except Exception:
                pass

            # ---------- Tuner: evaluate/switch arms ----------
            if TUNER_ENABLE and tuner_grid and (now - tuner_last_switch) >= TUNER_EVAL_SEC:
                # compute score
                thr_mean = float(sum(tuner_thr)/len(tuner_thr)) if tuner_thr else 0.0
                p99_med  = float(sorted(tuner_p99)[len(tuner_p99)//2]) if tuner_p99 else float('inf')
                # normalized components
                tgt = max(THROUGHPUT_TARGET, 1.0)
                slo = max(SLO_P99_MS, 1.0)
                thr_score = min(thr_mean / tgt, 1.2)
                tail_pen  = max((p99_med / slo), 0.0)
                decel_pen = tuner_decel_applied / max(1, len(tuner_thr))
                # weights for tuner scoring (fixed small constants)
                alpha, beta, gamma = 1.0, 0.7, 0.3
                score = alpha*thr_score - beta*tail_pen - gamma*decel_pen

                # update Q for current arm
                idx = tuner_arm
                if idx is not None:
                    nprev = tuner_N[idx]
                    qprev = tuner_Q[idx]
                    tuner_Q[idx] = (qprev * nprev + score) / (nprev + 1)
                    tuner_N[idx] = nprev + 1

                # pick next arm (epsilon-greedy)
                import random
                if random.random() < TUNER_EPS:
                    next_idx = random.randrange(len(tuner_grid))
                else:
                    # argmax with tie-breaking
                    best = max(tuner_Q)
                    cands = [i for i,q in enumerate(tuner_Q) if q==best]
                    next_idx = random.choice(cands)

                bw, pw, aw, ascale, dcap, hold, floor = tuner_grid[next_idx]

                # apply parameters live
                globals()['THROUGHPUT_BONUS_WEIGHT'] = float(bw)
                globals()['THROUGHPUT_PENALTY_WEIGHT'] = float(pw)
                globals()['THROUGHPUT_ABS_WEIGHT'] = float(aw)
                globals()['THROUGHPUT_ABS_SCALE'] = float(ascale)
                globals()['MAX_DECEL_FRAC'] = float(dcap)
                globals()['DECEL_HOLD_SEC'] = float(hold)
                globals()['THROUGHPUT_MIN_FLOOR'] = float(floor)
                # update shield live
                try:
                    shield.max_decel_frac = float(dcap)
                    shield.decel_hold_sec = float(hold)
                except Exception:
                    pass

                _emit(json.dumps({
                    "tuner": {
                        "ts": now,
                        "arm_idx": next_idx,
                        "params": {"bonus":bw, "penalty":pw, "abs_w":aw, "abs_scale":ascale,
                                    "max_decel_frac":dcap, "decel_hold_sec":hold, "floor":floor},
                        "score": round(score,4),
                        "thr_mean": round(thr_mean,2),
                        "p99_med": round(p99_med,2) if p99_med!=float('inf') else None,
                        "decel_applied": tuner_decel_applied,
                        "Q": tuner_Q, "N": tuner_N
                    }
                }))

                tuner_arm = next_idx
                tuner_last_switch = now
                tuner_thr.clear(); tuner_p99.clear(); tuner_decel_applied = 0

        # 상태 변화시 규칙제어(옵션): RL_MODE=shadow에서도 기존 규칙을 시험하려면 여기에 배치
        if RL_MODE != "online":
            # 섀도우: 실제 퍼블리셔 제어는 하지 않음
            pass
        else:
            # 온라인 모드에서 혼잡->해제 전환 시 원복 명령을 보내고 싶으면 여기에 구현
            pass

        prev_totals = snapshot

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
