import streamlit as st
import pandas as pd
import asyncio
from fugle_marketdata import WebMdaClient
import datetime

# --- 1. 頁面介面配置 ---
st.set_page_config(page_title="大戶盤口攻守雷達", layout="wide")

# CSS 樣式優化：讓表格與數據更易讀
st.markdown("""
    <style>
    .stTable { font-size: 18px !important; }
    .big-font { font-size: 24px !important; color: #ff4b4b; font-weight: bold; }
    </style>
""", unsafe_allow_html=True)

# --- 2. 密鑰讀取 (從 Streamlit Secrets) ---
try:
    API_KEY = st.secrets["FUGLE_API_KEY"]
except Exception:
    st.error("❌ 找不到 API Key，請檢查 Streamlit Secrets 是否設定為 FUGLE_API_KEY")
    st.stop()

# --- 3. 側邊欄設定 ---
with st.sidebar:
    st.title("⚡ 監控設定")
    target_stock = st.text_input("股票代號", value="3042")
    large_order_limit = st.number_input("大單門檻 (張)", value=50)
    st.divider()
    st.write("操作說明：")
    st.write("1. 確認 GitHub 已存檔")
    st.write("2. 點擊下方按鈕啟動連線")

# --- 4. 主畫面佈局 ---
st.title(f"📈 {target_stock} 即時盤口監控")

col_left, col_right = st.columns([1, 1])

with col_left:
    st.subheader("🛡️ 五檔即時掛單")
    orderbook_placeholder = st.empty() # 用來動態更新五檔

with col_right:
    st.subheader("⚔️ 大戶成交明細")
    trade_log_placeholder = st.empty() # 用來動態更新成交

# --- 5. WebSocket 數據處理核心 ---

# 初始化 session_state 用來存放成交紀錄
if 'trade_history' not in st.session_state:
    st.session_state.trade_history = []

async def run_market_data():
    client = WebMdaClient(api_key=API_KEY)
    stock = client.stock
    
    # 同時訂閱「五檔」與「成交」
    async with stock.connect_quote(symbol=target_stock) as quote_conn, \
               stock.connect_trade(symbol=target_stock) as trade_conn:
        
        # 併發執行兩個監聽任務
        await asyncio.gather(
            handle_quote(quote_conn),
            handle_trade(trade_conn)
        )

async def handle_quote(conn):
    """處理五檔變動 (偵測抽單)"""
    async for message in conn:
        if message['event'] == 'data':
            data = message['data']
            bids = data.get('bids', [])
            asks = data.get('asks', [])
            
            # 整理五檔表格數據
            # 買盤取前五，賣盤取前五
            df_display = pd.DataFrame({
                "買張": [b.get('size') for b in bids[:5]],
                "買價": [b.get('price') for b in bids[:5]],
                "賣價": [a.get('price') for a in asks[:5]],
                "賣張": [a.get('size') for a in asks[:5]]
            })
            orderbook_placeholder.table(df_display)

async def handle_trade(conn):
    """處理即時成交 (追蹤大戶)"""
    async for message in conn:
        if message['event'] == 'data':
            data = message['data']
            p = data.get('price')
            v = data.get('size')
            t = datetime.datetime.now().strftime("%H:%M:%S")
            
            # 判斷大單邏輯
            prefix = "🔴 [大單] " if v >= large_order_limit else "⚪ [成交] "
            log_entry = f"{prefix} {t} | 價格: {p} | 張數: {v}"
            
            # 更新紀錄清單
            st.session_state.trade_history.insert(0, log_entry)
            st.session_state.trade_history = st.session_state.trade_history[:20] # 僅保留最近 20 筆
            
            # 渲染到畫面上
            trade_log_placeholder.code("\n".join(st.session_state.trade_history))

# --- 6. 啟動按鈕 ---
if st.sidebar.button("🚀 啟動即時監控"):
    try:
        asyncio.run(run_market_data())
    except Exception as e:
        st.error(f"連線中斷或發生錯誤: {e}")
