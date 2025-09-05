#!/usr/bin/env python3
# generate_focused_experiments.py - Phase 2: 성공 구간 집중 탐색

import os
import json
import random
from pathlib import Path
from generate_distributed_experiments import ExperimentGenerator

class FocusedExperimentGenerator(ExperimentGenerator):
    def __init__(self, success_ranges=None):
        super().__init__()
        # Phase 1 결과에서 성공한 파라미터 범위
        self.success_ranges = success_ranges or self.get_default_success_ranges()
    
    def get_default_success_ranges(self):
        """Phase 1 분석 전 기본 좁은 범위 (사용자 성공 경험 기반)"""
        return {
            "hi_rtt_ms": (1500, 4500),      # 1.5~4.5초
            "lo_ratio": (0.6, 0.8),         # HI의 60~80%
            "t_hold_on": (0.5, 1.5),        # 0.5~1.5초
            "t_hold_off": (1.0, 3.0),       # 1.0~3.0초
            "interval_s": (0.8, 2.0),       # 0.8~2.0초
            "control_min_sec": (0.8, 2.0),  # 0.8~2.0초
            "ewma_alpha": (0.2, 0.4),       # 0.2~0.4
            "ctrl_rate": (3, 8),            # 3~8 Hz
            "ctrl_batch": (1, 3),           # 1~3 배치
            "snd_ratio_hi": (0.8, 0.95),    # 80~95%
            "snd_ratio_lo": (0.5, 0.7)      # 50~70%
        }
    
    def load_success_ranges_from_analysis(self, analysis_file):
        """Phase 1 분석 결과에서 성공 범위 로드"""
        try:
            with open(analysis_file, 'r') as f:
                analysis = json.load(f)
            
            # 상위 25% 성능 실험들의 파라미터 범위 추출
            top_experiments = analysis.get('top_25_percent', [])
            
            ranges = {}
            for param in ['hi_rtt_ms', 'interval_s', 'ewma_alpha', 'ctrl_rate']:
                values = [exp['params'][param] for exp in top_experiments if param in exp['params']]
                if values:
                    ranges[param] = (min(values) * 0.8, max(values) * 1.2)  # 20% 여유
            
            self.success_ranges.update(ranges)
            print(f"✅ 성공 범위 업데이트: {analysis_file}")
            
        except Exception as e:
            print(f"⚠️  분석 파일 로드 실패, 기본 범위 사용: {e}")
    
    def generate_eda_params(self, run_id):
        """Phase 2: 성공 구간 집중 파라미터 생성"""
        ranges = self.success_ranges
        
        # RTT 임계값 (성공 구간 집중)
        hi_rtt_ms = random.uniform(*ranges['hi_rtt_ms'])
        lo_rtt_ms = hi_rtt_ms * random.uniform(*ranges['lo_ratio'])
        hi_rtt_us = int(hi_rtt_ms * 1000)
        lo_rtt_us = int(lo_rtt_ms * 1000)
        
        # 홀드 타임 (성공 구간)
        t_hold_on = random.uniform(*ranges['t_hold_on'])
        t_hold_off = random.uniform(*ranges['t_hold_off'])
        
        # 버퍼 임계값 (검증된 값들 위주)
        th_sndbuf = random.choice([256, 512]) * 1024  # 256K, 512K 집중
        th_rcvbuf = random.choice([256, 512]) * 1024
        
        # 비율 임계값 (성공 구간)
        snd_ratio_hi = random.uniform(*ranges['snd_ratio_hi'])
        snd_ratio_lo = random.uniform(*ranges['snd_ratio_lo'])
        
        # 제어 파라미터 (성공 구간 집중)
        interval_s = random.uniform(*ranges['interval_s'])
        control_min_sec = random.uniform(*ranges['control_min_sec'])
        ewma_alpha = random.uniform(*ranges['ewma_alpha'])
        
        # 제어 명령 (성공 구간)
        ctrl_rate = random.randint(*ranges['ctrl_rate'])
        ctrl_batch = random.randint(*ranges['ctrl_batch'])
        
        # 재전송 임계값 (보수적)
        th_retrans = random.choice([0, 1])  # 0, 1만 (너무 관대하지 않게)
        
        # 적응형 (일단 끄고 시작)
        use_adaptive = 0  # Phase 2에서는 고정 임계값 집중
        
        return {
            "HI_RTT_US": hi_rtt_us,
            "LO_RTT_US": lo_rtt_us,
            "T_HOLD_ON": t_hold_on,
            "T_HOLD_OFF": t_hold_off,
            "TH_SNDBUF": th_sndbuf,
            "TH_RCVBUF": th_rcvbuf,
            "SND_RATIO_HI": snd_ratio_hi,
            "SND_RATIO_LO": snd_ratio_lo,
            "INTERVAL_S": interval_s,
            "CONTROL_MIN_SEC": control_min_sec,
            "EWMA_ALPHA": ewma_alpha,
            "CTRL_RATE": ctrl_rate,
            "CTRL_BATCH": ctrl_batch,
            "TH_RETRANS": th_retrans,
            "USE_ADAPTIVE": use_adaptive
        }
    
    def generate_workload_params(self, run_id):
        """Phase 2: 현실적 워크로드 집중"""
        return {
            "RATE": random.randint(50, 80),            # 50-80 msg/s (현실적 범위)
            "BATCH": random.choice([1, 2, 5]),         # 1, 2, 5 집중
            "QOS": random.choice([1, 2]),              # QoS 1,2 집중 (실용적)
            "PAYLOAD_BYTES": random.choice([256, 512, 1024]),  # 중간 크기 집중
            "PUB_COUNT": random.randint(18, 22),       # 18-22 publishers
            "SUB_COUNT": random.randint(9, 11),        # 9-11 subscribers  
            "DURATION": random.randint(180, 220)       # 180-220초 (충분한 데이터)
        }

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Phase 2: 성공 구간 집중 실험")
    parser.add_argument("--runs", type=int, default=500, help="생성할 실험 런 수")
    parser.add_argument("--analysis", type=str, help="Phase 1 분석 결과 JSON 파일")
    parser.add_argument("--test", action="store_true", help="테스트용 (10개 런)")
    
    args = parser.parse_args()
    
    generator = FocusedExperimentGenerator()
    
    if args.analysis:
        generator.load_success_ranges_from_analysis(args.analysis)
    
    if args.test:
        print("🧪 Phase 2 테스트 모드: 10개 실험 런 생성")
        generator.generate_all_experiments(10)
    else:
        print(f"🎯 Phase 2: 성공 구간 집중 {args.runs}개 실험 생성")
        generator.generate_all_experiments(args.runs)
        
    print("\n📊 Phase 2 실험 특징:")
    print("  - 성공한 파라미터 범위 집중 탐색")
    print("  - 적응형 임계값 비활성화")
    print("  - 현실적 워크로드 조건")
    print("  - 더 긴 실험 시간 (180-220초)")
