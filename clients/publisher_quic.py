#!/usr/bin/env python3
import os, sys, time, json, socket, signal, threading, random
import logging
import paho.mqtt.client as mqtt
import ssl  # ✅ TLS용 추가

# ---------- Env ----------
BROKER = os.getenv("BROKER", "192.168.0.1")
PORT = int(os.getenv("PORT", ""))
TRANSPORT = os.getenv("TRANSPORT", "quic")  # ✅ 'tcp' or 'quic'
TOPIC_DATA = os.getenv("TOPIC_DATA", "bench/foo1")
TOPIC_CTRL = os.getenv("TOPIC_CTRL", "control/room1")
RATE_HZ = int(os.getenv("RATE", "10"))
BATCH_SIZE = int(os.getenv("BATCH", "1"))
QOS = int(os.getenv("QOS", "1"))
PAYLOAD_BYTES = int(os.getenv("PAYLOAD_BYTES", "0"))
USERNAME = os.getenv("USERNAME")
PASSWORD = os.getenv("PASSWORD")

CID_SUFFIX = os.getenv("CID_SUFFIX", socket.gethostname()[:8])
CLIENT_ID = f"pub-room1-{CID_SUFFIX}"

KEEPALIVE = int(os.getenv("KEEPALIVE", "60"))

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
    logging.info(f"[CONNECT] rc={rc} (0=OK) transport={TRANSPORT}")
    if rc == 0:
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
            try:
                client.publish(TOPIC_DATA, json.dumps({"batch": buf}), qos=qos)
                with stats_lock:
                    sent_msgs += len(buf)
                buf.clear()
            except Exception as e:
                logging.error(f"[PUBLISH-ERR] {e}")

        now = time.time()
        if now - last_log >= 1.0:
            with stats_lock:
                sm = sent_msgs
                sent_msgs = 0
            logging.info(f"[STATS] sent/s={sm} rate={rate_hz} batch={batch_size} qos={qos}")
            last_log = now

        time.sleep(period)

# ---------- Graceful shutdown ----------
def handle_sigterm(signum, frame):
    logging.warning("[SIGNAL] SIGTERM received, shutting down...")
    stop_event.set()

signal.signal(signal.SIGTERM, handle_sigterm)
signal.signal(signal.SIGINT, handle_sigterm)

def main():
    # ✅ Transport에 따라 클라이언트 생성
    if TRANSPORT == "quic":
        logging.info("[INIT] Using QUIC transport (MQTTv5)")
        client = mqtt.Client(
            client_id=CLIENT_ID,
            transport="quic",  # ✅ QUIC 사용
            protocol=mqtt.MQTTv5,  # ✅ QUIC는 v5 필요
            clean_session=True
        )
        # ✅ TLS 설정 (QUIC 필수)
        client.tls_set(
            ca_certs=None,
            cert_reqs=ssl.CERT_NONE,
            tls_version=ssl.PROTOCOL_TLSv1_3
        )
        client.tls_insecure_set(True)
    else:
        logging.info("[INIT] Using TCP transport (MQTTv311)")
        client = mqtt.Client(
            client_id=CLIENT_ID,
            protocol=mqtt.MQTTv311,
            clean_session=True
        )

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    if USERNAME:
        client.username_pw_set(USERNAME, PASSWORD or "")

    # 연결
    logging.info(f"[INIT] broker={BROKER}:{PORT} transport={TRANSPORT} "
                 f"topic_data={TOPIC_DATA} ctrl={TOPIC_CTRL} "
                 f"rate={RATE_HZ} batch={BATCH_SIZE} qos={QOS} payload_bytes={PAYLOAD_BYTES}")
    
    try:
        client.connect(BROKER, PORT, KEEPALIVE)
    except Exception as e:
        logging.error(f"[CONNECT-ERR] {e}")
        sys.exit(1)
    
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

