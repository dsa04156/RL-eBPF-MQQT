#!/usr/bin/env python3
# eda.py — MQTT(23232) 전용 eBPF 관찰 + (옵션)제어 에이전트
# - 커널 TCP 신호: srtt_us, 재전송, sndbuf, rcvbuf
# - 관찰 전용(EDA_OBSERVE=1) / 제어 모드(기본) 토글
# - 임계값/주기/제어 파라미터 전부 환경변수로 조정
# - 강화: 히스테리시스(상/하한), EWMA, 멀티시그널 결합, 적응형 임계(옵션)

from bcc import BPF
from socket import inet_ntop, AF_INET, ntohs
import struct, time, os, json, sys
from collections import deque
from statistics import mean
from paho.mqtt import client as mqtt

# ====== 환경변수 ======
MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "23232"))
CONTROL_TOPIC = os.getenv("CONTROL_TOPIC", "control/room1")
METRICS_TOPIC = os.getenv("METRICS_TOPIC", "eda/latency")  # subscriber가 보내는 앱 레벨 지연 통계
OBSERVE = os.getenv("EDA_OBSERVE", "0") == "1"   # 1이면 관찰 전용(제어 발행 안 함)

# 기본 임계(백업)
TH_RTT_US  = int(os.getenv("TH_RTT_US",  "60000"))       # 60 ms
TH_RETRANS = int(os.getenv("TH_RETRANS", "1"))           # 구간 재전송 1회 초과
TH_SNDBUF  = int(os.getenv("TH_SNDBUF",  str(256*1024))) # 256 KB
TH_RCVBUF  = int(os.getenv("TH_RCVBUF",  str(256*1024))) # 256 KB

# 히스테리시스 / 홀드타임
HI_RTT_US  = int(os.getenv("HI_RTT_US",  "70000"))   # 켤 때
LO_RTT_US  = int(os.getenv("LO_RTT_US",  "50000"))   # 끌 때
T_HOLD_ON  = float(os.getenv("T_HOLD_ON",  "0.8"))   # 초: 조건 유지시 ON
T_HOLD_OFF = float(os.getenv("T_HOLD_OFF", "1.5"))   # 초: 안정 지속시 OFF

# 평활화
EWMA_ALPHA = float(os.getenv("EWMA_ALPHA", "0.3"))

# sndbuf 사용률 기준(상대)
SND_RATIO_HI = float(os.getenv("SND_RATIO_HI", "0.85"))
SND_RATIO_LO = float(os.getenv("SND_RATIO_LO", "0.60"))

# 수집/제어 주기
INTERVAL_S       = float(os.getenv("INTERVAL_S", "2.0"))     # eBPF 집계 주기
CONTROL_MIN_SEC  = float(os.getenv("CONTROL_MIN_SEC", "2.0"))# 최소 제어 간격(쿨다운)

# 제어 명령 파라미터 (퍼블리셔가 해석)
CTRL_THROTTLE_RATE = int(os.getenv("CTRL_RATE", "5"))  # Hz (과거 절대 목표값)
CTRL_BATCH_SIZE    = int(os.getenv("CTRL_BATCH", "5"))

# 단계적 증감 제어 옵션(비RL 환경에서 부드럽게 제어)
R_MIN = int(os.getenv("R_MIN", "1"))
R_MAX = int(os.getenv("R_MAX", "200"))
B_MIN = int(os.getenv("B_MIN", "1"))
B_MAX = int(os.getenv("B_MAX", "32"))
STEP_DOWN_FRAC_SEV = float(os.getenv("STEP_DOWN_FRAC_SEV", "0.30"))  # 심각 혼잡시 -30%
STEP_DOWN_FRAC_MOD = float(os.getenv("STEP_DOWN_FRAC_MOD", "0.15"))  # 보통 혼잡시 -15%
STEP_UP_FRAC       = float(os.getenv("STEP_UP_FRAC", "0.10"))        # 해제시 +10% (현재는 release 기본 사용)
CTRL_BASE_RATE     = int(os.getenv("CTRL_BASE_RATE", "50"))           # 정상시 목표(퍼블리셔 기본)
CTRL_BASE_BATCH    = int(os.getenv("CTRL_BASE_BATCH", "1"))

# 적응형 임계(옵션)
USE_ADAPTIVE = os.getenv("USE_ADAPTIVE", "0") == "1"
ADAPT_WIN    = int(os.getenv("ADAPT_WIN", "200"))      # 최근 샘플 개수
MIN_RTT_HARD = 40_000  # 40ms: 적응형에서 최소 기준
MAX_HI_CAP   = 120_000 # 120ms: HI 상한 캡

total_msgs = 0

BPF_PROGRAM = r"""
#include <uapi/linux/ptrace.h>
#include <net/sock.h>
#include <net/inet_sock.h>
#include <linux/tcp.h>
#include <linux/skbuff.h>

struct key_t {
    __u32 saddr;
    __u32 daddr;
    __u16 sport;
    __u16 dport;
};

struct val_t {
    __u64 retrans;     // 누적 재전송
    __u32 srtt_us;     // 최근 RTT(마이크로초, 커널 내부*8에서 보정하여 저장)
    __u32 sndbuf;      // 송신 큐 바이트(sk_wmem_queued)
    __u32 rcvbuf;      // 수신 큐 바이트(sk_rmem_alloc)
};

BPF_HASH(stats, struct key_t, struct val_t, 16384);

static __always_inline int is_mqtt_port(__u16 p_be) {
    __u16 p = bpf_ntohs(p_be);
    return p == 23232; // MQTT
}

static __always_inline int fill_key(struct sock *sk, struct key_t *key) {
    struct inet_sock *inet = (struct inet_sock *)sk;
    if (!inet) return 0;
    // MQTT 소켓만 추적
    if (!(is_mqtt_port(inet->inet_sport) || is_mqtt_port(inet->inet_dport))) return 0;

    key->saddr = inet->inet_saddr;
    key->daddr = inet->inet_daddr;
    key->sport = inet->inet_sport; // big-endian 저장
    key->dport = inet->inet_dport;
    return 1;
}

// ① 재전송 발생 시 누적 카운트 증가
TRACEPOINT_PROBE(tcp, tcp_retransmit_skb) {
    struct sock *sk = (struct sock *)args->skaddr;
    if (!sk) return 0;

    struct key_t k = {};
    if (!fill_key(sk, &k)) return 0;

    struct val_t zero = {};
    struct val_t *v = stats.lookup_or_init(&k, &zero);
    if (v) {
        __sync_fetch_and_add(&v->retrans, 1);
    }
    return 0;
}

// ② 송신 호출 시 sndbuf 샘플링
int kprobe__tcp_sendmsg(struct pt_regs *ctx, struct sock *sk, struct msghdr *msg, size_t size) {
    if (!sk) return 0;
    struct key_t k = {};
    if (!fill_key(sk, &k)) return 0;

    __u32 wmem = 0;
    bpf_probe_read_kernel(&wmem, sizeof(wmem), &sk->sk_wmem_queued);

    struct val_t zero = {};
    struct val_t *v = stats.lookup_or_init(&k, &zero);
    if (v) { v->sndbuf = wmem; }
    return 0;
}

// ③ 수신 경로에서 RTT/rcvbuf 샘플링
int kprobe__tcp_rcv_established(struct pt_regs *ctx, struct sock *sk, struct sk_buff *skb,
                                const struct tcphdr *th, unsigned int len) {
    if (!sk) return 0;
    struct key_t k = {};
    if (!fill_key(sk, &k)) return 0;

    struct tcp_sock *tp = (struct tcp_sock *)sk;
    __u32 srtt = 0;
    bpf_probe_read_kernel(&srtt, sizeof(srtt), &tp->srtt_us);
    if (srtt) srtt >>= 3; // 마이크로초(us)

    __u32 rmem = 0;
    bpf_probe_read_kernel(&rmem, sizeof(rmem), &sk->sk_rmem_alloc);

    struct val_t zero = {};
    struct val_t *v = stats.lookup_or_init(&k, &zero);
    if (v) { v->srtt_us = srtt; v->rcvbuf = rmem; }
    return 0;
}
""";

def ntoa(x):
    try:
        return inet_ntop(AF_INET, struct.pack("!I", x))
    except Exception:
        return inet_ntop(AF_INET, struct.pack("I", x))

def key_to_str(k):
    saddr = ntoa(k[0]); daddr = ntoa(k[1])
    sport = ntohs(k[2]); dport = ntohs(k[3])
    return f"{saddr}:{sport}->{daddr}:{dport}"

def make_mqtt():
    cli = mqtt.Client(client_id="eda-agent")
    cli.connect(MQTT_HOST, MQTT_PORT, 60)
    cli.loop_start()
    return cli

# -------- 앱 레벨 지연 메트릭 수신 (옵션) --------
LATEST_METRICS = {
    "ts": None, "n": None, "window_sec": None,
    "p50_ms": None, "p95_ms": None, "p99_ms": None,
    "mean_ms": None, "total_msgs": None
}

def on_metrics(cli, userdata, msg):
    try:
        payload = json.loads(msg.payload)
        for k in list(LATEST_METRICS.keys()):
            if k in payload:
                LATEST_METRICS[k] = payload[k]
    except Exception as e:
        print(json.dumps({"warn":"bad_metrics_payload","err":str(e)}), flush=True)

def main():
    global total_msgs
    b = BPF(text=BPF_PROGRAM)
    print("[OK] eBPF loaded (MQTT:23232; srtt/retrans/sndbuf/rcvbuf)", flush=True)
    cli = make_mqtt()
    # 앱 레벨 지연 메트릭 구독
    try:
        cli.message_callback_add(METRICS_TOPIC, on_metrics)
        cli.subscribe(METRICS_TOPIC, qos=0)
        print(json.dumps({"info":"subscribe_metrics","topic":METRICS_TOPIC}), flush=True)
    except Exception as e:
        print(json.dumps({"warn":"subscribe_metrics_failed","err":str(e)}), flush=True)
    last_congested_state = False
    # 단계적 제어 현재 상태(초기값은 퍼블리셔 기본과 정렬 권장)
    current_rate_cmd  = CTRL_BASE_RATE
    current_batch_cmd = CTRL_BASE_BATCH
    prev_totals = {}           # flow별 누적 재전송 스냅샷
    last_ctrl_ts = 0.0         # 제어 스팸 방지(쿨다운)

    # 히스테리시스 상태/타이머
    congested = False
    on_since = None
    off_since = time.time()

    # EWMA / 적응형 윈도우
    ewma_rtt_us = None
    rtt_window = deque(maxlen=ADAPT_WIN)

    while True:
        time.sleep(INTERVAL_S)
        now = time.time()
        table = b.get_table("stats")

        snapshot = {}
        alerts = []

        # 집계용
        rtt_ms_list = []
        had_retrans = False
        max_sndbuf = 0
        max_rcvbuf = 0

        for k, v in table.items():
            key = (k.saddr, k.daddr, k.sport, k.dport)
            snapshot[key] = int(v.retrans)
            total_msgs += 1
            rtt_ms = float(v.srtt_us) / 1000.0
            sndbuf = int(v.sndbuf)
            rcvbuf = int(v.rcvbuf)
            retrans_total = int(v.retrans)
            retrans_delta = max(0, retrans_total - prev_totals.get(key, 0))

            rtt_ms_list.append(rtt_ms)
            if retrans_delta > 0:
                had_retrans = True
            if sndbuf > max_sndbuf: max_sndbuf = sndbuf
            if rcvbuf > max_rcvbuf: max_rcvbuf = rcvbuf

            line = {
                "ts": now,
                "flow": key_to_str(key),
                "interval_s": INTERVAL_S,
                "rtt_ms": round(rtt_ms, 2),
                "retrans_delta": retrans_delta,
                "sndbuf": sndbuf,
                "rcvbuf": rcvbuf,
                "total_msgs": total_msgs
            }
            print(json.dumps(line), flush=True)  # JSONL 출력

        # ---- EWMA / 적응형 임계 갱신 ----
        if rtt_ms_list:
            avg_rtt_ms = mean(rtt_ms_list)
            cur_rtt_us = int(avg_rtt_ms * 1000)
            if ewma_rtt_us is None:
                ewma_rtt_us = cur_rtt_us
            else:
                ewma_rtt_us = int(ewma_rtt_us + EWMA_ALPHA * (cur_rtt_us - ewma_rtt_us))
            if USE_ADAPTIVE:
                rtt_window.append(cur_rtt_us)
                arr = sorted(rtt_window)
                p50 = arr[len(arr)//2] if arr else cur_rtt_us
                base = max(int(1.5 * p50), MIN_RTT_HARD)
                hi   = min(max(int(2.0 * p50), 60_000), MAX_HI_CAP)
                lo   = int(0.7 * hi)
            else:
                base, hi, lo = TH_RTT_US, HI_RTT_US, LO_RTT_US
        else:
            # 샘플이 없으면 기존 설정 유지
            avg_rtt_ms = 0.0
            base, hi, lo = TH_RTT_US, HI_RTT_US, LO_RTT_US

        # sndbuf/rcvbuf 사용률 근사(최대치를 TH_*로 가정)
        snd_ratio = max_sndbuf / max(1, TH_SNDBUF)
        rcv_ratio = max_rcvbuf / max(1, TH_RCVBUF)

        # ---- 멀티시그널 결합 조건 ----
        rtt_on  = (ewma_rtt_us or 0) > hi
        rtt_off = (ewma_rtt_us or 0) < lo
        buf_on  = (snd_ratio >= SND_RATIO_HI) or (rcv_ratio >= SND_RATIO_HI)
        buf_off = (snd_ratio <= SND_RATIO_LO) and (rcv_ratio <= SND_RATIO_LO)
        ret_on  = had_retrans and (TH_RETRANS <= 1)  # 재전송 감지 즉시 가중
        ret_off = not had_retrans

        want_on  = rtt_on and (buf_on or had_retrans)
        want_off = rtt_off and buf_off and ret_off

        # 히스테리시스 타이머 처리
        if want_on:
            if on_since is None:
                on_since = now
            if (now - on_since) >= T_HOLD_ON:
                congested = True
                off_since = None
        else:
            on_since = None

        if want_off:
            if off_since is None:
                off_since = now
            if (now - off_since) >= T_HOLD_OFF:
                congested = False
                on_since = None
        else:
            # 안정 상태가 아니면 off_since 리셋
            if not want_off:
                off_since = None

        # ---- 제어 발행 (쿨다운) : 단계적 증감 ----
        if not OBSERVE and (now - last_ctrl_ts) >= CONTROL_MIN_SEC:
            if congested:
                severe = (ewma_rtt_us or 0) > 100_000 or (snd_ratio > 0.9) or (had_retrans and TH_RETRANS <= 1)
                moderate = (ewma_rtt_us or 0) > 70_000 or snd_ratio > 0.8 or had_retrans
                frac = STEP_DOWN_FRAC_SEV if severe else (STEP_DOWN_FRAC_MOD if moderate else 0.0)

                cmds = []
                if frac > 0.0:
                    new_rate = int(max(R_MIN, round(current_rate_cmd * (1.0 - frac))))
                    bump = 2 if severe else (1 if moderate else 0)
                    new_batch = int(min(B_MAX, max(B_MIN, current_batch_cmd + bump)))
                    if new_rate != current_rate_cmd:
                        cmds.append({"cmd": "throttle", "rate": new_rate})
                        current_rate_cmd = new_rate
                    if bump > 0 and new_batch != current_batch_cmd:
                        cmds.append({"cmd": "batch", "size": new_batch})
                        current_batch_cmd = new_batch
                    if severe:
                        cmds.append({"cmd": "qos", "level": 0})
                if cmds:
                    for c in cmds:
                        cli.publish(CONTROL_TOPIC, payload=json.dumps(c), qos=1)
                    print(json.dumps({
                        "ts": now, "congested": True, "ewma_rtt_us": ewma_rtt_us,
                        "snd_ratio": round(snd_ratio,3), "rcv_ratio": round(rcv_ratio,3),
                        "control": cmds, "current_rate_cmd": current_rate_cmd,
                        "current_batch_cmd": current_batch_cmd
                    }), flush=True)
                    last_ctrl_ts = now
            else:
                # 혼잡 해제: 기본 복귀(release)
                release_cmd = {"cmd": "release", "defaults": {"rate": -1, "batch": -1, "qos": 1}}
                cli.publish(CONTROL_TOPIC, payload=json.dumps(release_cmd), qos=1)
                print(json.dumps({"ts": now, "status": "STABLE", "control": release_cmd}), flush=True)
                current_rate_cmd, current_batch_cmd = CTRL_BASE_RATE, CTRL_BASE_BATCH
                last_ctrl_ts = now
            last_congested_state = congested

        # 다음 라운드를 위해 스냅샷 보관
        prev_totals = snapshot

        # 앱 레벨 지연 메트릭 스냅샷도 주기적으로 출력(1회)
        ms = {k: LATEST_METRICS.get(k) for k in ["ts","n","window_sec","p50_ms","p95_ms","p99_ms","mean_ms","total_msgs"]}
        freshness = None
        try:
            if ms.get("ts") and ms.get("window_sec"):
                freshness = now - float(ms["ts"])
        except Exception:
            pass
        print(json.dumps({
            "ts": now,
            "metrics": ms,
            "metrics_fresh_sec": round(freshness,3) if isinstance(freshness,(int,float)) else None,
            "source": "subscriber_metrics"
        }), flush=True)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
