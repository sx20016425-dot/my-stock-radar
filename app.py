import streamlit as st
import pandas as pd
import datetime
import json
import threading
import time
import queue

# --- 1. 初始化 (API KEY 與 統計容器) ---
API_KEY = "ZGFiYmNkMjgtY2JjMy00YmRiLWFhOWItMWM3NDljY2VmNzRlIDcwZTM1OGUzLTYzNjItNDFiZC1hOGFlLWYxNmIyMDU4ZjU0Ng"

if 'price_stats' not in st.session_state: st.session_state.price_stats = {} # 格式: {price: {'buy': total, 'sell': total}}
if 'index_data' not in st.session_state: st.session_state.index_data = {"price": 0, "change": 0, "percent": 0}
if 'msg_queue' not in st.session_state: st.session_state.msg_queue = queue.Queue()

# --- 2. UI 配置 (分為大盤區與個股統計區) ---
st.set_page_config(page_title="專業操盤戰情室", layout="wide")

# 頂部大盤導航列
idx_col1, idx_col2, idx_col3 = st.columns(3)
with idx_col1:
    st.metric("台指期近月", f"{st.session_state.index_data['price']}", f"{st.session_state.index_data['percent']}%")

# 主畫面佈局
col_left, col_right = st.columns([1.5, 1])

with st.sidebar:
    st.header("監控設定")
    stock_target = st.text_input("監控個股代號", value="2330").upper()
    if st.button("🚀 開啟戰情室", use_container_width=True):
        st.session_state.price_stats = {} # 重置統計
        # 啟動背景監控執行緒 (可同時處理個股與大盤)
        t = threading.Thread(target=run_trading_engine, args=(stock_target, st.session_state.msg_queue), daemon=True)
        t.start()

# --- 3. 核心運算引擎 (WebSocket 接收與預處理) ---
def run_trading_engine(symbol, q):
    from fugle_marketdata import WebSocketClient
    
    def handle_msg(message):
        msg = json.loads(message)
        if msg.get("event") == "data":
            data = msg['data']
            # A. 處理個股成交 (計算買賣力道)
            if "price" in data and msg.get("channel") == "trades":
                q.put({"type": "stock_trade", "price": data['price'], "size": data['size'], "side": data.get('side', 'buy')})
            # B. 處理大盤/指數 (假設頻道為 Ticker)
            elif msg.get("channel") == "ticker" and msg.get("symbol") == "TX00": # TX00 為台指期代號
                q.put({"type": "index", "price": data['close'], "change": data['change'], "percent": data['changePercent']})

    try:
        client = WebSocketClient(api_key=API_KEY)
        stock = client.stock
        stock.on('message', handle_msg)
        stock.connect()
        # 同時訂閱個股與大盤
        stock.subscribe({"channel": "trades", "symbol": symbol})
        stock.subscribe({"channel": "ticker", "symbol": "TX00"}) # 訂閱大盤 Ticker
        while True: time.sleep(1)
    except Exception as e:
        q.put({"type": "log", "content": f"連線異常: {e}"})

# --- 4. 主循環數據處理 ---
# (在 while True 迴圈中)
while not st.session_state.msg_queue.empty():
    item = st.session_state.msg_queue.get()
    
    if item["type"] == "stock_trade":
        p = str(item["price"])
        if p not in st.session_state.price_stats:
            st.session_state.price_stats[p] = {'buy': 0, 'sell': 0}
        # 根據成交屬性累加張數
        if item["side"] == "buy": st.session_state.price_stats[p]['buy'] += item["size"]
        else: st.session_state.price_stats[p]['sell'] += item["size"]

    elif item["type"] == "index":
        st.session_state.index_data = {"price": item['price'], "percent": item['percent']}

# --- 5. 數據視覺化顯示 ---
with col_left:
    st.subheader(f"{stock_target} 價格分布統計")
    if st.session_state.price_stats:
        stats_df = pd.DataFrame.from_dict(st.session_state.price_stats, orient='index')
        stats_df.index.name = '價格'
        # 顯示統計表，讓你知道哪個價位是「關鍵戰區」
        st.bar_chart(stats_df) 
        st.table(stats_df.sort_index(ascending=False))
