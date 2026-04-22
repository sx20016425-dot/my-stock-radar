import streamlit as st
import pandas as pd
import asyncio
import datetime
from fugle_marketdata import WebMdaClient

# --- 介面配置 ---
st.set_page_config(page_title="即時盤口監控", layout="wide")

# --- 檢查環境 ---
if "FUGLE_API_KEY" not in st.secrets:
    st.error("❌ 請在 Secrets 中設定 FUGLE_API_KEY")
    st.stop()

API_KEY = st.secrets["FUGLE_API_KEY"]

# --- UI 佈局 ---
st.title("📈 大戶盤口實時監控")
with st.sidebar:
    target = st.text_input("輸入股票代號", value="3042")
    threshold = st.number_input("大單門檻 (張)", value=50)
    start_btn = st.button("🚀 開始即時監控")

col1, col2 = st.columns(2)
with col1:
    st.subheader("🛡️ 五檔委託")
    book_spot = st.empty()
with col2:
    st.subheader("⚔️ 成交明細")
    trade_spot = st.empty()

if 'history' not in st.session_state:
    st.session_state.history = []

# --- WebSocket 邏輯 ---
async def start_monitor():
    client = WebMdaClient(api_key=API_KEY)
    stock = client.stock
    try:
        async with stock.connect_quote(symbol=target) as q_conn, \
                   stock.connect_trade(symbol=target) as t_conn:
            
            st.toast(f"✅ 已連線至 {target}", icon="🚀")
            
            # 建立併發任務
            await asyncio.gather(
                handle_quote(q_conn),
                handle_trade(t_conn)
            )
    except Exception as e:
        st.error(f"連線發生錯誤: {e}")

async def handle_quote(conn):
    async for msg in conn:
        if msg.get('event') == 'data':
            d = msg['data']
            df = pd.DataFrame({
                "買張": [b['size'] for b in d.get('bids', [])[:5]],
                "買價": [b['price'] for b in d.get('bids', [])[:5]],
                "賣價": [a['price'] for a in d.get('asks', [])[:5]],
                "賣張": [a['size'] for a in d.get('asks', [])[:5]]
            })
            book_spot.table(df)

async def handle_trade(conn):
    async for msg in conn:
        if msg.get('event') == 'data':
            d = msg['data']
            p, v = d.get('price'), d.get('size')
            now = datetime.datetime.now().strftime("%H:%M:%S")
            log = f"{'🔥' if v >= threshold else '⚪'} {now} | 價: {p} | 量: {v}"
            st.session_state.history.insert(0, log)
            trade_spot.code("\n".join(st.session_state.history[:15]))

# --- 啟動 ---
if start_btn:
    asyncio.run(start_monitor())
