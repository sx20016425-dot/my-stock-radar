import streamlit as st
import pandas as pd
import asyncio
import datetime
from fugle_marketdata import WebsocketClient

# --- 1. 頁面基礎配置 ---
st.set_page_config(page_title="盤口監控雷達", layout="wide")

if "FUGLE_API_KEY" not in st.secrets:
    st.error("❌ 找不到 API Key。請在 Streamlit Cloud 的 Secrets 設定 FUGLE_API_KEY")
    st.stop()

API_KEY = st.secrets["FUGLE_API_KEY"]

# --- 2. UI 佈局 ---
st.title("🚀 實時盤口監控")
st.caption(f"環境：Python {'.'.join(map(str, sys.version_info[:3]))} | SDK v2.4.1")

with st.sidebar:
    st.header("⚙️ 參數設定")
    target = st.text_input("股票代號", value="3042")
    threshold = st.number_input("大單張數 (>=)", value=50)
    btn_start = st.button("🚀 開始監控", use_container_width=True)
    if st.button("🧹 清空紀錄"):
        st.session_state.history = []
        st.rerun()

col_left, col_right = st.columns([2, 3])
with col_left:
    st.subheader("🛡️ 即時五檔")
    book_ui = st.empty()
with col_right:
    st.subheader("⚔️ 大戶成交流")
    trade_ui = st.empty()

if 'history' not in st.session_state:
    st.session_state.history = []

# --- 3. 核心邏輯 ---
async def main():
    client = WebsocketClient(api_key=API_KEY)
    stock = client.stock
    
    try:
        # 使用 SDK v2.4.1 規範：直接調用 quote/trade 
        async with stock.quote(symbol=target) as q_conn, \
                   stock.trade(symbol=target) as t_conn:
            
            st.toast(f"連線成功: {target}", icon="✅")
            await asyncio.gather(
                handle_q(q_conn),
                handle_t(t_conn)
            )
    except Exception as e:
        st.error(f"連線中斷: {e}")

async def handle_q(conn):
    async for msg in conn:
        if msg.get('event') == 'data':
            d = msg['data']
            # 取前五檔數據
            df = pd.DataFrame({
                "買張": [b['size'] for b in d.get('bids', [])[:5]],
                "買價": [b['price'] for b in d.get('bids', [])[:5]],
                "賣價": [a['price'] for a in d.get('asks', [])[:5]],
                "賣張": [a['size'] for a in d.get('asks', [])[:5]]
            })
            book_ui.table(df)

async def handle_t(conn):
    async for msg in conn:
        if msg.get('event') == 'data':
            d = msg['data']
            p, v = d.get('price'), d.get('size')
            t = datetime.datetime.now().strftime("%H:%M:%S")
            
            icon = "🔥" if v >= threshold else "⚪"
            log = f"{icon} {t} | 價: {p} | 量: {v}"
            
            st.session_state.history.insert(0, log)
            st.session_state.history = st.session_state.history[:20] # 顯示 20 筆
            trade_spot.code("\n".join(st.session_state.history))

# --- 4. 啟動入口 ---
if btn_start:
    # 解決 Streamlit 在某些環境下 asyncio.run 的報錯問題
    try:
        asyncio.run(main())
    except RuntimeError:
        # 如果已經有 loop 在跑，則取得目前的 loop
        loop = asyncio.get_event_loop()
        loop.create_task(main())
