#!/usr/bin/env python3
"""Plot throughput/p99 curves comparing four controllers under each scenario."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, List
import math
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
NORM_ROOT = ROOT / "logs" / "2로그정리"
OUTPUT_DIR = ROOT / "results" / "plots"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

METHODS = {
    "Baseline": NORM_ROOT / "baseline",
    "BBR": NORM_ROOT / "bbr",
    "EMQX+RL": NORM_ROOT / "emqttrl",
    "EMQX": NORM_ROOT / "emqx_flow_control",
}

SCENARIOS: Dict[str, Dict[str, str]] = {
    "Normal": {
        "Baseline": "normal_v1.jsonl",
        "BBR": "normal_v1.jsonl",
        "EMQX+RL": "normol_v1.jsonl",
        "EMQX": "normol_v1.jsonl",
    },
    "Dynamic": {
        "Baseline": "dynamic_v1.jsonl",
        "BBR": "dynamic_v1.jsonl",
        "EMQX+RL": "dynamic_v1.jsonl",
        "EMQX": "dynamic_v1.jsonl",
    },
    "Congestion": {
        "Baseline": "congestion_v1.jsonl",
        "BBR": "congestion_v1.jsonl",
        "EMQX+RL": "congestion_v1.jsonl",
        "EMQX": "congestion_v1.jsonl",
    },
}

COLORS = {
    "Baseline": "#4c72b0",
    "BBR": "#dd8452",
    "EMQX+RL": "#55a868",
    "EMQX": "#c44e52",
}


def load_series(path: Path) -> Dict[str, List[float]]:
    thr: List[float] = []
    p99: List[float] = []
    if not path.exists():
        return {"thr": thr, "p99": p99}
    with path.open() as f:
        for line in f:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = rec.get("thr")
            p = rec.get("p99_ms")
            thr.append(float(t) if isinstance(t, (int, float)) else math.nan)
            p99.append(float(p) if isinstance(p, (int, float)) else math.nan)
    return {"thr": thr, "p99": p99}


def plot_scenario(scenario: str, files: Dict[str, str]):
    fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    x = None
    for method, rel in files.items():
        data_dir = METHODS.get(method)
        if data_dir is None:
            continue
        series = load_series(data_dir / rel)
        thr = series["thr"]
        p99 = series["p99"]
        if not thr:
            continue
        if x is None:
            x = [i / (len(thr) - 1) * 100 for i in range(len(thr))]
        axes[0].plot(x, thr, label=method, color=COLORS.get(method))
        axes[1].plot(x, p99, label=method, color=COLORS.get(method))
    axes[0].set_ylabel("Throughput (msg/s)")
    axes[1].set_ylabel("P99 Latency (ms)")
    axes[1].set_xlabel("Experiment Progress (%)")
    axes[0].set_title(f"Scenario: {scenario}")
    axes[0].grid(True, linestyle="--", alpha=0.4)
    axes[1].grid(True, linestyle="--", alpha=0.4)
    axes[0].legend()
    fig.tight_layout()
    out_path = OUTPUT_DIR / f"scenario_{scenario.lower()}_comparison.png"
    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    print("Saved", out_path)


def main():
    for scenario, mapping in SCENARIOS.items():
        plot_scenario(scenario, mapping)


if __name__ == "__main__":
    main()
