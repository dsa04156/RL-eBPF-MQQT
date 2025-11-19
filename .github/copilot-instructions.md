# RL-eBPF-MQTT: AI Coding Agent Instructions

## Project Overview
This is an eBPF-based reinforcement learning system for MQTT tail latency reduction through dynamic rate and batch size control. The core agent (`bpf/eda_rl.py`) collects kernel TCP signals (RTT, retransmissions, buffer usage) via eBPF probes and adjusts publisher behavior based on subscriber latency metrics received via MQTT.

**Critical Context**: This is a research prototype (master's thesis) combining eBPF kernel tracing, MQTT pub/sub, and online/shadow RL modes. Always preserve safety guards (cooldowns, step limits, throughput floors) when modifying control logic.

## Architecture & Data Flow

### 1. eBPF Kernel Data Collection
- **Probes**: `tcp_sendmsg`, `tcp_rcv_established`, `tcp:tcp_retransmit_skb` (`bpf/eda_rl.py:1091`)
- **Maps**: Per-flow aggregation → userspace EWMA smoothing every `INTERVAL_S` (default 2.0s)
- **Signals**: `ewma_rtt_us`, `snd_ratio` (wmem/sndbuf), `rcv_ratio`, `had_retrans`, `congestion_score`

### 2. MQTT Integration
- **Topics**:
  - `eda/latency` (subscribe): Subscriber p50/p95/p99 latency metrics (JSON)
  - `control/room1` (publish): Publisher control commands: `{"throttle": rate, "batch": size}`
- **Port Filtering**: eBPF filters by `MQTT_TRACK_PORT` (default=`MQTT_PORT`) to avoid self-trapping

### 3. RL Control Loop
```
State (9D) → Agent → Action → Shield → MQTT Publish
  ↑                                         ↓
  └─── Reward ← App Metrics ← Subscriber ──┘
```
- **State**: `[rtt_norm, snd_norm, rcv_norm, retrans, queue, rate_norm, batch_norm, last_d_rate, last_d_batch]`
- **Action**: `d_rate ∈ [-0.2, 0.2]`, `d_batch ∈ {-1, 0, 1}`
- **Shield**: MAX_STEP_FRAC, COOLDOWN_SEC, DECEL_HOLD_SEC, throughput floor checks
- **Backends**: `rule` (heuristic) or `torch` (TorchScript model)

### 4. Modes
- **Shadow** (`RL_MODE=shadow`): Logs (s,a,r,s') without applying actions → used for offline BC training
- **Online** (`RL_MODE=online`): Applies shielded actions to control publisher

## Key Developer Workflows

### Running the Agent
```bash
# Shadow mode (data collection)
USE_GYM_ENV=1 RL_MODE=shadow RL_LOG_PATH=logs/eda_rl.jsonl python3 bpf/eda_rl.py

# Online mode with rule-based control
USE_GYM_ENV=1 RL_MODE=online RL_BACKEND=rule python3 bpf/eda_rl.py

# Online mode with PyTorch model
USE_GYM_ENV=1 RL_MODE=online RL_BACKEND=torch RL_MODEL_PATH=models/bc_kernel_only.pt python3 bpf/eda_rl.py
```

### Training Behavior Cloning Model
```bash
# 1. Collect shadow data (run agent in shadow mode)
# 2. Prepare dataset
python3 rl/prep_dataset.py --input logs/eda_rl.jsonl --output dataset.npz

# 3. Train BC model
python3 rl/train_bc.py --data dataset.npz --out models/my_model.pt --epochs 25
```

### Visualizing RL Training
```bash
# Generates training curves, P99 reduction, action distribution, entropy, TD error
python3 bench/visualize_rl_training.py --log logs/eda_rl_torch_online.jsonl --output-dir results/rl_analysis
```

### Running Experiments with Dynamic Network Conditions
```bash
# Apply time-varying network delay/loss
sudo IF=eth0 PHASE_DUR=30 CYCLES=1 bash bench/netem_dynamic.sh

# Run baseline (no control)
python3 clients/mqtt_publisher.py &
python3 clients/mqtt_subscriber.py &

# Run with RL control (in separate terminal)
python3 bpf/eda_rl.py
```

## Critical Patterns & Conventions

### Safety Guards (NEVER bypass without justification)
1. **Step Limiting**: `MAX_STEP_FRAC=0.2` → rate changes capped at ±20% per step
2. **Cooldown**: `COOLDOWN_SEC` enforces minimum wait between control actions
3. **Deceleration Hold**: `DECEL_HOLD_SEC` prevents rapid successive rate drops
4. **Throughput Floor**: `THROUGHPUT_MIN_FLOOR` blocks deceleration if throughput too low
5. **Congestion-Aware**: `CLAMP_ACCEL_ON_CONGESTION=1` suppresses acceleration during congestion

**Location**: Shield application in `bpf/eda_rl.py:404-487` (function `apply_shield`)

### Environment Variables (see `bpf/eda_rl.py:42-102`)
- **RL Control**: `RL_MODE`, `RL_BACKEND`, `RL_MODEL_PATH`, `USE_GYM_ENV`
- **Rewards**: `SLO_P99_MS`, `THROUGHPUT_TARGET`, `THROUGHPUT_BONUS_WEIGHT`
- **eBPF**: `INTERVAL_S`, `EWMA_ALPHA`, `HI_RTT_US`, `TH_RETRANS`, `MQTT_TRACK_PORT`
- **Safety**: `MAX_STEP_FRAC`, `MAX_DECEL_FRAC`, `COOLDOWN_SEC`, `DECEL_HOLD_SEC`

### Log Schema (JSONL)
Each line in `logs/eda_rl.jsonl`:
```json
{
  "ts": 1758509275.34,
  "mode": "online",
  "backend": "torch",
  "s": [0.0386, 0.135, 0.0041, 1.0, 0.135, 0.005, 0.03125, 0.0, 0.0],
  "a_raw": {"d_rate": 0.0, "d_batch": 0},
  "a": {"d_rate": 0.0, "d_batch": 0},
  "r": 2.9547,
  "s_next": [...],
  "metrics": {"p50_ms": 10.7, "p95_ms": 2400.3, "p99_ms": 2689.2, "n": 5254},
  "kernel": {"ewma_rtt_us": 386040, "snd_ratio": 0.272, ...},
  "applied": false,
  "cmds": []
}
```

### PyTorch Model Requirements
- **Input**: 9D state vector (normalized)
- **Output**: 2D action `[d_rate_frac, d_batch_step]`
- **Format**: TorchScript (`.pt` file from `torch.jit.script`)
- **Loading**: `bpf/eda_rl.py:240-270` with fallback to rule-based if failed

## Code Navigation

### Core Files
- `bpf/eda_rl.py` (1572 lines): Main RL agent with eBPF integration
  - Lines 186-220: eBPF map aggregation
  - Lines 328-362: Reward computation
  - Lines 404-487: Shield application
  - Lines 651-900: Gym environment wrapper
  - Lines 1091-1120: eBPF program attachment
- `rl/train_bc.py`: Behavior cloning training script
- `rl/prep_dataset.py`: Convert JSONL logs to numpy dataset
- `bench/visualize_rl_training.py`: Training visualization tool

### Testing Infrastructure
- `bench/auto_test.sh`: Automated experiment runner
- `bench/netem_dynamic.sh`: Dynamic network condition injection
- `clients/mqtt_publisher.py`: Test publisher with throttle/batch control
- `clients/mqtt_subscriber.py`: Latency metric reporter

## Common Tasks

### Adding a New Reward Component
1. Modify reward computation in `bpf/eda_rl.py:328-362`
2. Add corresponding env vars in lines 42-102
3. Update shield constraints if reward changes behavior boundaries

### Adjusting Safety Constraints
1. Locate `apply_shield()` function (`bpf/eda_rl.py:404`)
2. Modify clamping logic (MAX_STEP_FRAC, cooldown checks, etc.)
3. Test in shadow mode first with `RL_MODE=shadow`

### Training a New Model
```bash
# 1. Collect diverse data (vary network conditions)
for i in {1..5}; do
  sudo bash bench/netem_dynamic.sh &
  RL_MODE=shadow python3 bpf/eda_rl.py
done

# 2. Merge and prepare dataset
python3 rl/prep_dataset.py --input "logs/eda_*.jsonl" --output dataset_merged.npz

# 3. Train with validation split
python3 rl/train_bc.py --data dataset_merged.npz --out models/new_model.pt --val_split 0.2
```

### Analyzing Results
- **Training Progress**: `python3 bench/visualize_rl_training.py --log logs/eda_rl.jsonl`
- **Performance Comparison**: `python3 bench/analyze_ppo_results.py` (compares baseline vs RL)
- **Live Monitoring**: `python3 bench/show_livedata.py` (real-time metric display)

## Debugging Tips

### eBPF Issues
- **Permission Denied**: Run with `sudo` or adjust capabilities
- **BPF Program Failed**: Check kernel version (need 4.14+), verify BCC installation
- **No Data**: Ensure `MQTT_TRACK_PORT` matches actual MQTT broker port

### MQTT Issues
- **No Metrics Received**: Check subscriber is publishing to correct topic (`METRICS_TOPIC`)
- **Commands Not Applied**: Verify publisher subscribes to `CONTROL_TOPIC`
- **Connection Refused**: Ensure broker is running (`systemctl status emqx` or similar)

### Model Loading Failures
- **TorchScript Error**: Model must be saved with `torch.jit.script()`, not `torch.save()`
- **Dimension Mismatch**: State vector changed? Retrain model with current state definition
- **Fallback to Rule**: Check logs for "Torch backend failed, falling back to rule" message

## Testing & Validation

### Unit Tests
- Currently: Manual testing with `bench/test_quick_run.sh`
- Coverage: eBPF data collection, MQTT round-trip, shield constraints

### Integration Tests
```bash
# Quick validation (30s run)
bash bench/quick_test_final.sh

# Full experiment with netem
bash bench/auto_test.sh
```

## References
- **Thesis PDF**: `KNUthesisformat (2).pdf` (Korean) - methodology, results, background
- **Methodology**: `docs/paper_methodology.md` (English) - experiment reproduction steps
- **RL Details**: `docs/EDA_RL_Methodology.md` - reward shaping, state design

## Notes for AI Agents
- **Preserve Guard Logic**: When modifying control flow, ALWAYS maintain safety constraints
- **Test in Shadow First**: New changes should be validated in shadow mode before online deployment
- **Respect Port Filtering**: eBPF must filter by MQTT_TRACK_PORT to avoid feedback loops
- **Model Training**: BC models expect 9D state input matching current state vector definition
- **Korean Comments**: Original codebase has Korean comments - preserve them for maintainability
