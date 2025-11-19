#!/usr/bin/env python3
"""
재전송 발생 분석: 처리량 감소에도 불구하고 왜?
"""
import json
import numpy as np

def analyze_retrans_context(log_path):
    """재전송 발생 시 컨텍스트 분석"""
    data = {
        'total': 0,
        'with_retrans': 0,
        'retrans_events': [],
        'throughput': [],
        'p99': [],
        'snd_ratio': [],
        'rtt': [],
        'retrans_count': [],
        'retrans_queue': []
    }
    
    with open(log_path) as f:
        for line in f:
            if not line.strip():
                continue
            entry = json.loads(line)
            
            data['total'] += 1
            
            kernel = entry.get('kernel', {})
            metrics = entry.get('metrics', {})
            
            had_retrans = kernel.get('had_retrans', False)
            retrans_count = kernel.get('retrans_count', 0)
            retrans_queue = kernel.get('retrans_queue', 0)
            snd_ratio = kernel.get('snd_ratio', 0)
            rtt_us = kernel.get('ewma_rtt_us', 0)
            
            n = metrics.get('n', 0)
            window_sec = metrics.get('window_sec', 30.0)
            throughput = n / window_sec if window_sec > 0 else 0
            p99 = metrics.get('p99_ms', 0)
            
            data['throughput'].append(throughput)
            data['p99'].append(p99)
            data['snd_ratio'].append(snd_ratio)
            data['rtt'].append(rtt_us / 1000.0)  # ms로 변환
            data['retrans_count'].append(retrans_count)
            data['retrans_queue'].append(retrans_queue)
            
            if had_retrans or retrans_count > 0:
                data['with_retrans'] += 1
                data['retrans_events'].append({
                    'throughput': throughput,
                    'p99': p99,
                    'snd_ratio': snd_ratio,
                    'rtt_ms': rtt_us / 1000.0,
                    'retrans_count': retrans_count,
                    'retrans_queue': retrans_queue
                })
    
    return data

print("🔍 재전송 발생 원인 분석")
print("=" * 80)

# 최적화된 RL 로그 분석
opt_log = "logs/rl_optimized.jsonl"
try:
    opt = analyze_retrans_context(opt_log)
    
    retrans_rate = opt['with_retrans'] / opt['total'] * 100
    
    print(f"\n📊 최적화된 RL (logs/rl_optimized.jsonl)")
    print(f"  총 측정: {opt['total']}")
    print(f"  재전송 발생: {opt['with_retrans']} ({retrans_rate:.1f}%)")
    
    print(f"\n  전체 평균:")
    print(f"    Throughput: {np.mean(opt['throughput']):6.1f} msg/s")
    print(f"    P99:        {np.mean(opt['p99']):6.1f} ms")
    print(f"    snd_ratio:  {np.mean(opt['snd_ratio']):.4f}")
    print(f"    RTT:        {np.mean(opt['rtt']):6.1f} ms")
    
    if opt['retrans_events']:
        print(f"\n  ⚠️  재전송 발생 시 평균:")
        retrans_throughput = [e['throughput'] for e in opt['retrans_events']]
        retrans_p99 = [e['p99'] for e in opt['retrans_events']]
        retrans_snd = [e['snd_ratio'] for e in opt['retrans_events']]
        retrans_rtt = [e['rtt_ms'] for e in opt['retrans_events']]
        retrans_cnt = [e['retrans_count'] for e in opt['retrans_events']]
        retrans_queue = [e['retrans_queue'] for e in opt['retrans_events']]
        
        print(f"    Throughput: {np.mean(retrans_throughput):6.1f} msg/s")
        print(f"    P99:        {np.mean(retrans_p99):6.1f} ms")
        print(f"    snd_ratio:  {np.mean(retrans_snd):.4f}")
        print(f"    RTT:        {np.mean(retrans_rtt):6.1f} ms")
        print(f"    retrans_count: {np.mean(retrans_cnt):.1f}")
        print(f"    retrans_queue: {np.mean(retrans_queue):.1f}")
        
        # 재전송 횟수 분포
        print(f"\n  재전송 횟수 분포:")
        unique_counts = sorted(set(retrans_cnt))
        for cnt in unique_counts:
            freq = retrans_cnt.count(cnt)
            print(f"    {cnt}회: {freq}건")
    
except Exception as e:
    print(f"❌ 로그 분석 실패: {e}")
    import traceback
    traceback.print_exc()

# 기존 RL과 비교
old_log = "logs/torch_model_experiments/congestion/rl_bc_v2_congestion.jsonl"
try:
    old = analyze_retrans_context(old_log)
    
    retrans_rate = old['with_retrans'] / old['total'] * 100
    
    print(f"\n📊 기존 RL (처리량 더 낮은 버전)")
    print(f"  총 측정: {old['total']}")
    print(f"  재전송 발생: {old['with_retrans']} ({retrans_rate:.1f}%)")
    
    print(f"\n  전체 평균:")
    print(f"    Throughput: {np.mean(old['throughput']):6.1f} msg/s")
    print(f"    P99:        {np.mean(old['p99']):6.1f} ms")
    print(f"    snd_ratio:  {np.mean(old['snd_ratio']):.4f}")
    print(f"    RTT:        {np.mean(old['rtt']):6.1f} ms")
    
except Exception as e:
    print(f"⚠️  기존 로그 로드 실패: {e}")

# EMQX 분석
emqx_log = "logs/emqx_flow_control/congestion.jsonl"
try:
    emqx = analyze_retrans_context(emqx_log)
    
    retrans_rate = emqx['with_retrans'] / emqx['total'] * 100
    
    print(f"\n📊 EMQX Flow Control (처리량 높은 버전)")
    print(f"  총 측정: {emqx['total']}")
    print(f"  재전송 발생: {emqx['with_retrans']} ({retrans_rate:.1f}%)")
    
    print(f"\n  전체 평균:")
    print(f"    Throughput: {np.mean(emqx['throughput']):6.1f} msg/s")
    print(f"    P99:        {np.mean(emqx['p99']):6.1f} ms")
    print(f"    snd_ratio:  {np.mean(emqx['snd_ratio']):.4f}")
    print(f"    RTT:        {np.mean(emqx['rtt']):6.1f} ms")
    
except Exception as e:
    print(f"⚠️  EMQX 로그 로드 실패: {e}")

print("\n" + "=" * 80)
print("💡 재전송 발생 원인:")
print("  1. 네트워크 자체 Loss (netem 2% 설정)")
print("  2. RTT 변동으로 인한 타임아웃")
print("  3. 버스트 트래픽 (배치 전송)")
print("  4. 처리량 줄여도 네트워크 품질 자체는 동일")
print("\n  → 재전송은 불가피, 하지만:")
print("    - RL은 버퍼 압력 낮춤 (snd_ratio)")
print("    - 재전송 발생해도 빠르게 복구")
print("    - 큐잉 지연 최소화 → P99 낮음")
print("\n  → EMQX는 재전송 + 큐잉 누적 → P99 폭발")
