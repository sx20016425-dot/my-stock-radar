import streamlit as st
import pandas as pd
import datetime
import json
import threading
import time

# --- 1. 相容性導入 (解決 ImportError) ---
try:
    # 嘗試新版路徑 (Streamlit 1.40+)
    from streamlit.runtime.scriptrunner_stack import add_script_run_context
except ImportError:
    try:
        # 嘗試舊版路徑
        from streamlit.runtime.scriptrunner import add_script_run_context
    except ImportError:
        # 如果都失敗，定義一個空的 dummy 函數避免程式崩潰
        def add_script_run_context(thread): pass

# --- 2. 基礎配置 ---
st.set_page_config(page_title="盤口監控-最終相容版", layout="wide")
API_KEY = st.secrets.get("FUGLE_API_KEY", "").strip()

# 初始化數據容器
if 'history' not in st.session_state: st.session_state.history = []
if 'last_quote' not in st.session_state: st.session_state.last_quote = None
if 'logs' not in st.session_state: st.session_state.logs = []

# --- 3. UI 佈局 ---
st.title("📈 盤口監控 (Final Fix)")

with st.sidebar:
    target = st.text_input("股票代號", value="2330").upper()
    btn_start = st.button("🚀 啟動監控", use_container_width=True)
    st.divider()
    st.write("### 狀態診斷")
    log_area = st.empty()

col_left, col_right = st.columns(2)
book_ui = col_left.empty()
trade_ui = col_right.empty()

# --- 4. 訊息與連線處理 ---
def on_message(message):
    try:
        msg = json.loads(message)
        if msg.get("event") == "data":
            data = msg['data']
            if "bids" in data:
                # 更新五檔
                st.session_state.last_quote = pd.DataFrame({
                    "買張": [b['size'] for b in data.get('bids', [])[:5]],
                    "買價": [b['price'] for b in data.get('bids', [])[:5]],
                    "賣價": [a['price'] for a in data.get('asks', [])[:5]],
                    "賣張": [a['size'] for a in data.get('asks', [])[:5]]
                })
            elif "price" in data:
                # 更新成交
                t = datetime.datetime.now().strftime("%H:%M:%S")
                st.session_state.history.insert(0, f"⚪ {t} | {data['price']} | {data['size']}張")
                st.session_state.history = st.session_state.history[:15]
    except:
        pass

def run_websocket(symbol):
    from fugle_marketdata import WebSocketClient
    try:
        # 建立客戶端
        client = WebSocketClient(api_key=API_KEY)
        stock = client.stock
        
        # 綁定事件
        stock.on('message', on_message)
        stock.on('connect', lambda: st.session_state.logs.insert(0, "✅ 連線成功"))
        stock.on('error', lambda e: st.session_state.logs.insert(0, f"❌ 錯誤: {e}"))
        
        # 執行連線
        st.session_state.logs.insert(0, "📡 正在認證...")
        stock.connect()
        
        # 等待並發送訂閱
        for _ in range(3):
            time.sleep(3)
            st.session_state.logs.insert(0, f"發送訂閱 {symbol}...")
            stock.subscribe({"channel": "trades", "symbol": symbol})
            stock.subscribe({"channel": "books", "symbol": symbol})
            
    except Exception as e:
        st.session_state.logs.insert(0, f"❌ 異常: {str(e)}")

# --- 5. 啟動入口 ---
if btn_start:
    if not API_KEY:
        st.error("請在 Secrets 設置 FUGLE_API_KEY")
    else:
        st.session_state.logs = ["系統啟動中..."]
        
        # 獲取當前 Context 並啟動執行緒
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        ctx = get_script_run_ctx()
        
        t = threading.Thread(target=run_websocket, args=(target,), daemon=True)
        add_script_run_context(t) # 這是關鍵：將背景執行緒掛載到 Streamlit 
        t.start()
        
        # 畫面重新整理循環
        while True:
            if st.session_state.last_quote is not None:
                book_ui.table(st.session_state.last_quote)
            if st.session_state.history:
                trade_ui.code("\n".join(st.session_state.history))
            log_area.code("\n".join(st.session_state.logs[:5]))
            time.sleep(1)
