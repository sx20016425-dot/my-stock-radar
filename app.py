import streamlit as st
import pandas as pd
import datetime
import json
import threading
import time
import queue
import random

# --- 1. 核心參數 ---
API_KEY = "MWI2Y2NlMTYtZmNjNy00NGJmLWFkMTYtNDVjZjk2MjJkNzFhIDA1YTliNzZhLWI0NzItNGYxMS1iYTIxLWYyN2ZkNjgzNzI5YQ=="

st.set_page_config(page_title="專業操盤戰情室", layout="wide")

# 初始化狀態
if 'price_stats' not in st.session_state: st.session_state.price_stats = {} 
if 'index_data' not in st.session_state: st.session_state.index_data = {"price": 0, "percent": 0}
if 'msg_queue' not in st.session_state: st.session_state.msg_queue = queue.Queue()
if 'logs' not in st.session_state: st.session_state.logs = []
if 'last_books' not in st.session_state: st.session_state.last_books = pd.DataFrame()
if 'trade_history' not in st.session_state: st.session_state.trade_history = []

# --- 2. 核心功能函數 ---
def run_trading_engine(symbol, q):
    from fugle_marketdata import WebSocketClient
    def handle_msg(message):
        try:
            msg = json.loads(message)
            if msg.get("event") == "data":
                data = msg['data']
                # 處理五檔 (Books)
                if msg.get("channel") == "books":
                    q.put({"type": "books", "data": data})
                # 處理成交 (Trades)
                elif msg.get("channel") == "trades":
                    q.put({"type": "stock_trade", "price": data['price'], "size": data['size'], "side": data.get('side', 'buy')})
                # 處理指數 (Ticker)
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
        stock.subscribe({"channel": "books", "symbol": symbol})
        stock.subscribe({"channel": "ticker", "symbol": "IX0001"})
        q.put({"type": "log", "content": f"🚀 監控啟動: {symbol}"})
        while True: time.sleep(1)
    except Exception as e:
        q.put({"type": "log", "content": f"⚠️ 連線提醒: {str(e)}"})

# --- 3. UI 介面佈局 ---
st.title("📊 操盤手實時戰情中心")

# 頂部大盤指標
idx_col1, idx_col2, idx_col3 = st.columns(3)
with idx_col1:
    st.metric("大盤指數 (加權)", f"{st.session_state.index_data['price']}", f"{st.session_state.index_data['percent']}%")
with idx_col3:
    st.caption(f"最後更新時間: {datetime.datetime.now().strftime('%H:%M:%S')}")

# 側邊欄
with st.sidebar:
    st.header("監控設定")
    stock_target = st.text_input("個股代號", value="2330").upper()
    start_btn = st.button("🚀 啟動連線", use_container_width=True)
    test_mode = st.checkbox("🛠️ 開啟測試模擬數據")
    st.divider()
    log_area = st.empty()

# 主畫面分為三欄
col_left, col_mid, col_right = st.columns([1, 1.2, 0.8])

with col_left:
    st.subheader("🏛️ 五檔報價 (Books)")
    book_table = st.empty()

with col_mid:
    st.subheader("📈 分價成交分布")
    dist_chart = st.empty()
    dist_table = st.empty()

with col_right:
    st.subheader("🔔 即時成交明細")
    trade_list = st.empty()
    power_ui = st.empty()

# --- 4. 數據處理循環 ---
if start_btn:
    t = threading.Thread(target=run_trading_engine, args=(stock_target, st.session_state.msg_queue), daemon=True)
    t.start()
    
    while True:
        # 測試模式數據注入 (模擬真實價格附近)
        if test_mode:
            base_p = 1050.0
            p = base_p + random.randint(-5, 5)
            st.session_state.msg_queue.put({"type": "stock_trade", "price": p, "size": random.randint(1, 10), "side": random.choice(["buy", "sell"])})
            st.session_state.msg_queue.put({"type": "books", "data": {
                "bids": [{"price": base_p-1, "size": 50}, {"price": base_p-2, "size": 120}],
                "asks": [{"price": base_p+1, "size": 80}, {"price": base_p+2, "size": 45}]
            }})

        # 處理 Queue 數據
        while not st.session_state.msg_queue.empty():
            item = st.session_state.msg_queue.get()
            
            if item["type"] == "books":
                d = item["data"]
                bids = pd.DataFrame(d.get('bids', [])).rename(columns={'price': '買價', 'size': '買量'})
                asks = pd.DataFrame(d.get('asks', [])).rename(columns={'price': '賣價', 'size': '賣量'})
                st.session_state.last_books = pd.concat([bids, asks], axis=1)

            elif item["type"] == "stock_trade":
                p_str = str(item["price"])
                # 統計分價量
                if p_str not in st.session_state.price_stats:
                    st.session_state.price_stats[p_str] = {'買入': 0, '賣出': 0}
                if item["side"] == "buy": st.session_state.price_stats[p_str]['買入'] += item["size"]
                else: st.session_state.price_stats[p_str]['賣出'] += item["size"]
                # 紀錄明細
                st.session_state.trade_history.insert(0, f"{item['price']} | {item['size']}張 | {'🔴' if item['side']=='buy' else '🟢'}")

            elif item["type"] == "index":
                st.session_state.index_data = {"price": item['price'], "percent": item['percent']}

        # --- 渲染 UI ---
        # 1. 五檔
        book_table.dataframe(st.session_state.last_books, use_container_width=True)
        
        # 2. 分價圖
        if st.session_state.price_stats:
            df = pd.DataFrame.from_dict(st.session_state.price_stats, orient='index')
            df.index = df.index.astype(float)
            df = df.sort_index(ascending=False)
            dist_chart.bar_chart(df)
            dist_table.dataframe(df, use_container_width=True)
            
            # 力道比
            t_buy, t_sell = df['買入'].sum(), df['賣出'].sum()
            power_ui.metric("多空力道 (買/賣)", f"{int(t_buy)} / {int(t_sell)}", f"{int(t_buy-t_sell)} 淨量")

        # 3. 明細
        trade_list.code("\n".join(st.session_state.trade_history[:15]))
        
        time.sleep(0.5)
