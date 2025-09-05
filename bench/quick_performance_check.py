#!/usr/bin/env python3
"""
빠른 PPO 성능 분석 - 샘플링 기반
"""

import os
import json
import pandas as pd
import numpy as np
from pathlib import Path

def quick_performance_analysis():
    results_path = Path("/home/sslab/mqtt-ebpf-edge/results/generated")
    
    print("빠른 성능 분석 시작...")
    
    # 1. 샘플 실험들 선택 (10개만)
    subs_dir = results_path / "subs"
    sample_experiments = []
    
    for exp_dir in list(subs_dir.iterdir())[:10]:
        if exp_dir.is_dir() and exp_dir.name.startswith("ppo_run_"):
            sample_experiments.append(exp_dir.name)
    
    performances = []
    
    for run_id in sample_experiments:
        print(f"분석 중: {run_id}")
        
        # CSV 파일에서 지연시간 분석
        sub_dir = subs_dir / run_id
        latency_data = []
        
        # 첫 번째 CSV 파일만 샘플링
        csv_files = list(sub_dir.glob("*_lat.csv"))
        if csv_files:
            try:
                df = pd.read_csv(csv_files[0], header=None)
                if len(df.columns) >= 3:
                    # 세 번째 컬럼(지연시간)을 밀리초로 변환
                    latency_values = pd.to_numeric(df.iloc[:, 2], errors='coerce') * 1000
                    latency_data = latency_values.dropna().tolist()
            except Exception as e:
                print(f"  오류: {e}")
                continue
        
        if latency_data:
            perf = {
                'run_id': run_id,
                'avg_latency': np.mean(latency_data),
                'median_latency': np.median(latency_data),
                'min_latency': np.min(latency_data),
                'max_latency': np.max(latency_data),
                'samples': len(latency_data)
            }
            performances.append(perf)
            print(f"  평균 지연시간: {perf['avg_latency']:.1f}ms (샘플: {perf['samples']}개)")
    
    # 2. 성능 순위 매기기
    if performances:
        sorted_perfs = sorted(performances, key=lambda x: x['avg_latency'])
        
        print(f"\n=== 성능 순위 (지연시간 기준) ===")
        for i, perf in enumerate(sorted_perfs):
            print(f"{i+1}. {perf['run_id']}: {perf['avg_latency']:.1f}ms "
                  f"(범위: {perf['min_latency']:.1f}~{perf['max_latency']:.1f}ms)")
        
        # 3. 최고/최악 성능 비교
        best = sorted_perfs[0]
        worst = sorted_perfs[-1]
        improvement = (worst['avg_latency'] - best['avg_latency']) / worst['avg_latency'] * 100
        
        print(f"\n=== 성능 차이 분석 ===")
        print(f"최고 성능: {best['run_id']} - {best['avg_latency']:.1f}ms")
        print(f"최악 성능: {worst['run_id']} - {worst['avg_latency']:.1f}ms") 
        print(f"성능 차이: {improvement:.1f}% 개선 가능")
        
        return best['run_id'], worst['run_id']
    
    return None, None

if __name__ == "__main__":
    best_exp, worst_exp = quick_performance_analysis()
    if best_exp:
        print(f"\n최고 성능 실험: {best_exp}")
        print(f"최악 성능 실험: {worst_exp}")
    else:
        print("분석할 데이터가 없습니다.")
