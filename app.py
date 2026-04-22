import streamlit as st
import pandas as pd
import datetime
import json
import threading
import time

# --- 1. 基礎配置 ---
st.set_page_config(page_title="盤口監控-穩定版", layout="wide")
API_KEY = st.secrets.get("FUGLE_API_KEY")

# 使用 Session State 存儲數據，避免 UI 重新渲染時丟失
if 'history' not in st.session_state:
    st.session_state.history = []
if 'last_quote' not in st.session_state:
    st.session_state.last_quote = None

# --- 2. UI 介面 ---
st.title("📈 實時盤口監控 (Threading 穩定版)")

with st.sidebar:
    target = st.text_input("股票代號", value="3042")
    threshold = st.number_input("大單張數 (>=)", value=50)
    btn_start = st.button("🚀 啟動監控", use_container_width=True)
    if st.button("🧹 清空歷史"):
        st.session_state.history = []
        st.rerun()

col_left, col_right = st.columns(2)
book_ui = col_left.empty()
trade_ui = col_right.empty()

# --- 3. 定時更新 UI 的函式 ---
# 因為 WebSocket 在後台執行緒，我們需要這個來刷新頁面
def update_display():
    if st.session_state.last_quote is not None:
        book_ui.table(st.session_state.last_quote)
    if st.session_state.history:
        trade_ui.code("\n".join(st.session_state.history))

# --- 4. WebSocket 訊息處理器 ---
def on_message(message):
    try:
        msg = json.loads(message)
        if msg.get("event") == "data":
            data = msg['data']
            
            # 處理五檔 (Quote)
            if "bids" in data:
                df = pd.DataFrame({
                    "買張": [b['size'] for b in data.get('bids', [])[:5]],
                    "買價": [b['price'] for b in data.get('bids', [])[:5]],
                    "賣價": [a['price'] for a in data.get('asks', [])[:5]],
                    "賣張": [a['size'] for a in data.get('asks', [])[:5]]
                })
                st.session_state.last_quote = df
            
            # 處理成交 (Trade)
            elif "price" in data:
                p, v = data['price'], data['size']
                t = datetime.datetime.now().strftime("%H:%M:%S")
                icon = "🔥" if v >= threshold else "⚪"
                log = f"{icon} {t} | {p} | {v}張"
                st.session_state.history.insert(0, log)
                st.session_state.history = st.session_state.history[:15]
                
    except Exception:
        pass

# --- 5. 背景執行緒執行函式 ---
def run_websocket():
    from fugle_marketdata import WebSocketClient
    try:
        # 初始化
        ws_client = WebSocketClient(api_key=API_KEY)
        stock = ws_client.stock
        
        # 綁定回調
        stock.on('message', on_message)
        
        # 執行連線 (這個方法在同步模式下會阻塞)
        stock.connect()
        
        # 連線後訂閱
        time.sleep(1)
        stock.subscribe({"symbol": target, "type": "quote"})
        stock.subscribe({"symbol": target, "type": "trade"})
        
    except Exception as e:
        print(f"WS Thread Error: {e}")

# --- 6. 啟動入口 ---
if btn_start:
    if not API_KEY:
        st.error("請先設定 API Key")
    else:
        # 啟動背景執行緒
        thread = threading.Thread(target=run_websocket, daemon=True)
        thread.start()
        st.success(f"監控執行緒已啟動：{target}")
        
        # 進入 UI 更新迴圈
        placeholder = st.empty()
        while True:
            update_display()
            time.sleep(0.5) # 每 0.5 秒重新整理一次畫面
