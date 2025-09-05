#!/bin/bash
# 완전 자동화 실험 런 29 - LHS 샘플 #29
# RTT: 4939ms, 제어: 9Hz/8batch
# 네트워크: light (지연: 10ms, 손실: 0.9%)

set -e

SSH_PASS="1231"
SSH_CMD="sshpass -p $SSH_PASS ssh -o StrictHostKeyChecking=no"

RUN_ID=ppo_run_29
echo "[*] 완전 자동화 실험 런 $RUN_ID 시작"

echo "[설정] 실험 설정:"
echo "  - RTT: 4939ms (Hi) / 3939ms (Lo)"
echo "  - 제어: 9Hz, 8batch"
echo "  - Publisher: 20개, 71msg/s"
echo "  - Subscriber: 9개"
echo "  - 지속시간: 188초"
echo "  - 네트워크: light (10ms, 0.9% 손실)"

# 1. 네트워크 혼잡 주입 (로컬 - Broker)
echo "[네트워크] 혼잡 주입..."
sudo tc qdisc del dev enp0s8 root 2>/dev/null || true
sudo tc qdisc add dev enp0s8 root handle 1: netem \
    delay 10ms \
    loss 0.9% \
    rate 50mbit

# 2. 결과 디렉토리 준비
mkdir -p ~/mqtt-ebpf-edge/results/generated/$RUN_ID
echo "[디렉토리] 생성 완료"

# 3. Subscriber 시작 (192.168.0.3)
echo "[Subscriber] 시작 (9개)..."
$SSH_CMD sslab@192.168.0.3 "
    cd ~/jinuk/clients
    docker compose -f subscriber-compose.yml down 2>/dev/null || true
    rm -rf results/
    mkdir -p ./results && chmod 777 ./results
    docker compose -f subscriber-compose.yml up -d --scale subscriber=9 > /dev/null 2>&1
    echo 'Subscriber 시작 완료'
"

sleep 5

# 4. eBPF 에이전트 시작 (로컬 - Broker)
echo "[eBPF] 에이전트 시작..."
cd ~/mqtt-ebpf-edge
sudo pkill -f 'eda.py' || true
sudo -E \
    MQTT_HOST=192.168.0.1 \
    MQTT_PORT=23232 \
    CONTROL_TOPIC=control/room1 \
    EDA_OBSERVE=0 \
    HI_RTT_US=4939266 \
    LO_RTT_US=3939292 \
    T_HOLD_ON=0.44 \
    T_HOLD_OFF=0.83 \
    TH_RETRANS=2 \
    TH_SNDBUF=534468 \
    TH_RCVBUF=534468 \
    SND_RATIO_HI=0.769 \
    SND_RATIO_LO=0.538 \
    INTERVAL_S=0.55 \
    CONTROL_MIN_SEC=0.55 \
    EWMA_ALPHA=0.424 \
    CTRL_RATE=9 \
    CTRL_BATCH=8 \
    USE_ADAPTIVE=1 \
    nohup python3 -u bpf/eda.py > ~/mqtt-ebpf-edge/results/generated/eda_$RUN_ID.jsonl 2>&1 &
echo 'eBPF 에이전트 백그라운드 시작'

sleep 3

# 5. Publisher 시작 (192.168.0.2)  
echo "[Publisher] 시작 (20개)..."
$SSH_CMD sslab@192.168.0.2 "
    cd ~/jinuk/clients
    docker compose -f publisher-compose.yml down 2>/dev/null || true
    RATE=71 \
    BATCH=1 \
    QOS=0 \
    PAYLOAD_BYTES=256 \
    docker compose -f publisher-compose.yml up -d --build --scale publisher=20 > /dev/null 2>&1 &
    echo 'Publisher 시작 완료
'
"

# 6. 실험 진행 중 - 실시간 모니터링
echo "[실험] 진행 중... (188초)"
echo "[진행] 상황:"

DURATION=188
STEP_SIZE=10
STEPS=$((DURATION / STEP_SIZE))

for ((i=1; i<=STEPS; i++)); do
    ELAPSED=$((i * STEP_SIZE))
    PROGRESS=$((ELAPSED * 100 / DURATION))
    
    echo -ne "[K[진행] ${ELAPSED}/${DURATION}초 (${PROGRESS}%)"
    sleep $STEP_SIZE
done

# 남은 시간 처리
REMAINING=$((DURATION % STEP_SIZE))
if [ $REMAINING -gt 0 ]; then
    echo "[마지막] ${REMAINING}초..."
    sleep $REMAINING
fi

echo "[완료] 실험 시간 완료!"

# 7. Publisher 종료
echo "[Publisher] 종료..."
$SSH_CMD sslab@192.168.0.2 "
    cd ~/jinuk/clients
    docker compose -f publisher-compose.yml down > /dev/null 2>&1
    RUN_ID=$RUN_ID SERVICE_LABEL=publisher ./collect_publisher_logs.sh
"

# 8. Subscriber 종료 (조금 더 대기)
sleep 10
echo "[Subscriber] 종료..."
$SSH_CMD sslab@192.168.0.3 "
    cd ~/jinuk/clients
    echo '[DEBUG] Subscriber 컨테이너 상태:'
    docker ps | grep subscriber || echo 'Subscriber 컨테이너 없음'
    echo '[DEBUG] Docker Compose 종료 중...'
    docker compose -f subscriber-compose.yml down > /dev/null 2>&1 || true
    echo '[DEBUG] 로그 수집 시작...'
    RUN_ID=$RUN_ID ./collect_subscriber_logs.sh || echo '[ERROR] 로그 수집 실패'
    echo '[DEBUG] Subscriber 처리 완료'
"

# 9. eBPF 에이전트 종료 (로컬 - Broker)
echo "[eBPF] 에이전트 종료..."
sudo pkill -f 'eda.py' || true

# 10. 로그 수집
echo "[로그] 수집..."
cd ~/mqtt-ebpf-edge
MODE=generated RUN_ID=$RUN_ID SUB_HOST=192.168.0.3 PUB_HOST=192.168.0.2 USER_NAME=sslab \
bash bench/pull_logs_from_nodes.sh

# 11. 네트워크 혼잡 해제 (로컬 - Broker)
echo "[네트워크] 혼잡 해제..."
sudo tc qdisc del dev enp0s8 root 2>/dev/null || true

echo "[완료] 실험 런 $RUN_ID 완료"

# 실험 메타데이터 저장
cat > ~/mqtt-ebpf-edge/results/generated/$RUN_ID/metadata.json << EOF
{
    "run_id": "$RUN_ID",
    "timestamp": "$(date -Iseconds)",
    "experiment_type": "lhs_distributed_ppo_training",
    "lhs_sample_id": 29,
    "network_config": {'scenario': 'light', 'delay_ms': 10, 'loss_pct': 0.8709453872293338, 'bandwidth_mbps': 50},
    "workload_config": {'RATE': 71, 'BATCH': 1, 'QOS': 0, 'PAYLOAD_BYTES': 256, 'PUB_COUNT': 20, 'SUB_COUNT': 9, 'DURATION': 188},
    "eda_config": {'HI_RTT_US': 4939266, 'LO_RTT_US': 3939292, 'T_HOLD_ON': 0.44, 'T_HOLD_OFF': 0.83, 'INTERVAL_S': 0.55, 'CONTROL_MIN_SEC': 0.55, 'CTRL_RATE': 9, 'CTRL_BATCH': 8, 'EWMA_ALPHA': 0.424, 'TH_RETRANS': 2, 'TH_SNDBUF': 534468, 'TH_RCVBUF': 534468, 'SND_RATIO_HI': 0.769, 'SND_RATIO_LO': 0.538, 'USE_ADAPTIVE': 1, 'SAMPLE_ID': 29, 'LHS_COORDS': [0.9877, 0.0538, 0.4288, 0.7813, 0.8109, 0.7045, 0.4397, 0.277, 0.7993]},
    "infrastructure": {
        "broker_host": "192.168.0.1",
        "publisher_host": "192.168.0.2",
        "subscriber_host": "192.168.0.3",
        "broker_port": 23232,
        "control_topic": "control/room1"
    },
    "data_collection": {
        "subscriber_csv_expected": 9,
        "eda_log_path": "eda_$RUN_ID.jsonl",
        "duration_sec": 188
    }
}
EOF

# 12. 결과 확인 및 요약
echo ""
echo " 실험 런 $RUN_ID 완료!"
echo ""
echo "수집된 데이터:"
SUB_CSV_COUNT=$(find ~/mqtt-ebpf-edge/results/generated/subs/$RUN_ID/ -name "*_lat.csv" 2>/dev/null | wc -l)
TOTAL_LINES=$(cat ~/mqtt-ebpf-edge/results/generated/subs/$RUN_ID/*_lat.csv 2>/dev/null | wc -l || echo 0)
EDA_SIZE=$(ls -lh ~/mqtt-ebpf-edge/results/generated/eda_$RUN_ID.jsonl 2>/dev/null | awk '{print $5}' || echo "N/A")

echo "  Subscriber CSV: ${SUB_CSV_COUNT}개"
echo "  총 지연 측정: ${TOTAL_LINES}개 라인"
echo "  eBPF 로그: ${EDA_SIZE}"
echo ""
echo "저장 위치: ~/mqtt-ebpf-edge/results/generated/$RUN_ID/"
echo ""
echo " 메타데이터:"
cat ~/mqtt-ebpf-edge/results/generated/$RUN_ID/metadata.json
echo ""
echo " LHS 실험 #29 완전 자동화 성공!"
