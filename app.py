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
st.set_page_config(page_title="盤口監控-最終版本", layout="wide")

if "FUGLE_API_KEY" not in st.secrets:
    st.error("❌ 請在 Secrets 設定 FUGLE_API_KEY")
    st.stop()

API_KEY = st.secrets["FUGLE_API_KEY"]

# --- 3. UI 介面 ---
st.title("📈 實時盤口監控雷達")
st.caption(f"適配 2026 最新 SDK 規範")

with st.sidebar:
    st.header("⚙️ 設定")
    target = st.text_input("股票代號", value="3042")
    threshold = st.number_input("大單張數 (>=)", value=50)
    btn_start = st.button("🚀 啟動監控", use_container_width=True)
    if st.button("🧹 清空歷史"):
        st.session_state.history = []
        st.rerun()

col_left, col_right = st.columns([2, 3])
with col_left:
    st.subheader("🛡️ 即時五檔")
    book_ui = st.empty()
with col_right:
    st.subheader("⚔️ 大戶成交")
    trade_ui = st.empty()

if 'history' not in st.session_state:
    st.session_state.history = []

# --- 4. 核心邏輯 (最新鏈式調用寫法) ---
async def start_monitor():
    client = WebSocketClient(api_key=API_KEY)
    
    try:
        # 2026 最新規範：
        # 使用 client.stock.quote.subscribe(symbol) 先訂閱
        # 再使用 async with 進行連線
        quote_stream = client.stock.quote.subscribe(target)
        trade_stream = client.stock.trade.subscribe(target)
        
        async with quote_stream as q_conn, trade_stream as t_conn:
            st.toast(f"✅ 連線成功: {target}", icon="🚀")
            
            await asyncio.gather(
                update_quotes(q_conn),
                update_trades(t_conn)
            )
            
    except Exception as e:
        # 如果上述鏈式調用仍不支援，則使用最原始的「全手動」模式
        st.error(f"❌ SDK 呼叫失敗: {e}")
        st.info("💡 嘗試切換至相容模式...")
        try:
            # 備援：部分版本將 subscribe 放在 stock 底下
            async with client.stock.subscribe(target, type='quote') as q_conn:
                await update_quotes(q_conn)
        except:
            st.warning("⚠️ 您的 SDK 版本可能與代碼不匹配，請檢查 requirements.txt 是否為 fugle-marketdata==2.4.1")

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
            log = f"{icon} {t} | 價: {p} | 量: {v}"
            st.session_state.history.insert(0, log)
            st.session_state.history = st.session_state.history[:20]
            trade_ui.code("\n".join(st.session_state.history))

# --- 5. 啟動 ---
if btn_start:
    try:
        asyncio.run(start_monitor())
    except RuntimeError:
        loop = asyncio.get_event_loop()
        loop.create_task(start_monitor())
