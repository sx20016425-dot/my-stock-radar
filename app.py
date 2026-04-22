import streamlit as st
import pandas as pd
import datetime
import json
import threading
import time
import queue

# --- 1. 核心參數與初始化 ---
API_KEY = "MWI2Y2NlMTYtZmNjNy00NGJmLWFkMTYtNDVjZjk2MjJkNzFhIDA1YTliNzZhLWI0NzItNGYxMS1iYTIxLWYyN2ZkNjgzNzI5YQ=="

st.set_page_config(page_title="專業操盤戰情室", layout="wide")

# 初始化所有狀態容器
if 'price_stats' not in st.session_state: st.session_state.price_stats = {} 
if 'index_data' not in st.session_state: st.session_state.index_data = {"price": 0, "percent": 0}
if 'msg_queue' not in st.session_state: st.session_state.msg_queue = queue.Queue()
if 'logs' not in st.session_state: st.session_state.logs = []

# --- 2. 核心功能函數 (必須放在主程式邏輯之前) ---

def run_trading_engine(symbol, q):
    """背景執行緒：負責接收 WebSocket 數據並塞入 Queue"""
    from fugle_marketdata import WebSocketClient
    
    def handle_msg(message):
        try:
            msg = json.loads(message)
            if msg.get("event") == "data":
                data = msg['data']
                # 處理個股成交 (Trades)
                if msg.get("channel") == "trades":
                    q.put({
                        "type": "stock_trade", 
                        "price": data['price'], 
                        "size": data['size'], 
                        "side": data.get('side', 'buy')
                    })
                # 處理大盤指數 (Ticker)
                elif msg.get("channel") == "ticker":
                    q.put({
                        "type": "index", 
                        "price": data['close'], 
                        "percent": data['changePercent']
                    })
        except Exception: pass

    try:
        client = WebSocketClient(api_key=API_KEY)
        stock = client.stock
        stock.on('message', handle_msg)
        stock.on('connect', lambda: q.put({"type": "log", "content": "✅ 伺服器連線成功"}))
        stock.connect()
        
        # 訂閱個股與大盤 (台指期近月通常為 TX00 或根據富果規範)
        stock.subscribe({"channel": "trades", "symbol": symbol})
        stock.subscribe({"channel": "ticker", "symbol": "IX0001"}) # 先以加權指數 IX0001 測試大盤趨勢
        
        while True: time.sleep(1)
    except Exception as e:
        q.put({"type": "log", "content": f"💥 連線異常: {e}"})

# --- 3. UI 介面設計 ---

# A. 頂部大盤看板
st.title("📊 即時操盤戰情中心")
idx_col1, idx_col2 = st.columns(2)
with idx_col1:
    st.metric("大盤指數 (加權)", 
              f"{st.session_state.index_data['price']}", 
              f"{st.session_state.index_data['percent']}%")

# B. 側邊控制欄
with st.sidebar:
    st.header("監控參數")
    stock_target = st.text_input("監控個股", value="2330").upper()
    start_btn = st.button("🚀 啟動監控系統", use_container_width=True)
    st.divider()
    log_area = st.empty()

# C. 主數據區
col_left, col_right = st.columns([1.5, 1])
with col_left:
    st.subheader("價格成交分布 (分價量統計)")
    dist_chart = st.empty()
    dist_table = st.empty()

with col_right:
    st.subheader("買賣力道對比")
    power_metric = st.empty()
    trade_log = st.empty()

# --- 4. 啟動與主循環 ---

if start_btn:
    # 啟動背景執行緒 (現在 run_trading_engine 已經定義好了)
    t = threading.Thread(target=run_trading_engine, args=(stock_target, st.session_state.msg_queue), daemon=True)
    t.start()
    
    while True:
        # 讀取數據籃子 (Queue)
        while not st.session_state.msg_queue.empty():
            item = st.session_state.msg_queue.get()
            
            if item["type"] == "log":
                st.session_state.logs.insert(0, item["content"])
            
            elif item["type"] == "index":
                st.session_state.index_data = {"price": item['price'], "percent": item['percent']}
            
            elif item["type"] == "stock_trade":
                p = str(item["price"])
                if p not in st.session_state.price_stats:
                    st.session_state.price_stats[p] = {'買入張數': 0, '賣出張數': 0}
                
                # 統計分價數據
                if item["side"] == "buy":
                    st.session_state.price_stats[p]['買入張數'] += item["size"]
                else:
                    st.session_state.price_stats[p]['賣出張數'] += item["size"]

        # --- 5. 實時更新 UI ---
        log_area.code("\n".join(st.session_state.logs[:3]))
        
        if st.session_state.price_stats:
            df = pd.DataFrame.from_dict(st.session_state.price_stats, orient='index')
            df.index.name = '價格'
            # 轉換索引為數字排序
            df.index = df.index.astype(float)
            df = df.sort_index(ascending=False)
            
            # 更新圖表與表格
            dist_chart.bar_chart(df)
            dist_table.table(df)
            
            # 計算總買賣力道
            total_buy = df['買入張數'].sum()
            total_sell = df['賣出張數'].sum()
            power_metric.metric("多空力道比 (買/賣)", f"{total_buy} / {total_sell}", 
                               f"{round(total_buy - total_sell, 2)} 張")

        time.sleep(0.5)
