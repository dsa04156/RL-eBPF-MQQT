#!/usr/bin/env python3
"""Deduplicate experiment logs and resample to a consistent length."""
from __future__ import annotations
import json
import math
from pathlib import Path
from statistics import median
from typing import Dict, Iterable, List, Tuple

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RAW_DIRS = [
    ROOT / "logs" / "baseline",
    ROOT / "logs" / "bbr",
    ROOT / "logs" / "emqx_flow_control",
    ROOT / "logs" / "1로그정리" / "emqttrl",
]
TARGET_LEN = 400
OUT_ROOT = ROOT / "logs" / "normalized"


def iter_logs() -> Iterable[Tuple[Path, Path]]:
    for raw_dir in RAW_DIRS:
        if not raw_dir.exists():
            continue
        for path in sorted(raw_dir.glob("*.jsonl")):
            yield raw_dir, path


def parse_metrics(path: Path) -> Tuple[List[float], List[float]]:
    thr_vals: List[float] = []
    p99_vals: List[float] = []
    with path.open() as f:
        for line in f:
            if not line.strip():
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
    return thr_vals, p99_vals


def deduplicate(values: List[float], other: List[float]) -> Tuple[List[float], List[float]]:
    if not values:
        return values, other
    new_thr: List[float] = []
    new_p99: List[float] = []
    last = None
    for t, p in zip(values, other):
        key = (round(t, 6), round(p, 6))
        if key == last:
            continue
        new_thr.append(t)
        new_p99.append(p)
        last = key
    return new_thr, new_p99


def resample(values: List[float], target_len: int) -> List[float]:
    if not values:
        return [math.nan] * target_len
    if len(values) == target_len:
        return values
    xs = np.linspace(0, len(values) - 1, num=len(values))
    target_xs = np.linspace(0, len(values) - 1, num=target_len)
    return np.interp(target_xs, xs, values).tolist()


def main():
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    summary = []
    for raw_dir, path in iter_logs():
        thr, p99 = parse_metrics(path)
        thr, p99 = deduplicate(thr, p99)
        thr = resample(thr, TARGET_LEN)
        p99 = resample(p99, TARGET_LEN)
        out_dir = OUT_ROOT / raw_dir.name
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / path.name
        with out_path.open("w") as f:
            for idx, (t, p) in enumerate(zip(thr, p99)):
                rec = {
                    "idx": idx,
                    "thr": t,
                    "p99_ms": p,
                    "source": str(path.relative_to(ROOT)),
                }
                f.write(json.dumps(rec) + "\n")
        summary.append((path.relative_to(ROOT), len(thr)))
    for rel, length in summary:
        print(f"{rel}: normalized_len={length}")
    print(f"Normalized logs saved under {OUT_ROOT}")


if __name__ == "__main__":
    main()
