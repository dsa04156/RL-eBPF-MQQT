#!/usr/bin/env python3
# 실험 조합 수 추정

def estimate_combinations():
    print("🔢 실험 파라미터 조합 수 추정\n")
    
    # EDA 파라미터 범위 (수정된 generate_distributed_experiments.py 기준)
    eda_params = {
        "HI_RTT_US": "50~500ms (연속값)",
        "LO_RTT_US": "HI의 60~80% (연속값)", 
        "T_HOLD": "0.5~3.0s (연속값)",
        "SNDBUF/RCVBUF": "4가지 (128K/256K/512K/1024K)",
        "SND_RATIO": "연속값 (0.4~0.95)",
        "INTERVAL_S": "0.5~3.0s (연속값)",
        "EWMA_ALPHA": "0.1~0.5 (연속값)",
        "CTRL_RATE": "1~20 (20가지)",
        "CTRL_BATCH": "1~10 (10가지)",
        "TH_RETRANS": "4가지 (0,1,2,3)",
        "USE_ADAPTIVE": "2가지 (0,1)"
    }
    
    # 워크로드 파라미터
    workload_params = {
        "RATE": "30~100 msg/s (70가지)",
        "BATCH": "4가지 (1,2,5,10)",
        "QOS": "3가지 (0,1,2)",
        "PAYLOAD": "4가지 (128,256,512,1024B)",
        "PUB_COUNT": "15~25 (11가지)",
        "SUB_COUNT": "8~12 (5가지)",
        "DURATION": "150~200s (50가지)"
    }
    
    # 네트워크 시나리오
    network_params = {
        "scenario": "4가지 (light/moderate/heavy/burst)",
        "delay_ms": "시나리오별 범위 (연속값)",
        "loss_pct": "시나리오별 범위 (연속값)", 
        "bandwidth": "시나리오별 범위 (연속값)"
    }
    
    print("📊 주요 이산 파라미터 조합:")
    discrete_combinations = (
        4 *     # SNDBUF/RCVBUF 조합
        20 *    # CTRL_RATE
        10 *    # CTRL_BATCH
        4 *     # TH_RETRANS
        2 *     # USE_ADAPTIVE
        4 *     # BATCH (워크로드)
        3 *     # QOS
        4 *     # PAYLOAD
        4       # 네트워크 시나리오
    )
    print(f"  이산 파라미터만: {discrete_combinations:,}가지")
    
    print(f"\n📈 연속 파라미터 (RTT, 비율, 시간 등):")
    print(f"  - 각각 거의 무한대 조합 가능")
    print(f"  - 200개 샘플로는 공간의 {200/discrete_combinations*100:.4f}%만 커버")
    
    print(f"\n🎯 권장 실험 규모:")
    print(f"  - 기본 탐색: 1,000~2,000개")
    print(f"  - 세밀한 분석: 5,000~10,000개")
    print(f"  - 프로덕션급 학습: 20,000+개")
    
    print(f"\n⚡ 현실적 접근:")
    print(f"  1. Phase 1: 200개 (주요 패턴 파악)")
    print(f"  2. Phase 2: 성공적 영역 중심 1,000개 추가")
    print(f"  3. Phase 3: 최적화된 파라미터로 대규모 학습")
    
    print(f"\n🚀 병렬 실행 최적화:")
    print(f"  - 3노드 동시 실행시 실험당 ~5분")
    print(f"  - 200개: ~17시간")
    print(f"  - 1,000개: ~3.5일") 
    print(f"  - 밤/주말 자동 실행 필수")

if __name__ == "__main__":
    estimate_combinations()
