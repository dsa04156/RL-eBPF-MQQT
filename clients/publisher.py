#!/usr/bin/env python3
import os, sys, time, json, socket, signal, threading, random
import logging
import paho.mqtt.client as mqtt

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
                client.publish(TOPIC_DATA, json.dumps({"batch": buf}), qos=qos)
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

def main():
    client = mqtt.Client(client_id=CLIENT_ID, protocol=mqtt.MQTTv311, clean_session=True)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

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

