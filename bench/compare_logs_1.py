#!/usr/bin/env python3
import json
import argparse
import numpy as np
import time

def process_log_file(filepath, label, subscriber_file=None):
    """
    하나의 JSONL 로그 파일을 읽어 통계 지표를 계산합니다.
    subscriber_file: Subscriber 로그 파일 경로 (throughput 계산용)
    """
    # 커널 RTT(rtt_ms)
    rtt_values = []
    # 앱 레벨 p99(ms) 스냅샷 (subscriber가 보낸 metrics)
    app_p99_values = []
    app_p95_values = []
    app_p50_values = []
    flows = set()
    timestamps = []
    msg_counts = []
    total_msgs = 0
    throughput_samples = []

    try:
        with open(filepath, 'r') as f:
            for line in f:
                try:
                    data = json.loads(line)
                    # 커널 RTT: per-flow 로그(rtt_ms) 또는 RL 로그(kernel.ewma_rtt_us)
                    v = data.get("rtt_ms")
                    if isinstance(v, (int, float)) and v > 0:
                        rtt_values.append(v)
                    elif isinstance(data.get("kernel"), dict):
                        rtt_u = data["kernel"].get("ewma_rtt_us")
                        if isinstance(rtt_u, (int, float)) and rtt_u > 0:
                            rtt_values.append(rtt_u / 1000.0)

                    # 앱 레벨 메트릭 스냅샷 (subscriber/source 또는 RL metrics)
                    metrics = data.get("metrics") if data.get("source") == "subscriber_metrics" else None
                    if metrics is None and isinstance(data.get("metrics"), dict) and data.get("mode") == "online":
                        metrics = data.get("metrics")

                    if isinstance(metrics, dict):
                        p50 = metrics.get("p50_ms")
                        p95 = metrics.get("p95_ms")
                        p99 = metrics.get("p99_ms")
                        if isinstance(p50, (int, float)):
                            app_p50_values.append(p50)
                        if isinstance(p95, (int, float)):
                            app_p95_values.append(p95)
                        if isinstance(p99, (int, float)):
                            app_p99_values.append(p99)

                        n = metrics.get("n")
                        w = metrics.get("window_sec")
                        if isinstance(n, (int, float)) and isinstance(w, (int, float)) and w > 0:
                            throughput_samples.append(n / w)
                    # 타임스탬프 수집
                    if "ts" in data:
                        timestamps.append(data["ts"])
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

    # 커널 RTT 통계
    rtt_array = np.array(rtt_values, dtype=float) if rtt_values else np.array([])
    if rtt_array.size:
        k_p50, k_p90, k_p95, k_p99 = np.percentile(rtt_array, [50, 90, 95, 99])
        k_mean, k_std = float(np.mean(rtt_array)), float(np.std(rtt_array))
        k_min, k_max = float(np.min(rtt_array)), float(np.max(rtt_array))
    else:
        k_p50 = k_p90 = k_p95 = k_p99 = k_mean = k_std = k_min = k_max = float("nan")
    
    # Throughput 계산 (msg/s) - 라인 수 기반 근사 (Subscriber 로그 없으면)
    if throughput_samples:
        throughput_msg_s = float(np.mean(throughput_samples))
    elif timestamps:
        start_time = min(timestamps)
        end_time = max(timestamps)
        duration = end_time - start_time
        line_count = len(rtt_values)  # 유효한 RTT 라인 수로 근사
        throughput_msg_s = line_count / duration if duration > 0 else 0
        # 디버그 출력은 과하다 싶으면 주석 처리 가능
        # print(f"Debug: timestamps={len(timestamps)}, line_count={line_count}, duration={duration}")
    else:
        throughput_msg_s = 0  # 데이터 없음
        # print(f"Debug: No timestamps found.")

    # 앱 레벨 p99 스냅샷 통계(있으면)
    app_stats = {}
    if app_p50_values or app_p95_values or app_p99_values:
        # 각 스냅샷 시리즈에 대해 중앙값/평균/95th 등을 계산
        def s_median(a):
            return float(np.median(a)) if a else float('nan')
        def s_mean(a):
            return float(np.mean(a)) if a else float('nan')
        def s_p95(a):
            return float(np.percentile(a,95)) if a else float('nan')
        def s_p99(a):
            return float(np.percentile(a,99)) if a else float('nan')
        app_stats = {
            # p50 스냅샷 통계
            "app_p50_ms_median": s_median(app_p50_values),
            "app_p50_ms_mean":   s_mean(app_p50_values),
            "app_p50_ms_95th":   s_p95(app_p50_values),
            # p95 스냅샷 통계
            "app_p95_ms_median": s_median(app_p95_values),
            "app_p95_ms_mean":   s_mean(app_p95_values),
            "app_p95_ms_95th":   s_p95(app_p95_values),
            # p99 스냅샷 통계
            "app_p99_ms_median": s_median(app_p99_values),
            "app_p99_ms_mean":   s_mean(app_p99_values),
            "app_p99_ms_95th":   s_p95(app_p99_values),
            "app_p99_ms_99th":   s_p99(app_p99_values),
            "app_samples": int(len(app_p99_values) or 0),
        }

    # 모든 통계 지표를 딕셔너리로 반환
    stats = {
        "label": label,
        "kernel_samples": int(rtt_array.size),
        "kernel_p50_ms": k_p50,
        "kernel_p90_ms": k_p90,
        "kernel_p95_ms": k_p95,
        "kernel_p99_ms": k_p99,
        "kernel_mean_ms": k_mean,
        "kernel_std_ms": k_std,
        "kernel_min_ms": k_min,
        "kernel_max_ms": k_max,
        "throughput_msg_s": throughput_msg_s,
    }
    stats.update(app_stats)
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

    # 출력: 의존성 없는 간단 표
    def fmt(x):
        if isinstance(x, (int,)):
            return str(x)
        try:
            return f"{float(x):.2f}"
        except Exception:
            return "-"

    headers = [
        "label",
        # 커널 RTT
        "kernel_p50_ms","kernel_p90_ms","kernel_p95_ms","kernel_p99_ms",
        "kernel_mean_ms","kernel_std_ms","kernel_min_ms","kernel_max_ms",
        "throughput_msg_s",
        # 앱 레벨 pxx 스냅샷 통계
        "app_p50_ms_median","app_p50_ms_mean","app_p50_ms_95th",
        "app_p95_ms_median","app_p95_ms_mean","app_p95_ms_95th",
        "app_p99_ms_median","app_p99_ms_mean","app_p99_ms_95th","app_p99_ms_99th",
        "app_samples",
    ]

    print("\n### RTT 통계 비교 결과 ###")
    print("\t".join(headers))
    for s in all_stats:
        row = [
            s.get("label","-"),
            fmt(s.get("kernel_p50_ms","nan")),
            fmt(s.get("kernel_p90_ms","nan")),
            fmt(s.get("kernel_p95_ms","nan")),
            fmt(s.get("kernel_p99_ms","nan")),
            fmt(s.get("kernel_mean_ms","nan")),
            fmt(s.get("kernel_std_ms","nan")),
            fmt(s.get("kernel_min_ms","nan")),
            fmt(s.get("kernel_max_ms","nan")),
            fmt(s.get("throughput_msg_s","nan")),
            fmt(s.get("app_p50_ms_median","nan")),
            fmt(s.get("app_p50_ms_mean","nan")),
            fmt(s.get("app_p50_ms_95th","nan")),
            fmt(s.get("app_p95_ms_median","nan")),
            fmt(s.get("app_p95_ms_mean","nan")),
            fmt(s.get("app_p95_ms_95th","nan")),
            fmt(s.get("app_p99_ms_median","nan")),
            fmt(s.get("app_p99_ms_mean","nan")),
            fmt(s.get("app_p99_ms_95th","nan")),
            fmt(s.get("app_p99_ms_99th","nan")),
            str(s.get("app_samples","-")),
        ]
        print("\t".join(row))

if __name__ == "__main__":
    main()
