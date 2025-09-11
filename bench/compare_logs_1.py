#!/usr/binbin/env python3
import json
import argparse
import numpy as np
import pandas as pd
import time  # 타임스탬프 처리용 추가

def process_log_file(filepath, label, subscriber_file=None):
    """
    하나의 JSONL 로그 파일을 읽어 통계 지표를 계산합니다.
    subscriber_file: Subscriber 로그 파일 경로 (throughput 계산용)
    """
    rtt_values = []
    flows = set()
    timestamps = []
    msg_counts = []
    total_msgs = 0

    try:
        with open(filepath, 'r') as f:
            for line in f:
                try:
                    data = json.loads(line)
                    # 유효한 RTT 값만 집계에 포함 (0은 보통 데이터 없음 의미)
                    if "rtt_ms" in data and data["rtt_ms"] > 0:
                        rtt_values.append(data["rtt_ms"])
                    if "ts" in data:  # timestamp 대신 ts 사용
                        timestamps.append(data["ts"])
                    # ...existing code...
                except json.JSONDecodeError:
                    pass
    except FileNotFoundError:
        print(f"오류: 파일을 찾을 수 없습니다 - {filepath}")
        return None

    # Subscriber 로그에서 msg_count 읽기 (throughput 계산용)
    if subscriber_file:
        try:
            with open(subscriber_file, 'r') as f:
                for line in f:
                    try:
                        data = json.loads(line)
                        if "msg_count" in data:
                            msg_counts.append(data["msg_count"])
                            total_msgs += data["msg_count"]
                        if "ts" in data:
                            timestamps.append(data["ts"])  # 타임스탬프도 추가
                    except json.JSONDecodeError:
                        pass
        except FileNotFoundError:
            print(f"경고: Subscriber 파일을 찾을 수 없습니다 - {subscriber_file}")

    # ...existing code...

    if not rtt_values:
        print(f"경고: {filepath} 파일에 유효한 RTT 데이터가 없습니다.")
        return {
            "label": label,
            "hosts": len(flows),
            "n": 0,
        }

    # Numpy 배열로 변환하여 통계 계산
    rtt_array = np.array(rtt_values)
    
    p50, p90, p95, p99 = np.percentile(rtt_array, [50, 90, 95, 99])
    
    # Throughput 계산 (msg/s) - 라인 수 기반 근사 (Subscriber 로그 없으면)
    if timestamps:
        start_time = min(timestamps)
        end_time = max(timestamps)
        duration = end_time - start_time
        line_count = len(rtt_values)  # 유효한 RTT 라인 수로 근사
        throughput_msg_s = line_count / duration if duration > 0 else 0
        print(f"Debug: timestamps={len(timestamps)}, line_count={line_count}, duration={duration}")  # 디버그 추가
    else:
        throughput_msg_s = 0  # 데이터 없음
        print(f"Debug: No timestamps found.")  # 디버그 추가

    # 요청하신 모든 통계 지표를 딕셔너리로 반환
    stats = {
        "label": label,
        "hosts": len(flows),
        "n": len(rtt_array),
        "p50_ms": p50,
        "p90_ms": p90,
        "p95_ms": p95,
        "p99_ms": p99,
        "mean_ms": np.mean(rtt_array),
        "std_ms": np.std(rtt_array),
        "min_ms": np.min(rtt_array),
        "max_ms": np.max(rtt_array),
        "throughput_msg_s": throughput_msg_s,  # 추가
    }
    
    return stats

def main():
    parser = argparse.ArgumentParser(
        description="여러 개의 eMQTT-AC 로그 파일을 비교하여 RTT 통계를 출력합니다."
    )
    parser.add_argument("files", nargs='+', help="비교할 로그 파일 경로들 (예: baseline.jsonl controlled.jsonl ...)")
    parser.add_argument("--subscriber", help="Subscriber 로그 파일 경로 (throughput 계산용)", default=None)
    
    args = parser.parse_args()

    if len(args.files) < 2:
        print("오류: 최소 2개의 파일을 지정하세요.")
        return

    # 각 로그 파일 처리
    all_stats = []
    for filepath in args.files:
        label = filepath.split('/')[-1].replace('.jsonl', '')  # 파일명으로 레이블 생성
        stats = process_log_file(filepath, label, args.subscriber)
        if stats:
            all_stats.append(stats)

    if not all_stats:
        print("오류: 유효한 데이터가 없습니다.")
        return

    # Pandas DataFrame으로 결과 보기 좋게 출력
    df = pd.DataFrame(all_stats)
    
    # 소수점 둘째 자리까지 표시하도록 포맷 설정
    pd.options.display.float_format = '{:,.2f}'.format
    
    print("\n### RTT 통계 비교 결과 ###")
    print(df.to_string(index=False))

if __name__ == "__main__":
    main()