#!/usr/bin/env python3
"""
RL 액션 분석: 가속 vs 감속 비율
"""
import json
import numpy as np

def analyze_actions(log_path):
    """액션 분포 분석"""
    actions = {
        'accel': 0,     # d_rate > 0
        'decel': 0,     # d_rate < 0
        'hold': 0,      # d_rate = 0
        'd_rates': [],
        'd_batches': [],
        'applied': 0,
        'blocked': 0
    }
    
    with open(log_path) as f:
        for line in f:
            if not line.strip():
                continue
            data = json.loads(line)
            
            a = data.get('a', {})
            d_rate = a.get('d_rate', 0)
            d_batch = a.get('d_batch', 0)
            applied = data.get('applied', False)
            
            actions['d_rates'].append(d_rate)
            actions['d_batches'].append(d_batch)
            
            if d_rate > 0.01:
                actions['accel'] += 1
            elif d_rate < -0.01:
                actions['decel'] += 1
            else:
                actions['hold'] += 1
            
            if applied:
                actions['applied'] += 1
            else:
                actions['blocked'] += 1
    
    return actions

# 기존 RL과 최적화된 RL 비교
print("📊 RL 액션 분석: 가속 vs 감속")
print("=" * 80)

# 최적화된 버전 분석
opt_log = "logs/rl_optimized.jsonl"
try:
    opt = analyze_actions(opt_log)
    
    total = opt['accel'] + opt['decel'] + opt['hold']
    
    print(f"\n🎯 최적화된 RL (logs/rl_optimized.jsonl)")
    print(f"  총 결정: {total}")
    print(f"  가속 (d_rate > 0):  {opt['accel']:4d} ({opt['accel']/total*100:5.1f}%)  📈")
    print(f"  감속 (d_rate < 0):  {opt['decel']:4d} ({opt['decel']/total*100:5.1f}%)  📉")
    print(f"  유지 (d_rate = 0):  {opt['hold']:4d} ({opt['hold']/total*100:5.1f}%)  ⏸️")
    print(f"\n  적용됨: {opt['applied']:4d} ({opt['applied']/total*100:5.1f}%)")
    print(f"  차단됨: {opt['blocked']:4d} ({opt['blocked']/total*100:5.1f}%)")
    
    print(f"\n  d_rate 통계:")
    print(f"    평균: {np.mean(opt['d_rates']):+.4f}")
    print(f"    중앙값: {np.median(opt['d_rates']):+.4f}")
    print(f"    최대: {np.max(opt['d_rates']):+.4f}")
    print(f"    최소: {np.min(opt['d_rates']):+.4f}")
    
except Exception as e:
    print(f"❌ 로그 분석 실패: {e}")

# 기존 RL 분석
old_log = "logs/torch_model_experiments/congestion/rl_bc_v2_congestion.jsonl"
try:
    old = analyze_actions(old_log)
    
    total = old['accel'] + old['decel'] + old['hold']
    
    print(f"\n📊 기존 RL (logs/torch_model_experiments/congestion/rl_bc_v2_congestion.jsonl)")
    print(f"  총 결정: {total}")
    print(f"  가속 (d_rate > 0):  {old['accel']:4d} ({old['accel']/total*100:5.1f}%)  📈")
    print(f"  감속 (d_rate < 0):  {old['decel']:4d} ({old['decel']/total*100:5.1f}%)  📉")
    print(f"  유지 (d_rate = 0):  {old['hold']:4d} ({old['hold']/total*100:5.1f}%)  ⏸️")
    
    print(f"\n  d_rate 통계:")
    print(f"    평균: {np.mean(old['d_rates']):+.4f}")
    print(f"    중앙값: {np.median(old['d_rates']):+.4f}")
    print(f"    최대: {np.max(old['d_rates']):+.4f}")
    print(f"    최소: {np.min(old['d_rates']):+.4f}")
    
except Exception as e:
    print(f"❌ 로그 분석 실패: {e}")

print("\n" + "=" * 80)
print("💡 문제 진단:")
print("  - 모델이 항상 d_rate=0 출력 → 가속 안함")
print("  - BC 학습 시 대부분 데이터가 감속/유지였을 가능성")
print("  - 해결책: Rule-based 모드로 전환하거나 모델 재학습 필요")
