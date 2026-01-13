#!/usr/bin/env python3
import time, json, os, math
from collections import deque
from paho.mqtt import client as mqtt
import uuid

BROKER = os.getenv("MQTT_HOST","192.168.0.1")
PORT   = int(os.getenv("MQTT_PORT","23232"))
SUB_TOPIC   = os.getenv("SUB_TOPIC","bench/foo1")
OUT_TOPIC   = os.getenv("OUT_TOPIC","eda/latency")
REPORT_EVERY= float(os.getenv("REPORT_EVERY","1.0"))  # 보고 주기(초)
WINDOW_SEC  = float(os.getenv("WINDOW_SEC","1.0"))   # 이동창 크기(초)
CLIENT_ID   = os.getenv("CLIENT_ID", f"sub-telemetry-{uuid.uuid4().hex[:8]}")

win = deque()  # (ts_sec, lat_ms)
last_report = 0.0
total_msgs=0
msgs_since_last_report = 0  # [추가] 이번 주기 처리량 카운터

def now_ns(): return time.time_ns()

def parse_send_ns(payload: bytes) -> int:
    s = payload.decode('utf-8','ignore').strip()
    if s.isdigit():           # payload가 "1725512345678901234" 같은 ns-epoch
        return int(s)
    try:                      # {"ts_ns": 17255...} 형태도 허용
        o = json.loads(s)
        if isinstance(o, dict):
            if "ts_ns" in o:
                return int(o["ts_ns"])
            elif "ts" in o:  # "ts" 키도 지원 추가
                return int(o["ts"])
            elif "batch" in o and isinstance(o["batch"], list) and o["batch"]:  # 배치 처리 추가
                first_item = o["batch"][0]
                if "ts_ns" in first_item:
                    return int(first_item["ts_ns"])
                elif "ts" in first_item:  # 배치 내 "ts" 지원
                    return int(first_item["ts"])
    except Exception:
        pass
    return 0  # 못 읽으면 무시

def on_message(cli, _, msg):
    global total_msgs, msgs_since_last_report
    try:
        payload_str = msg.payload.decode('utf-8', 'ignore').strip()
        o = json.loads(payload_str)
        
        # 배치를 풀어서 타임스탬프 리스트 확보
        ts_list = []
        if isinstance(o, dict) and "batch" in o and isinstance(o["batch"], list):
            for item in o["batch"]:
                if "ts" in item: ts_list.append(int(item["ts"]))
                elif "ts_ns" in item: ts_list.append(int(item["ts_ns"]))
        elif isinstance(o, dict):
             if "ts" in o: ts_list.append(int(o["ts"]))
             elif "ts_ns" in o: ts_list.append(int(o["ts_ns"]))
        # 각각 계산
        now = now_ns()
        for send_ns in ts_list:
            if send_ns <= 0: continue
            # ns -> ms 변환 (수신 - 발신)
            # 주의: publisher가 time.time_ns()를 썼다면 단위 일치. 
            # 만약 초 단위(float)라면 1e9 곱해야 함. (Publisher 코드엔 ns로 보임)
            lat_ms = (now - send_ns) / 1e6
            if lat_ms < 0: lat_ms = 0 # 시간 동기화 오차 보정
            
            t = time.time()
            win.append((t, lat_ms))
            total_msgs += 1
            msgs_since_last_report += 1
        
    except Exception:
        pass

    # 윈도우 정리
    t = time.time()
    cutoff = t - WINDOW_SEC
    while win and win[0][0] < cutoff:
        win.popleft()

def maybe_report(cli):
    global last_report, msgs_since_last_report
    t = time.time()
    delta = t - last_report

    if delta < REPORT_EVERY:
        return
    if not win or msgs_since_last_report == 0:
        last_report = t
        msgs_since_last_report = 0
        return

    last_report = t
    real_n = msgs_since_last_report
    arr = [x[1] for x in win]
    arr.sort()
    def qp(p):
        if not arr: return math.nan
        idx = max(0, min(len(arr)-1, int(round((p/100.0)*(len(arr)-1)))))
        return arr[idx]
    out = {
        "ts": t, 
        "client_id": CLIENT_ID,
        "n": real_n,
        "p50_ms": qp(50), "p95_ms": qp(95), "p99_ms": qp(99),
        "mean_ms": sum(arr)/len(arr), "window_sec": delta,
        "total_msgs": total_msgs
    }
    thr = real_n / delta if delta > 0 else 0.0
    print(f"[SUB] n={real_n}, window_sec={delta:.3f}, thr={thr:.1f} msg/s")

    cli.publish(OUT_TOPIC, json.dumps(out), qos=0)
    last_report = t
    msgs_since_last_report = 0  # 카운터 초기화

def on_connect(cli, userdata, flags, rc):
    cli.subscribe(SUB_TOPIC, qos=0)

def main():
    cli = mqtt.Client(client_id=CLIENT_ID)
    cli.on_connect = on_connect
    cli.on_message = on_message
    cli.connect(BROKER, PORT, 60)
    cli.loop_start()
    try:
        while True:
            maybe_report(cli)
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()

