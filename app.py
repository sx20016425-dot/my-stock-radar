import streamlit as st
import pandas as pd
import asyncio
from fugle_marketdata import WebMdaClient

# 介面設定
st.set_page_config(page_title="極速盤口雷達", layout="wide")

# 從 Secrets 讀取 Key
API_KEY = st.secrets["FUGLE_API_KEY"]

# 側邊欄設定
st.sidebar.title("⚡ 實時監控設定")
symbol = st.sidebar.text_input("輸入股票代號", value="3042")
volume_threshold = st.sidebar.number_input("大單警示張數", value=50)

# 建立顯示區塊
header = st.empty()
col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("🛡️ 五檔即時掛單 (抽單偵測)")
    order_book_view = st.empty()
    alert_view = st.empty()

with col2:
    st.subheader("⚔️ 瞬間成交明細 (大戶追蹤)")
    trade_log_view = st.empty()

# --- WebSocket 數據處理核心 ---
async def main():
    client = WebMdaClient(api_key=API_KEY)
    stock = client.stock
    
    # 建立一個存放紀錄的 list
    if 'trades' not in st.session_state:
        st.session_state.trades = []

    # 訂閱五檔 (Quotes) 與 成交 (Trades)
    async with stock.connect_quote(symbol=symbol) as quote_conn, \
               stock.connect_trade(symbol=symbol) as trade_conn:
        
        async for message in quote_conn:
            # 這裡處理五檔變動邏輯
            data = message.get('data', {})
            bids = data.get('bids', [])
            asks = data.get('asks', [])
            
            # 視覺化呈現五檔
            df_book = pd.DataFrame({
                "買進": [b.get('price') for b in bids[:5]],
                "買張": [b.get('size') for b in bids[:5]],
                "賣張": [a.get('size') for a in asks[:5]],
                "賣出": [a.get('price') for a in asks[:5]]
            })
            order_book_view.table(df_book)
            
            # 偵測抽單：如果第一檔賣張突然減少超過門檻
            # (此處需比對前一筆 message 邏輯)
            
        async for trade in trade_conn:
            # 處理成交大單
            t_data = trade.get('data', {})
            price = t_data.get('price')
            size = t_data.get('size')
            if size >= volume_threshold:
                log_msg = f"🚩 大單成交！價格: {price} | 張數: {size}"
                st.session_state.trades.insert(0, log_msg)
                trade_log_view.write("\n".join(st.session_state.trades[:10]))

# 執行監控
if st.sidebar.button("開啟極速監控"):
    asyncio.run(main())
