import streamlit as st
import pandas as pd
import asyncio
import datetime
from fugle_marketdata import WebsocketClient

# --- 介面配置 ---
st.set_page_config(page_title="大戶盤口監控-新版SDK", layout="wide")

# --- 檢查密鑰 ---
if "FUGLE_API_KEY" not in st.secrets:
    st.error("❌ 請在 Secrets 設定 FUGLE_API_KEY")
    st.stop()

API_KEY = st.secrets["FUGLE_API_KEY"]

st.title("📈 實時盤口監控 (最新 SDK 版)")

with st.sidebar:
    target = st.text_input("輸入代號", value="3042")
    threshold = st.number_input("大單張數門檻", value=50)
    btn = st.button("🚀 開始監控")

col1, col2 = st.columns(2)
with col1:
    st.subheader("🛡️ 五檔委託")
    book_ui = st.empty()
with col2:
    st.subheader("⚔️ 成交明細")
    trade_ui = st.empty()

if 'logs' not in st.session_state:
    st.session_state.logs = []

# --- 新版 WebSocket 處理邏輯 ---
async def run_app():
    # 最新版使用 WebsocketClient
    client = WebsocketClient(api_key=API_KEY)
    
    # 取得股票連線實例
    stock = client.stock
    
    try:
        # 最新版 SDK 改為直接調用 quote 與 trade 方法
        async with stock.quote(symbol=target) as q_conn, \
                   stock.trade(symbol=target) as t_conn:
            
            st.toast(f"✅ 連線成功: {target}", icon="🚀")
            await asyncio.gather(handle_q(q_conn), handle_t(t_conn))
            
    except Exception as e:
        st.error(f"連線失敗: {e}")
        st.info("💡 提示：請確認您的 API Key 是否支援即時 WebSocket 權限。")

async def handle_q(conn):
    async for msg in conn:
        # 新版數據結構微調，直接讀取 data
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
            
            # 大單偵測
            icon = '🔥' if v >= threshold else '⚪'
            log = f"{icon} {t} | 價: {p} | 量: {v}"
            
            st.session_state.logs.insert(0, log)
            st.session_state.logs = st.session_state.logs[:15]
            trade_ui.code("\n".join(st.session_state.logs))

if btn:
    asyncio.run(run_app())
