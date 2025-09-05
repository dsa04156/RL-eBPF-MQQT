#!/usr/bin/env python3
"""
PPO 실험 결과 성능 분석 스크립트
- 각 실험의 지연시간, 처리량 분석
- 최적 파라미터 조합 식별
- 성능 순위 매기기
"""

import os
import json
import pandas as pd
import numpy as np
from pathlib import Path
import glob
import matplotlib.pyplot as plt

class PPOPerformanceAnalyzer:
    def __init__(self, results_path="/home/sslab/mqtt-ebpf-edge/results/generated"):
        self.results_path = Path(results_path)
        self.performance_data = []
        
    def analyze_experiment_performance(self, run_id):
        """개별 실험의 성능 분석"""
        
        # 1. Subscriber CSV 데이터 분석 (지연시간)
        sub_dir = self.results_path / "subs" / run_id
        latency_data = []
        
        if sub_dir.exists():
            csv_files = list(sub_dir.glob("*_lat.csv"))
            for csv_file in csv_files:
                try:
                    df = pd.read_csv(csv_file, header=None)
                    if len(df.columns) >= 3:
                        # 세 번째 컬럼이 지연시간(초)인 경우 밀리초로 변환
                        latency_values = pd.to_numeric(df.iloc[:, 2], errors='coerce') * 1000
                        latency_data.extend(latency_values.dropna().tolist())
                except Exception as e:
                    print(f"CSV 파일 읽기 오류 {csv_file}: {e}")
        
        # 2. eBPF 로그 분석 (제어 행동)
        ebpf_file = self.results_path / f"eda_{run_id}.jsonl"
        control_actions = 0
        throughput_data = []
        
        if ebpf_file.exists():
            try:
                with open(ebpf_file, 'r') as f:
                    for line in f:
                        data = json.loads(line.strip())
                        if 'action' in data:
                            control_actions += 1
                        if 'throughput' in data:
                            throughput_data.append(data['throughput'])
            except Exception as e:
                print(f"eBPF 로그 읽기 오류 {ebpf_file}: {e}")
        
        # 3. 메타데이터에서 실험 설정 가져오기
        metadata_file = self.results_path / run_id / "metadata.json"
        experiment_config = {}
        
        if metadata_file.exists():
            try:
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)
                    experiment_config = metadata.get('eda_config', {})
            except Exception as e:
                print(f"메타데이터 읽기 오류 {metadata_file}: {e}")
        
        # 4. 성능 지표 계산
        performance = {
            'run_id': run_id,
            'avg_latency': np.mean(latency_data) if latency_data else float('inf'),
            'median_latency': np.median(latency_data) if latency_data else float('inf'),
            'p95_latency': np.percentile(latency_data, 95) if latency_data else float('inf'),
            'latency_std': np.std(latency_data) if latency_data else float('inf'),
            'total_samples': len(latency_data),
            'avg_throughput': np.mean(throughput_data) if throughput_data else 0,
            'control_actions': control_actions,
            'config': experiment_config
        }
        
        # 5. 성능 점수 계산 (낮은 지연시간이 좋음)
        if latency_data:
            performance['performance_score'] = 1000 / performance['avg_latency']  # 점수가 높을수록 좋음
        else:
            performance['performance_score'] = 0
            
        return performance
    
    def analyze_all_experiments(self):
        """모든 실험의 성능 분석"""
        print("모든 실험 성능 분석 중...")
        
        # 완료된 실험 목록 가져오기
        completed_experiments = []
        subs_dir = self.results_path / "subs"
        
        if subs_dir.exists():
            for exp_dir in subs_dir.iterdir():
                if exp_dir.is_dir() and exp_dir.name.startswith("ppo_run_"):
                    completed_experiments.append(exp_dir.name)
        
        # 각 실험 분석
        for run_id in completed_experiments:
            perf = self.analyze_experiment_performance(run_id)
            if perf['total_samples'] > 1000:  # 충분한 데이터가 있는 경우만
                self.performance_data.append(perf)
                
        return len(self.performance_data)
    
    def find_best_performance_regions(self):
        """최고 성능 구간 찾기"""
        if not self.performance_data:
            print("분석할 데이터가 없습니다.")
            return
            
        # 성능 순으로 정렬
        sorted_experiments = sorted(
            self.performance_data,
            key=lambda x: x['performance_score'],
            reverse=True
        )
        
        print(f"\n=== 최고 성능 실험 TOP 10 ===")
        for i, exp in enumerate(sorted_experiments[:10]):
            print(f"{i+1:2d}. {exp['run_id']}: "
                  f"평균지연 {exp['avg_latency']:.1f}ms, "
                  f"P95지연 {exp['p95_latency']:.1f}ms, "
                  f"샘플수 {exp['total_samples']:,}개, "
                  f"점수 {exp['performance_score']:.1f}")
        
        # 최적 파라미터 분석
        top_experiments = sorted_experiments[:10]
        self.analyze_optimal_parameters(top_experiments)
        
        return sorted_experiments[:10]
    
    def analyze_optimal_parameters(self, top_experiments):
        """최적 파라미터 조합 분석"""
        print(f"\n=== 최적 파라미터 분석 ===")
        
        # 파라미터별 평균값 계산
        param_values = {}
        param_names = [
            'HI_RTT_US', 'LO_RTT_US', 'CTRL_RATE', 'CTRL_BATCH',
            'T_HOLD_ON', 'T_HOLD_OFF', 'EWMA_ALPHA', 'USE_ADAPTIVE'
        ]
        
        for param in param_names:
            values = []
            for exp in top_experiments:
                if param in exp['config']:
                    values.append(exp['config'][param])
            
            if values:
                param_values[param] = {
                    'mean': np.mean(values),
                    'std': np.std(values),
                    'min': np.min(values),
                    'max': np.max(values)
                }
        
        # 최적 파라미터 범위 출력
        print("최고 성능 실험들의 파라미터 특성:")
        for param, stats in param_values.items():
            if param == 'HI_RTT_US' or param == 'LO_RTT_US':
                print(f"  {param}: {stats['mean']/1000:.1f}±{stats['std']/1000:.1f}ms "
                      f"(범위: {stats['min']/1000:.1f}-{stats['max']/1000:.1f}ms)")
            elif param == 'CTRL_RATE':
                print(f"  {param}: {stats['mean']:.1f}±{stats['std']:.1f}Hz "
                      f"(범위: {stats['min']:.0f}-{stats['max']:.0f}Hz)")
            elif param == 'USE_ADAPTIVE':
                adaptive_ratio = stats['mean']
                print(f"  {param}: {adaptive_ratio:.1f} (적응형 모드 사용 비율)")
            else:
                print(f"  {param}: {stats['mean']:.3f}±{stats['std']:.3f} "
                      f"(범위: {stats['min']:.3f}-{stats['max']:.3f})")
    
    def find_worst_performance_regions(self):
        """최악 성능 구간 찾기"""
        if not self.performance_data:
            return
            
        # 성능 순으로 정렬 (낮은 것부터)
        sorted_experiments = sorted(
            self.performance_data,
            key=lambda x: x['performance_score']
        )
        
        print(f"\n=== 최악 성능 실험 TOP 10 ===")
        for i, exp in enumerate(sorted_experiments[:10]):
            print(f"{i+1:2d}. {exp['run_id']}: "
                  f"평균지연 {exp['avg_latency']:.1f}ms, "
                  f"P95지연 {exp['p95_latency']:.1f}ms, "
                  f"샘플수 {exp['total_samples']:,}개, "
                  f"점수 {exp['performance_score']:.1f}")
    
    def generate_performance_insights(self):
        """성능 인사이트 생성"""
        if not self.performance_data:
            return
            
        latencies = [exp['avg_latency'] for exp in self.performance_data if exp['avg_latency'] != float('inf')]
        scores = [exp['performance_score'] for exp in self.performance_data]
        
        print(f"\n=== 전체 성능 통계 ===")
        print(f"분석된 실험 수: {len(self.performance_data)}개")
        print(f"평균 지연시간: {np.mean(latencies):.1f}ms")
        print(f"최소 지연시간: {np.min(latencies):.1f}ms")
        print(f"최대 지연시간: {np.max(latencies):.1f}ms")
        print(f"지연시간 표준편차: {np.std(latencies):.1f}ms")
        
        # 성능 분포 분석
        high_perf = len([s for s in scores if s > np.percentile(scores, 80)])
        medium_perf = len([s for s in scores if np.percentile(scores, 20) <= s <= np.percentile(scores, 80)])
        low_perf = len([s for s in scores if s < np.percentile(scores, 20)])
        
        print(f"\n성능 분포:")
        print(f"  고성능 (상위 20%): {high_perf}개 실험")
        print(f"  중성능 (중간 60%): {medium_perf}개 실험")
        print(f"  저성능 (하위 20%): {low_perf}개 실험")
    
    def save_performance_report(self):
        """성능 분석 결과 저장"""
        # 상세 성능 데이터를 JSON으로 저장
        output_file = self.results_path / "performance_analysis.json"
        
        report_data = {
            'analysis_timestamp': pd.Timestamp.now().isoformat(),
            'total_experiments': len(self.performance_data),
            'performance_data': self.performance_data,
            'summary_stats': {
                'avg_latency_overall': np.mean([exp['avg_latency'] for exp in self.performance_data if exp['avg_latency'] != float('inf')]),
                'best_performance_score': max([exp['performance_score'] for exp in self.performance_data]),
                'worst_performance_score': min([exp['performance_score'] for exp in self.performance_data])
            }
        }
        
        with open(output_file, 'w') as f:
            json.dump(report_data, f, indent=2)
        
        print(f"\n성능 분석 결과 저장: {output_file}")
        return output_file

def main():
    print("PPO 실험 성능 분석 시작...")
    
    analyzer = PPOPerformanceAnalyzer()
    
    # 1. 모든 실험 분석
    analyzed_count = analyzer.analyze_all_experiments()
    print(f"총 {analyzed_count}개 실험 분석 완료")
    
    if analyzed_count == 0:
        print("분석할 실험 데이터가 없습니다.")
        return
    
    # 2. 최고 성능 구간 찾기
    best_experiments = analyzer.find_best_performance_regions()
    
    # 3. 최악 성능 구간 분석
    analyzer.find_worst_performance_regions()
    
    # 4. 전체 성능 인사이트
    analyzer.generate_performance_insights()
    
    # 5. 결과 저장
    analyzer.save_performance_report()
    
    print(f"\n=== 분석 완료 ===")
    print(f"최고 성능: {best_experiments[0]['run_id']} (평균 지연시간: {best_experiments[0]['avg_latency']:.1f}ms)")
    print(f"성능 향상 포인트를 확인하려면 performance_analysis.json 파일을 참조하세요.")

if __name__ == "__main__":
    main()
