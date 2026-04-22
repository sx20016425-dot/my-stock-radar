import streamlit as st
import pandas as pd
import asyncio
import datetime
import fugle_marketdata

# --- 超強相容性導入邏輯 ---
# 自動偵測富果 SDK 提供的 Client 名稱
def get_client():
    if hasattr(fugle_marketdata, 'WebsocketClient'):
        return fugle_marketdata.WebsocketClient
    elif hasattr(fugle_marketdata, 'WebMdaClient'):
        return fugle_marketdata.WebMdaClient
    elif hasattr(fugle_marketdata, 'RestClient'):
        return fugle_marketdata.RestClient
    else:
        # 如果都找不到，列出所有可用屬性供除錯
        st.error(f"找不到可用的 Client。套件內含屬性：{dir(fugle_marketdata)}")
        st.stop()

MyClient = get_client()

# --- 介面配置 ---
st.set_page_config(page_title="大戶盤口監控-穩定版", layout="wide")

if "FUGLE_API_KEY" not in st.secrets:
    st.error("❌ 請在 Secrets 設定 FUGLE_API_KEY")
    st.stop()

API_KEY = st.secrets["FUGLE_API_KEY"]

st.title("📈 實時盤口監控")

with st.sidebar:
    target = st.text_input("輸入代號 (例如 3042)", value="3042")
    threshold = st.number_input("大單門檻 (張)", value=50)
    btn = st.button("🚀 開始啟動")

col1, col2 = st.columns(2)
with col1:
    st.subheader("🛡️ 五檔委託")
    book_ui = st.empty()
with col2:
    st.subheader("⚔️ 成交明細")
    trade_ui = st.empty()

if 'logs' not in st.session_state:
    st.session_state.logs = []

# --- 數據處理核心 ---
async def run_app():
    client = MyClient(api_key=API_KEY)
    stock = client.stock
    
    # 自動偵測連線方法名稱 (新版為 quote/trade, 舊版為 connect_quote/connect_trade)
    q_func = stock.quote if hasattr(stock, 'quote') else stock.connect_quote
    t_func = stock.trade if hasattr(stock, 'trade') else stock.connect_trade
    
    try:
        async with q_func(symbol=target) as q_conn, \
                   t_func(symbol=target) as t_conn:
            
            st.toast(f"✅ 連線成功: {target}", icon="🚀")
            await asyncio.gather(handle_q(q_conn), handle_t(t_conn))
            
    except Exception as e:
        st.error(f"運行中斷: {e}")

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
            icon = '🔥' if v >= threshold else '⚪'
            log = f"{icon} {t} | 價: {p} | 量: {v}"
            st.session_state.logs.insert(0, log)
            trade_ui.code("\n".join(st.session_state.logs[:15]))

if btn:
    asyncio.run(run_app())
