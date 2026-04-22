import streamlit as st
import pandas as pd
import datetime
import json
import threading
import time
import queue
import random
import yfinance as yf
import requests

# --- 1. 核心參數配置 ---
API_KEY = "MWI2Y2NlMTYtZmNjNy00NGJmLWFkMTYtNDVjZjk2MjJkNzFhIDA1YTliNzZhLWI0NzItNGYxMS1iYTIxLWYyN2ZkNjgzNzI5YQ=="

st.set_page_config(page_title="專業操盤戰情室", layout="wide")

# 初始化 Session State
if 'price_stats' not in st.session_state: st.session_state.price_stats = {} 
if 'index_data' not in st.session_state: st.session_state.index_data = {"price": 0, "percent": 0}
if 'msg_queue' not in st.session_state: st.session_state.msg_queue = queue.Queue()
if 'logs' not in st.session_state: st.session_state.logs = []
if 'last_books' not in st.session_state: st.session_state.last_books = pd.DataFrame()
if 'trade_history' not in st.session_state: st.session_state.trade_history = []
if 'last_heartbeat' not in st.session_state: st.session_state.last_heartbeat = "等待連線"

# --- 2. 核心功能函數 ---

def get_snapshot(symbol):
    """利用 REST API 獲取啟動時的初始快照"""
    url = f"https://api.fugle.tw/marketdata/v1.0/stock/snapshot/quotes/{symbol}"
    headers = {"X-API-KEY": API_KEY}
    try:
        resp = requests.get(url, headers=headers)
        return resp.json()
    except:
        return None

def get_us_data(symbols):
    """抓取美股連動指標 (可能有 15 分鐘延遲)"""
    results = {}
    for sym in symbols:
        try:
            ticker = yf.Ticker(sym)
            info = ticker.fast_info
            results[sym] = {
                "price": info['last_price'],
                "percent": ((info['last_price'] - info['previous_close']) / info['previous_close']) * 100
            }
        except:
            results[sym] = {"price": 0, "percent": 0}
    return results

def run_trading_engine(symbol, q):
    """背景 WebSocket 引擎"""
    from fugle_marketdata import WebSocketClient
    
    def handle_msg(message):
        try:
            msg = json.loads(message)
            if msg.get("event") == "data":
                data = msg['data']
                q.put({"type": "heartbeat", "content": datetime.datetime.now().strftime("%H:%M:%S")})
                if msg.get("channel") == "books":
                    q.put({"type": "books", "data": data})
                elif msg.get("channel") == "trades":
                    q.put({
                        "type": "stock_trade", 
                        "price": data['price'], 
                        "size": data['size'], 
                        "side": data.get('side', 'buy')
                    })
                elif msg.get("channel") == "ticker":
                    q.put({"type": "index", "price": data['close'], "percent": data['changePercent']})
        except: pass

    try:
        client = WebSocketClient(api_key=API_KEY)
        stock = client.stock
        stock.on('message', handle_msg)
        stock.connect()
        time.sleep(2) # 等待連線穩定
        stock.subscribe({"channel": "trades", "symbol": symbol})
        stock.subscribe({"channel": "books", "symbol": symbol})
        stock.subscribe({"channel": "ticker", "symbol": "IX0001"}) # 監控台股大盤
        q.put({"type": "log", "content": f"✅ 監控通道已開啟: {symbol}"})
        while True: time.sleep(1)
    except Exception as e:
        q.put({"type": "log", "content": f"⚠️ 連線提醒: {str(e)}"})

# --- 3. UI 介面佈局 ---

st.title("📊 操盤手實時戰情中心")

# 頂部：大盤與美股指標
us_indices = get_us_data(["TSM", "NVDA", "^SOX"])
idx_c1, idx_c2, idx_c3, idx_c4 = st.columns(4)
with idx_c1:
    st.metric("台股加權 (大盤)", f"{st.session_state.index_data['price']}", f"{st.session_state.index_data['percent']}%")
with idx_c2:
    st.metric("TSM (台積ADR)", f"{us_indices['TSM']['price']:.2f}", f"{us_indices['TSM']['percent']:.2f}%")
with idx_c3:
    st.metric("NVDA (輝達)", f"{us_indices['NVDA']['price']:.2f}", f"{us_indices['NVDA']['percent']:.2f}%")
with idx_c4:
    st.metric("費城半導體", f"{us_indices['^SOX']['price']:.1f}", f"{us_indices['^SOX']['percent']:.2f}%")

# 側邊控制欄
with st.sidebar:
    st.header("監控參數")
    stock_target = st.text_input("輸入個股代號", value="2330").upper()
    start_btn = st.button("🚀 啟動連線系統", use_container_width=True)
    
    st.divider()
    test_mode = st.checkbox("🛠️ 開啟模擬測試模式")
    if st.button("🗑️ 清除統計數據"):
        st.session_state.price_stats = {}
        st.session_state.trade_history = []
        st.rerun()

    st.write("### 診斷日誌")
    log_area = st.empty()
    st.caption(f"最後通訊時間: {st.session_state.last_heartbeat}")

# 主畫面三分佈局
col_left, col_mid, col_right = st.columns([1, 1.3, 0.7])

with col_left:
    st.subheader("🏛️ 即時五檔 (Books)")
    book_ui = st.empty()

with col_mid:
    st.subheader("📈 分價成交分布 (Volume Profile)")
    dist_chart = st.empty()
    dist_table = st.empty()

with col_right:
    st.subheader("🔔 即時成交明細")
    power_ui = st.empty()
    trade_list_ui = st.empty()

# --- 4. 數據處理與渲染循環 ---

if start_btn:
    # 啟動前先抓取快照，解決初期空白問題
    init_data = get_snapshot(stock_target)
    if init_data:
        st.session_state.index_data['price'] = init_data.get('lastPrice', 0)
        # 初始化五檔表格
        b_df = pd.DataFrame(init_data.get('bids', [])).rename(columns={'price':'買價','size':'買量'})
        a_df = pd.DataFrame(init_data.get('asks', [])).rename(columns={'price':'賣價','size':'賣量'})
        st.session_state.last_books = pd.concat([b_df, a_df], axis=1)

    # 開啟 WebSocket 執行緒
    t = threading.Thread(target=run_trading_engine, args=(stock_target, st.session_state.msg_queue), daemon=True)
    t.start()
    
    while True:
        # 測試模式：注入隨機數據
        if test_mode:
            p = round(random.uniform(1040, 1060), 1)
            st.session_state.msg_queue.put({
                "type": "stock_trade", "price": p, "size": random.randint(1, 20), "side": random.choice(["buy", "sell"])
            })
            st.session_state.last_heartbeat = datetime.datetime.now().strftime("%H:%M:%S")

        # 處理隊列訊息
        while not st.session_state.msg_queue.empty():
            item = st.session_state.msg_queue.get()
            
            if item["type"] == "log":
                st.session_state.logs.insert(0, item["content"])
            
            elif item["type"] == "heartbeat":
                st.session_state.last_heartbeat = item["content"]
            
            elif item["type"] == "books":
                d = item["data"]
                b_df = pd.DataFrame(d.get('bids', [])).rename(columns={'price':'買價','size':'買量'})
                a_df = pd.DataFrame(d.get('asks', [])).rename(columns={'price':'賣價','size':'賣量'})
                st.session_state.last_books = pd.concat([b_df, a_df], axis=1)

            elif item["type"] == "index":
                st.session_state.index_data = {"price": item['price'], "percent": item['percent']}

            elif item["type"] == "stock_trade":
                p_str = str(item["price"])
                if p_str not in st.session_state.price_stats:
                    st.session_state.price_stats[p_str] = {'買入': 0, '賣出': 0}
                if item["side"] == "buy": st.session_state.price_stats[p_str]['買入'] += item["size"]
                else: st.session_state.price_stats[p_str]['賣出'] += item["size"]
                
                # 更新明細紀錄
                side_icon = "🔴" if item["side"] == "buy" else "🟢"
                st.session_state.trade_history.insert(0, f"{item['price']} | {item['size']}張 | {side_icon}")

        # --- 定時渲染 UI ---
        log_area.code("\n".join(st.session_state.logs[:3]))
        
        # 1. 更新五檔
        book_ui.dataframe(st.session_state.last_books, use_container_width=True)
        
        # 2. 更新分價圖與表格
        if st.session_state.price_stats:
            df = pd.DataFrame.from_dict(st.session_state.price_stats, orient='index')
            df.index = df.index.astype(float)
            df = df.sort_index(ascending=False)
            dist_chart.bar_chart(df)
            dist_table.dataframe(df, use_container_width=True)
            
            # 3. 更新多空力道
            t_buy = df['買入'].sum()
            t_sell = df['賣出'].sum()
            diff = t_buy - t_sell
            power_ui.metric("多空力道 (買/賣)", f"{int(t_buy)} / {int(t_sell)}", f"{int(diff)} 淨量")

        # 4. 更新明細
        trade_list_ui.code("\n".join(st.session_state.trade_history[:15]))
        
        time.sleep(0.5 if not test_mode else 0.1)
