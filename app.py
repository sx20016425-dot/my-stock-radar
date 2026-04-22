import streamlit as st
import pandas as pd
import datetime
import json
import threading
import time

# --- 1. 初始化 ---
st.set_page_config(page_title="盤口監控-診斷版", layout="wide")
API_KEY = st.secrets.get("FUGLE_API_KEY")

if 'history' not in st.session_state:
    st.session_state.history = []
if 'last_quote' not in st.session_state:
    st.session_state.last_quote = None
if 'debug_logs' not in st.session_state:
    st.session_state.debug_logs = []

# --- 2. UI ---
st.title("📈 盤口監控 (診斷模式)")

with st.sidebar:
    target = st.text_input("股票代號", value="2330").upper()
    threshold = st.number_input("大單門檻", value=50)
    btn_start = st.button("🚀 啟動監控")
    st.divider()
    st.write("### 系統日誌")
    debug_placeholder = st.empty()

col_left, col_right = st.columns(2)
book_ui = col_left.empty()
trade_ui = col_right.empty()

# --- 3. 訊息處理器 ---
def on_message(message):
    try:
        msg = json.loads(message)
        # 紀錄收到的訊息事件
        event_time = datetime.datetime.now().strftime("%H:%M:%S")
        st.session_state.debug_logs.insert(0, f"[{event_time}] Event: {msg.get('event')}")
        
        if msg.get("event") == "data":
            data = msg['data']
            if "bids" in data:
                st.session_state.last_quote = pd.DataFrame({
                    "買張": [b['size'] for b in data.get('bids', [])[:5]],
                    "買價": [b['price'] for b in data.get('bids', [])[:5]],
                    "賣價": [a['price'] for a in data.get('asks', [])[:5]],
                    "賣張": [a['size'] for a in data.get('asks', [])[:5]]
                })
            elif "price" in data:
                p, v = data['price'], data['size']
                icon = "🔥" if v >= threshold else "⚪"
                st.session_state.history.insert(0, f"{icon} {event_time} | {p} | {v}張")
    except Exception as e:
        st.session_state.debug_logs.insert(0, f"Error parsing: {e}")

# --- 4. 背景連線 ---
def run_websocket(symbol):
    from fugle_marketdata import WebSocketClient
    try:
        client = WebSocketClient(api_key=API_KEY)
        stock = client.stock
        
        stock.on('message', on_message)
        stock.on('error', lambda e: st.session_state.debug_logs.insert(0, f"❌ WS Error: {e}"))
        stock.on('connect', lambda: st.session_state.debug_logs.insert(0, "✅ 已連線至富果伺服器"))
        
        stock.connect()
        
        # 循環訂閱嘗試 (2.4.1 強制規範)
        for i in range(3):
            time.sleep(3)
            st.session_state.debug_logs.insert(0, f"嘗試訂閱 {symbol}...({i+1}/3)")
            stock.subscribe({"channel": "trades", "symbol": symbol})
            stock.subscribe({"channel": "books", "symbol": symbol})
            
    except Exception as e:
        st.session_state.debug_logs.insert(0, f"Thread Crash: {e}")

# --- 5. 執行與刷新 ---
if btn_start:
    if not API_KEY:
        st.error("請檢查 Secrets 裡的 FUGLE_API_KEY")
    else:
        st.session_state.debug_logs = ["開始啟動執行緒..."]
        threading.Thread(target=run_websocket, args=(target,), daemon=True).start()
        
        while True:
            # 更新左側五檔
            if st.session_state.last_quote is not None:
                book_ui.table(st.session_state.last_quote)
            # 更新右側成交
            if st.session_state.history:
                trade_ui.code("\n".join(st.session_state.history[:15]))
            # 更新側邊欄 Debug 資訊
            debug_placeholder.code("\n".join(st.session_state.debug_logs[:10]))
            
            time.sleep(1)
