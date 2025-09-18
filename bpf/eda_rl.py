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
THROUGHPUT_BONUS_WEIGHT = float(os.getenv("THROUGHPUT_BONUS_WEIGHT", "0.6"))
THROUGHPUT_PENALTY_WEIGHT = float(os.getenv("THROUGHPUT_PENALTY_WEIGHT", "1.2"))
# 절대 처리량 보너스(타깃 비율 외에 순수 msg/s에 대한 보너스)
THROUGHPUT_ABS_WEIGHT = float(os.getenv("THROUGHPUT_ABS_WEIGHT", "0.3"))
THROUGHPUT_ABS_SCALE  = float(os.getenv("THROUGHPUT_ABS_SCALE",  "100.0"))  # msg/s 기준 스케일
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
# 절대 처리량 보너스(타깃 비율 외에 순수 msg/s에 대한 보너스)
THROUGHPUT_ABS_WEIGHT = float(os.getenv("THROUGHPUT_ABS_WEIGHT", "0.3"))
THROUGHPUT_ABS_SCALE  = float(os.getenv("THROUGHPUT_ABS_SCALE",  "100.0"))  # msg/s 기준 스케일

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
    struct val_t zero = {};
    struct val_t *v = stats.lookup_or_init(&k, &zero);
    if (v) { v->srtt_us = srtt; v->rcvbuf = rmem; }
    return 0;
}
"""


# =========================
# MQTT & 메트릭 수신
# =========================
LATEST_METRICS = {"ts": None, "n": None, "window_sec": None,
                  "p50_ms": None, "p95_ms": None, "p99_ms": None, "mean_ms": None, "total_msgs": None}

def on_metrics(cli, userdata, msg):
    try:
        payload = json.loads(msg.payload)
        # 기대 필드: ts, n, window_sec, p50_ms, p95_ms, p99_ms, mean_ms, total_msgs
        for k in LATEST_METRICS.keys():
            if k in payload:
                LATEST_METRICS[k] = payload[k]
    except Exception as e:
        _emit(json.dumps({"warn":"bad_metrics_payload","err":str(e)}))

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
               current_rate, current_batch, last_action):
    # 간단 정규화
    # rtt_norm  = clamp((ewma_rtt_us or 0)/100_000.0, 0.0, 5.0)
    rtt_norm = min( (ewma_rtt_us or 0) / (SLO_P99_MS*1000.0), 10.0)
    import math

    # s_norm    = clamp(snd_ratio, 0.0, 5.0)
    # r_norm    = clamp(rcv_ratio, 0.0, 5.0)
    s_norm = math.tanh(snd_ratio/2.0)         # 0~1 근처
    r_norm = math.tanh(rcv_ratio/2.0)
    retr_norm = 1.0 if had_retrans else 0.0
    cong_norm = clamp(queue_pressure, 0.0, 1.0)
    rate_norm = clamp(current_rate/float(R_MAX), 0.0, 1.0)
    batch_norm= clamp(current_batch/float(B_MAX), 0.0, 1.0)
    drate     = clamp(last_action.get("d_rate", 0.0), -1.0, 1.0)
    dbatch    = clamp(last_action.get("d_batch", 0), -3, 3)/3.0
    return [rtt_norm, s_norm, r_norm, retr_norm, cong_norm, rate_norm, batch_norm, drate, dbatch]

def compute_throughput(metrics):
    n = metrics.get("n"); win = metrics.get("window_sec")
    if n is None or not win or win <= 0: return None
    return float(n)/float(win)

def compute_reward(metrics,
                   *,
                   ewma_rtt_us,
                   snd_ratio,
                   rcv_ratio,
                   queue_pressure,
                   had_retrans,
                   current_rate,
                   SLO_p99_ms
                   ):
    """Compute reward from either application metrics or kernel-only signals."""
    # ── 1) 애플리케이션 p99 사용 (옵션) ───────────────────────────────
    if USE_APP_METRICS and isinstance(metrics, dict):
        p99 = metrics.get("p99_ms"); thru = compute_throughput(metrics)
        if p99 is not None and thru is not None:
            over = max(0.0, (p99 - SLO_p99_ms) / SLO_p99_ms)

            delta_bonus = 0.0
            prev = getattr(compute_reward, "_last_p99", None)
            if prev is not None and prev > 0:
                delta_bonus = 0.5 * max(0.0, (prev - p99) / prev)
            compute_reward._last_p99 = p99

            return float(-(2.0 * over) + 0.2 * clamp(thru / 1000.0, 0.0, 1.0) + delta_bonus)

    # ── 2) 커널 기반 대리지표 ────────────────────────────────────────
    import math
    rtt_norm = min((ewma_rtt_us or 0) / (SLO_p99_ms * 1000.0), 10.0)
    queue_pen = queue_pressure
    snd_pen = math.tanh(max(0.0, snd_ratio - 0.4))
    rcv_pen = math.tanh(max(0.0, rcv_ratio - 0.4))
    retrans_pen = 1.0 if had_retrans else 0.0
    base_rate_norm = clamp(current_rate / max(1.0, float(INIT_RATE)), 0.0, 2.0)
    low_queue_bonus = 1.0 - queue_pressure

    throughput = None
    throughput_ratio = None
    throughput_penalty = 0.0
    throughput_bonus = 0.0
    if isinstance(metrics, dict):
        throughput = compute_throughput(metrics)
        if throughput is not None:
            target = max(THROUGHPUT_TARGET, 1.0)
            throughput_ratio = throughput / target
            throughput_penalty = max(0.0, 1.0 - throughput_ratio)
            throughput_bonus = max(0.0, throughput_ratio - 1.0)

    effective_rate_norm = base_rate_norm
    if throughput_ratio is not None:
        effective_rate_norm = clamp(throughput_ratio, 0.0, 2.5)

    penalty = (
        1.6 * rtt_norm +
        1.0 * queue_pen +
        0.8 * snd_pen +
        0.6 * rcv_pen +
        0.6 * retrans_pen +
        THROUGHPUT_PENALTY_WEIGHT * throughput_penalty
    )

    if queue_pressure > 0.6 or snd_ratio > 0.8:
        penalty += 0.3

    reward = -penalty
    bonus = (
        0.35 * effective_rate_norm +
        0.25 * low_queue_bonus +
        0.2 * (1.0 - snd_pen) +
        0.2 * (1.0 - rcv_pen)
    )
    if throughput_bonus > 0.0:
        bonus += THROUGHPUT_BONUS_WEIGHT * throughput_bonus

    # 절대 처리량 보너스: 타깃 비율과 무관하게 일정 msg/s 자체에 보너스 부여
    if throughput is not None and THROUGHPUT_ABS_SCALE > 0:
        bonus += THROUGHPUT_ABS_WEIGHT * min(throughput / THROUGHPUT_ABS_SCALE, 2.0)

    reward += bonus
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

        # rate 스텝 제한(음수/양수 비대칭) + 최소 변화(정수 반올림 보정)
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

            # Observation = [rtt_norm, snd_norm, rcv_norm, retrans_flag, queue, rate, batch, last_d_rate, last_d_batch]
            obs_low = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, -1.0, -1.0], dtype=np.float32)
            obs_high = np.array([10.0, 1.0, 1.0, 1.0, 1.0, 1.2, 1.0, 1.0, 1.0], dtype=np.float32)
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

            raw_d_rate, raw_d_batch = self._parse_action(action)
            d_rate_frac = float(clamp(raw_d_rate, -0.2, 0.2))
            d_batch = int(max(-1, min(1, round(raw_d_batch))))

            # policy shields/gates
            d_rate_frac, d_batch = self._apply_policy_guards(d_rate_frac, d_batch)

            now = time.time()
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
            try:
                if self.congested and os.getenv("CLAMP_ACCEL_ON_CONGESTION", "1") == "1" and d_rate_frac > 0.0:
                    d_rate_frac = 0.0
            except Exception:
                pass

            try:
                metrics = LATEST_METRICS
                thr = compute_throughput(metrics)
                if (
                    thr is not None
                    and THROUGHPUT_MIN_FLOOR > 0.0
                    and thr < THROUGHPUT_MIN_FLOOR
                    and d_rate_frac < 0.0
                ):
                    d_rate_frac = 0.0
            except Exception:
                pass

            try:
                metrics = LATEST_METRICS
                thr = compute_throughput(metrics)
                low_queue = self.last_info.get("kernel", {}).get("queue_pressure", 0.0) <= 0.2
                low_rtt = (self.ewma_rtt_us or 0) <= max(LO_RTT_US, 50_000)
                if (
                    thr is not None
                    and RECOVERY_THR_FLOOR > 0.0
                    and thr < RECOVERY_THR_FLOOR
                    and (low_queue or low_rtt)
                ):
                    d_rate_frac = max(d_rate_frac, min(RECOVERY_MAX_PUSH, MAX_STEP_FRAC / 2.0))
                    if d_batch > 0:
                        d_batch = 0
            except Exception:
                pass

            try:
                metrics = LATEST_METRICS
                p99_now = metrics.get("p99_ms") if isinstance(metrics, dict) else None
                abs_thr = DECEL_P99_WAIT_ABS_MS if DECEL_P99_WAIT_ABS_MS > 0 else None
                if d_rate_frac < 0.0 and self.last_dec_ts > 0:
                    cond_drop = (
                        p99_now is not None
                        and self.last_dec_p99_ms is not None
                        and p99_now <= self.last_dec_p99_ms * (1.0 - DECEL_P99_WAIT_DROP_FRAC)
                    )
                    cond_abs = (
                        abs_thr is not None
                        and p99_now is not None
                        and p99_now <= abs_thr
                    )
                    time_ok = (time.time() - self.last_dec_ts) >= DECEL_HOLD_SEC
                    if not (time_ok and (cond_drop or cond_abs)):
                        d_rate_frac = 0.0
            except Exception:
                pass

            return d_rate_frac, d_batch

        def _collect_kernel_snapshot(self) -> dict:
            now = time.time()
            snapshot = {}
            rtt_ms_list = []
            had_retrans = False
            max_sndbuf = 0
            max_rcvbuf = 0

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
                    retrans_delta = max(0, total_retrans - self.prev_totals.get(key, 0))

                    if rtt_ms > 0:
                        rtt_ms_list.append(rtt_ms)
                    if retrans_delta > 0:
                        had_retrans = True
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
            keys = ["p50_ms", "p95_ms", "p99_ms", "n", "window_sec", "total_msgs"]
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
            retrans_delta = max(0, retrans_total - prev_totals.get(key, 0))

            if rtt_ms > 0: rtt_ms_list.append(rtt_ms)
            if retrans_delta > 0: had_retrans = True
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
            state = make_state(ewma_rtt_us, snd_ratio, rcv_ratio, had_retrans, queue_pressure,
                               current_rate, current_batch, last_action)
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
                if d_rate_frac < 0.0 and last_dec_ts_global > 0:
                    cond_drop = (p99_now is not None and last_dec_p99_ms is not None and 
                                 p99_now <= last_dec_p99_ms * (1.0 - DECEL_P99_WAIT_DROP_FRAC))
                    cond_abs = (abs_thr is not None and p99_now is not None and p99_now <= abs_thr)
                    time_ok = (time.time() - last_dec_ts_global) >= DECEL_HOLD_SEC
                    # 추가 감속 허용 조건: (시간 홀드 만족) AND (p99가 충분히 내려왔거나 절대 임계 이하)
                    if not (time_ok and (cond_drop or cond_abs)):
                        d_rate_frac = 0.0
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

            next_state = make_state(ewma_rtt_us, snd_ratio, rcv_ratio, had_retrans, queue_pressure,
                                    current_rate, current_batch, {"d_rate": d_rate_frac, "d_batch": d_batch})

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
                            "had_retrans": had_retrans, "congested": congested,
                            "congestion_score": queue_pressure},
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
