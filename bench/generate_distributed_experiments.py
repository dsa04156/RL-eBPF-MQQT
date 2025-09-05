#!/usr/bin/env python3
# generate_distributed_experiments.py - LHS 기반 분산 실험 자동 생성

import os
import time
import random
import subprocess
import numpy as np
from pathlib import Path
from scipy.stats import qmc

class ExperimentGenerator:
    def __init__(self):
        self.broker_host = "192.168.0.1"
        self.publisher_host = "192.168.0.2" 
        self.subscriber_host = "192.168.0.3"
        self.mqtt_port = 23232
        self.lhs_samples = None  # LHS 샘플을 저장
        
    def generate_lhs_samples(self, n_samples=200, seed=42):
        """Latin Hypercube Sampling으로 파라미터 공간 생성"""
        
        # 9차원 파라미터 공간 정의
        dimensions = [
            "hi_rtt_scale",     # 0: RTT 규모 (0=50ms, 1=5000ms)
            "timing_factor",    # 1: 타이밍 스케일 (0=빠름, 1=느림)
            "ctrl_rate_scale",  # 2: 제어 속도 (0=1Hz, 1=20Hz)
            "ctrl_batch_scale", # 3: 배치 크기 (0=1, 1=10)
            "ewma_alpha",       # 4: EWMA 계수 (0=0.1, 1=0.5)
            "th_retrans",       # 5: 재전송 임계값 (0=0, 1=3)
            "buffer_scale",     # 6: 버퍼 크기 (0=128KB, 1=1024KB)
            "ratio_hi",         # 7: 비율 상한 (0=0.7, 1=0.95)
            "adaptive_prob"     # 8: 적응형 확률 (0=OFF, 1=ON)
        ]
        
        print(f"🎲 LHS로 {n_samples}개 샘플 생성 중... (seed={seed})")
        
        # LHS 샘플러 생성
        sampler = qmc.LatinHypercube(d=len(dimensions), seed=seed)
        samples = sampler.random(n=n_samples)
        
        self.lhs_samples = []
        for i, sample in enumerate(samples):
            # 각 차원을 실제 파라미터로 변환
            hi_rtt_ms = 50 + sample[0] * (5000 - 50)  # 50ms ~ 5000ms
            lo_rtt_ms = hi_rtt_ms * (0.6 + 0.2 * sample[0])  # 60~80% of HI
            
            timing_factor = 0.3 + sample[1] * 4.7  # 0.3x ~ 5.0x
            
            params = {
                "HI_RTT_US": int(hi_rtt_ms * 1000),
                "LO_RTT_US": int(lo_rtt_ms * 1000),
                "T_HOLD_ON": round(0.8 * timing_factor, 2),
                "T_HOLD_OFF": round(1.5 * timing_factor, 2),
                "INTERVAL_S": round(1.0 * timing_factor, 2),
                "CONTROL_MIN_SEC": round(1.0 * timing_factor, 2),
                "CTRL_RATE": int(1 + sample[2] * 19),  # 1~20 Hz
                "CTRL_BATCH": int(1 + sample[3] * 9),  # 1~10
                "EWMA_ALPHA": round(0.1 + sample[4] * 0.4, 3),  # 0.1~0.5
                "TH_RETRANS": int(sample[5] * 4),  # 0~3
                "TH_SNDBUF": int((128 + sample[6] * 896) * 1024),  # 128KB~1024KB
                "TH_RCVBUF": int((128 + sample[6] * 896) * 1024),
                "SND_RATIO_HI": round(0.7 + sample[7] * 0.25, 3),  # 0.7~0.95
                "SND_RATIO_LO": round((0.7 + sample[7] * 0.25) * 0.7, 3),  # HI의 70%
                "USE_ADAPTIVE": 1 if sample[8] > 0.75 else 0,  # 25% 확률로 적응형
                "SAMPLE_ID": i + 1,
                "LHS_COORDS": [round(x, 4) for x in sample]  # 디버깅용
            }
            self.lhs_samples.append(params)
        
        print(f"✅ LHS 샘플 생성 완료!")
        print(f"📊 RTT 범위: {min(s['HI_RTT_US']//1000 for s in self.lhs_samples)}ms ~ {max(s['HI_RTT_US']//1000 for s in self.lhs_samples)}ms")
        print(f"📊 제어 속도: {min(s['CTRL_RATE'] for s in self.lhs_samples)}~{max(s['CTRL_RATE'] for s in self.lhs_samples)} Hz")
        print(f"📊 적응형 모드: {sum(s['USE_ADAPTIVE'] for s in self.lhs_samples)}/{n_samples}개")
        
        return self.lhs_samples
        
    def generate_eda_params(self, run_id):
        """LHS 샘플에서 EDA 파라미터 반환"""
        
        if self.lhs_samples is None:
            raise ValueError("먼저 generate_lhs_samples()를 호출하세요")
        
        if run_id > len(self.lhs_samples):
            raise ValueError(f"run_id {run_id}가 샘플 수 {len(self.lhs_samples)}를 초과")
        
        # LHS 샘플에서 해당 run_id의 파라미터 반환
        return self.lhs_samples[run_id - 1].copy()
    
    def generate_workload_params(self, run_id):
        """워크로드 파라미터 다양화"""
        
        return {
            "RATE": random.randint(30, 100),           # 30-100 msg/s
            "BATCH": random.choice([1, 2, 5, 10]),     # 배치 크기
            "QOS": random.choice([0, 1, 2]),           # QoS 레벨
            "PAYLOAD_BYTES": random.choice([128, 256, 512, 1024]),
            "PUB_COUNT": random.randint(15, 25),       # 15-25 publishers
            "SUB_COUNT": random.randint(8, 12),        # 8-12 subscribers
            "DURATION": random.randint(150, 200)       # 150-200초
        }
    
    def generate_network_params(self, run_id):
        """네트워크 혼잡 파라미터 다양화"""
        
        # 혼잡 시나리오 선택
        scenario = random.choice(["light", "moderate", "heavy", "burst"])
        
        if scenario == "light":
            delay_ms = random.randint(10, 50)
            loss_pct = random.uniform(0, 1)
            bandwidth_mbps = random.randint(50, 100)
        elif scenario == "moderate":
            delay_ms = random.randint(50, 150)
            loss_pct = random.uniform(1, 3)
            bandwidth_mbps = random.randint(20, 50)
        elif scenario == "heavy":
            delay_ms = random.randint(150, 300)
            loss_pct = random.uniform(3, 8)
            bandwidth_mbps = random.randint(5, 20)
        else:  # burst
            delay_ms = random.randint(20, 100)
            loss_pct = random.uniform(0, 2)
            bandwidth_mbps = random.randint(10, 30)
            
        return {
            "scenario": scenario,
            "delay_ms": delay_ms,
            "loss_pct": loss_pct,
            "bandwidth_mbps": bandwidth_mbps
        }
    
    def create_experiment_script(self, run_id):
        """단일 실험을 위한 스크립트 생성"""
        
        eda_params = self.generate_eda_params(run_id)
        workload_params = self.generate_workload_params(run_id)
        network_params = self.generate_network_params(run_id)
        
        script_content = f"""#!/bin/bash
# 완전 자동화 실험 런 {run_id} - LHS 샘플 #{eda_params['SAMPLE_ID']}
# RTT: {eda_params['HI_RTT_US']//1000}ms, 제어: {eda_params['CTRL_RATE']}Hz/{eda_params['CTRL_BATCH']}batch
# 네트워크: {network_params['scenario']} (지연: {network_params['delay_ms']}ms, 손실: {network_params['loss_pct']:.1f}%)

set -e

SSH_PASS="1231"
SSH_CMD="sshpass -p $SSH_PASS ssh -o StrictHostKeyChecking=no"

RUN_ID=ppo_run_{run_id}
echo "[*] 완전 자동화 실험 런 $RUN_ID 시작"

echo "[설정] 실험 설정:"
echo "  - RTT: {eda_params['HI_RTT_US']//1000}ms (Hi) / {eda_params['LO_RTT_US']//1000}ms (Lo)"
echo "  - 제어: {eda_params['CTRL_RATE']}Hz, {eda_params['CTRL_BATCH']}batch"
echo "  - Publisher: {workload_params['PUB_COUNT']}개, {workload_params['RATE']}msg/s"
echo "  - Subscriber: {workload_params['SUB_COUNT']}개"
echo "  - 지속시간: {workload_params['DURATION']}초"
echo "  - 네트워크: {network_params['scenario']} ({network_params['delay_ms']}ms, {network_params['loss_pct']:.1f}% 손실)"

# 1. 네트워크 혼잡 주입 (로컬 - Broker)
echo "[네트워크] 혼잡 주입..."
sudo tc qdisc del dev enp0s8 root 2>/dev/null || true
sudo tc qdisc add dev enp0s8 root handle 1: netem \\
    delay {network_params['delay_ms']}ms \\
    loss {network_params['loss_pct']:.1f}% \\
    rate {network_params['bandwidth_mbps']}mbit

# 2. 결과 디렉토리 준비
mkdir -p ~/mqtt-ebpf-edge/results/generated/$RUN_ID
echo "[디렉토리] 생성 완료"

# 3. Subscriber 시작 ({self.subscriber_host})
echo "[Subscriber] 시작 ({workload_params['SUB_COUNT']}개)..."
$SSH_CMD sslab@{self.subscriber_host} "
    cd ~/jinuk/clients
    docker compose -f subscriber-compose.yml down 2>/dev/null || true
    rm -rf results/
    mkdir -p ./results && chmod 777 ./results
    docker compose -f subscriber-compose.yml up -d --scale subscriber={workload_params['SUB_COUNT']} > /dev/null 2>&1
    echo 'Subscriber 시작 완료'
"

sleep 5

# 4. eBPF 에이전트 시작 (로컬 - Broker)
echo "[eBPF] 에이전트 시작..."
cd ~/mqtt-ebpf-edge
sudo pkill -f 'eda.py' || true
sudo -E \\
    MQTT_HOST={self.broker_host} \\
    MQTT_PORT={self.mqtt_port} \\
    CONTROL_TOPIC=control/room1 \\
    EDA_OBSERVE=0 \\
    HI_RTT_US={eda_params['HI_RTT_US']} \\
    LO_RTT_US={eda_params['LO_RTT_US']} \\
    T_HOLD_ON={eda_params['T_HOLD_ON']} \\
    T_HOLD_OFF={eda_params['T_HOLD_OFF']} \\
    TH_RETRANS={eda_params['TH_RETRANS']} \\
    TH_SNDBUF={eda_params['TH_SNDBUF']} \\
    TH_RCVBUF={eda_params['TH_RCVBUF']} \\
    SND_RATIO_HI={eda_params['SND_RATIO_HI']} \\
    SND_RATIO_LO={eda_params['SND_RATIO_LO']} \\
    INTERVAL_S={eda_params['INTERVAL_S']} \\
    CONTROL_MIN_SEC={eda_params['CONTROL_MIN_SEC']} \\
    EWMA_ALPHA={eda_params['EWMA_ALPHA']} \\
    CTRL_RATE={eda_params['CTRL_RATE']} \\
    CTRL_BATCH={eda_params['CTRL_BATCH']} \\
    USE_ADAPTIVE={eda_params['USE_ADAPTIVE']} \\
    nohup python3 -u bpf/eda.py > ~/mqtt-ebpf-edge/results/generated/eda_$RUN_ID.jsonl 2>&1 &
echo 'eBPF 에이전트 백그라운드 시작'

sleep 3

# 5. Publisher 시작 ({self.publisher_host})  
echo "[Publisher] 시작 ({workload_params['PUB_COUNT']}개)..."
$SSH_CMD sslab@{self.publisher_host} "
    cd ~/jinuk/clients
    docker compose -f publisher-compose.yml down 2>/dev/null || true
    RATE={workload_params['RATE']} \\
    BATCH={workload_params['BATCH']} \\
    QOS={workload_params['QOS']} \\
    PAYLOAD_BYTES={workload_params['PAYLOAD_BYTES']} \\
    docker compose -f publisher-compose.yml up -d --build --scale publisher={workload_params['PUB_COUNT']} > /dev/null 2>&1 &
    echo 'Publisher 시작 완료\n'
"

# 6. 실험 진행 중 - 실시간 모니터링
echo "[실험] 진행 중... ({workload_params['DURATION']}초)"
echo "[진행] 상황:"

DURATION={workload_params['DURATION']}
STEP_SIZE=10
STEPS=$((DURATION / STEP_SIZE))

for ((i=1; i<=STEPS; i++)); do
    ELAPSED=$((i * STEP_SIZE))
    PROGRESS=$((ELAPSED * 100 / DURATION))
    
    echo -ne "\r\033[K[진행] ${{ELAPSED}}/${{DURATION}}초 (${{PROGRESS}}%)"
    sleep $STEP_SIZE
done

# 남은 시간 처리
REMAINING=$((DURATION % STEP_SIZE))
if [ $REMAINING -gt 0 ]; then
    echo "[마지막] ${{REMAINING}}초..."
    sleep $REMAINING
fi

echo "[완료] 실험 시간 완료!"

# 7. Publisher 종료
echo "[Publisher] 종료..."
$SSH_CMD sslab@{self.publisher_host} "
    cd ~/jinuk/clients
    docker compose -f publisher-compose.yml down > /dev/null 2>&1
    RUN_ID=$RUN_ID SERVICE_LABEL=publisher ./collect_publisher_logs.sh
"

# 8. Subscriber 종료 (조금 더 대기)
sleep 10
echo "[Subscriber] 종료..."
$SSH_CMD sslab@{self.subscriber_host} "
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
MODE=generated RUN_ID=$RUN_ID SUB_HOST={self.subscriber_host} PUB_HOST={self.publisher_host} USER_NAME=sslab \\
bash bench/pull_logs_from_nodes.sh

# 11. 네트워크 혼잡 해제 (로컬 - Broker)
echo "[네트워크] 혼잡 해제..."
sudo tc qdisc del dev enp0s8 root 2>/dev/null || true

echo "[완료] 실험 런 $RUN_ID 완료"

# 실험 메타데이터 저장
cat > ~/mqtt-ebpf-edge/results/generated/$RUN_ID/metadata.json << EOF
{{
    "run_id": "$RUN_ID",
    "timestamp": "$(date -Iseconds)",
    "experiment_type": "lhs_distributed_ppo_training",
    "lhs_sample_id": {eda_params['SAMPLE_ID']},
    "network_config": {network_params},
    "workload_config": {workload_params},
    "eda_config": {eda_params},
    "infrastructure": {{
        "broker_host": "{self.broker_host}",
        "publisher_host": "{self.publisher_host}",
        "subscriber_host": "{self.subscriber_host}",
        "broker_port": 23232,
        "control_topic": "control/room1"
    }},
    "data_collection": {{
        "subscriber_csv_expected": {workload_params['SUB_COUNT']},
        "eda_log_path": "eda_$RUN_ID.jsonl",
        "duration_sec": {workload_params['DURATION']}
    }}
}}
EOF

# 12. 결과 확인 및 요약
echo ""
echo " 실험 런 $RUN_ID 완료!"
echo ""
echo "수집된 데이터:"
SUB_CSV_COUNT=$(find ~/mqtt-ebpf-edge/results/generated/subs/$RUN_ID/ -name "*_lat.csv" 2>/dev/null | wc -l)
TOTAL_LINES=$(cat ~/mqtt-ebpf-edge/results/generated/subs/$RUN_ID/*_lat.csv 2>/dev/null | wc -l || echo 0)
EDA_SIZE=$(ls -lh ~/mqtt-ebpf-edge/results/generated/eda_$RUN_ID.jsonl 2>/dev/null | awk '{{print $5}}' || echo "N/A")

echo "  Subscriber CSV: ${{SUB_CSV_COUNT}}개"
echo "  총 지연 측정: ${{TOTAL_LINES}}개 라인"
echo "  eBPF 로그: ${{EDA_SIZE}}"
echo ""
echo "저장 위치: ~/mqtt-ebpf-edge/results/generated/$RUN_ID/"
echo ""
echo " 메타데이터:"
cat ~/mqtt-ebpf-edge/results/generated/$RUN_ID/metadata.json
echo ""
echo " LHS 실험 #{eda_params['SAMPLE_ID']} 완전 자동화 성공!"
"""
        
        script_path = Path(f"experiment_scripts/run_{run_id}.sh")
        script_path.parent.mkdir(exist_ok=True)
        
        with open(script_path, 'w') as f:
            f.write(script_content)
        
        os.chmod(script_path, 0o755)
        return script_path
    
    def generate_all_experiments(self, num_runs=200):
        """LHS 기반 모든 실험 스크립트 생성"""
        
        print(f"🔧 LHS 기반 {num_runs}개 실험 스크립트 생성 중...")
        
        # 먼저 LHS 샘플 생성
        self.generate_lhs_samples(num_runs)
        
        script_paths = []
        for run_id in range(1, num_runs + 1):
            script_path = self.create_experiment_script(run_id)
            script_paths.append(script_path)
            
            if run_id % 20 == 0:
                print(f"  📝 {run_id}/{num_runs} 스크립트 생성 완료")
        
        print(f"✅ 모든 스크립트 생성 완료!")
        print(f"📁 위치: experiment_scripts/")
        
        # LHS 샘플 정보 저장
        import json
        with open("lhs_samples.json", 'w') as f:
            json.dump(self.lhs_samples, f, indent=2)
        print(f"📊 LHS 샘플 정보 저장: lhs_samples.json")
        
        # 마스터 실행 스크립트 생성
        master_script = f"""#!/bin/bash
# LHS 기반 마스터 실험 실행 스크립트
echo "🚀 LHS 샘플링 {num_runs}개 실험 런 시작"

for i in {{1..{num_runs}}}; do
    echo "📊 LHS 실험 $i/{num_runs} 실행 중..."
    ./experiment_scripts/run_$i.sh
    
    if [ $? -eq 0 ]; then
        echo "✅ 실험 $i 성공"
    else
        echo "❌ 실험 $i 실패"
    fi
    
    # 서버 간 쿨다운
    echo "😴 30초 쿨다운..."
    sleep 30
done

echo "🎉 모든 LHS 실험 완료!"
"""
        
        with open("run_all_experiments.sh", 'w') as f:
            f.write(master_script)
        os.chmod("run_all_experiments.sh", 0o755)
        
        print(f"🎯 실행 방법:")
        print(f"  전체 실행: ./run_all_experiments.sh")
        print(f"  개별 실행: ./experiment_scripts/run_1.sh")
        print(f"  부분 실행: ./experiment_scripts/run_{{1..50}}.sh")
        
        return script_paths

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="분산 환경 실험 스크립트 생성")
    parser.add_argument("--runs", type=int, default=200, help="생성할 실험 런 수")
    parser.add_argument("--test", action="store_true", help="테스트용 (5개 런)")
    
    args = parser.parse_args()
    
    generator = ExperimentGenerator()
    
    if args.test:
        print("🧪 테스트 모드: 5개 실험 런 생성")
        generator.generate_all_experiments(5)
    else:
        generator.generate_all_experiments(args.runs)