import streamlit as st
import pandas as pd
import asyncio
import datetime
from fugle_marketdata import WebsocketClient

# --- 1. 頁面配置 ---
st.set_page_config(page_title="大戶盤口監控-最終穩定版", layout="wide")

# --- 2. 檢查 API Key ---
if "FUGLE_API_KEY" not in st.secrets:
    st.error("❌ 請在 Secrets 設定 FUGLE_API_KEY")
    st.stop()

API_KEY = st.secrets["FUGLE_API_KEY"]

# --- 3. UI 介面 ---
st.title("📈 實時盤口大單監控")

with st.sidebar:
    st.header("設定")
    target = st.text_input("輸入代號", value="3042")
    threshold = st.number_input("大單張數門檻", value=50)
    btn = st.button("🚀 開始啟動監控")

col_left, col_right = st.columns(2)
with col_left:
    st.subheader("🛡️ 五檔即時掛單")
    book_ui = st.empty()
with col_right:
    st.subheader("⚔️ 大戶成交紀錄")
    trade_ui = st.empty()

if 'logs' not in st.session_state:
    st.session_state.logs = []

# --- 4. 核心數據處理 ---
async def run_app():
    # 最新版 SDK 直接初始化 WebsocketClient
    client = WebsocketClient(api_key=API_KEY)
    
    try:
        # 使用最新 API 規範：client.stock(symbol).quote()
        # 這是目前最穩定的連線方式
        async with client.stock.quote(symbol=target) as q_conn, \
                   client.stock.trade(symbol=target) as t_conn:
            
            st.toast(f"✅ 已成功連線至 {target}", icon="🚀")
            
            # 同時監聽五檔與成交
            await asyncio.gather(
                handle_quotes(q_conn),
                handle_trades(t_conn)
            )
            
    except Exception as e:
        st.error(f"連線中斷: {e}")
        st.info("💡 溫馨提示：請確認您的 API Key 是否具備即時數據權限。")

async def handle_quotes(conn):
    """處理五檔數據"""
    async for msg in conn:
        if msg.get('event') == 'data':
            d = msg['data']
            # 整理五檔表格
            df = pd.DataFrame({
                "買張": [b['size'] for b in d.get('bids', [])[:5]],
                "買價": [b['price'] for b in d.get('bids', [])[:5]],
                "賣價": [a['price'] for a in d.get('asks', [])[:5]],
                "賣張": [a['size'] for a in d.get('asks', [])[:5]]
            })
            book_ui.table(df)

async def handle_trades(conn):
    """處理成交明細"""
    async for msg in conn:
        if msg.get('event') == 'data':
            d = msg['data']
            p, v = d.get('price'), d.get('size')
            t = datetime.datetime.now().strftime("%H:%M:%S")
            
            icon = '🔥' if v >= threshold else '⚪'
            log_msg = f"{icon} {t} | 價: {p} | 量: {v}"
            
            st.session_state.logs.insert(0, log_msg)
            st.session_state.logs = st.session_state.logs[:15]
            trade_ui.code("\n".join(st.session_state.logs))

# --- 5. 執行 ---
if btn:
    asyncio.run(run_app())
