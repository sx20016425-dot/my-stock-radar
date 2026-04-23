import streamlit as st
import pandas as pd
import requests
import time

# --- 基礎設定 ---
st.set_page_config(page_title="富果即時狙擊手", layout="wide")

# 在 Streamlit Secrets 或 側邊欄設定 API Key
FUGLE_API_KEY = st.sidebar.text_input("輸入 Fugle API Key", type="password")
symbol = st.sidebar.text_input("股票代號", value="2330")
update_speed = st.sidebar.slider("更新頻率 (秒)", 1, 10, 2)

st.title(f"🚀 {symbol} 即時行情監控")

# --- 定義 API 抓取函式 ---
def get_fugle_data(resource, symbol):
    """
    resource: 'orderbook' (五檔) 或 'quote' (行情/明細)
    """
    url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/{resource}/{symbol}"
    headers = {"X-API-KEY": FUGLE_API_KEY}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json()
    return None

# --- UI 佈局 ---
col1, col2 = st.columns([2, 3])

with col1:
    st.subheader("階梯式最佳五檔")
    orderbook_placeholder = st.empty()

with col2:
    st.subheader("⚡ 即時交易明細")
    details_placeholder = st.empty()

# --- 主監控程式 ---
if st.sidebar.button("啟動監控"):
    if not FUGLE_API_KEY:
        st.error("請先輸入 API Key！")
    else:
        # 建立一個清單記錄成交明細 (因為 Fugle Quote API 通常回傳最新一筆)
        tick_history = []

        while True:
            # 1. 抓取五檔 (Orderbook)
            ob_data = get_fugle_data("orderbook", symbol)
            # 2. 抓取成交資訊 (Quote)
            quote_data = get_fugle_data("quote", symbol)

            if ob_data and quote_data:
                # --- 處理五檔表格 ---
                # 取得 bids (買) 與 asks (賣)
                bids = pd.DataFrame(ob_data['bids'])
                asks = pd.DataFrame(ob_data['asks']).sort_values('price', ascending=False)
                
                # 合併五檔顯示 (賣在上，買在下)
                asks.columns = ['賣價', '賣量']
                bids.columns = ['買價', '買量']
                orderbook_df = pd.concat([asks, bids], axis=0).reset_index(drop=True)
                
                orderbook_placeholder.table(orderbook_df.style.format({"賣價": "{:.2f}", "買價": "{:.2f}"})
                                           .bar(subset=['賣量'], color='#ff4b4b')
                                           .bar(subset=['買量'], color='#00c853'))

                # --- 處理交易明細 ---
                last_trial = quote_data.get('lastTrial', {}) # 最近一次撮合
                new_tick = {
                    "時間": time.strftime("%H:%M:%S"),
                    "成交價": quote_data.get('lastPrice'),
                    "成交量": quote_data.get('lastSize'),
                    "單筆金額": round(quote_data.get('lastPrice', 0) * quote_data.get('lastSize', 0) * 1000, 0)
                }
                
                # 簡單去重，若價格與量沒變就不重複累加 (這只是簡易邏輯)
                if not tick_history or new_tick['成交量'] != tick_history[0]['成交量']:
                    tick_history.insert(0, new_tick)

                details_placeholder.dataframe(pd.DataFrame(tick_history[:20]), use_container_width=True)

            time.sleep(update_speed)
            # st.rerun() # 在某些版本的 Streamlit 中需要此行強制刷新
