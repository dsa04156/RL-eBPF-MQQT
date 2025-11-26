#!/usr/bin/env python3
# ppo_plot_pro.py
#
# ppo_train.jsonl -> 발표용 "학습 과정 개요" 그림 1장 생성

import json
import math
import numpy as np
import matplotlib.pyplot as plt

LOG_PATH = "ppo_train.jsonl"
WINDOW = 50  # 이동평균 윈도우 (슬라이드용이니까 좀 크게 해서 매끈하게)

# -------------------------------------------------
# 1) 로그 읽기
# -------------------------------------------------
steps = []
rewards = []
p99s = []
thrs = []

with open(LOG_PATH, "r") as f:
    for i, line in enumerate(f):
        line = line.strip()
        if not line:
            continue
        o = json.loads(line)

        steps.append(i)
        rewards.append(o.get("r", 0.0))

        m = o.get("metrics") or {}
        p99 = m.get("p99_ms")
        thr = m.get("thr")

        p99s.append(p99 if p99 is not None else float("nan"))
        thrs.append(thr if thr is not None else float("nan"))

steps = np.asarray(steps, dtype=float)
rewards = np.asarray(rewards, dtype=float)
p99s = np.asarray(p99s, dtype=float)
thrs = np.asarray(thrs, dtype=float)


def moving_avg(x, w):
    """단순 이동평균"""
    if len(x) < w:
        return x, np.arange(len(x))
    ma = np.convolve(x, np.ones(w) / w, mode="valid")
    idx = np.arange(w - 1, w - 1 + len(ma))
    return ma, idx


# -------------------------------------------------
# 2) 이동평균 계산
# -------------------------------------------------
reward_ma, reward_ma_idx = moving_avg(rewards, WINDOW)

valid_p99 = ~np.isnan(p99s)
valid_thr = ~np.isnan(thrs)

# -------------------------------------------------
# 3) 스타일 설정 (좀 그럴듯하게)
# -------------------------------------------------
plt.style.use("seaborn-v0_8")  # 내장 스타일이라 추가 설치 필요 없음

fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
fig.suptitle("PPO Training Progress", fontsize=14)

# -------------------------------------------------
# (1) 위 그래프: Reward
# -------------------------------------------------
ax0 = axes[0]
ax0.plot(steps, rewards, alpha=0.25, linewidth=1.0, label="Reward (raw)")
ax0.plot(steps[reward_ma_idx], reward_ma, linewidth=2.0,
         label=f"Reward (moving avg, w={WINDOW})")

ax0.set_ylabel("Reward")
ax0.grid(True, linestyle="--", alpha=0.4)
ax0.legend(loc="best", frameon=True)

# -------------------------------------------------
# (2) 아래 그래프: p99 + Throughput (twin axis)
# -------------------------------------------------
ax1 = axes[1]
ax1.plot(steps[valid_p99], p99s[valid_p99],
         linewidth=1.5, label="p99 latency (ms)")

ax1.set_ylabel("p99 (ms)")
ax1.grid(True, linestyle="--", alpha=0.4)

# twin y-axis for throughput
ax2 = ax1.twinx()
ax2.plot(steps[valid_thr], thrs[valid_thr],
         linewidth=1.5, linestyle="--", label="Throughput (msg/s)")

ax2.set_ylabel("Throughput (msg/s)")

ax1.set_xlabel("Training step")

# 두 축 레전드 합치기
lines1, labels1 = ax1.get_legend_handles_labels()
lines2, labels2 = ax2.get_legend_handles_labels()
ax1.legend(lines1 + lines2, labels1 + labels2,
           loc="upper right", frameon=True)

fig.tight_layout(rect=[0, 0.0, 1, 0.96])
fig.savefig("ppo_training_overview.png", dpi=300)
print("saved: ppo_training_overview.png")
