#!/usr/bin/env python3
import json
from pathlib import Path
from statistics import median
from typing import Dict, List, Tuple
import math
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
LOG_ROOT = ROOT / "logs" / "1로그정리"
OUTPUT_DIR = ROOT / "results" / "plots"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

EXPERIMENTS = {
    "Base": LOG_ROOT / "base",
    "BBR": LOG_ROOT / "bbr",
    "EMQX+RL": LOG_ROOT / "emqttrl",
    "EMQX": LOG_ROOT / "emqx",
}

SCENARIOS = {
    "Normal": "normal_v1.jsonl",
    "Dynamic": "dynamic_v1.jsonl",
    "Congestion": "congestion_v1.jsonl",
}

ALT_FILENAMES = {
    ("EMQX+RL", "Normal"): "normol_v1.jsonl",
}

def read_metrics(path: Path) -> Tuple[float, float]:
    thr_vals: List[float] = []
    p99_vals: List[float] = []
    if not path.exists():
        return math.nan, math.nan
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            metrics: Dict = rec.get("metrics") or {}
            p99 = metrics.get("p99_ms")
            if isinstance(p99, (int, float)):
                p99_vals.append(float(p99))
            thr = metrics.get("thr")
            if not isinstance(thr, (int, float)):
                n = metrics.get("n")
                win = metrics.get("window_sec") or 0
                if isinstance(n, (int, float)) and isinstance(win, (int, float)) and win > 0:
                    thr = float(n) / float(win)
            if isinstance(thr, (int, float)):
                thr_vals.append(float(thr))
    thr_med = median(thr_vals) if thr_vals else math.nan
    p99_med = median(p99_vals) if p99_vals else math.nan
    return thr_med, p99_med

stats = {scenario: {} for scenario in SCENARIOS}

for scenario, default_file in SCENARIOS.items():
    for exp_name, exp_dir in EXPERIMENTS.items():
        fname = ALT_FILENAMES.get((exp_name, scenario), default_file)
        thr_med, p99_med = read_metrics(exp_dir / fname)
        stats[scenario][exp_name] = {"thr": thr_med, "p99": p99_med}


def plot_metric(metric: str, ylabel: str, suffix: str):
    fig, ax = plt.subplots(figsize=(10, 5))
    experiments = list(EXPERIMENTS.keys())
    x_positions = list(range(len(SCENARIOS)))
    total = len(experiments)
    width = 0.18
    for idx, exp_name in enumerate(experiments):
        values = [stats[scenario].get(exp_name, {}).get(metric, math.nan) for scenario in SCENARIOS]
        offsets = [x + (idx - (total - 1) / 2) * width for x in x_positions]
        ax.bar(offsets, values, width=width, label=exp_name)
    ax.set_xticks(x_positions)
    ax.set_xticklabels(SCENARIOS.keys())
    ax.set_ylabel(ylabel)
    ax.set_title(f"Median {ylabel} per Scenario")
    ax.legend()
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    fig.tight_layout()
    out_path = OUTPUT_DIR / f"experiment_{suffix}.png"
    fig.savefig(out_path, dpi=200)
    plt.close(fig)

plot_metric("thr", "Throughput (msg/s)", "throughput")
plot_metric("p99", "P99 Latency (ms)", "p99")

print("Saved plots to", OUTPUT_DIR)
