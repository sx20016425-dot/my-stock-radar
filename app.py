import streamlit as st
import pandas as pd
import asyncio
import datetime
import sys

# --- 1. 精確導入 (根據成員清單校正大小寫) ---
try:
    # 根據你的 logs，確定名稱是 WebSocketClient (大寫 S)
    from fugle_marketdata import WebSocketClient
except ImportError:
    # 備用方案：如果還是失敗，嘗試從 websocket 模組導入
    try:
        from fugle_marketdata.websocket import WebSocketClient
    except ImportError:
        st.error("導入失敗：請確認 fugle-marketdata 版本為 2.4.1")
        st.stop()

# --- 2. 頁面配置 ---
st.set_page_config(page_title="盤口監控雷達", layout="wide")

if "FUGLE_API_KEY" not in st.secrets:
    st.error("❌ 找不到 API Key。請在 Streamlit Cloud 的 Secrets 設定 FUGLE_API_KEY")
    st.stop()

API_KEY = st.secrets["FUGLE_API_KEY"]

# --- 3. UI 佈局 ---
st.title("📈 實時盤口監控 (校正版)")
st.caption(f"Python {sys.version.split()[0]} | SDK 2.4.1 | 類別: WebSocketClient")

with st.sidebar:
    st.header("⚙️ 參數設定")
    target = st.text_input("股票代號", value="3042")
    threshold = st.number_input("大單張數門檻", value=50)
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

# --- 4. 核心邏輯 ---
async def main():
    # 使用正確大小寫的 WebSocketClient
    client = WebSocketClient(api_key=API_KEY)
    stock = client.stock
    
    try:
        # v2.4.1 標準方法名是 quote 和 trade
        async with stock.quote(symbol=target) as q_conn, \
                   stock.trade(symbol=target) as t_conn:
            
            st.toast(f"連線成功: {target}", icon="✅")
            await asyncio.gather(handle_q(q_conn), handle_t(t_conn))
    except Exception as e:
        st.error(f"連線失敗: {e}")
        st.info("💡 提示：請確認您的 API Key 具有 WebSocket 權限。")

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
            icon = "🔥" if v >= threshold else "⚪"
            log = f"{icon} {t} | 價: {p} | 量: {v}"
            st.session_state.history.insert(0, log)
            st.session_state.history = st.session_state.history[:20]
            trade_ui.code("\n".join(st.session_state.history))

# --- 5. 執行 ---
if btn_start:
    try:
        asyncio.run(main())
    except RuntimeError:
        loop = asyncio.get_event_loop()
        loop.create_task(main())
