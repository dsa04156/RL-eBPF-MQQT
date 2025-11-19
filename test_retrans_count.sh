#!/bin/bash
# 수정된 eda_rl.py로 간단한 테스트 실행
# retrans_count 필드가 제대로 기록되는지 확인

echo "=================================="
echo "🧪 retrans_count 테스트 실행"
echo "=================================="
echo ""
echo "1. EMQX 브로커가 실행중인지 확인..."
if ps -ef| grep "emqx" > /dev/null; then
    echo "   ✅ EMQX 실행 중"
else
    echo "   ❌ EMQX가 실행되지 않았습니다. 먼저 EMQX를 시작하세요:"
    echo "      sudo systemctl start emqx"
    exit 1
fi

echo ""
echo "2. 네트워크 혼잡 조건 적용 (30초)..."
sudo tc qdisc del dev lo root 2>/dev/null
sudo tc qdisc add dev lo root netem delay 100ms loss 5%
echo "   ✅ tc netem 적용: delay 100ms, loss 5%"

echo ""
echo "3. Publisher 시작 (백그라운드)..."
python3 clients/mqtt_publisher.py &
PUB_PID=$!
echo "   ✅ Publisher PID: $PUB_PID"

echo ""
echo "4. Subscriber 시작 (백그라운드)..."
python3 clients/mqtt_subscriber.py &
SUB_PID=$!
echo "   ✅ Subscriber PID: $SUB_PID"

sleep 2

echo ""
echo "5. eBPF+RL Agent 시작 (30초 테스트)..."
echo "   로그: logs/test_retrans_count.jsonl"
echo ""

timeout 30 sudo python3 bpf/eda_rl.py > logs/test_retrans_count.jsonl 2>&1 &
AGENT_PID=$!

echo "   ⏱️ 30초 동안 실행 중..."
sleep 30

echo ""
echo "6. 프로세스 정리..."
sudo kill $AGENT_PID 2>/dev/null
kill $PUB_PID 2>/dev/null
kill $SUB_PID 2>/dev/null
sudo tc qdisc del dev lo root 2>/dev/null
echo "   ✅ 정리 완료"

echo ""
echo "7. retrans_count 필드 확인..."
if grep -q "retrans_count" logs/test_retrans_count.jsonl 2>/dev/null; then
    echo "   ✅ retrans_count 필드 발견!"
    echo ""
    echo "   샘플 데이터:"
    grep "retrans_count" logs/test_retrans_count.jsonl | head -3 | python3 -m json.tool 2>/dev/null || echo "   (JSON 파싱 실패)"
    
    echo ""
    echo "8. 통계 분석..."
    python3 << 'EOF'
import json
retrans_counts = []
with open('logs/test_retrans_count.jsonl', 'r') as f:
    for line in f:
        try:
            data = json.loads(line)
            if 'kernel' in data and 'retrans_count' in data['kernel']:
                retrans_counts.append(data['kernel']['retrans_count'])
        except:
            pass

if retrans_counts:
    print(f"   총 샘플: {len(retrans_counts)}")
    print(f"   총 재전송: {sum(retrans_counts)} 회")
    print(f"   평균 재전송: {sum(retrans_counts)/len(retrans_counts):.2f} 회/interval")
    print(f"   최대 재전송: {max(retrans_counts)} 회")
else:
    print("   ⚠️ retrans_count 데이터 없음")
EOF
else
    echo "   ❌ retrans_count 필드 없음"
    echo "   로그 파일 확인: logs/test_retrans_count.jsonl"
fi

echo ""
echo "=================================="
echo "✅ 테스트 완료"
echo "=================================="
