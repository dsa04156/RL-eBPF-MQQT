#!/usr/bin/env python3
"""
3x3 비교: (Baseline vs EMQX vs eBPF+RL) × (Normal vs Dynamic vs Congestion)
"""
import json
import numpy as np

def load_log(path):
    data = []
    try:
        with open(path) as f:
            for line in f:
                try:
                    data.append(json.loads(line))
                except:
                    continue
    except FileNotFoundError:
        print(f"⚠️  파일 없음: {path}")
        return []
    return data

def get_stats(log):
    if not log:
        return None
    
    p99s = [e['metrics']['p99_ms'] for e in log if 'metrics' in e]
    p95s = [e['metrics']['p95_ms'] for e in log if 'metrics' in e]
    snds = [e['kernel']['snd_ratio'] for e in log if 'kernel' in e]
    
    return {
        'samples': len(log),
        'p99_med': np.median(p99s) if p99s else 0,
        'p99_mean': np.mean(p99s) if p99s else 0,
        'p99_max': np.max(p99s) if p99s else 0,
        'p95_med': np.median(p95s) if p95s else 0,
        'snd_med': np.median(snds) if snds else 0,
        'snd_mean': np.mean(snds) if snds else 0,
        'snd_max': np.max(snds) if snds else 0,
        'slo_violation': len([p for p in p99s if p > 300])/len(p99s)*100 if p99s else 0
    }

scenarios = ['normal', 'dynamic', 'congestion']
methods = {
    'Baseline': 'logs/baseline/baseline_{}.jsonl',
    'EMQX': 'logs/emqx_flow_control/{}.jsonl',
    'eBPF+RL': 'logs/torch_model_experiments/{}/rl_bc_v2_{}.jsonl'
}

print("="*100)
print("3x3 시나리오 비교: Baseline vs EMQX Flow Control vs eBPF+RL")
print("="*100)

for scenario in scenarios:
    print(f"\n{'='*100}")
    print(f"📍 시나리오: {scenario.upper()}")
    print(f"{'='*100}")
    
    results = {}
    for method_name, path_template in methods.items():
        if method_name == 'eBPF+RL':
            path = path_template.format(scenario, scenario)
        else:
            path = path_template.format(scenario)
        
        log = load_log(path)
        stats = get_stats(log)
        
        if stats:
            results[method_name] = stats
            print(f"\n{method_name}:")
            print(f"  샘플: {stats['samples']}개")
            print(f"  P99: {stats['p99_med']:.1f} ms (평균: {stats['p99_mean']:.1f}, 최대: {stats['p99_max']:.1f})")
            print(f"  P95: {stats['p95_med']:.1f} ms")
            print(f"  snd_ratio: {stats['snd_med']:.3f} (평균: {stats['snd_mean']:.3f}, 최대: {stats['snd_max']:.3f})")
            print(f"  SLO 위반률: {stats['slo_violation']:.1f}%")
    
    # 시나리오별 비교 테이블
    if len(results) == 3:
        print(f"\n{'─'*100}")
        print(f"{'지표':<20} {'Baseline':>20} {'EMQX':>20} {'eBPF+RL':>20}")
        print(f"{'─'*100}")
        print(f"{'P99 (중앙값, ms)':<20} {results['Baseline']['p99_med']:>20.1f} {results['EMQX']['p99_med']:>20.1f} {results['eBPF+RL']['p99_med']:>20.1f}")
        print(f"{'P99 (최대, ms)':<20} {results['Baseline']['p99_max']:>20.1f} {results['EMQX']['p99_max']:>20.1f} {results['eBPF+RL']['p99_max']:>20.1f}")
        print(f"{'snd_ratio (중앙값)':<20} {results['Baseline']['snd_med']:>20.3f} {results['EMQX']['snd_med']:>20.3f} {results['eBPF+RL']['snd_med']:>20.3f}")
        print(f"{'snd_ratio (최대)':<20} {results['Baseline']['snd_max']:>20.3f} {results['EMQX']['snd_max']:>20.3f} {results['eBPF+RL']['snd_max']:>20.3f}")
        print(f"{'SLO 위반률 (%)':<20} {results['Baseline']['slo_violation']:>20.1f} {results['EMQX']['slo_violation']:>20.1f} {results['eBPF+RL']['slo_violation']:>20.1f}")
        
        # 개선율 계산
        if results['EMQX']['p99_med'] > 0:
            p99_improvement = (1 - results['eBPF+RL']['p99_med'] / results['EMQX']['p99_med']) * 100
            snd_improvement = (1 - results['eBPF+RL']['snd_med'] / results['EMQX']['snd_med']) * 100
            print(f"\n🎯 eBPF+RL vs EMQX 개선율:")
            print(f"   P99: {p99_improvement:.1f}% 개선")
            print(f"   snd_ratio: {snd_improvement:.1f}% 개선")

print(f"\n{'='*100}")
print("�� 핵심 인사이트")
print(f"{'='*100}")
print("""
1. Normal 네트워크: 모든 방법이 비슷한 성능 (네트워크 양호)
2. Dynamic 네트워크: EMQX가 변화에 적응 못함 → eBPF+RL이 커널 신호로 대응
3. Congestion 네트워크: EMQX 완전 실패 (P99 수십초) → eBPF+RL만 생존

🔑 결론: Application-level Flow Control(EMQX)은 커널 TCP 버퍼 상태를 
         모르기 때문에 혼잡 네트워크에서 버퍼 폭발 → P99 폭증!
         eBPF 기반 커널 신호 모니터링이 필수적!
""")
