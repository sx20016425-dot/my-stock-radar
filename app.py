import streamlit as st
import pandas as pd
import datetime
import json
import threading
import time
import queue

# --- 1. 基礎配置 ---
st.set_page_config(page_title="盤口監控-最終穩定版", layout="wide")
API_KEY = st.secrets.get("FUGLE_API_KEY", "").strip()

# 初始化 UI 容器
if 'history_list' not in st.session_state: st.session_state.history_list = []
if 'last_df' not in st.session_state: st.session_state.last_df = None

# 建立跨執行緒的隊列 (核心溝通橋樑)
if 'msg_queue' not in st.session_state:
    st.session_state.msg_queue = queue.Queue()

# --- 2. UI 佈局 ---
st.title("📈 盤口監控 (Queue 傳遞版)")

with st.sidebar:
    target = st.text_input("股票代號", value="2330").upper()
    btn_start = st.button("🚀 啟動監控", use_container_width=True)
    st.divider()
    status_log = st.empty()

col_left, col_right = st.columns(2)
book_ui = col_left.empty()
trade_ui = col_right.empty()

# --- 3. WebSocket 執行緒功能 (純淨邏輯，不存取 st.session_state) ---
def run_websocket(symbol, q):
    from fugle_marketdata import WebSocketClient
    
    def on_message(message):
        try:
            msg = json.loads(message)
            q.put({"type": "data", "content": msg})
        except: pass

    try:
        q.put({"type": "log", "content": "📡 正在連線認證..."})
        client = WebSocketClient(api_key=API_KEY)
        stock = client.stock
        
        stock.on('message', on_message)
        stock.on('connect', lambda: q.put({"type": "log", "content": "✅ 連線成功"}))
        stock.on('error', lambda e: q.put({"type": "log", "content": f"❌ 錯誤: {e}"}))
        
        stock.connect()
        
        # 訂閱循環
        for _ in range(5):
            time.sleep(2)
            q.put({"type": "log", "content": f"嘗試訂閱 {symbol}..."})
            stock.subscribe({"channel": "trades", "symbol": symbol})
            stock.subscribe({"channel": "books", "symbol": symbol})
    except Exception as e:
        q.put({"type": "log", "content": f"💥 崩潰: {str(e)}"})

# --- 4. 主循環啟動 ---
if btn_start:
    if not API_KEY:
        st.error("Secrets 缺少 API KEY")
    else:
        # 啟動背景執行緒，傳入隊列 q
        t = threading.Thread(
            target=run_websocket, 
            args=(target, st.session_state.msg_queue), 
            daemon=True
        )
        t.start()
        
        # 主執行緒不斷從隊列中提取數據並更新 UI
        while True:
            while not st.session_state.msg_queue.empty():
                item = st.session_state.msg_queue.get()
                
                # 處理日誌
                if item["type"] == "log":
                    status_log.code(item["content"])
                
                # 處理盤口數據
                elif item["type"] == "data":
                    msg = item["content"]
                    if msg.get("event") == "data":
                        data = msg['data']
                        # 五檔
                        if "bids" in data:
                            st.session_state.last_df = pd.DataFrame({
                                "買張": [b['size'] for b in data.get('bids', [])[:5]],
                                "買價": [b['price'] for b in data.get('bids', [])[:5]],
                                "賣價": [a['price'] for a in data.get('asks', [])[:5]],
                                "賣張": [a['size'] for a in data.get('asks', [])[:5]]
                            })
                        # 成交
                        elif "price" in data:
                            now = datetime.datetime.now().strftime("%H:%M:%S")
                            st.session_state.history_list.insert(0, f"{now} | {data['price']} | {data['size']}張")
            
            # 刷新畫面
            if st.session_state.last_df is not None:
                book_ui.table(st.session_state.last_df)
            if st.session_state.history_list:
                trade_ui.code("\n".join(st.session_state.history_list[:20]))
            
            time.sleep(0.5)
