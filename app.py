import streamlit as st
import pandas as pd
import datetime
import json
import threading
import time
import queue
import random

# --- 1. 核心參數與初始化 ---
# 已更新為你提供的新 API Key
API_KEY = "MWI2Y2NlMTYtZmNjNy00NGJmLWFkMTYtNDVjZjk2MjJkNzFhIDA1YTliNzZhLWI0NzItNGYxMS1iYTIxLWYyN2ZkNjgzNzI5YQ=="

st.set_page_config(page_title="專業操盤戰情室", layout="wide")

if 'price_stats' not in st.session_state: st.session_state.price_stats = {} 
if 'index_data' not in st.session_state: st.session_state.index_data = {"price": 0, "percent": 0}
if 'msg_queue' not in st.session_state: st.session_state.msg_queue = queue.Queue()
if 'logs' not in st.session_state: st.session_state.logs = []
if 'last_heartbeat' not in st.session_state: st.session_state.last_heartbeat = "無"

# --- 2. 核心功能函數 ---
def run_trading_engine(symbol, q):
    from fugle_marketdata import WebSocketClient
    def handle_msg(message):
        try:
            msg = json.loads(message)
            if msg.get("event") == "data":
                data = msg['data']
                q.put({"type": "heartbeat", "content": datetime.datetime.now().strftime("%H:%M:%S")})
                if msg.get("channel") == "trades":
                    q.put({"type": "stock_trade", "price": data['price'], "size": data['size'], "side": data.get('side', 'buy')})
                elif msg.get("channel") == "ticker":
                    q.put({"type": "index", "price": data['close'], "percent": data['changePercent']})
        except: pass

    try:
        client = WebSocketClient(api_key=API_KEY)
        stock = client.stock
        stock.on('message', handle_msg)
        stock.connect()
        time.sleep(2) 
        stock.subscribe({"channel": "trades", "symbol": symbol})
        stock.subscribe({"channel": "ticker", "symbol": "IX0001"})
        q.put({"type": "log", "content": f"🚀 監控啟動: {symbol} & 大盤"})
        while True: time.sleep(1)
    except Exception as e:
        q.put({"type": "log", "content": f"⚠️ 連線提醒: {str(e)}"})

# --- 3. UI 介面 ---
st.title("📊 即時操盤戰情中心")
idx_col1, idx_col2 = st.columns(2)
with idx_col1:
    st.metric("大盤指數 (加權)", f"{st.session_state.index_data['price']}", f"{st.session_state.index_data['percent']}%")

with st.sidebar:
    st.header("監控參數")
    stock_target = st.text_input("監控個股代號", value="2330").upper()
    start_btn = st.button("🚀 啟動監控系統", use_container_width=True)
    
    st.divider()
    test_mode = st.checkbox("🛠️ 開啟模擬測試模式")
    
    st.write("### 診斷日誌")
    log_area = st.empty()
    st.caption(f"最後通訊: {st.session_state.last_heartbeat}")

col_left, col_right = st.columns([1.5, 1])
with col_left:
    st.subheader("價格成交分布 (分價量統計)")
    dist_chart = st.empty()
    dist_table = st.empty()

with col_right:
    st.subheader("買賣力道對比")
    power_metric = st.empty()
    trade_log = st.empty()

# --- 4. 執行與主循環 ---
if start_btn:
    t = threading.Thread(target=run_trading_engine, args=(stock_target, st.session_state.msg_queue), daemon=True)
    t.start()
    
    while True:
        # --- 測試代碼：手動注入模擬數據 ---
        if test_mode:
            test_data = {
                "type": "stock_trade",
                "price": 1000.0 + random.randint(-3, 3), 
                "size": random.randint(1, 15),
                "side": random.choice(["buy", "sell"])
            }
            st.session_state.msg_queue.put(test_data)
            st.session_state.last_heartbeat = datetime.datetime.now().strftime("%H:%M:%S")

        # 處理隊列訊息
        while not st.session_state.msg_queue.empty():
            item = st.session_state.msg_queue.get()
            if item["type"] == "log":
                st.session_state.logs.insert(0, item["content"])
            elif item["type"] == "heartbeat":
                st.session_state.last_heartbeat = item["content"]
            elif item["type"] == "index":
                st.session_state.index_data = {"price": item['price'], "percent": item['percent']}
            elif item["type"] == "stock_trade":
                p = str(item["price"])
                if p not in st.session_state.price_stats:
                    st.session_state.price_stats[p] = {'買入張數': 0, '賣出張數': 0}
                if item["side"] == "buy":
                    st.session_state.price_stats[p]['買入張數'] += item["size"]
                else:
                    st.session_state.price_stats[p]['賣出張數'] += item["size"]

        # 更新 UI 元件
        log_area.code("\n".join(st.session_state.logs[:3]))
        
        if st.session_state.price_stats:
            df = pd.DataFrame.from_dict(st.session_state.price_stats, orient='index')
            df.index = df.index.astype(float)
            df = df.sort_index(ascending=False)
            
            # 渲染圖表與表格
            dist_chart.bar_chart(df)
            dist_table.table(df)
            
            # 計算力道
            total_buy = df['買入張數'].sum()
            total_sell = df['賣出張數'].sum()
            diff = total_buy - total_sell
            power_metric.metric("累積買/賣力道", f"{int(total_buy)} / {int(total_sell)}", f"{int(diff)} 張")

        # 根據模式調整刷新頻率
        time.sleep(0.1 if test_mode else 0.5)
