# eBPF‑Guided Reinforcement Learning for MQTT Network Optimization

## Abstract

This work presents a practical methodology to optimize MQTT traffic under adverse and dynamic network conditions using kernel‑level signals and reinforcement‑learning style control. We combine low‑overhead eBPF instrumentation (RTT, retransmissions, socket buffer pressure) with application‑level latency snapshots to drive a policy that adjusts publisher throttle and batch size in real time. Our key contributions are: (1) a clean state/action representation that bridges kernel telemetry and MQTT control, (2) a reward design that preserves target throughput while reducing tail latency, (3) a fair evaluation protocol that compares results at matched throughput bands and stabilized windows, and (4) a reproducible toolchain (netem, log comparators, dataset filters, BC training scripts) that enables rapid iteration. Experiments on a controlled netem testbed show significant tail improvements at matched throughput compared to a baseline configuration, with kernel p99 cut from hundreds of milliseconds to tens, and application p99 mean reduced to sub‑second levels at the same throughput band.

## 1. Introduction and Problem Statement

MQTT is increasingly used for telemetry and edge streaming workloads that are sensitive to tail latency (e.g., p99 of end‑to‑end delivery time). In volatile networks (variable delay/loss), static publisher settings cause unacceptable tail latencies or force a throughput compromise. Our goal is to design a controller that reduces tail latency while maintaining a target application throughput (messages per second).

Challenges:
- Tail latency is influenced by multiple layers: TCP congestion control, socket buffers, broker behaviors, QoS, batching, and application backpressure.
- Traditional black‑box control (application metrics only) reacts slowly and can be noisy; kernel signals are needed for faster, low‑overhead detection of incipient congestion.
- Fair comparison requires matched throughput; simply throttling to reduce p99 is not acceptable in performance‑critical pipelines.

Contributions:
- An eBPF‑based observability path that streams kernel TCP signals (srtt_us, retransmissions, sndbuf/rcvbuf usage) with minimal overhead.
- A state/action formulation and a shielded continuous controller (rate/batch) that can be rule‑based or learned via behavioral cloning (BC) and later upgraded to online RL.
- A reward shaping design that combines tail penalties with target/absolute throughput bonuses, enabling the controller to “push” throughput without exploding tails.
- A matched‑throughput evaluation protocol (band‑matching + stabilization window) and scripts that automate comparison, dataset filtering, and model training.

## 2. System Overview

Architecture:
- Publisher(s) send MQTT messages to an EMQX broker; Subscriber(s) consume and publish periodic metrics snapshots on topic `eda/latency` with `{p50_ms, p95_ms, p99_ms, n, window_sec, total_msgs}`.
- eBPF agents (Python + BCC) observe TCP events for MQTT sockets: smoothed RTT (srtt_us), retransmit events, socket buffer usage (`sk_wmem_queued`, `sk_rmem_alloc`).
- Control agent (`bpf/eda_rl.py`) computes actions every interval and publishes JSON control commands over MQTT topic `control/room1`:
  - `{"cmd":"throttle","rate": R}` (Hz) and `{"cmd":"batch","size": B}`.
- Logs are serialized to JSONL as (s, a, r, s′, metrics, kernel, applied, cmds, metrics_fresh_sec) for both analysis and training.

Key implementation units in repo:
- Kernel observability: `bpf/eda.py`, `bpf/eda_rl.py` (eBPF programs embedded as strings, BCC for attach).
- Control/learning: `bpf/eda_rl.py` (rule and torch backends; shielded actuation).
- Dataset tooling: `rl/prep_dataset.py` (now with throughput/tail/freshness filters), `rl/train_bc.py`.
- Evaluation: `bench/compare_logs_1.py` (matched table output), `bench/netem_on.sh` (egress netem), optional IFB recipe for ingress.

## 3. eBPF Observability

Signals per MQTT socket (filtered by port, default 23232):
- RTT (srtt_us) recorded from `tcp_sock`; right‑shifted by 3 to normalize internal kernel scaling.
- Retransmissions via `tcp:tcp_retransmit_skb` tracepoint.
- Sender/receiver buffer usage via `sk_wmem_queued`, `sk_rmem_alloc`.

Sampling and logging:
- 2‑second interval aggregation of per‑flow measurements; per‑flow JSON lines include `rtt_ms`, `retrans_delta`, `sndbuf`, `rcvbuf`.
- A second logical stream captures application metrics snapshots from subscriber topic `eda/latency`.

Design considerations:
- eBPF path is strictly read‑only; no packet rewrite or heavy per‑event processing.
- Signals are chosen for early congestion detection: rising RTT EWMA, retrans bursts, buffer pressure.

## 4. State, Action, and Shielded Control

State vector s (9D, normalized):
1. `rtt_norm` = min(ewma_rtt_us / (SLO_P99_MS * 1000), 10.0)
2. `snd_ratio` = tanh(sndbuf / (2 * TH_SNDBUF))
3. `rcv_ratio` = tanh(rcvbuf / (2 * TH_RCVBUF))
4. `had_retrans` ∈ {0,1}
5. `queue_pressure` = tanh(max(snd_ratio_raw, rcv_ratio_raw) / 2)
6. `rate_norm` = current_rate / R_MAX
7. `batch_norm` = current_batch / B_MAX
8–9. previous action components (d_rate, d_batch) clamped

Actions a (continuous + discrete):
- `d_rate` ∈ [−0.2, +0.2] as a multiplicative step; `d_batch` ∈ {−1, 0, +1}.

Shield:
- `MAX_STEP_FRAC`: caps |Δrate| per actuation; `COOLDOWN_SEC`: minimum time between effectual changes.
- Optional `CLAMP_ACCEL_ON_CONGESTION`: disable positive rate changes when congestion flag is true.

Backends:
- RuleAgent: deterministic score from (latency, buffer, retrans); gentle deceleration when congested, modest acceleration when stabilized.
- TorchAgent: BC policy; actions clamped (+ε exploration and online update can be added in future work).

## 5. Reward Shaping (for RL formulation and logging)

Objective: preserve or elevate throughput while preventing pathological tails.

Components:
- Tail penalty (kernel‑proxy when app metrics are stale):
  - weighted sum of `rtt_norm`, `queue_pen`, `snd_pen`, `rcv_pen`, `retrans_pen`.
- Throughput bonus/penalty:
  - target‑ratio terms: `throughput_ratio = (n / window_sec) / THROUGHPUT_TARGET` with bonus for >1, penalty for <1.
  - absolute throughput bonus: `min(throughput / THROUGHPUT_ABS_SCALE, 2.0) * THROUGHPUT_ABS_WEIGHT`.

Notes:
- In this codebase, rewards are logged and used for off‑policy analysis; the deployed BC policy itself does not update online yet. The shaping accelerates future on‑policy upgrades (PPO/AC) and improves interpretability of logged (s,a,r).

## 6. Dataset Curation and Band‑Matching

Why band‑matching? Fairness. We compare tails at the same application throughput band. Without this, “lower tails” can be a trivial artifact of lower load.

Filters (implemented in `rl/prep_dataset.py`):
- `--min_thr / --max_thr`: include samples within a throughput band (msg/s) computed as `n / window_sec`.
- `--p99_cap`: drop samples with extreme app p99 (e.g., > 8000 ms) to avoid poisoning BC by pathological episodes.
- `--fresh_max`: ignore snapshots older than a threshold (metrics_fresh_sec) to avoid repeated stale entries.
- `--applied_only`: keep only records where control was actually applied.

Recommended bands:
- Baseline band: 39 ± 5 msg/s.
- Observe band: 160 ± 15 msg/s.

Stabilization window:
- For evaluation, select the last 180 seconds of each run or use freshness to ensure comparisons reflect stabilized behavior.

## 7. Experimental Protocol

Network emulation (netem):
- Use `bench/netem_on.sh` to apply HTB + netem on egress of the physical interface (e.g., `enp0s8`).
- For ingress control, add an IFB device and redirect ingress to IFB with netem.

Routing sanity checks:
- `ip route get $BROKER` → ensure path uses the interface under netem.
- `sudo tcpdump -i enp0s8 -nn 'port 23232'` to confirm actual MQTT traffic.

Execution modes:
- Observe only: `EDA_OBSERVE=1` (no control). Use to build baselines.
- Rule runs: collect logs with active control to generate diverse (s,a) coverage.
- Torch runs: deploy BC policy for evaluation at specific bands.

Reproducibility commands:
```bash
# Rule: multi‑run collection (10 min × 6)
for i in {1..6}; do
  LOG_TS=$(date +%Y%m%d_%H%M%S)
  sudo -E RL_BACKEND=rule RL_MODE=online \
    USE_APP_METRICS=0 THROUGHPUT_TARGET=160 \
    MAX_STEP_FRAC=0.30 COOLDOWN_SEC=0.10 CLAMP_ACCEL_ON_CONGESTION=0 \
    RL_LOG_PATH=$(pwd)/logs/kernel_only/eda_rl_kernel_${LOG_TS}.jsonl \
    MQTT_HOST=$BROKER MQTT_PORT=$PORT \
    CONTROL_TOPIC=control/room1 METRICS_TOPIC=eda/latency \
    timeout 600s /usr/bin/python3 bpf/eda_rl.py \
    > logs/kernel_only/eda_rl_kernel_${LOG_TS}.out 2>&1
done

# Merge rule logs
rg -l '"backend": "rule"' logs/kernel_only/eda_rl_kernel_*.jsonl | xargs cat > \
  logs/kernel_only/eda_rl_kernel_rule_merged.jsonl

# Dataset (observe band 160 ± 15 msg/s)
python3 rl/prep_dataset.py logs/kernel_only/eda_rl_kernel_rule_merged.jsonl \
  --out logs/kernel_only/dataset_band160.npz \
  --min_thr 145 --max_thr 175 --p99_cap 8000 --fresh_max 45 --applied_only

# Train BC
source ~/myenv/bin/activate
python3 rl/train_bc.py --data logs/kernel_only/dataset_band160.npz \
  --out models/bc_band160.pt --epochs 160 --bs 128 --lr 3e-4 --val_split 0.2

deactivate

# Run RL (torch) at band 160
LOG_TS=$(date +%Y%m%d_%H%M%S)
sudo -E USE_APP_METRICS=0 \
  THROUGHPUT_TARGET=160 \
  THROUGHPUT_BONUS_WEIGHT=2.0 THROUGHPUT_PENALTY_WEIGHT=0.6 \
  THROUGHPUT_ABS_WEIGHT=0.6 THROUGHPUT_ABS_SCALE=120 \
  MAX_STEP_FRAC=0.30 COOLDOWN_SEC=0.10 CLAMP_ACCEL_ON_CONGESTION=0 \
  RL_MODE=online RL_BACKEND=torch \
  RL_MODEL_PATH=$(pwd)/models/bc_band160.pt \
  RL_LOG_PATH=$(pwd)/logs/kernel_only/eda_rl_kernel_${LOG_TS}.jsonl \
  MQTT_HOST=$BROKER MQTT_PORT=$PORT \
  CONTROL_TOPIC=control/room1 METRICS_TOPIC=eda/latency \
  /usr/bin/python3 bpf/eda_rl.py \
  > logs/kernel_only/eda_rl_kernel_${LOG_TS}.out 2>&1 &

# Compare (band‑matched or stabilized)
python3 bench/compare_logs_1.py results/eda_observe_run2.jsonl \
  logs/kernel_only/eda_rl_kernel_${LOG_TS}.jsonl
```

## 8. Evaluation Metrics and Tables

Primary metric: Application throughput (`n / window_sec`) and p99 latency (median/mean/95th/99th) at matched bands. Secondary: kernel RTT percentiles (p50/p90/p95/p99).

Reporting tips:
- Use stabilization windows (e.g., last 180 s) or freshness filtering to avoid counting repeated snapshots.
- For EMQX dashboard “out rate” (MQTT frames/s), report batch size alongside and note the reconciliation: App msgs/s ≈ (Frames/s) × (batch size).

## 9. Representative Results (from this repository)

Illustrative summaries (exact values depend on runs; band‑matching applied in analysis scripts):

- Observe run1 (high load): throughput ≈ 190 msg/s; app p99 mean ≈ 150 s (extremely long tails).
- Observe run2: throughput ≈ 160 msg/s; app p99 mean ≈ 5.8 s.
- Baseline (our_run_final): throughput ≈ 39 msg/s; app p99 mean ≈ 6.9 s; app p99 99th ≈ 32 s.
- RL (stabilized, baseline band): throughput ≈ 39.16 msg/s; kernel p99 ≈ 63 ms; app p99 mean ≈ 0.51 s — large tail reduction at matched throughput.
- RL (higher throughput example): throughput ≈ 147.7 msg/s; app p99 ≈ 4.49 s — higher throughput preserved, moderate tail.

Key takeaway: At matched throughput (baseline band), RL reduces both kernel and app tails significantly; at higher bands, tail reductions are harder but still achievable with shaping and shield tuning.

## 10. Ablations and Sensitivity

Throughput shaping weights:
- Increasing `THROUGHPUT_BONUS_WEIGHT` and `THROUGHPUT_ABS_WEIGHT` induces more aggressive acceleration; if tails grow, increase `THROUGHPUT_PENALTY_WEIGHT` and queue/RTT penalty weights.

Shield parameters:
- Lower `MAX_STEP_FRAC` (e.g., 0.25) and higher `COOLDOWN_SEC` (e.g., 0.15–0.2) mitigate precipitous drops when negative actions trigger.
- Consider asymmetric clamps: cap negative `d_rate` at −0.10 while allowing positive up to +0.20.

Batch limits:
- Constrain `B_MAX` (e.g., 8–16) to avoid extreme batch escalation that may desynchronize app msgs/s and MQTT frames/s.

Ingress vs egress netem:
- Egress‑only netem does not degrade inbound ACKs; add IFB ingress shaping for symmetric realism.

## 11. Threats to Validity

- BC policy is fixed; no online policy updates — sensitivity to non‑stationarity.
- Metrics duplication: repeated snapshots inflate counts unless filtered by freshness or dedup.
- Single‑host or specific netem parameters; generalization beyond this setup requires further validation.

## 12. Related Work (Brief)

- Kernel‑assisted transport optimization: eBPF programs for TCP diagnostics and AQM.
- Application‑aware congestion control: controllers that integrate app SLOs with networking metrics.
- RL for systems: BC/PPO‑based schedulers, congestion control (e.g., Remy‑like), and queue management.

## 13. Conclusion and Future Work

We introduced a practical RL‑style control methodology for MQTT traffic that leverages eBPF signals and app snapshots to maintain throughput while cutting tail latency. The approach is deployable with minimal overhead, yields fair apples‑to‑apples comparisons via band‑matching and stabilization, and provides a reproducible pipeline from logging to training to evaluation. Future work integrates on‑policy updates (PPO/AC), multi‑flow fairness, and broader topologies.

## Appendix A. Quick Reference

File overview:
- `bpf/eda.py`: eBPF observer (observe/control toggle via EDA_OBSERVE).
- `bpf/eda_rl.py`: RL/BC agent with shield and reward shaping; logs (s, a, r, s′).
- `rl/prep_dataset.py`: dataset creation with throughput/tail/freshness filters.
- `rl/train_bc.py`: BC training.
- `bench/compare_logs_1.py`: table comparison (kernel RTT, throughput, app pxx).
- `bench/netem_on.sh`: HTB + netem egress script.

Band‑matched evaluation checklist:
1) Collect rule runs under netem.
2) Merge to `logs/kernel_only/eda_rl_kernel_rule_merged.jsonl`.
3) Create dataset with `--min_thr/--max_thr` for the desired band, apply `--p99_cap/--fresh_max`.
4) Train BC and run torch agent with matching `THROUGHPUT_TARGET`.
5) Extract stabilization window (e.g., last 180 s) and compare against baseline/observe.

