#!/usr/bin/env python3
import os, sys, time, json, socket, signal, threading, random
import logging
import paho.mqtt.client as mqtt
import threading

HEDGE_DELAY_MS = int(os.getenv("HEDGE_DELAY_MS", "0"))  # 0이면 헤징 비활성
mid_payload = {}                     # mid -> payload_str 저장(ACK 안 오면 재발행 판단)
mid_lock = threading.Lock()          # 콜백/타이머 동시 접근 보호
# ---------- Env ----------
BROKER = os.getenv("BROKER", "192.168.0.1")
PORT = int(os.getenv("PORT", "23232"))
TOPIC_DATA = os.getenv("TOPIC_DATA", "bench/foo1")
TOPIC_CTRL = os.getenv("TOPIC_CTRL", "control/room1")
RATE_HZ = int(os.getenv("RATE", "10"))            # 초당 메시지 생성 수
BATCH_SIZE = int(os.getenv("BATCH", "1"))         # 배치 크기(메시지 n개 모아 한 번에 publish)
QOS = int(os.getenv("QOS", "1"))                  # 0/1/2
PAYLOAD_BYTES = int(os.getenv("PAYLOAD_BYTES", "0"))  # 페이로드 padding 바이트 수
USERNAME = os.getenv("USERNAME")                  # 필요 시 사용
PASSWORD = os.getenv("PASSWORD")

CID_SUFFIX = os.getenv("CID_SUFFIX", socket.gethostname()[:8])
CLIENT_ID = f"pub-room1-{CID_SUFFIX}"

KEEPALIVE = int(os.getenv("KEEPALIVE", "60"))     # MQTT keepalive

# ---------- Logging ----------
logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

# ---------- Globals ----------
stop_event = threading.Event()
stats_lock = threading.Lock()
sent_msgs = 0

rate_hz = RATE_HZ
batch_size = BATCH_SIZE
qos = QOS

buf = []

# 기존 콜백들 아래에 추가
def on_publish(client, userdata, mid):
    # QoS1 PUBACK 수신시 호출
    with mid_lock:
        mid_payload.pop(mid, None)

# ---------- MQTT Callbacks ----------
def on_connect(client, userdata, flags, rc, properties=None):
    logging.info(f"[CONNECT] rc={rc} (0=OK)")
    if rc == 0:
        # 제어 토픽 구독
        client.subscribe(TOPIC_CTRL, qos=1)

def on_disconnect(client, userdata, rc, properties=None):
    logging.warning(f"[DISCONNECT] rc={rc}")

def on_message(client, userdata, msg):
    global rate_hz, batch_size, qos
    try:
        cmd = json.loads(msg.payload.decode())
        if cmd.get("cmd") == "throttle":
            rate_hz = max(1, int(cmd["rate"]))
        if cmd.get("cmd") == "batch":
            batch_size = max(1, int(cmd["size"]))
        if cmd.get("cmd") == "qos":
            qos = int(cmd["level"])
        logging.info(f"[CTRL] {cmd} -> rate={rate_hz} batch={batch_size} qos={qos}")
    except Exception as e:
        logging.error(f"[CTRL-ERR] {e}")

# ---------- Publisher worker ----------
def publisher_loop(client: mqtt.Client):
    global sent_msgs
    pad = "x" * max(0, PAYLOAD_BYTES)
    last_log = time.time()
    period = 1.0 / max(1, rate_hz)

    while not stop_event.is_set():
        # 동적으로 갱신된 rate 반영
        period = 1.0 / max(1, rate_hz)

        payload = {
            "ts": int(time.time_ns()),
            "value": 23.5,
            "publisher": CLIENT_ID,
            "seq": random.getrandbits(32),
        }
        if PAYLOAD_BYTES > 0:
            payload["pad"] = pad

        buf.append(payload)
        if len(buf) >= batch_size:
            # publish
            try:
                payload_str = json.dumps({"batch": buf})
                publish_with_hedge(client,payload_str, TOPIC_DATA, qos_now=qos)
                with stats_lock:
                    sent_msgs += len(buf)
                buf.clear()
            except Exception as e:
                logging.error(f"[PUBLISH-ERR] {e}")

        # 1초마다 통계 로그
        now = time.time()
        if now - last_log >= 1.0:
            with stats_lock:
                sm = sent_msgs
                sent_msgs = 0
            logging.info(f"[STATS] sent/s={sm} rate={rate_hz} batch={batch_size} qos={qos}")
            last_log = now

        # 주기 대기
        time.sleep(period)

# ---------- Graceful shutdown ----------
def handle_sigterm(signum, frame):
    logging.warning("[SIGNAL] SIGTERM received, shutting down...")
    stop_event.set()

signal.signal(signal.SIGTERM, handle_sigterm)
signal.signal(signal.SIGINT, handle_sigterm)

def publish_with_hedge(client: mqtt.Client, payload_str: str, topic: str, qos_now: int):
    # QoS1이 아니거나 헤징 꺼짐이면 그냥 발행
    if qos_now != 1 or HEDGE_DELAY_MS <= 0:
        client.publish(topic, payload_str, qos=qos_now)
        return
    # 1) 원본 발행
    info = client.publish(topic, payload_str, qos=qos_now)
    mid = getattr(info, "mid", None)
    if mid is None:
        return

    # 2) mid -> payload 매핑 저장
    with mid_lock:
        mid_payload[mid] = payload_str

    # 3) 딜레이 후 ACK 없으면 동일 payload 1회 재발행
    def _timer(mid_local=mid, payload_local=payload_str, topic_local=topic, qos_local=qos_now):
        time.sleep(HEDGE_DELAY_MS / 1000.0)
        with mid_lock:
            still_pending = mid_local in mid_payload
        if still_pending:
            client.publish(topic_local, payload_local, qos=qos_local)
            logging.info(f"[HEDGE] re-publish mid={mid_local} after {HEDGE_DELAY_MS}ms")
            with mid_lock:
                mid_payload.pop(mid_local, None)  # 1회만 헤지

    threading.Thread(target=_timer, daemon=True).start()

def main():
    client = mqtt.Client(client_id=CLIENT_ID, protocol=mqtt.MQTTv311, clean_session=True)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.on_publish = on_publish
    if USERNAME:
        client.username_pw_set(USERNAME, PASSWORD or "")

    # 연결
    logging.info(f"[INIT] broker={BROKER}:{PORT} topic_data={TOPIC_DATA} ctrl={TOPIC_CTRL} "
                 f"rate={RATE_HZ} batch={BATCH_SIZE} qos={QOS} payload_bytes={PAYLOAD_BYTES}")
    client.connect(BROKER, PORT, KEEPALIVE)
    client.loop_start()

    pub_th = threading.Thread(target=publisher_loop, args=(client,), daemon=True)
    pub_th.start()

    try:
        while not stop_event.is_set():
            time.sleep(0.5)
    finally:
        client.loop_stop()
        client.disconnect()
        logging.info("[EXIT] bye.")

if __name__ == "__main__":
    main()
