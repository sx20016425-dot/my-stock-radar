import streamlit as st
import pandas as pd
import asyncio
import datetime

# --- 環境自檢與導入 ---
try:
    from fugle_marketdata import WebMdaClient
except ImportError:
    st.error("🚨 套件安裝失敗！請確認 requirements.txt 檔名為全小寫，並包含 fugle-marketdata")
    st.info("💡 建議動作：點擊右下角 Manage app -> ... -> Reboot app")
    st.stop()

# --- 1. 頁面配置 ---
st.set_page_config(page_title="極速盤口監控", layout="wide")

# --- 2. 讀取 Secrets ---
if "FUGLE_API_KEY" not in st.secrets:
    st.error("❌ 找不到 API Key。請在 Streamlit Cloud 的 Secrets 設定 FUGLE_API_KEY")
    st.stop()

API_KEY = st.secrets["FUGLE_API_KEY"]

# --- 3. UI 佈局 ---
st.sidebar.title("⚡ 監控設定")
target = st.sidebar.text_input("股票/期貨代號", value="2330")
threshold = st.sidebar.number_input("大單門檻 (張)", value=50)

st.title(f"🚀 {target} 實時盤口雷達")
col1, col2 = st.columns(2)

with col1:
    st.subheader("🛡️ 五檔委託")
    book_spot = st.empty()

with col2:
    st.subheader("⚔️ 成交明細")
    trade_spot = st.empty()

if 'history' not in st.session_state:
    st.session_state.history = []

# --- 4. 數據處理核心 ---
async def start_wss():
    client = WebMdaClient(api_key=API_KEY)
    stock = client.stock
    
    # 建立連線任務
    async with stock.connect_quote(symbol=target) as q_conn, \
               stock.connect_trade(symbol=target) as t_conn:
        
        await asyncio.gather(
            handle_q(q_conn),
            handle_t(t_conn)
        )

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
            book_spot.table(df)

async def handle_t(conn):
    async for msg in conn:
        if msg.get('event') == 'data':
            d = msg['data']
            p, v = d.get('price'), d.get('size')
            now = datetime.datetime.now().strftime("%H:%M:%S")
            log = f"{'🔴' if v >= threshold else '⚪'} {now} | 價: {p} | 量: {v}"
            st.session_state.history.insert(0, log)
            trade_spot.code("\n".join(st.session_state.history[:15]))

# --- 5. 啟動按鈕 ---
if st.sidebar.button("開始監控"):
    asyncio.run(start_wss())
