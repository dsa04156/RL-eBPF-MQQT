#!/usr/bin/env python3
"""
재전송 데이터 분석: had_retrans vs 실제 retrans_count
"""
import json
import numpy as np

print("="*80)
print("📊 재전송 데이터 분석: EMQX vs Torch (Congestion)")
print("="*80)

# EMQX 데이터 확인
print("\n[1] EMQX (무제어) - Congestion")
print("-"*80)
emqx_had_retrans = []
emqx_retrans_count = []

with open('logs/emqx_flow_control/congestion.jsonl', 'r') as f:
    for line in f:
        data = json.loads(line)
        if 'kernel' in data:
            emqx_had_retrans.append(1 if data['kernel'].get('had_retrans', False) else 0)
            # retrans_count가 있으면 사용, 없으면 0
            emqx_retrans_count.append(data['kernel'].get('retrans_count', 0))

print(f"  총 샘플: {len(emqx_had_retrans)}")
print(f"  had_retrans=True 비율: {np.mean(emqx_had_retrans)*100:.1f}%")
if any(emqx_retrans_count):
    print(f"  평균 retrans_count: {np.mean(emqx_retrans_count):.2f}")
    print(f"  총 retrans_count: {np.sum(emqx_retrans_count)}")
    print(f"  최대 retrans_count: {np.max(emqx_retrans_count)}")
else:
    print(f"  ⚠️ retrans_count 필드 없음 (기존 로그)")

# Torch 데이터 확인
print("\n[2] Torch RL (제어) - Congestion")
print("-"*80)
torch_had_retrans = []
torch_retrans_count = []

with open('logs/torch_model_experiments/congestion/rl_bc_v2_congestion.jsonl', 'r') as f:
    for line in f:
        data = json.loads(line)
        if 'kernel' in data:
            torch_had_retrans.append(1 if data['kernel'].get('had_retrans', False) else 0)
            torch_retrans_count.append(data['kernel'].get('retrans_count', 0))

print(f"  총 샘플: {len(torch_had_retrans)}")
print(f"  had_retrans=True 비율: {np.mean(torch_had_retrans)*100:.1f}%")
if any(torch_retrans_count):
    print(f"  평균 retrans_count: {np.mean(torch_retrans_count):.2f}")
    print(f"  총 retrans_count: {np.sum(torch_retrans_count)}")
    print(f"  최대 retrans_count: {np.max(torch_retrans_count)}")
else:
    print(f"  ⚠️ retrans_count 필드 없음 (기존 로그)")

# 비교
print("\n[3] 비교 분석")
print("="*80)

if any(emqx_retrans_count) and any(torch_retrans_count):
    print(f"\n✅ retrans_count 필드 있음!")
    print(f"\n  총 재전송 횟수:")
    print(f"    EMQX:  {np.sum(emqx_retrans_count):,} 회")
    print(f"    Torch: {np.sum(torch_retrans_count):,} 회")
    
    reduction = (1 - np.sum(torch_retrans_count) / np.sum(emqx_retrans_count)) * 100
    print(f"    감소율: {reduction:+.1f}%")
    
    print(f"\n  평균 재전송 (per interval):")
    print(f"    EMQX:  {np.mean(emqx_retrans_count):.2f} 회")
    print(f"    Torch: {np.mean(torch_retrans_count):.2f} 회")
else:
    print(f"\n⚠️ 기존 로그는 retrans_count 없음")
    print(f"   had_retrans만 있음:")
    print(f"     EMQX:  {np.mean(emqx_had_retrans)*100:.1f}% (재전송 발생 비율)")
    print(f"     Torch: {np.mean(torch_had_retrans)*100:.1f}% (재전송 발생 비율)")
    print(f"\n   🔧 수정 사항:")
    print(f"      - eda_rl.py에 retrans_count 필드 추가됨")
    print(f"      - 다음 실험부터는 실제 재전송 횟수 기록됨")

print("\n[4] 문제점과 해결")
print("="*80)
print("""
문제:
  • had_retrans는 boolean (재전송 있었는지만 기록)
  • 실제 재전송 횟수는 모름
  • 100% vs 100% 비교는 의미 없음

해결:
  • retrans_count 필드 추가 (실제 재전송 횟수)
  • EMQX: 1000회, Torch: 100회 → 90% 감소 같은 정량적 비교 가능

다음 실험:
  • 수정된 eda_rl.py로 재실험 필요
  • retrans_count로 실제 재전송 감소 효과 측정
""")
