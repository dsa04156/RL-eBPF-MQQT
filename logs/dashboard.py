import streamlit as st
import pandas as pd
import json
import time
import os

# ==========================================
# 설정: 로그 파일 절대 경로를 권장합니다.
# ==========================================
LOG_FILE = "/home/sslab/mqtt-ebpf-edge/logs/ppo_reset_v1.jsonl"
MAX_POINTS = 50  # 그래프에 표시할 최대 데이터 포인트 수

st.set_page_config(layout="wide", page_title="RL Agent Monitor")
st.title("🚀 Real-time Network & RL Agent Monitor")

# 사이드바: 상태 모니터링
st.sidebar.header("System Status")
status_indicator = st.sidebar.empty()
file_status = st.sidebar.empty()
last_update_time = st.sidebar.empty()

# 레이아웃: 탭 구성
tab1, tab2, tab3 = st.tabs(["📊 Overview", "🔧 Kernel Signals", "🧠 Policy & Momentum"])

with tab1:
    col1, col2, col3 = st.columns(3)
    with col1:
        st.subheader("Latency (ms)")
        ph_latency = st.empty()
    with col2:
        st.subheader("Throughput (msg/s)")
        ph_thr = st.empty()
    with col3:
        st.subheader("Reward")
        ph_reward = st.empty()

with tab2:
    col_k1, col_k2 = st.columns(2)
    with col_k1:
        st.subheader("Buffer Occupancy")
        ph_buffer = st.empty()
    with col_k2:
        st.subheader("RTT (us) & Congestion Score")
        ph_rtt_cong = st.empty()
    
    st.subheader("Retransmission Event")
    ph_retrans = st.empty()

with tab3:
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        st.subheader("Action: Rate & Batch")
        ph_policy = st.empty()
    with col_p2:
        st.subheader("Momentum: d_Rate & d_Batch")
        ph_momentum = st.empty()

# -------------------------------------------------------
# 데이터 파싱 함수 (에러 처리 강화)
# -------------------------------------------------------
def parse_log_line(line):
    try:
        log = json.loads(line)
        if not isinstance(log, dict):
            return None
            
        # 타임스탬프 변환
        ts = pd.to_datetime(log["ts"], unit="s")
        
        # Metrics
        metrics = log.get("metrics", {})
        p50 = metrics.get("p50_ms", 0)
        p99 = metrics.get("p99_ms", 0)
        thr = metrics.get("thr", 0)
        reward = log.get("r", 0)
        
        # Kernel
        kernel = log.get("kernel", {})
        snd_ratio = kernel.get("snd_ratio", 0)
        rcv_ratio = kernel.get("rcv_ratio", 0)
        rtt = kernel.get("ewma_rtt_us", 0)
        cong_score = kernel.get("congestion_score", 0)
        had_retrans = 1 if kernel.get("had_retrans") else 0
        
        # Action Info
        rate = 0
        batch = 0
        if "cmds" in log and isinstance(log["cmds"], list):
            for cmd in log["cmds"]:
                if cmd.get("cmd") == "throttle":
                    rate = cmd.get("rate", 0)
                elif cmd.get("cmd") == "batch":
                    batch = cmd.get("size", 0)
                
        # A_Raw (Momentum)
        a_raw = log.get("a_raw", {})
        d_rate = a_raw.get("d_rate", 0)
        d_batch = a_raw.get("d_batch", 0)
        
        return {
            "ts": ts,
            "p50_ms": p50,
            "p99_ms": p99,
            "thr": thr,
            "reward": reward,
            "snd_ratio": snd_ratio,
            "rcv_ratio": rcv_ratio,
            "rtt_us": rtt,
            "cong_score": cong_score,
            "had_retrans": had_retrans,
            "rate": rate,
            "batch": batch,
            "d_rate": d_rate,
            "d_batch": d_batch
        }
    except Exception:
        # 파싱 실패 시 무시
        return None

# 차트 업데이트
def update_charts(df):
    if df.empty:
        return

    # Tab 1
    ph_latency.line_chart(df[["p50_ms", "p99_ms"]])
    ph_thr.line_chart(df[["thr"]])
    ph_reward.line_chart(df[["reward"]])
    
    # Tab 2
    ph_buffer.line_chart(df[["snd_ratio", "rcv_ratio"]])
    ph_rtt_cong.line_chart(df[["rtt_us", "cong_score"]])
    ph_retrans.bar_chart(df[["had_retrans"]])
    
    # Tab 3
    ph_policy.line_chart(df[["rate", "batch"]])
    ph_momentum.line_chart(df[["d_rate", "d_batch"]])

# -------------------------------------------------------
# 메인 루프
# -------------------------------------------------------

# 1. 파일 존재 확인
if not os.path.exists(LOG_FILE):
    st.error(f"❌ Log file not found: {LOG_FILE}")
    st.stop()

# 2. 파일 권한 확인
if not os.access(LOG_FILE, os.R_OK):
    st.error(f"❌ Permission denied: {LOG_FILE} (Try: sudo chmod 644 {LOG_FILE})")
    st.stop()

file_status.success(f"Watching: {os.path.basename(LOG_FILE)}")

# 3. 파일 열기
try:
    f = open(LOG_FILE, "r")
except Exception as e:
    st.error(f"Error opening file: {e}")
    st.stop()

# 상태 변수
data_buffer = []
json_buffer = ""
brace_balance = 0

# 디버깅용 변수
total_lines_read = 0
json_objects_detected = 0
parsed_success_count = 0
last_error = "None"

# 4. 실시간 업데이트 루프
status_indicator.info("Running...")

# 초기 로딩을 위해 파일 끝까지 읽기 (블로킹 없이)
initial_lines = f.readlines()
total_lines_read = len(initial_lines)

for line in initial_lines:
    json_buffer += line
    brace_balance += line.count('{') - line.count('}')
    
    # 괄호 짝이 맞고 버퍼가 비어있지 않으면 파싱 시도
    if brace_balance == 0 and json_buffer.strip():
        json_objects_detected += 1
        try:
            parsed = parse_log_line(json_buffer)
            if parsed:
                data_buffer.append(parsed)
                parsed_success_count += 1
            else:
                last_error = "Parsed result is None (missing keys?)"
        except Exception as e:
            last_error = str(e)
        json_buffer = ""
        brace_balance = 0

# 사이드바에 디버그 정보 표시
st.sidebar.markdown("---")
st.sidebar.subheader("Debug Info")
st.sidebar.text(f"Lines Read: {total_lines_read}")
st.sidebar.text(f"JSON Objects: {json_objects_detected}")
st.sidebar.text(f"Parsed Success: {parsed_success_count}")
st.sidebar.text(f"Last Error: {last_error}")

# 초기 데이터프레임 생성
if data_buffer:
    df = pd.DataFrame(data_buffer)
    df.set_index("ts", inplace=True)
    df = df.tail(MAX_POINTS)
    update_charts(df)
else:
    df = pd.DataFrame()
    st.warning(f"Waiting for data... (Read {total_lines_read} lines, Found {json_objects_detected} objects)")

# 실시간 루프
while True:
    line = f.readline()
    if not line:
        time.sleep(0.1)
        continue
        
    json_buffer += line
    brace_balance += line.count('{') - line.count('}')
    
    if brace_balance == 0 and json_buffer.strip():
        try:
            parsed = parse_log_line(json_buffer)
            if parsed:
                new_row = pd.DataFrame([parsed])
                new_row.set_index("ts", inplace=True)
                
                if df.empty:
                    df = new_row
                else:
                    df = pd.concat([df, new_row])
                
                # 데이터 유지 개수 제한
                if len(df) > MAX_POINTS:
                    df = df.iloc[-MAX_POINTS:]
                    
                update_charts(df)
                last_update_time.text(f"Last Update: {time.strftime('%H:%M:%S')}")
        except:
            pass
        json_buffer = ""
        brace_balance = 0