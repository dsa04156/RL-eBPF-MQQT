#!/bin/bash
# 빠른 테스트 실험 (30초만) - sshpass 사용
# RTT: 3243ms, 제어: 1Hz/1batch

set -e

SSH_PASS="1231"
SSH_CMD="sshpass -p $SSH_PASS ssh -o StrictHostKeyChecking=no"

RUN_ID=test_run_1
echo "🚀 테스트 실험 런 $RUN_ID 시작 (30초 단축 버전)"

# 1. 네트워크 혼잡 주입 건너뛰기 (로컬 테스트)
echo "📡 네트워크 혼잡 주입 건너뛰기..."

# 2. 결과 디렉토리 준비
mkdir -p ~/jinuk/results/generated/$RUN_ID

# 3. Subscriber 시작 (192.168.0.3)
echo "📥 Subscriber 시작 (10개)..."
$SSH_CMD sslab@192.168.0.3 "
    cd ~/jinuk/clients
    rm -rf results/
    mkdir -p ./results && chmod 777 ./results
    docker compose -f subscriber-compose.yml up -d --scale subscriber=10
" &

sleep 5

# 4. eBPF 에이전트 시작 (Broker)
echo "🔍 eBPF 에이전트 시작..."
$SSH_CMD sslab@192.168.0.1 "
    cd ~/mqtt-ebpf-edge
    sudo -E \
        MQTT_HOST=192.168.0.1 \
        MQTT_PORT=23232 \
        CONTROL_TOPIC=control/room1 \
        EDA_OBSERVE=0 \
        HI_RTT_US=3243783 \
        LO_RTT_US=2364853 \
        T_HOLD_ON=3.67 \
        T_HOLD_OFF=6.88 \
        TH_RETRANS=0 \
        TH_SNDBUF=174903 \
        TH_RCVBUF=174903 \
        SND_RATIO_HI=0.761 \
        SND_RATIO_LO=0.532 \
        INTERVAL_S=4.59 \
        CONTROL_MIN_SEC=4.59 \
        EWMA_ALPHA=0.492 \
        CTRL_RATE=1 \
        CTRL_BATCH=1 \
        USE_ADAPTIVE=1 \
        python3 -u bpf/eda.py > ~/results/eda_$RUN_ID.jsonl 2>&1
" &

sleep 5

# 5. Publisher 시작 (192.168.0.2)  
echo "📤 Publisher 시작 (20개)..."
$SSH_CMD sslab@192.168.0.2 "
    cd ~/jinuk/clients
    RATE=50 \
    BATCH=1 \
    QOS=1 \
    PAYLOAD_BYTES=256 \
    docker compose -f publisher-compose.yml up -d --build --scale publisher=20
" &

# 6. 짧은 실험 지속 (30초만)
echo "⏱️  테스트 실험 진행 중... (30초)"
sleep 30

# 7. Publisher 종료
echo "📤 Publisher 종료..."
$SSH_CMD sslab@192.168.0.2 "
    cd ~/jinuk/clients
    docker compose -f publisher-compose.yml down
"

# 8. Subscriber 종료
sleep 5
echo "📥 Subscriber 종료..."
$SSH_CMD sslab@192.168.0.3 "
    cd ~/jinuk/clients
    docker compose -f subscriber-compose.yml down
"

# 9. eBPF 에이전트 종료
echo "🔍 eBPF 에이전트 종료..."
$SSH_CMD sslab@192.168.0.1 "sudo pkill -f 'eda.py' || true"

# 10. 로그 확인
echo "📊 로그 확인..."
$SSH_CMD sslab@192.168.0.1 "
    echo '=== EDA 로그 샘플 ==='
    tail -5 ~/results/eda_$RUN_ID.jsonl || echo 'EDA 로그 없음'
"

echo "✅ 테스트 실험 런 $RUN_ID 완료"
