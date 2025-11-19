#!/bin/bash
# retrans_count 필드가 수치로 나오는지 빠르게 테스트

echo "🧪 재전송 횟수 수치 표시 테스트"
echo "================================"

# 로그 파일 설정
TEST_LOG="logs/test_retrans_display.jsonl"
rm -f "$TEST_LOG"

# 1. 네트워크 혼잡 설정 (재전송 유발)
echo "📡 네트워크 혼잡 설정 (10ms delay, 5% loss)..."
sudo tc qdisc add dev lo root netem delay 10ms loss 5% 2>/dev/null || \
sudo tc qdisc change dev lo root netem delay 10ms loss 5%

# 2. Publisher 시작
echo "📤 Publisher 시작..."
python3 clients/mqtt_publisher.py --host 127.0.0.1 --port 23232 --rate 100 --batch 32 &
PUB_PID=$!
sleep 2

# 3. eBPF agent 시작 (15초만)
echo "🔬 eBPF agent 시작 (15초 실행)..."
sudo USE_GYM_ENV=1 RL_MODE=shadow RL_LOG_PATH="$TEST_LOG" \
  MQTT_HOST=127.0.0.1 MQTT_PORT=23232 INTERVAL_S=2.0 \
  timeout 15 python3 bpf/eda_rl.py

# 4. 정리
echo "🧹 정리 중..."
kill $PUB_PID 2>/dev/null
sudo tc qdisc del dev lo root 2>/dev/null

# 5. 결과 확인
echo ""
echo "📊 결과 분석:"
echo "================================"
if [ -f "$TEST_LOG" ]; then
    python3 show_retrans_counts.py "$TEST_LOG"
    
    echo ""
    echo "📝 실제 로그 샘플 (처음 2줄):"
    echo "--------------------------------"
    head -2 "$TEST_LOG" | python3 -m json.tool | grep -A 5 '"kernel"'
else
    echo "❌ 로그 파일이 생성되지 않았습니다: $TEST_LOG"
fi
