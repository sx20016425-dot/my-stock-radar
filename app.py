import streamlit as st
import pandas as pd
import asyncio
import datetime
import sys
import subprocess

# --- 1. 自動修復 ImportError 的保護機制 ---
try:
    import fugle_marketdata
    from fugle_marketdata import WebsocketClient
except ImportError:
    # 如果系統沒裝好，我們在啟動時強制再裝一次 (針對 Python 3.14 優化)
    st.warning("正在嘗試自動修復套件環境，請稍候...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "fugle-marketdata==2.4.1"])
    st.rerun()

# --- 2. 頁面配置與祕鑰檢查 ---
st.set_page_config(page_title="大戶盤口監控-終極版", layout="wide")

if "FUGLE_API_KEY" not in st.secrets:
    st.error("❌ 找不到 API Key。請在 Streamlit Cloud 的 Secrets 設定 FUGLE_API_KEY")
    st.stop()

API_KEY = st.secrets["FUGLE_API_KEY"]

# --- 3. UI 介面設計 ---
st.title("🚀 實時盤口大單監控雷達")
st.caption("適配 Python 3.11-3.14 | Fugle SDK v2.4.1")

with st.sidebar:
    st.header("📊 監控設定")
    target = st.text_input("股票/期貨代號", value="3042", help="例如 2330, 3042")
    threshold = st.number_input("大單張數門檻", value=50, step=10)
    btn_start = st.button("🔥 開始啟動監控", use_container_width=True)
    
    if st.button("🧹 清除紀錄"):
        st.session_state.history = []
        st.rerun()

col_left, col_right = st.columns([2, 3])
with col_left:
    st.subheader("🛡️ 即時五檔")
    book_spot = st.empty()
with col_right:
    st.subheader("⚔️ 大戶成交流")
    trade_spot = st.empty()

# 初始化 Session State
if 'history' not in st.session_state:
    st.session_state.history = []

# --- 4. 核心數據處理核心 ---
async def start_monitor():
    # 使用新版 SDK 的 WebsocketClient
    client = WebsocketClient(api_key=API_KEY)
    
    try:
        # 使用最新規範路徑 client.stock.quote 與 client.stock.trade
        async with client.stock.quote(symbol=target) as q_conn, \
                   client.stock.trade(symbol=target) as t_conn:
            
            st.toast(f"連線成功: {target}", icon="✅")
            
            # 併發執行監控
            await asyncio.gather(
                handle_quotes(q_conn),
                handle_trades(t_conn)
            )
            
    except Exception as e:
        st.error(f"連線異常: {e}")
        st.info("💡 提示：請確認您的 API Key 是否具有 WebSocket 即時權限。")

async def handle_quotes(conn):
    """處理五檔委託數據"""
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

async def handle_trades(conn):
    """處理成交明細與大單偵測"""
    async for msg in conn:
        if msg.get('event') == 'data':
            d = msg['data']
            price = d.get('price')
            size = d.get('size')
            time_str = datetime.datetime.now().strftime("%H:%M:%S")
            
            # 大單判定與圖示
            status_icon = "🔥" if size >= threshold else "⚪"
            log_entry = f"{status_icon} {time_str} | 價: {price} | 量: {size}"
            
            # 更新紀錄 (只保留最近 15 筆)
            st.session_state.history.insert(0, log_entry)
            st.session_state.history = st.session_state.history[:15]
            trade_spot.code("\n".join(st.session_state.history))

# --- 5. 啟動入口 ---
if btn_start:
    # 確保非同步迴圈在 Streamlit 中正確執行
    asyncio.run(start_monitor())
