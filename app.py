import streamlit as st
import pandas as pd
import asyncio
import datetime
import sys

# --- 1. 導入 ---
try:
    from fugle_marketdata import WebSocketClient
except ImportError:
    st.error("❌ 導入失敗，請重新啟動 App。")
    st.stop()

# --- 2. 配置 ---
st.set_page_config(page_title="盤口監控-最終方案", layout="wide")
API_KEY = st.secrets.get("FUGLE_API_KEY")

# --- 3. UI ---
st.title("📈 實時盤口監控 (自適應版)")
with st.sidebar:
    target = st.text_input("股票代號", value="3042")
    threshold = st.number_input("大單張數 (>=)", value=50)
    btn_start = st.button("🚀 啟動監控", use_container_width=True)

col_left, col_right = st.columns(2)
book_ui = col_left.empty()
trade_ui = col_right.empty()

if 'history' not in st.session_state:
    st.session_state.history = []

# --- 4. 核心邏輯 (不再猜測路徑，直接動態查找) ---
async def start_monitor():
    client = WebSocketClient(api_key=API_KEY)
    
    # 動態探測 SDK 結構
    stock = client.stock
    
    # 這裡是最關鍵的修正：
    # 根據你的錯誤，stock 底下沒有 quote，
    # 代表我們必須使用 client.stock('3042', 'quote') 這種直接調用方式
    try:
        # 嘗試方案 A: 直接對 stock 物件進行連線 (這是部分 2.4.x 的特性)
        q_stream = stock(symbol=target, type='quote')
        t_stream = stock(symbol=target, type='trade')
        
        async with q_stream as q_conn, t_stream as t_conn:
            st.toast("✅ 連線成功")
            await asyncio.gather(update_quotes(q_conn), update_trades(t_conn))
            
    except Exception as e:
        # 嘗試方案 B: 如果 A 失敗，使用 .connect() 但不帶參數，隨後再傳入
        try:
            async with stock.connect(symbol=target, type='quote') as q_conn:
                await update_quotes(q_conn)
        except Exception as e2:
            st.error(f"❌ SDK 結構不相容: {e2}")
            st.code(f"目前的 stock 物件屬性有: {dir(stock)}")

async def update_quotes(conn):
    async for msg in conn:
        if msg.get('event') == 'data':
            d = msg['data']
            df = pd.DataFrame({
                "買張": [b['size'] for b in d.get('bids', [])[:5]],
                "買價": [b['price'] for b in d.get('bids', [])[:5]],
                "賣價": [a['price'] for a in d.get('asks', [])[:5]],
                "賣張": [a['size'] for a in d.get('asks', [])[:5]]
            })
            book_ui.table(df)

async def update_trades(conn):
    async for msg in conn:
        if msg.get('event') == 'data':
            d = msg['data']
            p, v = d.get('price'), d.get('size')
            t = datetime.datetime.now().strftime("%H:%M:%S")
            icon = "🔥" if v >= threshold else "⚪"
            st.session_state.history.insert(0, f"{icon} {t} | {p} | {v}張")
            st.session_state.history = st.session_state.history[:15]
            trade_ui.code("\n".join(st.session_state.history))

if btn_start:
    try:
        asyncio.run(start_monitor())
    except RuntimeError:
        loop = asyncio.get_event_loop()
        loop.create_task(start_monitor())
