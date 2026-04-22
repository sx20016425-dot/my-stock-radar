import streamlit as st
import pandas as pd
import datetime
import json
import threading
import time
from streamlit.runtime.scriptrunner import add_script_run_context

# --- 1. 基礎配置 ---
st.set_page_config(page_title="盤口監控-穩定認證版", layout="wide")

# 安全取得 API KEY
API_KEY = st.secrets.get("FUGLE_API_KEY", "").strip()

# 初始化 Session State
if 'history' not in st.session_state: st.session_state.history = []
if 'last_quote' not in st.session_state: st.session_state.last_quote = None
if 'logs' not in st.session_state: st.session_state.logs = []

# --- 2. UI ---
st.title("📈 盤口監控 (認證修復版)")

with st.sidebar:
    target = st.text_input("股票代號", value="2330").upper()
    btn_start = st.button("🚀 啟動監控")
    st.divider()
    log_area = st.empty()

col_left, col_right = st.columns(2)
book_ui = col_left.empty()
trade_ui = col_right.empty()

# --- 3. 訊息處理 (透過列表傳遞數據，避免執行緒衝突) ---
def on_message(message):
    try:
        msg = json.loads(message)
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
                t = datetime.datetime.now().strftime("%H:%M:%S")
                st.session_state.history.insert(0, f"⚪ {t} | {data['price']} | {data['size']}張")
    except:
        pass

# --- 4. 背景執行緒 (加入 ScriptRunContext 修復) ---
def run_websocket(symbol, ctx):
    # 將主執行緒的 context 注入背景執行緒，這樣才能用 st.session_state
    add_script_run_context(ctx)
    from fugle_marketdata import WebSocketClient
    
    try:
        st.session_state.logs.insert(0, "📡 正在向富果申請認證...")
        client = WebSocketClient(api_key=API_KEY)
        stock = client.stock
        
        stock.on('message', on_message)
        stock.on('connect', lambda: st.session_state.logs.insert(0, "✅ 認證成功，連線已建立"))
        stock.on('error', lambda e: st.session_state.logs.insert(0, f"❌ 伺服器錯誤: {e}"))
        
        # 啟動連線
        stock.connect()
        
        # 暴力訂閱循環
        for _ in range(5):
            time.sleep(3)
            st.session_state.logs.insert(0, f"嘗試訂閱 {symbol}...")
            stock.subscribe({"channel": "trades", "symbol": symbol})
            stock.subscribe({"channel": "books", "symbol": symbol})
            
    except Exception as e:
        st.session_state.logs.insert(0, f"❌ 連線失敗: {str(e)}")

# --- 5. 執行 ---
if btn_start:
    if not API_KEY:
        st.error("❌ 找不到 API KEY，請檢查 Secrets。")
    else:
        st.session_state.logs = ["準備啟動..."]
        # 抓取目前執行緒的 context
        from threading import current_thread
        ctx = getattr(current_thread(), 'streamlit_script_run_ctx', None)
        
        t = threading.Thread(target=run_websocket, args=(target, ctx), daemon=True)
        t.start()
        
        # UI 刷新迴圈
        while True:
            if st.session_state.last_quote is not None:
                book_ui.table(st.session_state.last_quote)
            if st.session_state.history:
                trade_ui.code("\n".join(st.session_state.history[:15]))
            log_area.code("\n".join(st.session_state.logs[:5]))
            time.sleep(1)
