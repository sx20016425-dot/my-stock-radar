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

# --- 1. 配置與初始化 ---
API_KEY = "MWI2Y2NlMTYtZmNjNy00NGJmLWFkMTYtNDVjZjk2MjJkNzFhIDA1YTliNzZhLWI0NzItNGYxMS1iYTIxLWYyN2ZkNjgzNzI5YQ=="

st.set_page_config(page_title="專業操盤戰情室 - 亞洲聯動版", layout="wide")

# 狀態容器
for key in ['price_stats', 'index_data', 'msg_queue', 'logs', 'last_books', 'trade_history', 'last_heartbeat']:
    if key not in st.session_state:
        if key == 'price_stats': st.session_state[key] = {}
        elif key == 'index_data': st.session_state[key] = {"price": 0, "percent": 0}
        elif key == 'msg_queue': st.session_state[key] = queue.Queue()
        elif key == 'logs': st.session_state[key] = []
        elif key == 'last_books': st.session_state[key] = pd.DataFrame()
        elif key == 'trade_history': st.session_state[key] = []
        elif key == 'last_heartbeat': st.session_state[key] = "未連線"

# --- 2. 核心 API 函數 ---

def get_snapshot(symbol):
    """抓取初始靜態數據 (REST API)"""
    url = f"https://api.fugle.tw/marketdata/v1.0/stock/snapshot/quotes/{symbol}"
    headers = {"X-API-KEY": API_KEY}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        return resp.json()
    except Exception:
        return None

@st.cache_data(ttl=300) # 每 5 分鐘快取一次
def get_global_indices(symbols_dict):
    """抓取全球指數數據"""
    results = {}
    for label, sym in symbols_dict.items():
        try:
            ticker = yf.Ticker(sym)
            info = ticker.fast_info
            price = info['last_price']
            prev = info['previous_close']
            results[label] = {
                "price": price,
                "percent": ((price - prev) / prev) * 100
            }
        except:
            results[label] = {"price": 0, "percent": 0}
    return results

def run_trading_engine(symbol, q):
    """防禦性 WebSocket 引擎"""
    from fugle_marketdata import WebSocketClient
    
    def handle_msg(message):
        try:
            msg = json.loads(message)
            if msg.get("event") == "data":
                data = msg['data']
                q.put({"type": "heartbeat", "content": datetime.datetime.now().strftime("%H:%M:%S")})
                if msg.get("channel") == "books": q.put({"type": "books", "data": data})
                elif msg.get("channel") == "trades": q.put({"type": "stock_trade", "price": data['price'], "size": data['size'], "side": data.get('side', 'buy')})
                elif msg.get("channel") == "ticker": q.put({"type": "index", "price": data['close'], "percent": data['changePercent']})
        except: pass

    while True:
        try:
            q.put({"type": "log", "content": "🔄 正在嘗試建立安全連線..."})
            client = WebSocketClient(api_key=API_KEY)
            stock = client.stock
            stock.on('message', handle_msg)
            stock.connect()
            time.sleep(5) 
            
            if not stock.is_connected(): raise Exception("Auth Timeout")
                
            q.put({"type": "log", "content": "✅ 驗證成功，正在訂閱頻道..."})
            stock.subscribe({"channel": "trades", "symbol": symbol})
            time.sleep(1)
            stock.subscribe({"channel": "books", "symbol": symbol})
            time.sleep(1)
            stock.subscribe({"channel": "ticker", "symbol": "IX0001"})
            
            q.put({"type": "log", "content": "🚀 數據通道已全面開啟"})
            while stock.is_connected(): time.sleep(5)
        except Exception as e:
            q.put({"type": "log", "content": f"⚠️ 連線異常: {str(e)}，10秒後嘗試回連..."})
            time.sleep(10)

# --- 3. UI 顯示介面 ---

st.title("📊 專業操盤手實時戰情室 (亞洲聯動版)")

# 指數對照表
indices_to_track = {
    "日經 225": "^N225",      # 日本
    "恒生指數": "^HSI",       # 香港
    "TSM (ADR)": "TSM",       # 台積電 ADR (核心影響)
    "美股標普 500": "^GSPC"    # 全球多頭指標
}
global_data = get_global_indices(indices_to_track)

# 頂部指標
idx_c1, idx_c2, idx_c3, idx_c4, idx_c5 = st.columns(5)
with idx_c1: st.metric("台股加權", f"{st.session_state.index_data['price']}", f"{st.session_state.index_data['percent']}%")
with idx_c2: st.metric("日經 225", f"{global_data['日經 225']['price']:.0f}", f"{global_data['日經 225']['percent']:.2f}%")
with idx_c3: st.metric("恒生指數", f"{global_data['恒生指數']['price']:.0f}", f"{global_data['恒生指數']['percent']:.2f}%")
with idx_c4: st.metric("TSM (ADR)", f"{global_data['TSM (ADR)']['price']:.2f}", f"{global_data['TSM (ADR)']['percent']:.2f}%")
with idx_c5: st.metric("標普 500", f"{global_data['美股標普 500']['price']:.0f}", f"{global_data['美股標普 500']['percent']:.2f}%")

# 側邊欄
with st.sidebar:
    st.header("操作面板")
    stock_target = st.text_input("股票代號", value="2330").upper()
    start_btn = st.button("🚀 啟動連線", use_container_width=True)
    st.divider()
    test_mode = st.checkbox("🛠️ 測試模式 (模擬數據)")
    if st.button("🗑️ 重置統計"):
        st.session_state.price_stats = {}
        st.session_state.trade_history = []
        st.rerun()
    st.write("---")
    log_area = st.empty()
    st.caption(f"通訊狀態: {st.session_state.last_heartbeat}")

# 三大板塊佈局
col_l, col_m, col_r = st.columns([1, 1.3, 0.7])
with col_l:
    st.subheader("🏛️ 即時五檔")
    book_ui = st.empty()
with col_m:
    st.subheader("📈 分價成交分布")
    dist_chart = st.empty()
    dist_table = st.empty()
with col_r:
    st.subheader("🔔 即時明細")
    power_ui = st.empty()
    trade_list_ui = st.empty()

# --- 4. 邏輯循環 ---

if start_btn:
    # 啟動時先用 REST 抓一波數據
    snapshot = get_snapshot(stock_target)
    if snapshot:
        st.session_state.index_data['price'] = snapshot.get('lastPrice', 0)
        b_df = pd.DataFrame(snapshot.get('bids', [])).rename(columns={'price':'買價','size':'買量'})
        a_df = pd.DataFrame(snapshot.get('asks', [])).rename(columns={'price':'賣價','size':'賣量'})
        st.session_state.last_books = pd.concat([b_df, a_df], axis=1)

    t = threading.Thread(target=run_trading_engine, args=(stock_target, st.session_state.msg_queue), daemon=True)
    t.start()
    
    while True:
        if test_mode:
            p = round(random.uniform(1040, 1060), 1)
            st.session_state.msg_queue.put({"type":"stock_trade", "price":p, "size":random.randint(1,10), "side":random.choice(["buy","sell"])})

        while not st.session_state.msg_queue.empty():
            item = st.session_state.msg_queue.get()
            if item["type"] == "log": st.session_state.logs.insert(0, item["content"])
            elif item["type"] == "heartbeat": st.session_state.last_heartbeat = item["content"]
            elif item["type"] == "books":
                d = item["data"]
                b = pd.DataFrame(d.get('bids', [])).rename(columns={'price':'買價','size':'買量'})
                a = pd.DataFrame(d.get('asks', [])).rename(columns={'price':'賣價','size':'賣量'})
                st.session_state.last_books = pd.concat([b, a], axis=1)
            elif item["type"] == "index": st.session_state.index_data = {"price":item['price'], "percent":item['percent']}
            elif item["type"] == "stock_trade":
                p_s = str(item["price"])
                if p_s not in st.session_state.price_stats: st.session_state.price_stats[p_s] = {'買入':0, '賣出':0}
                if item["side"] == "buy": st.session_state.price_stats[p_s]['買入'] += item["size"]
                else: st.session_state.price_stats[p_s]['賣出'] += item["size"]
                st.session_state.trade_history.insert(0, f"{item['price']} | {item['size']}張 | {'🔴' if item['side']=='buy' else '🟢'}")

        # 更新 UI
        log_area.code("\n".join(st.session_state.logs[:3]))
        book_ui.dataframe(st.session_state.last_books, use_container_width=True)
        if st.session_state.price_stats:
            df = pd.DataFrame.from_dict(st.session_state.price_stats, orient='index')
            df.index = df.index.astype(float)
            df = df.sort_index(ascending=False)
            dist_chart.bar_chart(df)
            dist_table.dataframe(df, use_container_width=True)
            tb, ts = df['買入'].sum(), df['賣出'].sum()
            power_ui.metric("多空力道", f"{int(tb)} / {int(ts)}", f"{int(tb-ts)} 淨量")
        trade_list_ui.code("\n".join(st.session_state.trade_history[:15]))
        time.sleep(0.5)
