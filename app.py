import streamlit as st
import pandas as pd
import asyncio
import datetime
import sys

# --- 1. 深度暴力導入 (解決 ImportError 的最終手段) ---
try:
    # 嘗試方案 A: 標準導入
    from fugle_marketdata import WebsocketClient
except ImportError:
    try:
        # 嘗試方案 B: 絕對路徑導入 (針對 SDK 內部結構)
        from fugle_marketdata.websocket.client import WebsocketClient
    except ImportError:
        try:
            # 嘗試方案 C: 舊版相容導入
            from fugle_marketdata import WebMdaClient as WebsocketClient
        except ImportError:
            import fugle_marketdata
            st.error("❌ 嚴重導入錯誤！")
            st.write("環境內的套件成員：", dir(fugle_marketdata))
            st.stop()

# --- 2. 頁面配置 ---
st.set_page_config(page_title="盤口監控雷達", layout="wide")

if "FUGLE_API_KEY" not in st.secrets:
    st.error("❌ 找不到 API Key。請在 Secrets 設定 FUGLE_API_KEY")
    st.stop()

API_KEY = st.secrets["FUGLE_API_KEY"]

# --- 3. UI 佈局 ---
st.title("📈 實時盤口監控")
st.caption(f"Python {sys.version.split()[0]} | SDK 2.4.1 暴力相容模式")

with st.sidebar:
    st.header("⚙️ 參數設定")
    target = st.text_input("股票代號", value="3042")
    threshold = st.number_input("大單張數門檻", value=50)
    btn_start = st.button("🚀 開始監控", use_container_width=True)

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
    # 這裡加入一個保護，確保 Client 存在
    try:
        client = WebsocketClient(api_key=API_KEY)
        stock = client.stock
        
        # 偵測方法名稱
        q_func = stock.quote if hasattr(stock, 'quote') else stock.connect_quote
        t_func = stock.trade if hasattr(stock, 'trade') else stock.connect_trade
        
        async with q_func(symbol=target) as q_conn, \
                   t_func(symbol=target) as t_conn:
            
            st.toast(f"連線成功: {target}", icon="✅")
            await asyncio.gather(handle_q(q_conn), handle_t(t_conn))
    except Exception as e:
        st.error(f"連線中斷或初始化失敗: {e}")

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
            st.session_state.history = st.session_state.history[:15]
            trade_spot.code("\n".join(st.session_state.history))

# --- 5. 啟動入口 ---
if btn_start:
    try:
        asyncio.run(main())
    except RuntimeError:
        loop = asyncio.get_event_loop()
        loop.create_task(main())
