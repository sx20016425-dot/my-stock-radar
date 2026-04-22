import streamlit as st
import pandas as pd
import asyncio
import datetime
import fugle_marketdata

# --- 自動處理版本相容性 ---
if hasattr(fugle_marketdata, 'WebMdaClient'):
    from fugle_marketdata import WebMdaClient
elif hasattr(fugle_marketdata, 'RestClient'):
    from fugle_marketdata import RestClient as WebMdaClient
else:
    st.error("富果 SDK 版本不相容，請聯繫開發者。")
    st.stop()

# --- 介面配置 ---
st.set_page_config(page_title="大戶盤口雷達", layout="wide")

if "FUGLE_API_KEY" not in st.secrets:
    st.error("❌ 請在 Secrets 設定 FUGLE_API_KEY")
    st.stop()

API_KEY = st.secrets["FUGLE_API_KEY"]

st.title("📈 即時盤口監控")

# 側邊欄控制
with st.sidebar:
    target = st.text_input("輸入代號 (例如 3042)", value="3042")
    threshold = st.number_input("大單張數門檻", value=50)
    btn = st.button("🚀 啟動監控")

col1, col2 = st.columns(2)
with col1:
    st.subheader("🛡️ 五檔委託")
    book_ui = st.empty()
with col2:
    st.subheader("⚔️ 成交明細")
    trade_ui = st.empty()

if 'logs' not in st.session_state:
    st.session_state.logs = []

async def run_app():
    # 根據 SDK 版本初始化 Client
    client = WebMdaClient(api_key=API_KEY)
    stock = client.stock
    try:
        async with stock.connect_quote(symbol=target) as q_conn, \
                   stock.connect_trade(symbol=target) as t_conn:
            await asyncio.gather(handle_q(q_conn), handle_t(t_conn))
    except Exception as e:
        st.error(f"連線失敗: {e}")

async def handle_q(conn):
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

async def handle_t(conn):
    async for msg in conn:
        if msg.get('event') == 'data':
            d = msg['data']
            p, v = d.get('price'), d.get('size')
            t = datetime.datetime.now().strftime("%H:%M:%S")
            log = f"{'🔥' if v >= threshold else '⚪'} {t} | 價: {p} | 量: {v}"
            st.session_state.logs.insert(0, log)
            trade_ui.code("\n".join(st.session_state.logs[:15]))

if btn:
    asyncio.run(run_app())
