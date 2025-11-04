#!/usr/bin/env python3
# eda_rl_main.py — Main control loop for eBPF+RL agent
# Loads tcp_monitor.c and uses eda_rl_agent for agent/shield/env

import sys, time, json, os
from pathlib import Path

from bcc import BPF
from paho.mqtt import client as mqtt

# Import agent module
from eda_rl_agent import (
    _emit, _to_bool_env, _tuner_param_grid,
    MQTT_HOST, MQTT_PORT, METRICS_TOPIC, CONTROL_TOPIC, TRACK_PORT,
    EDA_RL, RL_MODE, RL_LOG_PATH, SLO_P99_MS, USE_APP_METRICS,
    THROUGHPUT_TARGET, THROUGHPUT_BONUS_WEIGHT, THROUGHPUT_PENALTY_WEIGHT,
    THROUGHPUT_ABS_WEIGHT, THROUGHPUT_ABS_SCALE,
    MAX_DECEL_FRAC, THROUGHPUT_MIN_FLOOR, DECEL_HOLD_SEC,
    DECEL_P99_WAIT_DROP_FRAC, DECEL_P99_WAIT_ABS_MS,
    RECOVERY_THR_FLOOR, RECOVERY_MAX_PUSH,
    INTERVAL_S, EWMA_ALPHA, HI_RTT_US, LO_RTT_US, TH_RETRANS,
    TH_SNDBUF, TH_RCVBUF, SND_RATIO_HI, SND_RATIO_LO,
    T_HOLD_ON, T_HOLD_OFF,
    INIT_RATE, INIT_BATCH, INIT_QOS,
    R_MIN, R_MAX, B_MIN, B_MAX, MAX_STEP_FRAC, COOLDOWN_SEC,
    SKIP_EBPF, SKIP_MQTT,
    TUNER_ENABLE, TUNER_EVAL_SEC, TUNER_EPS,
    TUNER_CANDS_BONUS, TUNER_CANDS_PENALTY, TUNER_CANDS_ABS_W,
    TUNER_CANDS_ABS_S, TUNER_CANDS_DECEL, TUNER_CANDS_HOLD, TUNER_CANDS_FLOOR,
    ntoa_hostorder, key_to_str, clamp,
    compute_queue_pressure, make_state, compute_throughput, compute_reward,
    log_transition,
    Shield, RuleAgent, TorchAgent, load_agent,
    gym,
)

if gym is not None:
    from eda_rl_agent import MQTTRLGymEnv

# =========================
# MQTT & 메트릭 수신
# =========================
LATEST_METRICS = {"ts": None, "n": None, "window_sec": None,
                  "p50_ms": None, "p95_ms": None, "p99_ms": None, "mean_ms": None, "total_msgs": None}

def on_metrics(cli, userdata, msg):
    try:
        payload = json.loads(msg.payload)
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
        cli = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="eda-rl-agent")
    except (AttributeError, TypeError):
        cli = mqtt.Client(client_id="eda-rl-agent")
    cli.connect(MQTT_HOST, MQTT_PORT, 60)
    cli.loop_start()
    cli.message_callback_add(METRICS_TOPIC, on_metrics)
    cli.subscribe(METRICS_TOPIC, qos=0)
    return cli

# =========================
# eBPF 프로그램 로드
# =========================
def load_bpf_program():
    if SKIP_EBPF:
        _emit("[SKIP] eBPF disabled")
        return None

    # Read C code from external file
    c_path = Path(__file__).parent / "tcp_monitor.c"
    if not c_path.exists():
        raise FileNotFoundError(f"eBPF C code not found: {c_path}")

    with open(c_path, "r", encoding="utf-8") as f:
        bpf_text = f.read()

    # Replace placeholder with actual port
    bpf_text = bpf_text.replace("__TRACK_PORT__", str(TRACK_PORT))

    b = BPF(text=bpf_text, debug=0x4)
    _emit(f"[OK] eBPF loaded for port {TRACK_PORT}")

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
    return b

# =========================
# 메인
# =========================
def main():
    b = load_bpf_program()
    cli = make_mqtt()

    # 에이전트/쉴드
    agent, backend = load_agent()
    shield = Shield(R_MIN, R_MAX, B_MIN, B_MAX, MAX_STEP_FRAC, COOLDOWN_SEC, MAX_DECEL_FRAC, DECEL_HOLD_SEC)

    use_gym_env = os.getenv("USE_GYM_ENV", "1") == "1"
    if use_gym_env and gym is None:
        _emit(json.dumps({"warn": "gymnasium_not_available", "fallback": "legacy_loop"}))
        use_gym_env = False

    if use_gym_env:
        env = MQTTRLGymEnv(
            bpf_obj=b, mqtt_client=cli, shield=shield,
            mode=RL_MODE, backend=backend, log_path=RL_LOG_PATH,
            interval_s=INTERVAL_S, slo_p99_ms=SLO_P99_MS,
            latest_metrics=LATEST_METRICS,
        )

        # Tuner state
        tuner_grid = _tuner_param_grid() if TUNER_ENABLE else []
        tuner_Q = [0.0 for _ in tuner_grid]
        tuner_N = [0 for _ in tuner_grid]
        tuner_arm = 0 if tuner_grid else None
        tuner_last_switch = time.time()
        tuner_thr = []
        tuner_p99 = []
        tuner_decel_applied = 0

        obs, info = env.reset()
        while True:
            kernel_info = info.get("kernel", {}) if isinstance(info, dict) else {}
            state_for_agent = obs.tolist() if hasattr(obs, 'tolist') else list(obs)
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

                # Apply parameters to agent module globals
                import eda_rl_agent
                eda_rl_agent.THROUGHPUT_BONUS_WEIGHT = float(bw)
                eda_rl_agent.THROUGHPUT_PENALTY_WEIGHT = float(pw)
                eda_rl_agent.THROUGHPUT_ABS_WEIGHT = float(aw)
                eda_rl_agent.THROUGHPUT_ABS_SCALE = float(ascale)
                eda_rl_agent.MAX_DECEL_FRAC = float(dcap)
                eda_rl_agent.DECEL_HOLD_SEC = float(hold)
                eda_rl_agent.THROUGHPUT_MIN_FLOOR = float(floor)

                try:
                    shield.max_decel_frac = float(dcap)
                    shield.decel_hold_sec = float(hold)
                except Exception:
                    pass

                _emit(json.dumps({
                    "tuner": {
                        "ts": now, "arm_idx": next_idx,
                        "params": {"bonus": bw, "penalty": pw, "abs_w": aw, "abs_scale": ascale,
                                    "max_decel_frac": dcap, "decel_hold_sec": hold, "floor": floor},
                        "score": round(score, 4),
                        "thr_mean": round(thr_mean, 2),
                        "p99_med": round(p99_med, 2) if p99_med != float('inf') else None,
                        "decel_applied": tuner_decel_applied,
                        "Q": tuner_Q, "N": tuner_N,
                    }
                }))

                tuner_arm = next_idx
                tuner_last_switch = now
                tuner_thr.clear(); tuner_p99.clear(); tuner_decel_applied = 0

            if terminated or truncated:
                obs, info = env.reset()
                tuner_thr.clear(); tuner_p99.clear(); tuner_decel_applied = 0

        return

    # ─────────────────────────────────────────────────────────────
    # Legacy loop (without Gym)
    # ─────────────────────────────────────────────────────────────
    from statistics import mean

    prev_totals = {}
    ewma_rtt_us = None
    congested = False
    on_since, off_since = None, time.time()
    last_action = {"d_rate": 0.0, "d_batch": 0}

    # Tuner state
    tuner_grid = _tuner_param_grid() if TUNER_ENABLE else []
    tuner_Q = [0.0 for _ in tuner_grid]
    tuner_N = [0 for _ in tuner_grid]
    tuner_arm = 0 if tuner_grid else None
    tuner_last_switch = time.time()
    tuner_thr = []
    tuner_p99 = []
    tuner_decel_applied = 0

    current_rate  = int(INIT_RATE)
    current_batch = int(INIT_BATCH)
    current_qos   = int(INIT_QOS)

    last_dec_ts_global = 0.0
    last_dec_p99_ms = None

    while True:
        time.sleep(INTERVAL_S)
        now = time.time()
        if b is None:
            table = {}
        else:
            table = b.get_table("stats")

        snapshot = {}
        rtt_ms_list = []
        had_retrans = False
        max_sndbuf = 0
        max_rcvbuf = 0
        keys = list(table.keys())

        for k in keys:
            try:
                v = table[k]
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

            line = {
                "ts": now, "flow": key_to_str(key), "interval_s": INTERVAL_S,
                "rtt_ms": round(rtt_ms, 2), "retrans_delta": retrans_delta,
                "sndbuf": sndbuf, "rcvbuf": rcvbuf
            }
            _emit(json.dumps(line))

        if rtt_ms_list:
            avg_rtt_ms = mean(rtt_ms_list)
            cur_rtt_us = int(avg_rtt_ms * 1000)
            if ewma_rtt_us is None:
                ewma_rtt_us = cur_rtt_us
            else:
                ewma_rtt_us = int(ewma_rtt_us + EWMA_ALPHA * (cur_rtt_us - ewma_rtt_us))
        else:
            if ewma_rtt_us is None: ewma_rtt_us = 0

        snd_ratio = max_sndbuf / max(1, TH_SNDBUF)
        rcv_ratio = max_rcvbuf / max(1, TH_RCVBUF)

        rtt_on  = (ewma_rtt_us or 0) > HI_RTT_US
        rtt_off = (ewma_rtt_us or 0) < LO_RTT_US
        buf_on  = (snd_ratio >= SND_RATIO_HI) or (rcv_ratio >= SND_RATIO_HI)
        buf_off = (snd_ratio <= SND_RATIO_LO) and (rcv_ratio <= SND_RATIO_LO)
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

        if EDA_RL:
            queue_pressure = compute_queue_pressure(snd_ratio, rcv_ratio)
            state = make_state(ewma_rtt_us, snd_ratio, rcv_ratio, had_retrans, queue_pressure,
                               current_rate, current_batch, last_action)
            act = agent.act(state, ewma_rtt_us=ewma_rtt_us, snd_ratio=snd_ratio, had_retrans=had_retrans)
            d_rate_frac_raw = float(act.get("d_rate", 0.0))
            d_batch_raw     = int(act.get("d_batch", 0))
            d_rate_frac = d_rate_frac_raw
            d_batch     = d_batch_raw

            # Policy guards
            try:
                if congested and os.getenv("CLAMP_ACCEL_ON_CONGESTION", "1") == "1" and d_rate_frac > 0.0:
                    d_rate_frac = 0.0
            except Exception:
                pass

            try:
                thr = compute_throughput(LATEST_METRICS)
                if thr is not None and THROUGHPUT_MIN_FLOOR > 0.0 and thr < THROUGHPUT_MIN_FLOOR and d_rate_frac < 0.0:
                    d_rate_frac = 0.0
            except Exception:
                pass

            try:
                thr = compute_throughput(LATEST_METRICS)
                low_queue = (queue_pressure <= 0.2) and (snd_ratio <= 0.3) and (rcv_ratio <= 0.3)
                low_rtt   = (ewma_rtt_us or 0) <= max(LO_RTT_US, 50_000)
                if thr is not None and RECOVERY_THR_FLOOR > 0.0 and thr < RECOVERY_THR_FLOOR and (low_queue or low_rtt):
                    d_rate_frac = max(d_rate_frac, min(RECOVERY_MAX_PUSH, MAX_STEP_FRAC/2.0))
                    if d_batch > 0:
                        d_batch = 0
            except Exception:
                pass

            try:
                p99_now = LATEST_METRICS.get("p99_ms") if isinstance(LATEST_METRICS, dict) else None
                abs_thr = DECEL_P99_WAIT_ABS_MS if DECEL_P99_WAIT_ABS_MS > 0 else None
                if d_rate_frac < 0.0 and last_dec_ts_global > 0:
                    cond_drop = (p99_now is not None and last_dec_p99_ms is not None and 
                                 p99_now <= last_dec_p99_ms * (1.0 - DECEL_P99_WAIT_DROP_FRAC))
                    cond_abs = (abs_thr is not None and p99_now is not None and p99_now <= abs_thr)
                    time_ok = (time.time() - last_dec_ts_global) >= DECEL_HOLD_SEC
                    if not (time_ok and (cond_drop or cond_abs)):
                        d_rate_frac = 0.0
            except Exception:
                pass

            m_ts  = LATEST_METRICS.get("ts")
            m_win = LATEST_METRICS.get("window_sec") or 0
            if USE_APP_METRICS and m_ts and (now - m_ts) > max(10.0, 1.5 * m_win):
                reward = None
            else:
                reward = compute_reward(
                    LATEST_METRICS,
                    ewma_rtt_us=ewma_rtt_us, snd_ratio=snd_ratio, rcv_ratio=rcv_ratio,
                    queue_pressure=queue_pressure, had_retrans=had_retrans,
                    current_rate=current_rate, SLO_p99_ms=SLO_P99_MS,
                )

            applied = False; applied_cmds = []
            if RL_MODE == "online":
                can_apply, new_rate, new_batch = shield.clamp(now, current_rate, current_batch, d_rate_frac, d_batch)
                if can_apply and (new_rate != current_rate or new_batch != current_batch):
                    cmds = [
                        {"cmd":"throttle","rate": int(new_rate)},
                        {"cmd":"batch","size": int(new_batch)}
                    ]
                    if cli is not None:
                        for c in cmds:
                            cli.publish(CONTROL_TOPIC, json.dumps(c), qos=1)
                    current_rate, current_batch = new_rate, new_batch
                    applied = True; applied_cmds = cmds
                    _emit(json.dumps({"ts":now,"applied":True,"rate":current_rate,"batch":current_batch}))
                    try:
                        if d_rate_frac < 0.0:
                            last_dec_ts_global = now
                            last_dec_p99_ms = LATEST_METRICS.get("p99_ms") if isinstance(LATEST_METRICS, dict) else None
                            tuner_decel_applied += 1
                    except Exception:
                        pass

            next_state = make_state(ewma_rtt_us, snd_ratio, rcv_ratio, had_retrans, queue_pressure,
                                    current_rate, current_batch, {"d_rate": d_rate_frac, "d_batch": d_batch})

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
            try:
                mts = LATEST_METRICS.get("ts")
                mwin = LATEST_METRICS.get("window_sec")
                if mts and mwin:
                    rec["metrics_fresh_sec"] = round(now - float(mts), 3)
            except Exception:
                pass
            log_transition(RL_LOG_PATH, rec)
            last_action = {"d_rate": d_rate_frac, "d_batch": d_batch}

            # Tuner: collect window stats
            try:
                n = LATEST_METRICS.get("n"); w = LATEST_METRICS.get("window_sec"); p99 = LATEST_METRICS.get("p99_ms")
                if isinstance(n,(int,float)) and isinstance(w,(int,float)) and w>0:
                    tuner_thr.append(n/ w)
                if isinstance(p99,(int,float)):
                    tuner_p99.append(p99)
            except Exception:
                pass

            # Tuner: evaluate/switch arms
            if TUNER_ENABLE and tuner_grid and (now - tuner_last_switch) >= TUNER_EVAL_SEC:
                thr_mean = float(sum(tuner_thr)/len(tuner_thr)) if tuner_thr else 0.0
                p99_med  = float(sorted(tuner_p99)[len(tuner_p99)//2]) if tuner_p99 else float('inf')
                tgt = max(THROUGHPUT_TARGET, 1.0)
                slo = max(SLO_P99_MS, 1.0)
                thr_score = min(thr_mean / tgt, 1.2)
                tail_pen  = max((p99_med / slo), 0.0)
                decel_pen = tuner_decel_applied / max(1, len(tuner_thr))
                alpha, beta, gamma = 1.0, 0.7, 0.3
                score = alpha*thr_score - beta*tail_pen - gamma*decel_pen

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
                    cands = [i for i,q in enumerate(tuner_Q) if q==best]
                    next_idx = random.choice(cands)

                bw, pw, aw, ascale, dcap, hold, floor = tuner_grid[next_idx]

                # Apply parameters to agent module globals
                import eda_rl_agent
                eda_rl_agent.THROUGHPUT_BONUS_WEIGHT = float(bw)
                eda_rl_agent.THROUGHPUT_PENALTY_WEIGHT = float(pw)
                eda_rl_agent.THROUGHPUT_ABS_WEIGHT = float(aw)
                eda_rl_agent.THROUGHPUT_ABS_SCALE = float(ascale)
                eda_rl_agent.MAX_DECEL_FRAC = float(dcap)
                eda_rl_agent.DECEL_HOLD_SEC = float(hold)
                eda_rl_agent.THROUGHPUT_MIN_FLOOR = float(floor)

                try:
                    shield.max_decel_frac = float(dcap)
                    shield.decel_hold_sec = float(hold)
                except Exception:
                    pass

                _emit(json.dumps({
                    "tuner": {
                        "ts": now, "arm_idx": next_idx,
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

        prev_totals = snapshot

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
