#!/bin/bash
# RL 모델로 3가지 시나리오 테스트 스크립트
# Usage: bash bench/run_rl_scenarios.sh

set -e

MODEL_PATH="models/bc_kernel_only.pt"
LOG_BASE="logs/rl_scenarios"
MQTT_HOST="127.0.0.1"
MQTT_PORT="23232"
DURATION=600  # 10분

echo "🚀 RL Model Scenario Testing"
echo "Model: $MODEL_PATH"
echo "Duration: ${DURATION}s (10 minutes) per scenario"
echo ""

# 로그 디렉토리 생성
mkdir -p "$LOG_BASE"

# 네트워크 인터페이스 확인
IFACE=$(ip route | grep default | awk '{print $5}' | head -1)
echo "Network Interface: $IFACE"
echo ""

#==============================================================================
# 1. Normal (평시) - 네트워크 제약 없음
#==============================================================================
echo "=================================="
echo "1️⃣  NORMAL Scenario (No constraints)"
echo "=================================="

# 네트워크 초기화
sudo tc qdisc del dev $IFACE root 2>/dev/null || true
sleep 2

echo "Starting RL agent (Normal scenario)..."
timeout $DURATION sudo USE_GYM_ENV=1 RL_MODE=online RL_BACKEND=torch \
  RL_MODEL_PATH="$MODEL_PATH" \
  RL_LOG_PATH="$LOG_BASE/normal_torch.jsonl" \
  MQTT_HOST="$MQTT_HOST" MQTT_PORT="$MQTT_PORT" \
  INTERVAL_S=2.0 \
  python3 bpf/eda_rl.py || true

echo "✅ Normal scenario completed"
echo ""
sleep 5

#==============================================================================
# 2. Dynamic (동적) - 30초 주기 네트워크 변화
#==============================================================================
echo "=================================="
echo "2️⃣  DYNAMIC Scenario (30s cycles)"
echo "=================================="

# 네트워크 초기화
sudo tc qdisc del dev $IFACE root 2>/dev/null || true
sleep 2

echo "Starting dynamic network conditions..."
sudo IF=$IFACE PHASE_DUR=30 CYCLES=5 bash bench/netem_dynamic.sh &
NETEM_PID=$!
sleep 2

echo "Starting RL agent (Dynamic scenario)..."
timeout $DURATION sudo USE_GYM_ENV=1 RL_MODE=online RL_BACKEND=torch \
  RL_MODEL_PATH="$MODEL_PATH" \
  RL_LOG_PATH="$LOG_BASE/dynamic_torch.jsonl" \
  MQTT_HOST="$MQTT_HOST" MQTT_PORT="$MQTT_PORT" \
  INTERVAL_S=2.0 \
  python3 bpf/eda_rl.py || true

# netem 종료
kill $NETEM_PID 2>/dev/null || true
sudo tc qdisc del dev $IFACE root 2>/dev/null || true

echo "✅ Dynamic scenario completed"
echo ""
sleep 5

#==============================================================================
# 3. Congestion (혼잡) - 심각한 네트워크 제약
#==============================================================================
echo "=================================="
echo "3️⃣  CONGESTION Scenario (Severe constraints)"
echo "=================================="

# 네트워크 초기화
sudo tc qdisc del dev $IFACE root 2>/dev/null || true
sleep 2

# 혼잡 조건 적용
echo "Applying congestion network conditions..."
sudo tc qdisc add dev $IFACE root handle 1: htb default 10
sudo tc class add dev $IFACE parent 1: classid 1:10 htb rate 2mbit ceil 2mbit
sudo tc qdisc add dev $IFACE parent 1:10 handle 10: netem delay 120ms 50ms loss 2%
sleep 2

echo "Starting RL agent (Congestion scenario)..."
timeout $DURATION sudo USE_GYM_ENV=1 RL_MODE=online RL_BACKEND=torch \
  RL_MODEL_PATH="$MODEL_PATH" \
  RL_LOG_PATH="$LOG_BASE/congestion_torch.jsonl" \
  MQTT_HOST="$MQTT_HOST" MQTT_PORT="$MQTT_PORT" \
  INTERVAL_S=2.0 \
  python3 bpf/eda_rl.py || true

# 네트워크 복구
sudo tc qdisc del dev $IFACE root 2>/dev/null || true

echo "✅ Congestion scenario completed"
echo ""

#==============================================================================
# 결과 요약
#==============================================================================
echo "=================================="
echo "📊 Test Summary"
echo "=================================="
echo ""
echo "Logs saved to: $LOG_BASE/"
ls -lh "$LOG_BASE/"
echo ""

echo "📈 Quick Analysis:"
for scenario in normal dynamic congestion; do
    logfile="$LOG_BASE/${scenario}_torch.jsonl"
    if [ -f "$logfile" ]; then
        lines=$(wc -l < "$logfile")
        echo "  - $scenario: $lines steps"
    fi
done

echo ""
echo "🎯 Next steps:"
echo "  1. Visualize results:"
echo "     python3 bench/visualize_rl_training.py --log $LOG_BASE/normal_torch.jsonl --output-dir results/rl_scenarios/normal --episode-len 25"
echo "     python3 bench/visualize_rl_training.py --log $LOG_BASE/dynamic_torch.jsonl --output-dir results/rl_scenarios/dynamic --episode-len 25"
echo "     python3 bench/visualize_rl_training.py --log $LOG_BASE/congestion_torch.jsonl --output-dir results/rl_scenarios/congestion --episode-len 25"
echo ""
echo "  2. Compare with baseline:"
echo "     Compare with logs/emqx_flow_control/{normal,dynamic,congestion}.jsonl"
echo ""
echo "✅ All scenarios completed!"
