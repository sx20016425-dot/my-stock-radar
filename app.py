import streamlit as st
import pandas as pd
import asyncio
import datetime
import sys

# --- 1. 導入校正 (大小寫與成員清單匹配) ---
try:
    from fugle_marketdata import WebSocketClient
except ImportError:
    st.error("❌ 找不到 WebSocketClient。請重啟 App 以重新安裝環境。")
    st.stop()

# --- 2. 頁面配置 ---
st.set_page_config(page_title="大戶盤口監控-完整版", layout="wide")

if "FUGLE_API_KEY" not in st.secrets:
    st.error("❌ 請在 Secrets 中設定 FUGLE_API_KEY")
    st.stop()

API_KEY = st.secrets["FUGLE_API_KEY"]

# --- 3. UI 介面 ---
st.title("📈 實時盤口監控雷達")
st.caption(f"環境: Python {sys.version.split()[0]} | SDK v2.4.1")

with st.sidebar:
    st.header("⚙️ 設定")
    target = st.text_input("代號 (例: 3042, 2330)", value="3042")
    threshold = st.number_input("大單門檻 (張)", value=50)
    btn_start = st.button("🚀 啟動監控", use_container_width=True)
    
    st.divider()
    if st.button("🧹 清空歷史"):
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

# --- 4. 核心監控邏輯 ---
async def start_monitor():
    client = WebSocketClient(api_key=API_KEY)
    stock = client.stock
    
    try:
        # 使用 v2.4.1 標準路徑
        async with stock.quote(symbol=target) as q_conn, \
                   stock.trade(symbol=target) as t_conn:
            
            st.toast(f"✅ 連線成功: {target}", icon="🚀")
            
            # 併發處理五檔與成交紀錄
            await asyncio.gather(
                update_quotes(q_conn),
                update_trades(t_conn)
            )
            
    except Exception as e:
        # --- 診斷邏輯 ---
        error_msg = str(e)
        st.error(f"❌ 連線失敗: {error_msg}")
        
        if "403" in error_msg:
            st.warning("⚠️ [診斷] 403 Forbidden: 你的 API Key 沒有 WebSocket 權限。請前往富果後台確認「行情資訊 API」是否已啟用。")
        elif "401" in error_msg:
            st.warning("⚠️ [診斷] 401 Unauthorized: API Key 無效。請檢查 Secrets 設定是否有空格或填錯。")
        elif "1006" in error_msg:
            st.info("💡 [診斷] 1006: 連線被強制關閉。可能是非交易時段，或該代號不支持即時數據。")
        else:
            st.info("💡 提示：請確認您的帳戶已完成開戶並啟用 API 功能。")

async def update_quotes(conn):
    """處理五檔數據"""
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
    """處理成交明細"""
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

# --- 5. 執行啟動 ---
if btn_start:
    try:
        asyncio.run(start_monitor())
    except RuntimeError:
        # 針對 Streamlit 異步環境的緩衝處理
        loop = asyncio.get_event_loop()
        loop.create_task(start_monitor())
