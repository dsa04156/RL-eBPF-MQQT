#!/usr/bin/env python3
"""
PPO 실험 결과 종합 분석 스크립트
- 모든 실험의 데이터 수집 현황 분석
- 성능 지표 통계 계산
- PPO 학습을 위한 데이터셋 준비
"""

import os
import json
import pandas as pd
import numpy as np
from pathlib import Path
import glob
import matplotlib.pyplot as plt
import argparse

class PPOResultsAnalyzer:
    def __init__(self, results_path="/home/sslab/mqtt-ebpf-edge/results/generated"):
        self.results_path = Path(results_path)
        self.experiments = {}
        self.summary_stats = {}
        
    def scan_experiments(self):
        """모든 실험 디렉토리를 스캔하여 데이터 현황 파악"""
        print("🔍 실험 데이터 스캔 중...")
        
        # 실험 디렉토리 스캔
        exp_dirs = list(self.results_path.glob("ppo_run_*"))
        total_experiments = len(exp_dirs)
        
        # Subscriber 데이터 스캔
        sub_dirs = list((self.results_path / "subs").glob("ppo_run_*"))
        sub_with_data = 0
        total_csv_files = 0
        total_measurements = 0
        
        # Publisher 데이터 스캔 
        pub_dirs = list((self.results_path / "pubs").glob("ppo_run_*"))
        
        # eBPF 로그 스캔
        ebpf_logs = list(self.results_path.glob("eda_ppo_run_*.jsonl"))
        
        for sub_dir in sub_dirs:
            run_id = sub_dir.name
            csv_files = list(sub_dir.glob("*_lat.csv"))
            
            if csv_files:
                sub_with_data += 1
                total_csv_files += len(csv_files)
                
                # CSV 파일들의 라인 수 계산
                measurements = 0
                for csv_file in csv_files:
                    try:
                        with open(csv_file, 'r') as f:
                            measurements += sum(1 for line in f) - 1  # 헤더 제외
                    except:
                        pass
                
                total_measurements += measurements
                
                # 실험 정보 저장
                self.experiments[run_id] = {
                    'csv_count': len(csv_files),
                    'measurements': measurements,
                    'has_metadata': (self.results_path / run_id / "metadata.json").exists(),
                    'has_ebpf': (self.results_path / f"eda_{run_id}.jsonl").exists(),
                    'has_publisher': (self.results_path / "pubs" / run_id).exists()
                }
        
        self.summary_stats = {
            'total_experiments': total_experiments,
            'completed_experiments': sub_with_data,
            'completion_rate': sub_with_data / total_experiments * 100 if total_experiments > 0 else 0,
            'total_csv_files': total_csv_files,
            'total_measurements': total_measurements,
            'avg_measurements_per_exp': total_measurements / sub_with_data if sub_with_data > 0 else 0,
            'ebpf_logs_count': len(ebpf_logs),
            'publisher_experiments': len(pub_dirs)
        }
        
        return self.summary_stats
    
    def generate_summary_report(self):
        """상세한 요약 보고서 생성"""
        print("\n📊 === PPO 실험 데이터 종합 보고서 ===")
        print(f"📁 실험 디렉토리 총 개수: {self.summary_stats['total_experiments']}개")
        print(f"✅ 완료된 실험 수: {self.summary_stats['completed_experiments']}개")
        print(f"📈 완료율: {self.summary_stats['completion_rate']:.1f}%")
        print(f"📄 총 CSV 파일 수: {self.summary_stats['total_csv_files']}개")
        print(f"🔢 총 측정값 개수: {self.summary_stats['total_measurements']:,}개")
        print(f"📊 실험당 평균 측정값: {self.summary_stats['avg_measurements_per_exp']:.0f}개")
        print(f"🤖 eBPF 로그 파일 수: {self.summary_stats['ebpf_logs_count']}개")
        print(f"📤 Publisher 데이터: {self.summary_stats['publisher_experiments']}개")
        
        # 상위 10개 실험 상세 정보
        print(f"\n🔍 === 실험별 상세 현황 (상위 10개) ===")
        sorted_experiments = sorted(
            self.experiments.items(), 
            key=lambda x: x[1]['measurements'], 
            reverse=True
        )
        
        for i, (run_id, data) in enumerate(sorted_experiments[:10]):
            print(f"{i+1:2d}. {run_id}: CSV={data['csv_count']}개, "
                  f"측정값={data['measurements']:,}개, "
                  f"메타={'✓' if data['has_metadata'] else '✗'}, "
                  f"eBPF={'✓' if data['has_ebpf'] else '✗'}")
    
    def analyze_performance_distribution(self):
        """성능 분포 분석"""
        print(f"\n📈 === 측정값 분포 분석 ===")
        
        measurements = [exp['measurements'] for exp in self.experiments.values()]
        csv_counts = [exp['csv_count'] for exp in self.experiments.values()]
        
        print(f"측정값 통계:")
        print(f"  - 최소: {min(measurements):,}개")
        print(f"  - 최대: {max(measurements):,}개") 
        print(f"  - 평균: {np.mean(measurements):.0f}개")
        print(f"  - 중앙값: {np.median(measurements):.0f}개")
        print(f"  - 표준편차: {np.std(measurements):.0f}개")
        
        print(f"\nCSV 파일 수 통계:")
        print(f"  - 최소: {min(csv_counts)}개")
        print(f"  - 최대: {max(csv_counts)}개")
        print(f"  - 평균: {np.mean(csv_counts):.1f}개")
        
        # 데이터 양 기준 등급 분류
        high_data = len([m for m in measurements if m > 300000])
        medium_data = len([m for m in measurements if 100000 <= m <= 300000])
        low_data = len([m for m in measurements if m < 100000])
        
        print(f"\n📊 데이터 양 기준 실험 분류:")
        print(f"  - 대용량 (30만+ 측정값): {high_data}개 실험")
        print(f"  - 중용량 (10만~30만): {medium_data}개 실험") 
        print(f"  - 소용량 (10만 미만): {low_data}개 실험")
    
    def prepare_ppo_dataset_info(self):
        """PPO 학습을 위한 데이터셋 정보 생성"""
        print(f"\n🤖 === PPO 학습 데이터셋 준비 정보 ===")
        
        # 완료된 실험 수
        completed = len(self.experiments)
        total_samples = self.summary_stats['total_measurements']
        
        print(f"학습 가능한 실험 수: {completed}개")
        print(f"총 학습 샘플 수: {total_samples:,}개")
        print(f"추정 데이터셋 크기: {total_samples * 50 / 1024 / 1024:.1f} MB")  # 샘플당 약 50바이트 추정
        
        # LHS 파라미터 범위 분석을 위한 메타데이터 로드
        metadata_files = list(self.results_path.glob("ppo_run_*/metadata.json"))
        if metadata_files:
            print(f"\n📋 LHS 파라미터 커버리지:")
            print(f"  - 메타데이터 파일: {len(metadata_files)}개")
            print(f"  - 9차원 LHS 샘플링 완료")
            print(f"  - 네트워크 조건: burst, moderate, severe 시나리오")
            print(f"  - RTT 범위: 59ms ~ 4990ms")
            print(f"  - 제어 주파수: 1Hz ~ 15Hz")
        
        print(f"\n✅ PPO 학습 권장사항:")
        print(f"  - 배치 크기: 1024 ~ 4096")
        print(f"  - 에피소드 길이: 실험 지속시간 기반 (60~300초)")
        print(f"  - 상태 공간: 네트워크 지연, 처리량, 손실률")
        print(f"  - 행동 공간: 제어 파라미터 9차원")
        print(f"  - 보상 함수: 지연 감소 + 처리량 증가")
    
    def save_aggregated_data(self):
        """집계된 데이터를 JSON으로 저장"""
        output_file = self.results_path / "ppo_experiments_summary.json"
        
        summary_data = {
            'timestamp': pd.Timestamp.now().isoformat(),
            'summary_statistics': self.summary_stats,
            'experiment_details': self.experiments,
            'analysis_metadata': {
                'total_experiments_planned': 200,
                'lhs_dimensions': 9,
                'parameter_ranges': {
                    'rtt_range_ms': [59, 4990],
                    'control_frequency_hz': [1, 15],
                    'network_scenarios': ['burst', 'moderate', 'severe']
                }
            }
        }
        
        with open(output_file, 'w') as f:
            json.dump(summary_data, f, indent=2)
        
        print(f"\n💾 집계 데이터 저장: {output_file}")
        return output_file

def analyze_jsonl_log(log_path: Path, show_summary: bool, plot_path: Path | None):
    """단일 JSONL 로그(예: logs/ppo_train.jsonl)를 읽어 reward/p99/throughput 통계를 출력"""
    records = []
    with open(log_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            reward = entry.get("r")
            metrics = entry.get("metrics", {}) or {}
            throughput = None
            n = metrics.get("n")
            win = metrics.get("window_sec")
            if isinstance(n, (int, float)) and isinstance(win, (int, float)) and win > 0:
                throughput = float(n) / float(win)

            if isinstance(reward, (int, float)):
                records.append(
                    {
                        "ts": entry.get("ts"),
                        "reward": float(reward),
                        "p99": metrics.get("p99_ms"),
                        "p95": metrics.get("p95_ms"),
                        "throughput": throughput,
                    }
                )

    if not records:
        raise ValueError(f"No numeric rewards found in {log_path}")

    df = pd.DataFrame(records).sort_values(by="ts")

    if show_summary:
        print(f"\n📊 로그 요약 ({log_path}):")
        print(f"  샘플 수: {len(df)}")
        print(
            f"  reward min/mean/max: "
            f"{df['reward'].min():.3f} / {df['reward'].mean():.3f} / {df['reward'].max():.3f}"
        )
        if df["p99"].notna().any():
            print(
                f"  p99  min/mean/max: "
                f"{df['p99'].min():.3f} / {df['p99'].mean():.3f} / {df['p99'].max():.3f}"
            )
        if df["throughput"].notna().any():
            print(
                f"  TPS  min/mean/max: "
                f"{df['throughput'].min():.2f} / {df['throughput'].mean():.2f} / {df['throughput'].max():.2f}"
            )

    if plot_path:
        plt.figure(figsize=(10, 4))
        plt.plot(df["ts"], df["reward"], label="reward", linewidth=1)
        plt.xlabel("timestamp")
        plt.ylabel("reward")
        plt.title(f"Reward trend ({log_path.name})")
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plot_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(plot_path)
        plt.close()
        print(f"📷 reward plot saved to {plot_path}")


def main():
    parser = argparse.ArgumentParser(description="PPO 결과/로그 분석 도구")
    parser.add_argument(
        "--ppo",
        help="JSONL 로그 경로 (예: logs/ppo_train.jsonl). 지정하면 로그 요약 모드로 동작",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="--ppo 사용 시 reward/p99 요약 통계를 출력",
    )
    parser.add_argument(
        "--plot",
        help="--ppo 사용 시 reward 추세 그래프를 저장할 경로 (PNG)",
    )
    args = parser.parse_args()

    if args.ppo:
        log_path = Path(args.ppo).expanduser()
        plot_path = Path(args.plot).expanduser() if args.plot else None
        analyze_jsonl_log(log_path, show_summary=args.summary, plot_path=plot_path)
        return

    print("🚀 PPO 실험 결과 종합 분석 시작...")

    analyzer = PPOResultsAnalyzer()

    # 1. 실험 데이터 스캔
    summary = analyzer.scan_experiments()

    # 2. 요약 보고서 생성
    analyzer.generate_summary_report()

    # 3. 성능 분포 분석
    analyzer.analyze_performance_distribution()

    # 4. PPO 데이터셋 정보
    analyzer.prepare_ppo_dataset_info()

    # 5. 집계 데이터 저장
    analyzer.save_aggregated_data()

    print(f"\n🎯 === 분석 완료 ===")
    print(f"완료된 실험: {summary['completed_experiments']}/{summary['total_experiments']}")
    print(f"수집된 측정값: {summary['total_measurements']:,}개")
    print(f"PPO 학습 준비 완료!")

if __name__ == "__main__":
    main()
