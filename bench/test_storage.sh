#!/bin/bash
# 짧은 테스트 - 저장 경로 확인용 (30초)

set -e

SSH_PASS="1231"
SSH_CMD="sshpass -p $SSH_PASS ssh -o StrictHostKeyChecking=no"

RUN_ID=test_storage
echo "🚀 짧은 테스트 $RUN_ID 시작 (30초)"

# 1. 네트워크 혼잡 건너뛰기
echo "📡 네트워크 혼잡 주입 건너뛰기..."

# 2. 결과 디렉토리 준비
mkdir -p ~/mqtt-ebpf-edge/results/generated/$RUN_ID

# 3. Subscriber 시작 (5개만)
echo "📥 Subscriber 시작 (5개)..."
$SSH_CMD sslab@192.168.0.3 "
    cd ~/jinuk/clients
    rm -rf results/
    mkdir -p ./results && chmod 777 ./results
    docker compose -f subscriber-compose.yml up -d --scale subscriber=5
" &

sleep 5

# 4. eBPF 에이전트 시작 (간단한 설정)
echo "🔍 eBPF 에이전트 시작..."
$SSH_CMD sslab@192.168.0.1 "
    cd ~/mqtt-ebpf-edge
    sudo -E \
        MQTT_HOST=192.168.0.1 \
        MQTT_PORT=23232 \
        CONTROL_TOPIC=control/room1 \
        EDA_OBSERVE=0 \
        HI_RTT_US=1000000 \
        LO_RTT_US=500000 \
        USE_ADAPTIVE=0 \
        python3 -u bpf/eda.py > ~/mqtt-ebpf-edge/results/generated/eda_$RUN_ID.jsonl 2>&1
" &

sleep 5

# 5. Publisher 시작 (5개만)
echo "📤 Publisher 시작 (5개)..."
$SSH_CMD sslab@192.168.0.2 "
    cd ~/jinuk/clients
    RATE=20 \
    BATCH=1 \
    QOS=1 \
    PAYLOAD_BYTES=128 \
    docker compose -f publisher-compose.yml up -d --build --scale publisher=5
" &

# 6. 짧은 실험 지속 (30초)
echo "⏱️  테스트 진행 중... (30초)"
sleep 30

# 7. Publisher 종료
echo "📤 Publisher 종료..."
$SSH_CMD sslab@192.168.0.2 "
    cd ~/jinuk/clients
    docker compose -f publisher-compose.yml down
    RUN_ID=$RUN_ID SERVICE_LABEL=publisher ./collect_publisher_logs.sh
"

# 8. Subscriber 종료
sleep 5
echo "📥 Subscriber 종료..."
$SSH_CMD sslab@192.168.0.3 "
    cd ~/jinuk/clients
    docker compose -f subscriber-compose.yml down
    RUN_ID=$RUN_ID ./collect_subscriber_logs.sh
"

# 9. eBPF 에이전트 종료
echo "🔍 eBPF 에이전트 종료..."
$SSH_CMD sslab@192.168.0.1 "sudo pkill -f 'eda.py' || true"

# 10. 로그 수집
echo "📊 로그 수집..."
MODE=generated RUN_ID=$RUN_ID SUB_HOST=192.168.0.3 PUB_HOST=192.168.0.2 USER_NAME=sslab \
bench/pull_logs_from_nodes.sh

echo "✅ 테스트 $RUN_ID 완료"

# 결과 확인
echo "📁 저장된 파일들:"
echo "📂 결과 디렉토리:"
ls -la ~/mqtt-ebpf-edge/results/generated/
echo ""
echo "📂 Subscriber 로그:"
ls -la ~/mqtt-ebpf-edge/results/generated/subs/$RUN_ID/ 2>/dev/null || echo "Subscriber 로그 없음"
echo ""
echo "📂 eBPF 로그:"
ls -la ~/mqtt-ebpf-edge/results/generated/eda_$RUN_ID.jsonl 2>/dev/null || echo "eBPF 로그 없음"

# 테스트 메타데이터 저장
cat > ~/mqtt-ebpf-edge/results/generated/$RUN_ID/metadata.json << EOF
{
    "run_id": "$RUN_ID",
    "timestamp": "$(date -Iseconds)",
    "test_type": "storage_verification",
    "duration": 30,
    "sub_count": 5,
    "pub_count": 5
}
EOF

echo "🎯 메타데이터:"
cat ~/mqtt-ebpf-edge/results/generated/$RUN_ID/metadata.json
