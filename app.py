import streamlit as st
import pandas as pd
import datetime
import json
import threading
import time
import queue

# --- 1. 直接導入 API Key ---
# 這裡已經幫你把剛才那串代碼整合進來了
API_KEY = "ZGFiYmNkMjgtY2JjMy00YmRiLWFhOWItMWM3NDljY2VmNzRlIDcwZTM1OGUzLTYzNjItNDFiZC1hOGFlLWYxNmIyMDU4ZjU0Ng"

# --- 2. 基礎配置與狀態初始化 ---
st.set_page_config(page_title="台股盤口監控雷達", layout="wide")

# 初始化 session_state，確保程式重新整理時不會出錯
if 'history_list' not in st.session_state: st.session_state.history_list = []
if 'last_df' not in st.session_state: st.session_state.last_df = None
if 'msg_queue' not in st.session_state: st.session_state.msg_queue = queue.Queue()
if 'logs' not in st.session_state: st.session_state.logs = []
if 'last_heartbeat' not in st.session_state: st.session_state.last_heartbeat = "無"

# --- 3. UI 佈局 ---
st.title("📈 盤口動態監控系統")

with st.sidebar:
    st.header("控制台")
    target = st.text_input("輸入股票代號 (如: 2330, 2884)", value="2330").upper()
    btn_start = st.button("🚀 啟動即時連線", use_container_width=True)
    st.divider()
    st.write("### 📡 連線診斷區")
    log_area = st.empty()
    heartbeat_area = st.empty()

col_left, col_right = st.columns([2, 1])
with col_left:
    st.subheader("五檔報價 (Books)")
    book_ui = st.empty()
with col_right:
    st.subheader("即時成交 (Trades)")
    trade_ui = st.empty()

# --- 4. WebSocket 核心執行緒 ---
def run_websocket(symbol, q):
    from fugle_marketdata import WebSocketClient
    
    def on_message(message):
        try:
            msg = json.loads(message)
            # 發送心跳與數據到隊列
            q.put({"type": "heartbeat", "content": datetime.datetime.now().strftime("%H:%M:%S")})
            q.put({"type": "data", "content": msg})
        except: pass

    try:
        q.put({"type": "log", "content": f"正在嘗試連線至富果... 代號: {symbol}"})
        client = WebSocketClient(api_key=API_KEY)
        stock = client.stock
        
        stock.on('message', on_message)
        stock.on('connect', lambda: q.put({"type": "log", "content": "✅ 連線成功！"}))
        stock.on('error', lambda e: q.put({"type": "log", "content": f"❌ 錯誤: {e}"}))
        
        stock.connect()
        
        # 訂閱邏輯
        while True:
            q.put({"type": "log", "content": f"發送訂閱請求: {symbol}"})
            stock.subscribe({"channel": "trades", "symbol": symbol})
            stock.subscribe({"channel": "books", "symbol": symbol})
            time.sleep(30) # 每 30 秒維持一次訂閱狀態
    except Exception as e:
        q.put({"type": "log", "content": f"💥 系統異常: {str(e)}"})

# --- 5. 主程式循環 ---
if btn_start:
    st.session_state.logs = ["連線程序初始化..."]
    # 啟動背景執行緒
    t = threading.Thread(target=run_websocket, args=(target, st.session_state.msg_queue), daemon=True)
    t.start()
    
    # 主執行緒不斷刷新畫面
    while True:
        while not st.session_state.msg_queue.empty():
            item = st.session_state.msg_queue.get()
            
            if item["type"] == "log":
                st.session_state.logs.insert(0, item["content"])
            elif item["type"] == "heartbeat":
                st.session_state.last_heartbeat = item["content"]
            elif item["type"] == "data":
                msg = item["content"]
                if msg.get("event") == "data":
                    data = msg['data']
                    # 處理五檔數據
                    if "bids" in data:
                        st.session_state.last_df = pd.DataFrame({
                            "買張": [b['size'] for b in data.get('bids', [])[:5]],
                            "買價": [b['price'] for b in data.get('bids', [])[:5]],
                            "賣價": [a['price'] for a in data.get('asks', [])[:5]],
                            "賣張": [a['size'] for a in data.get('asks', [])[:5]]
                        })
                    # 處理成交數據
                    elif "price" in data:
                        now = datetime.datetime.now().strftime("%H:%M:%S")
                        st.session_state.history_list.insert(0, f"⚪ {now} | {data['price']} | {data['size']}張")

        # 更新畫面的 UI 元件
        log_area.code("\n".join(st.session_state.logs[:5]))
        heartbeat_area.write(f"最後通訊時間: {st.session_state.last_heartbeat}")
        
        if st.session_state.last_df is not None:
            book_ui.table(st.session_state.last_df)
            
        if st.session_state.history_list:
            trade_ui.code("\n".join(st.session_state.history_list[:20]))
        
        time.sleep(0.5) # 控制刷新頻率，避免瀏覽器卡死
