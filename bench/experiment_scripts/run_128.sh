#!/bin/bash
# 완전 자동화 실험 런 128 - LHS 샘플 #128
# RTT: 2009ms, 제어: 10Hz/5batch
# 네트워크: heavy (지연: 268ms, 손실: 6.7%)

set -e

SSH_PASS="1231"
SSH_CMD="sshpass -p $SSH_PASS ssh -o StrictHostKeyChecking=no"

RUN_ID=ppo_run_128
echo "[*] 완전 자동화 실험 런 $RUN_ID 시작"

echo "[설정] 실험 설정:"
echo "  - RTT: 2009ms (Hi) / 1364ms (Lo)"
echo "  - 제어: 10Hz, 5batch"
echo "  - Publisher: 23개, 37msg/s"
echo "  - Subscriber: 10개"
echo "  - 지속시간: 174초"
echo "  - 네트워크: heavy (268ms, 6.7% 손실)"

# 1. 네트워크 혼잡 주입 (로컬 - Broker)
echo "[네트워크] 혼잡 주입..."
sudo tc qdisc del dev enp0s8 root 2>/dev/null || true
sudo tc qdisc add dev enp0s8 root handle 1: netem \
    delay 268ms \
    loss 6.7% \
    rate 10mbit

# 2. 결과 디렉토리 준비
mkdir -p ~/mqtt-ebpf-edge/results/generated/$RUN_ID
echo "[디렉토리] 생성 완료"

# 3. Subscriber 시작 (192.168.0.3)
echo "[Subscriber] 시작 (10개)..."
$SSH_CMD sslab@192.168.0.3 "
    cd ~/jinuk/clients
    docker compose -f subscriber-compose.yml down 2>/dev/null || true
    rm -rf results/
    mkdir -p ./results && chmod 777 ./results
    docker compose -f subscriber-compose.yml up -d --scale subscriber=10 > /dev/null 2>&1
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
    HI_RTT_US=2009674 \
    LO_RTT_US=1364928 \
    T_HOLD_ON=3.05 \
    T_HOLD_OFF=5.72 \
    TH_RETRANS=3 \
    TH_SNDBUF=672890 \
    TH_RCVBUF=672890 \
    SND_RATIO_HI=0.927 \
    SND_RATIO_LO=0.649 \
    INTERVAL_S=3.82 \
    CONTROL_MIN_SEC=3.82 \
    EWMA_ALPHA=0.478 \
    CTRL_RATE=10 \
    CTRL_BATCH=5 \
    USE_ADAPTIVE=0 \
    nohup python3 -u bpf/eda.py > ~/mqtt-ebpf-edge/results/generated/eda_$RUN_ID.jsonl 2>&1 &
echo 'eBPF 에이전트 백그라운드 시작'

sleep 3

# 5. Publisher 시작 (192.168.0.2)  
echo "[Publisher] 시작 (23개)..."
$SSH_CMD sslab@192.168.0.2 "
    cd ~/jinuk/clients
    docker compose -f publisher-compose.yml down 2>/dev/null || true
    RATE=37 \
    BATCH=10 \
    QOS=0 \
    PAYLOAD_BYTES=512 \
    docker compose -f publisher-compose.yml up -d --build --scale publisher=23 > /dev/null 2>&1 &
    echo 'Publisher 시작 완료
'
"

# 6. 실험 진행 중 - 실시간 모니터링
echo "[실험] 진행 중... (174초)"
echo "[진행] 상황:"

DURATION=174
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
    "lhs_sample_id": 128,
    "network_config": {'scenario': 'heavy', 'delay_ms': 268, 'loss_pct': 6.712457120187706, 'bandwidth_mbps': 10},
    "workload_config": {'RATE': 37, 'BATCH': 10, 'QOS': 0, 'PAYLOAD_BYTES': 512, 'PUB_COUNT': 23, 'SUB_COUNT': 10, 'DURATION': 174},
    "eda_config": {'HI_RTT_US': 2009674, 'LO_RTT_US': 1364928, 'T_HOLD_ON': 3.05, 'T_HOLD_OFF': 5.72, 'INTERVAL_S': 3.82, 'CONTROL_MIN_SEC': 3.82, 'CTRL_RATE': 10, 'CTRL_BATCH': 5, 'EWMA_ALPHA': 0.478, 'TH_RETRANS': 3, 'TH_SNDBUF': 672890, 'TH_RCVBUF': 672890, 'SND_RATIO_HI': 0.927, 'SND_RATIO_LO': 0.649, 'USE_ADAPTIVE': 0, 'SAMPLE_ID': 128, 'LHS_COORDS': [0.3959, 0.7479, 0.4984, 0.4913, 0.946, 0.8075, 0.5905, 0.9093, 0.5306]},
    "infrastructure": {
        "broker_host": "192.168.0.1",
        "publisher_host": "192.168.0.2",
        "subscriber_host": "192.168.0.3",
        "broker_port": 23232,
        "control_topic": "control/room1"
    },
    "data_collection": {
        "subscriber_csv_expected": 10,
        "eda_log_path": "eda_$RUN_ID.jsonl",
        "duration_sec": 174
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
echo " LHS 실험 #128 완전 자동화 성공!"
