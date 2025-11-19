#!/usr/bin/env python3
import json
import statistics
import numpy as np

def summarize(path):
    data = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data.append(json.loads(line))
            except:
                continue
    
    if not data:
        return None
    
    cnt = len(data)
    mode = data[0].get('mode', 'unknown')
    backend = data[0].get('backend', 'unknown')
    
    applied_count = sum(1 for d in data if d.get('applied', False))
    applied_pct = applied_count * 100.0 / cnt if cnt else 0
    
    p99s = [d.get('metrics', {}).get('p99_ms') for d in data if d.get('metrics', {}).get('p99_ms')]
    p95s = [d.get('metrics', {}).get('p95_ms') for d in data if d.get('metrics', {}).get('p95_ms')]
    p50s = [d.get('metrics', {}).get('p50_ms') for d in data if d.get('metrics', {}).get('p50_ms')]
    
    rewards = [d.get('r') for d in data if d.get('r') is not None]
    
    actions = [d.get('a_raw', {}) or d.get('a', {}) for d in data]
    nonzero_actions = sum(1 for a in actions if a.get('d_rate', 0) != 0.0)
    nonzero_pct = nonzero_actions * 100.0 / cnt if cnt else 0
    
    accel_count = sum(1 for a in actions if a.get('d_rate', 0) > 0.01)
    decel_count = sum(1 for a in actions if a.get('d_rate', 0) < -0.01)
    
    congestion_scores = [d.get('kernel', {}).get('congestion_score', 0) for d in data if 'kernel' in d]
    congested_count = sum(1 for d in data if d.get('kernel', {}).get('congested', False))
    
    total_msgs = [d.get('metrics', {}).get('total_msgs', 0) for d in data if 'metrics' in d]
    
    if p99s and len(p99s) >= 10:
        third = max(len(p99s)//3, 1)
        initial_p99 = np.mean(p99s[:third])
        final_p99 = np.mean(p99s[-third:])
        p99_reduction = (initial_p99 - final_p99) / initial_p99 * 100 if initial_p99 > 0 else 0
    else:
        initial_p99 = final_p99 = p99_reduction = None
    
    return {
        "file": path,
        "mode": mode,
        "backend": backend,
        "lines": cnt,
        "applied_count": applied_count,
        "applied_pct": applied_pct,
        "p99_mean": statistics.mean(p99s) if p99s else None,
        "p99_max": max(p99s) if p99s else None,
        "p99_min": min(p99s) if p99s else None,
        "initial_p99": initial_p99,
        "final_p99": final_p99,
        "p99_reduction": p99_reduction,
        "p95_mean": statistics.mean(p95s) if p95s else None,
        "p50_mean": statistics.mean(p50s) if p50s else None,
        "reward_mean": statistics.mean(rewards) if rewards else None,
        "reward_std": statistics.stdev(rewards) if len(rewards) > 1 else None,
        "nonzero_actions": nonzero_actions,
        "nonzero_pct": nonzero_pct,
        "accel_count": accel_count,
        "decel_count": decel_count,
        "congestion_mean": statistics.mean(congestion_scores) if congestion_scores else None,
        "congested_pct": congested_count * 100.0 / cnt if cnt else 0,
        "total_msgs_max": max(total_msgs) if total_msgs else None
    }

log1 = "logs/emqx_flow_control/dynamic.jsonl"
log2 = "logs/torch_model_experiments/dynamic/rl_bc_v2_dynamic.jsonl"

print("=" * 100)
print("📊 DYNAMIC SCENARIO LOG COMPARISON")
print("=" * 100)

s1 = summarize(log1)
s2 = summarize(log2)

if not s1 or not s2:
    print("❌ Error reading files")
    exit(1)

print("\n{:<35} | {:<25} | {:<25}".format('Metric', 'EMQX Flow Control', 'BC v2 Model (Torch)'))
print("-" * 100)

print("{:<35} | {:<25} | {:<25}".format('File', s1['file'].split('/')[-1], s2['file'].split('/')[-1]))
print("{:<35} | {:<25} | {:<25}".format('Mode / Backend', s1['mode'] + '/' + s1['backend'], s2['mode'] + '/' + s2['backend']))
print("{:<35} | {:<25} | {:<25}".format('Total Steps', s1['lines'], s2['lines']))

print("\n" + "=" * 100)
print("🎯 CONTROL ACTIONS")
print("-" * 100)

print("{:<35} | {} ({:.1f}%) {:<13} | {} ({:.1f}%)".format(
    'Applied Actions', s1['applied_count'], s1['applied_pct'], '', s2['applied_count'], s2['applied_pct']))
print("{:<35} | {} ({:.1f}%) {:<13} | {} ({:.1f}%)".format(
    'Non-zero Actions', s1['nonzero_actions'], s1['nonzero_pct'], '', s2['nonzero_actions'], s2['nonzero_pct']))
print("{:<35} | {:<25} | {:<25}".format('Acceleration (d_rate > 0)', s1['accel_count'], s2['accel_count']))
print("{:<35} | {:<25} | {:<25}".format('Deceleration (d_rate < 0)', s1['decel_count'], s2['decel_count']))

print("\n" + "=" * 100)
print("📈 LATENCY METRICS (ms)")
print("-" * 100)

p99_mean1 = "{:.1f}".format(s1['p99_mean']) if s1['p99_mean'] else "N/A"
p99_mean2 = "{:.1f}".format(s2['p99_mean']) if s2['p99_mean'] else "N/A"
print("{:<35} | {:<25} | {:<25}".format('P99 Mean', p99_mean1, p99_mean2))

p99_max1 = "{:.1f}".format(s1['p99_max']) if s1['p99_max'] else "N/A"
p99_max2 = "{:.1f}".format(s2['p99_max']) if s2['p99_max'] else "N/A"
print("{:<35} | {:<25} | {:<25}".format('P99 Max (Spike)', p99_max1, p99_max2))

if s1['initial_p99'] and s2['initial_p99']:
    init_final1 = "{:.1f} → {:.1f}".format(s1['initial_p99'], s1['final_p99'])
    init_final2 = "{:.1f} → {:.1f}".format(s2['initial_p99'], s2['final_p99'])
    print("{:<35} | {:<25} | {:<25}".format('P99 Initial → Final', init_final1, init_final2))
    
    red1 = "{:.1f}%".format(s1['p99_reduction'])
    red2 = "{:.1f}%".format(s2['p99_reduction'])
    print("{:<35} | {:<25} | {:<25}".format('P99 Reduction', red1, red2))

p95_mean1 = "{:.1f}".format(s1['p95_mean']) if s1['p95_mean'] else "N/A"
p95_mean2 = "{:.1f}".format(s2['p95_mean']) if s2['p95_mean'] else "N/A"
print("{:<35} | {:<25} | {:<25}".format('P95 Mean', p95_mean1, p95_mean2))

print("\n" + "=" * 100)
print("🎁 REWARDS")
print("-" * 100)

r_mean1 = "{:.3f}".format(s1['reward_mean']) if s1['reward_mean'] else "N/A"
r_mean2 = "{:.3f}".format(s2['reward_mean']) if s2['reward_mean'] else "N/A"
print("{:<35} | {:<25} | {:<25}".format('Mean Reward', r_mean1, r_mean2))

cv1_str = "N/A"
if s1['reward_mean'] and s1['reward_std']:
    cv1 = s1['reward_std'] / abs(s1['reward_mean'])
    cv1_str = "{:.3f}".format(cv1)

cv2_str = "N/A"
if s2['reward_mean'] and s2['reward_std']:
    cv2 = s2['reward_std'] / abs(s2['reward_mean'])
    cv2_str = "{:.3f}".format(cv2)

print("{:<35} | {:<25} | {:<25}".format('Reward CV (stability)', cv1_str, cv2_str))

print("\n" + "=" * 100)
print("🌐 NETWORK CONDITION")
print("-" * 100)

cong1 = "{:.3f}".format(s1['congestion_mean']) if s1['congestion_mean'] else "N/A"
cong2 = "{:.3f}".format(s2['congestion_mean']) if s2['congestion_mean'] else "N/A"
print("{:<35} | {:<25} | {:<25}".format('Mean Congestion Score', cong1, cong2))
print("{:<35} | {:.1f}% {:<19} | {:.1f}%".format('Congested % (steps)', s1['congested_pct'], '', s2['congested_pct']))

print("\n" + "=" * 100)
print("🔍 KEY INSIGHTS")
print("=" * 100)

insight1 = "⚠️  BC model barely acts!" if s2['nonzero_pct'] < 5 else "✅ Both show active control"
p99_red1_str = "{:.1f}%".format(s1['p99_reduction']) if s1['p99_reduction'] else "N/A"
p99_red2_str = "{:.1f}%".format(s2['p99_reduction']) if s2['p99_reduction'] else "N/A"
insight3 = "⚠️  Safety shield blocking! (COOLDOWN/DECEL_HOLD)" if s2['applied_pct'] < 5 else ""

cv1_stable = "✅ stable" if cv1_str != "N/A" and float(cv1_str) < 0.5 else ""
cv2_stable = "✅ stable" if cv2_str != "N/A" and float(cv2_str) < 0.5 else ""

print("""
1️⃣ Control Behavior:
   - EMQX: {:.1f}% non-zero ({} accel, {} decel)
   - BC v2: {:.1f}% non-zero ({} accel, {} decel)
   {}

2️⃣ P99 Reduction:
   - EMQX: {}
   - BC v2: {}

3️⃣ Applied Actions:
   - EMQX: {:.1f}% (shadow - not applied)
   - BC v2: {:.1f}% (online - SHOULD apply!)
   {}

4️⃣ Stability:
   - EMQX CV: {} {}
   - BC v2 CV: {} {}
""".format(
    s1['nonzero_pct'], s1['accel_count'], s1['decel_count'],
    s2['nonzero_pct'], s2['accel_count'], s2['decel_count'],
    insight1,
    p99_red1_str,
    p99_red2_str,
    s1['applied_pct'],
    s2['applied_pct'],
    insight3,
    cv1_str, cv1_stable,
    cv2_str, cv2_stable
))

print("=" * 100)
