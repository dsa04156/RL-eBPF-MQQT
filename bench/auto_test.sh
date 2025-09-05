#!/bin/bash
# 완전 자동화된 저장 테스트 스크립트 (30초)

set -e

SSH_PASS="1231"
SSH_CMD="sshpass -p $SSH_PASS ssh -o StrictHostKeyChecking=no"

RUN_ID=auto_test_$(date +%H%M%S)
echo "🚀 완전 자동화 테스트 $RUN_ID 시작 (30초)"

# 실험 설정
HI_RTT_US=1000000
LO_RTT_US=500000
CTRL_RATE=5
CTRL_BATCH=2
SUB_COUNT=3
PUB_COUNT=3
RATE=10
DURATION=30

echo "📋 실험 설정:"
echo "  - RTT: ${HI_RTT_US}us (Hi) / ${LO_RTT_US}us (Lo)"
echo "  - 제어: ${CTRL_RATE}Hz, ${CTRL_BATCH}batch"
echo "  - Publisher: ${PUB_COUNT}개, ${RATE}msg/s"
echo "  - Subscriber: ${SUB_COUNT}개"
echo "  - 지속시간: ${DURATION}초"

# 1. 네트워크 혼잡 건너뛰기
echo "📡 네트워크 혼잡 주입 건너뛰기..."

# 2. 결과 디렉토리 준비
mkdir -p ~/mqtt-ebpf-edge/results/generated/$RUN_ID
echo "📁 결과 디렉토리 생성: ~/mqtt-ebpf-edge/results/generated/$RUN_ID"

# 3. Subscriber 시작
echo "📥 Subscriber 시작 (${SUB_COUNT}개)..."
$SSH_CMD sslab@192.168.0.3 "
    cd ~/jinuk/clients
    rm -rf results/
    mkdir -p ./results && chmod 777 ./results
    docker compose -f subscriber-compose.yml up -d --scale subscriber=${SUB_COUNT}
" &

sleep 3

# 4. eBPF 에이전트 시작
echo "🔍 eBPF 에이전트 시작..."
$SSH_CMD sslab@192.168.0.1 "
    cd ~/mqtt-ebpf-edge
    sudo -E \
        MQTT_HOST=192.168.0.1 \
        MQTT_PORT=23232 \
        CONTROL_TOPIC=control/room1 \
        EDA_OBSERVE=0 \
        HI_RTT_US=${HI_RTT_US} \
        LO_RTT_US=${LO_RTT_US} \
        CTRL_RATE=${CTRL_RATE} \
        CTRL_BATCH=${CTRL_BATCH} \
        USE_ADAPTIVE=0 \
        nohup python3 -u bpf/eda.py > ~/mqtt-ebpf-edge/results/generated/eda_$RUN_ID.jsonl 2>&1 &
    echo 'eBPF 에이전트 백그라운드 시작'
"

sleep 3

# 5. Publisher 시작
echo "📤 Publisher 시작 (${PUB_COUNT}개)..."
$SSH_CMD sslab@192.168.0.2 "
    cd ~/jinuk/clients
    RATE=${RATE} \
    BATCH=1 \
    QOS=1 \
    PAYLOAD_BYTES=128 \
    docker compose -f publisher-compose.yml up -d --build --scale publisher=${PUB_COUNT}
"

# 6. 실험 지속
echo "⏱️  실험 진행 중... (${DURATION}초)"
sleep $DURATION

# 7. Publisher 종료
echo "📤 Publisher 종료..."
$SSH_CMD sslab@192.168.0.2 "
    cd ~/jinuk/clients
    docker compose -f publisher-compose.yml down
    RUN_ID=$RUN_ID SERVICE_LABEL=publisher ./collect_publisher_logs.sh
"

# 8. Subscriber 종료
sleep 3
echo "📥 Subscriber 종료..."
$SSH_CMD sslab@192.168.0.3 "
    cd ~/jinuk/clients
    docker compose -f subscriber-compose.yml down
    RUN_ID=$RUN_ID ./collect_subscriber_logs.sh
"

# 9. eBPF 에이전트 종료
echo "🔍 eBPF 에이전트 종료..."
$SSH_CMD sslab@192.168.0.1 "sudo pkill -f 'eda.py' || true"

sleep 2

# 10. 로그 수집 (자동화)
echo "📊 로그 수집..."
cd ~/mqtt-ebpf-edge
MODE=generated RUN_ID=$RUN_ID SUB_HOST=192.168.0.3 PUB_HOST=192.168.0.2 USER_NAME=sslab \
bash bench/pull_logs_from_nodes.sh

# 11. 상세 메타데이터 저장
echo "📝 실험 메타데이터 저장..."
cat > ~/mqtt-ebpf-edge/results/generated/$RUN_ID/metadata.json << EOF
{
    "run_id": "$RUN_ID",
    "timestamp": "$(date -Iseconds)",
    "test_type": "automated_storage_test",
    "experiment_config": {
        "duration_sec": $DURATION,
        "network": {
            "congestion": false,
            "scenario": "clean"
        },
        "workload": {
            "publisher_count": $PUB_COUNT,
            "subscriber_count": $SUB_COUNT,
            "message_rate": $RATE,
            "batch_size": 1,
            "qos": 1,
            "payload_bytes": 128
        },
        "eda_params": {
            "HI_RTT_US": $HI_RTT_US,
            "LO_RTT_US": $LO_RTT_US,
            "CTRL_RATE": $CTRL_RATE,
            "CTRL_BATCH": $CTRL_BATCH,
            "USE_ADAPTIVE": 0,
            "MQTT_HOST": "192.168.0.1",
            "MQTT_PORT": 23232,
            "CONTROL_TOPIC": "control/room1"
        },
        "nodes": {
            "broker": "192.168.0.1",
            "publisher": "192.168.0.2", 
            "subscriber": "192.168.0.3"
        }
    }
}
EOF

# 12. 결과 확인 및 요약
echo ""
echo "✅ 실험 $RUN_ID 완료!"
echo ""
echo "📊 수집된 데이터:"
SUB_CSV_COUNT=$(find ~/mqtt-ebpf-edge/results/generated/subs/$RUN_ID/ -name "*_lat.csv" 2>/dev/null | wc -l)
TOTAL_LINES=$(cat ~/mqtt-ebpf-edge/results/generated/subs/$RUN_ID/*_lat.csv 2>/dev/null | wc -l || echo 0)
EDA_SIZE=$(ls -lh ~/mqtt-ebpf-edge/results/generated/eda_$RUN_ID.jsonl 2>/dev/null | awk '{print $5}' || echo "N/A")

echo "  📂 Subscriber CSV: ${SUB_CSV_COUNT}개"
echo "  📊 총 지연 측정: ${TOTAL_LINES}개 라인"
echo "  🔍 eBPF 로그: ${EDA_SIZE}"
echo ""
echo "📁 저장 위치: ~/mqtt-ebpf-edge/results/generated/$RUN_ID/"
echo ""
echo "🎯 메타데이터:"
cat ~/mqtt-ebpf-edge/results/generated/$RUN_ID/metadata.json | jq '.' 2>/dev/null || cat ~/mqtt-ebpf-edge/results/generated/$RUN_ID/metadata.json

echo ""
echo "🚀 PPO 학습 데이터 준비 완료!"
