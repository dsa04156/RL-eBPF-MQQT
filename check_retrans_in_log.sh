#!/bin/bash
# 실행 중이거나 완료된 로그에서 retrans_count 확인

LOG_FILE="${1:-logs/emqx_flow_control/dynamic.jsonl}"

echo "🔍 로그 파일 확인: $LOG_FILE"
echo "================================"

if [ ! -f "$LOG_FILE" ]; then
    echo "❌ 파일이 없습니다: $LOG_FILE"
    exit 1
fi

echo ""
echo "📊 첫 번째 줄의 kernel 필드:"
head -1 "$LOG_FILE" | python3 -c "import json, sys; d=json.load(sys.stdin); k=d.get('kernel',{}); print('  Fields:', list(k.keys())); print('  had_retrans:', k.get('had_retrans')); print('  retrans_count:', k.get('retrans_count', 'N/A'))"

echo ""
echo "📈 재전송 통계 (전체 로그):"
python3 -c "
import json
import sys

total = 0
with_retrans = 0
total_count = 0
max_count = 0

with open('$LOG_FILE', 'r') as f:
    for line in f:
        if not line.strip():
            continue
        d = json.loads(line)
        k = d.get('kernel', {})
        total += 1
        
        if 'retrans_count' in k:
            count = k['retrans_count']
            total_count += count
            if count > 0:
                with_retrans += 1
            if count > max_count:
                max_count = count
        elif k.get('had_retrans'):
            with_retrans += 1

print(f'  총 라인: {total}')
print(f'  재전송 있는 라인: {with_retrans} ({with_retrans/max(1,total)*100:.1f}%)')
if max_count > 0:
    print(f'  총 재전송 횟수: {total_count}')
    print(f'  최대 재전송: {max_count}')
    print(f'  평균 재전송: {total_count/max(1,total):.2f}')
    print(f'  ✅ retrans_count 필드 있음 - 수치 측정 가능!')
else:
    print(f'  ⚠️  retrans_count 필드 없음 - boolean만 측정됨')
"

echo ""
echo "💡 retrans_count가 있으면 실제 재전송 횟수를 볼 수 있습니다!"
echo "   예: had_retrans=true, retrans_count=5 → 5번 재전송"
