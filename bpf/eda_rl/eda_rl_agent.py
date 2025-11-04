#!/usr/bin/env python3
# eda_rl_agent.py — RL Agent, Shield, State/Reward logic, Gym environment
# Separated from main loop for modularity

# PyTorch + eBPF 호환성을 위한 환경 최적화
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
except Exception:
    gym = None
    spaces = None

from socket import inet_ntop, AF_INET, ntohs
from statistics import mean
from collections import deque
from pathlib import Path

# =========================
# 환경변수
# =========================
MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "23232"))
DATA_TOPIC  = os.getenv("SUB_TOPIC", "bench/foo1")
METRICS_TOPIC = os.getenv("METRICS_TOPIC", "eda/latency")
CONTROL_TOPIC = os.getenv("CONTROL_TOPIC", "control/room1")

# RL
EDA_RL   = os.getenv("EDA_RL", "1") == "1"
RL_MODE  = os.getenv("RL_MODE", "shadow")  # 'shadow' | 'online'
RL_LOG_PATH = os.getenv("RL_LOG_PATH", "./logs/eda_rl.jsonl")
SLO_P99_MS  = float(os.getenv("SLO_P99_MS", "10000"))
USE_APP_METRICS = os.getenv("USE_APP_METRICS", "0") == "1"
THROUGHPUT_TARGET = float(os.getenv("THROUGHPUT_TARGET", "45.0"))
THROUGHPUT_BONUS_WEIGHT = float(os.getenv("THROUGHPUT_BONUS_WEIGHT", "0.6"))
THROUGHPUT_PENALTY_WEIGHT = float(os.getenv("THROUGHPUT_PENALTY_WEIGHT", "1.2"))
THROUGHPUT_ABS_WEIGHT = float(os.getenv("THROUGHPUT_ABS_WEIGHT", "0.3"))
THROUGHPUT_ABS_SCALE  = float(os.getenv("THROUGHPUT_ABS_SCALE",  "100.0"))
MAX_DECEL_FRAC = float(os.getenv("MAX_DECEL_FRAC", os.getenv("MAX_STEP_FRAC", "0.2")))
THROUGHPUT_MIN_FLOOR = float(os.getenv("THROUGHPUT_MIN_FLOOR", "0.0"))
DECEL_HOLD_SEC = float(os.getenv("DECEL_HOLD_SEC", "1.0"))
DECEL_P99_WAIT_DROP_FRAC = float(os.getenv("DECEL_P99_WAIT_DROP_FRAC", "0.15"))
DECEL_P99_WAIT_ABS_MS = float(os.getenv("DECEL_P99_WAIT_ABS_MS", "0"))
RECOVERY_THR_FLOOR = float(os.getenv("RECOVERY_THR_FLOOR", "0.0"))
RECOVERY_MAX_PUSH = float(os.getenv("RECOVERY_MAX_PUSH", "0.10"))

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
MAX_STEP_FRAC = float(os.getenv("MAX_STEP_FRAC", "0.2"))
COOLDOWN_SEC  = float(os.getenv("COOLDOWN_SEC", "3.0"))

# MQTT 관찰 포트
TRACK_PORT = int(os.getenv("MQTT_TRACK_PORT", str(MQTT_PORT)))

# Torch 에이전트 경로
RL_BACKEND  = os.getenv("RL_BACKEND", "rule")  # 'rule' | 'torch'
RL_MODEL_PATH = os.getenv("RL_MODEL_PATH", "")

# eBPF/MQTT 스킵 옵션
SKIP_EBPF = os.getenv("SKIP_EBPF", "0") == "1"
SKIP_MQTT = os.getenv("SKIP_MQTT", "0") == "1"

# Tuner 옵션
TUNER_ENABLE = os.getenv("TUNER_ENABLE", "0") == "1"
TUNER_EVAL_SEC = float(os.getenv("TUNER_EVAL_SEC", "90"))
TUNER_EPS = float(os.getenv("TUNER_EPS", "0.1"))

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
    return combos[:256]

# =========================
# 유틸/상태·보상·로깅
# =========================
def ntoa_hostorder(x: int) -> str:
    return inet_ntop(AF_INET, struct.pack("<I", x))

def key_to_str(k):
    saddr = ntoa_hostorder(k[0]); daddr = ntoa_hostorder(k[1])
    sport = int(k[2])
    dport = ntohs(k[3])
    return f"{saddr}:{sport}->{daddr}:{dport}"

def clamp(x, lo, hi):
    return max(lo, min(hi, x))

def compute_queue_pressure(snd_ratio: float, rcv_ratio: float) -> float:
    return math.tanh(max(snd_ratio, rcv_ratio) / 2.0)

def make_state(ewma_rtt_us, snd_ratio, rcv_ratio, had_retrans, queue_pressure,
               current_rate, current_batch, last_action):
    rtt_norm = min((ewma_rtt_us or 0) / (SLO_P99_MS*1000.0), 10.0)
    s_norm = math.tanh(snd_ratio/2.0)
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

def compute_reward(metrics, *, ewma_rtt_us, snd_ratio, rcv_ratio, queue_pressure,
                   had_retrans, current_rate, SLO_p99_ms):
    """Compute reward from either application metrics or kernel-only signals."""
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
        can_apply = (now - self.last_ts) >= self.cooldown

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

        if d_batch > 0:
            new_batch = current_batch + max(1, d_batch)
        elif d_batch < 0:
            new_batch = current_batch + min(-1, d_batch)
        else:
            new_batch = current_batch
        new_batch = clamp(new_batch, self.b_min, self.b_max)

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
    def act(self, state, ewma_rtt_us=None, snd_ratio=None, had_retrans=None):
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
            d_batch = 0 if buffer_score >= 0.6 else (-1 if buffer_score <= 0.2 else 0)
        else:
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
                _emit(json.dumps({"info":"torch_main_skip","reason":"forced_subprocess","fallback":"subprocess"}))
            else:
                _emit(json.dumps({"warn":"env_optimization_failed","fallback":"subprocess","err": msg}))
            return self._subprocess_fallback(state)

    def _subprocess_fallback(self, state):
        try:
            import subprocess
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
            env = os.environ.copy()
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=20, env=env)
            if result.returncode == 0:
                if result.stderr.strip():
                    _emit(json.dumps({"subproc_stderr": result.stderr.strip()}))
                return json.loads(result.stdout.strip())
            else:
                raise Exception(f"subprocess failed: {result.stderr}")
        except Exception as e:
            _emit(json.dumps({"warn":"all_torch_methods_failed","fallback":"rule","err":str(e)}))
            congested = state[4] >= 0.5
            if congested:
                return {"d_rate": -0.2, "d_batch": +1}
            else:
                return {"d_rate": 0.0, "d_batch": 0}

# =========================
# Gymnasium Environment (optional)
# =========================
if gym is not None:
    class MQTTRLGymEnv(gym.Env):
        """Streaming Gymnasium environment that wraps live MQTT eBPF control loop."""

        metadata = {"render_modes": []}

        def __init__(self, *, bpf_obj, mqtt_client, shield: Shield, mode: str, backend: str,
                     log_path: str, interval_s: float, slo_p99_ms: float, latest_metrics: dict):
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
            self.latest_metrics = latest_metrics

            obs_low = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, -1.0, -1.0], dtype=np.float32)
            obs_high = np.array([10.0, 1.0, 1.0, 1.0, 1.0, 1.2, 1.0, 1.0, 1.0], dtype=np.float32)
            self.observation_space = spaces.Box(low=obs_low, high=obs_high, dtype=np.float32)

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
                kernel["ewma_rtt_us"], kernel["snd_ratio"], kernel["rcv_ratio"],
                kernel["had_retrans"], kernel["queue_pressure"],
                self.current_rate, self.current_batch, self.last_action,
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

            d_rate_frac, d_batch = self._apply_policy_guards(d_rate_frac, d_batch)

            now = time.time()
            can_apply, new_rate, new_batch = self.shield.clamp(
                now, self.current_rate, self.current_batch, d_rate_frac, d_batch,
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
                        self.last_dec_p99_ms = float(self.latest_metrics.get("p99_ms"))
                    except Exception:
                        self.last_dec_p99_ms = None

            self.last_action = {"d_rate": d_rate_frac, "d_batch": d_batch}

            time.sleep(self.interval_s)

            kernel = self._collect_kernel_snapshot()

            reward_valid = True
            reward = self._compute_reward(kernel)
            if reward is None:
                reward_valid = False
                reward = 0.0

            next_state = make_state(
                kernel["ewma_rtt_us"], kernel["snd_ratio"], kernel["rcv_ratio"],
                kernel["had_retrans"], kernel["queue_pressure"],
                self.current_rate, self.current_batch, self.last_action,
            )

            info = self._build_info(
                kernel, applied=applied, cmds=applied_cmds, reward_valid=reward_valid, reward=reward,
                raw_action={"d_rate": raw_d_rate, "d_batch": raw_d_batch},
                clamped_action=self.last_action.copy(),
            )

            rec = {
                "ts": kernel["ts"], "mode": self.mode, "backend": self.backend,
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
                thr = compute_throughput(self.latest_metrics)
                if thr is not None and THROUGHPUT_MIN_FLOOR > 0.0 and thr < THROUGHPUT_MIN_FLOOR and d_rate_frac < 0.0:
                    d_rate_frac = 0.0
            except Exception:
                pass

            try:
                thr = compute_throughput(self.latest_metrics)
                low_queue = self.last_info.get("kernel", {}).get("queue_pressure", 0.0) <= 0.2
                low_rtt = (self.ewma_rtt_us or 0) <= max(LO_RTT_US, 50_000)
                if thr is not None and RECOVERY_THR_FLOOR > 0.0 and thr < RECOVERY_THR_FLOOR and (low_queue or low_rtt):
                    d_rate_frac = max(d_rate_frac, min(RECOVERY_MAX_PUSH, MAX_STEP_FRAC / 2.0))
                    if d_batch > 0:
                        d_batch = 0
            except Exception:
                pass

            try:
                p99_now = self.latest_metrics.get("p99_ms") if isinstance(self.latest_metrics, dict) else None
                abs_thr = DECEL_P99_WAIT_ABS_MS if DECEL_P99_WAIT_ABS_MS > 0 else None
                if d_rate_frac < 0.0 and self.last_dec_ts > 0:
                    cond_drop = (
                        p99_now is not None and self.last_dec_p99_ms is not None and
                        p99_now <= self.last_dec_p99_ms * (1.0 - DECEL_P99_WAIT_DROP_FRAC)
                    )
                    cond_abs = (abs_thr is not None and p99_now is not None and p99_now <= abs_thr)
                    time_ok = (time.time() - self.last_dec_ts) >= DECEL_HOLD_SEC
                    if not (time_ok and (cond_drop or cond_abs)):
                        d_rate_frac = 0.0
            except Exception:
                pass

            return d_rate_frac, d_batch

        def _collect_kernel_snapshot(self) -> dict:
            now = time.time()
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
                        "ts": now, "flow": key_to_str(key), "interval_s": self.interval_s,
                        "rtt_ms": round(rtt_ms, 2), "retrans_delta": retrans_delta,
                        "sndbuf": sndbuf, "rcvbuf": rcvbuf,
                    }
                    _emit(json.dumps(line))

                self.prev_totals = new_totals

            if rtt_ms_list:
                avg_rtt_ms = mean(rtt_ms_list)
                cur_rtt_us = int(avg_rtt_ms * 1000)
                if self.ewma_rtt_us is None:
                    self.ewma_rtt_us = cur_rtt_us
                else:
                    self.ewma_rtt_us = int(self.ewma_rtt_us + EWMA_ALPHA * (cur_rtt_us - self.ewma_rtt_us))
            else:
                if self.ewma_rtt_us is None:
                    self.ewma_rtt_us = 0

            snd_ratio = max_sndbuf / max(1, TH_SNDBUF)
            rcv_ratio = max_rcvbuf / max(1, TH_RCVBUF)

            queue_pressure = compute_queue_pressure(snd_ratio, rcv_ratio)
            congested = self._update_congestion(now, had_retrans, snd_ratio, rcv_ratio)

            return {
                "ts": now, "ewma_rtt_us": self.ewma_rtt_us,
                "snd_ratio": snd_ratio, "rcv_ratio": rcv_ratio,
                "had_retrans": had_retrans, "queue_pressure": queue_pressure,
                "congested": congested,
            }

        def _update_congestion(self, now: float, had_retrans: bool, snd_ratio: float, rcv_ratio: float) -> bool:
            rtt_on = (self.ewma_rtt_us or 0) > HI_RTT_US
            rtt_off = (self.ewma_rtt_us or 0) < LO_RTT_US
            buf_on = (snd_ratio >= SND_RATIO_HI) or (rcv_ratio >= SND_RATIO_HI)
            buf_off = (snd_ratio <= SND_RATIO_LO) and (rcv_ratio <= SND_RATIO_LO)
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
            return {k: self.latest_metrics.get(k) for k in keys}

        def _compute_reward(self, kernel: dict) -> Optional[float]:
            if USE_APP_METRICS:
                m_ts = self.latest_metrics.get("ts")
                m_win = self.latest_metrics.get("window_sec") or 0
                if m_ts and (kernel["ts"] - float(m_ts)) > max(10.0, 1.5 * float(m_win)):
                    return None

            return compute_reward(
                self.latest_metrics,
                ewma_rtt_us=kernel["ewma_rtt_us"], snd_ratio=kernel["snd_ratio"],
                rcv_ratio=kernel["rcv_ratio"], queue_pressure=kernel["queue_pressure"],
                had_retrans=kernel["had_retrans"], current_rate=self.current_rate,
                SLO_p99_ms=self.slo_p99_ms,
            )

        def _build_info(self, kernel: dict, *, applied: bool, cmds: list, reward_valid: bool,
                        reward: Optional[float], raw_action: dict, clamped_action: dict) -> dict:
            info = {
                "ts": kernel["ts"], "metrics": self._metrics_slice(),
                "kernel": {
                    "ewma_rtt_us": kernel["ewma_rtt_us"], "snd_ratio": kernel["snd_ratio"],
                    "rcv_ratio": kernel["rcv_ratio"], "had_retrans": kernel["had_retrans"],
                    "congested": kernel["congested"], "congestion_score": kernel["queue_pressure"],
                },
                "applied": applied, "cmds": cmds, "reward_valid": reward_valid,
                "reward": reward, "raw_action": raw_action, "action": clamped_action,
            }
            try:
                mts = self.latest_metrics.get("ts")
                mwin = self.latest_metrics.get("window_sec")
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
