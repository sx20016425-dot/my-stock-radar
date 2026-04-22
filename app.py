import streamlit as st
import pandas as pd
import asyncio
from fugle_marketdata import WebMdaClient
import datetime

# --- 1. 頁面配置 ---
st.set_page_config(page_title="大戶盤口攻守雷達", layout="wide", initial_sidebar_state="expanded")

# 自定義 CSS 讓介面更像專業看盤軟體
st.markdown("""
    <style>
    .reportview-container { background: #0e1117; }
    .stMetric { background-color: #1f2937; padding: 10px; border-radius: 10px; border: 1px solid #374151; }
    .big-font { font-size:20px !important; font-weight: bold; }
    </style>
""", unsafe_allow_html=True)

# --- 2. 讀取密鑰 ---
try:
    API_KEY = st.secrets["FUGLE_API_KEY"]
except Exception:
    st.error("❌ 找不到 API Key，請檢查 Streamlit Secrets 設定。")
    st.stop()

# --- 3. 側邊欄：監控參數 ---
with st.sidebar:
    st.title("🛡️ 監控設定")
    target_stock = st.text_input("股票代號", value="3042")
    large_order_limit = st.number_input("大單成交門檻 (張)", value=50)
    st.divider()
    st.info("💡 建議同時觀察台指期趨勢，當台指急拉且個股賣單抽單時，通常是發動訊號。")

# --- 4. 主畫面佈局 ---
# 頂部即時狀態
head_col1, head_col2, head_col3 = st.columns(3)
with head_col1:
    index_placeholder = st.empty() # 台指期顯示區
with head_col2:
    stock_price_placeholder = st.empty() # 個股現價顯示區
with head_col3:
    st.metric("監控狀態", "運作中", delta="Real-time")

st.divider()

col_left, col_right = st.columns([1, 1])

with col_left:
    st.subheader("📊 五檔掛單 (偵測抽單)")
    orderbook_placeholder = st.empty()
    alert_placeholder = st.container()

with col_right:
    st.subheader("⚔️ 即時成交紀錄 (大戶追蹤)")
    trade_log_placeholder = st.empty()

# --- 5. 數據處理核心 ---
if 'trade_history' not in st.session_state:
    st.session_state.trade_history = []

async def start_monitor():
    client = WebMdaClient(api_key=API_KEY)
    stock = client.stock
    
    # 同時訂閱行情與成交明細
    async with stock.connect_quote(symbol=target_stock) as quote_conn, \
               stock.connect_trade(symbol=target_stock) as trade_conn:
        
        # 建立併發任務
        quote_task = asyncio.create_task(handle_quotes(quote_conn))
        trade_task = asyncio.create_task(handle_trades(trade_conn))
        
        await asyncio.gather(quote_task, trade_task)

async def handle_quotes(conn):
    """處理五檔數據"""
    async for message in conn:
        if message['event'] == 'data':
            data = message['data']
            bids = data.get('bids', [])
            asks = data.get('asks', [])
            
            # 轉換為 DataFrame 顯示
            df_bids = pd.DataFrame(bids).head(5)
            df_asks = pd.DataFrame(asks).head(5)
            
            # 整理出對應的五檔表格
            display_df = pd.DataFrame({
                "買張": df_bids['size'] if not df_bids.empty else [],
                "買價": df_bids['price'] if not df_bids.empty else [],
                "賣價": df_asks['price'] if not df_asks.empty else [],
                "賣張": df_asks['size'] if not df_asks.empty else []
            })
            orderbook_placeholder.table(display_df)

async def handle_trades(conn):
    """處理成交明細"""
    async for message in conn:
        if message['event'] == 'data':
            data = message['data']
            p = data.get('price')
            v = data.get('size')
            t = datetime.datetime.now().strftime("%H:%M:%S")
            
            # 判斷是否為大單
            if v >= large_order_limit:
                msg = f"🔥 [{t}] 價格: {p} | 大單: {v} 張"
                st.session_state.trade_history.insert(0, msg)
            else:
                msg = f"⚪ [{t}] 價格: {p} | 成交: {v} 張"
                st.session_state.trade_history.insert(0, msg)
            
            # 保持紀錄在 15 筆以內
            st.session_state.trade_history = st.session_state.trade_history[:15]
            trade_log_placeholder.code("\n".join(st.session_state.trade_history))

# --- 6. 啟動按鈕 ---
if st.sidebar.button("🚀 開始即時監控"):
    asyncio.run(start_monitor())
else:
    st.warning("請點擊左側『開始即時監控』按鈕啟動 WebSocket 連線。")
