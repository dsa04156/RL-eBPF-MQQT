import json, time, numpy as np

path='logs/eda_rl_run_20250916_192728_online.jsonl'
now=time.time()
p99=[]; applied=tot=0

with open(path) as f:
    for L in f:
        try:
            rec=json.loads(L)
        except json.JSONDecodeError:
            continue
        if now - rec.get('ts', 0) > 120:
            continue
        tot += 1
        if rec.get('applied'):
            applied += 1
        m = rec.get('metrics', {}).get('p99_ms')
        if isinstance(m, (int, float)):
            p99.append(m)

if p99:
    q = np.percentile(p99, [25, 50, 75, 95])
    print('p99 25/50/75/95: {} ms / {} ms / {} ms / {} ms'.format(*(f'{v:.0f}' for v in q)))
    print('p99 mean/std: {} ms / {} ms'.format(f'{np.mean(p99):.0f}', f'{np.std(p99):.0f}'))
else:
    print('No p99 values in last 120s')

print('applied ratio: {:.2%} ({}/{})'.format(applied / max(1, tot), applied, tot))
