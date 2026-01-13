#!/usr/bin/env python3
import os, sys, time, json, socket, signal, logging
import paho.mqtt.client as mqtt

# ---------- Env ----------
BROKER = os.getenv("BROKER", "192.168.0.1")
PORT = int(os.getenv("PORT", "23232"))
TOPIC_DATA = os.getenv("TOPIC_DATA", "sensor/room1/temp")
KEEPALIVE = int(os.getenv("KEEPALIVE", "60"))

CID_SUFFIX = os.getenv("CID_SUFFIX", socket.gethostname()[:8])
CLIENT_ID = f"sub-logger-{CID_SUFFIX}"

OUT_DIR = os.getenv("OUT_DIR", "/logs")
os.makedirs(OUT_DIR, exist_ok=True)
RAW_FILE = os.path.join(OUT_DIR, f"{CID_SUFFIX}_raw.log")
LAT_FILE = os.path.join(OUT_DIR, f"{CID_SUFFIX}_lat.csv")

# ---------- Logging ----------
logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

# ---------- MQTT Callbacks ----------
def on_connect(client, userdata, flags, rc, properties=None):
    logging.info(f"[CONNECT] rc={rc}")
    if rc == 0:
        client.subscribe(TOPIC_DATA, qos=1)

def on_disconnect(client, userdata, rc, properties=None):
    logging.warning(f"[DISCONNECT] rc={rc}")

def on_message(client, userdata, msg):
    now = time.time()
    try:
        data = json.loads(msg.payload.decode())
        items = data["batch"] if "batch" in data else [data]
        with open(RAW_FILE, "a") as f_raw, open(LAT_FILE, "a") as f_lat:
            for it in items:
                if "ts" in it:
                    latency = now - it["ts"]
                    line = f"{now:.3f},latency_s,{latency:.6f}\n"
                    f_raw.write(json.dumps(it) + "\n")
                    f_lat.write(line)
    except Exception as e:
        logging.error(f"[PARSE-ERR] {e}")

# ---------- Graceful shutdown ----------
stop = False
def handle_sigterm(signum, frame):
    global stop
    logging.warning("[SIGNAL] terminating...")
    stop = True

signal.signal(signal.SIGTERM, handle_sigterm)
signal.signal(signal.SIGINT, handle_sigterm)

# ---------- Main ----------
def main():
    client = mqtt.Client(client_id=CLIENT_ID, protocol=mqtt.MQTTv311)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    logging.info(f"[INIT] broker={BROKER}:{PORT} topic={TOPIC_DATA}")
    client.connect(BROKER, PORT, KEEPALIVE)
    client.loop_start()

    try:
        while not stop:
            time.sleep(0.5)
    finally:
        client.loop_stop()
        client.disconnect()
        logging.info("[EXIT] bye.")

if __name__ == "__main__":
    main()

