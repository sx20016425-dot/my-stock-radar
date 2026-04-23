import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime

# --- 1. 介面設定 ---
st.set_page_config(page_title="富果極速監控", layout="wide")
st.markdown("<style>.stTable {font-size: 1.1rem !important;}</style>", unsafe_allow_html=True)

# --- 2. 側邊欄設定 ---
st.sidebar.header("⚡ 監控設定")
default_key = st.secrets.get("FUGLE_API_KEY", "")
api_key = st.sidebar.text_input("Fugle API Key", value=default_key, type="password")
# 將輸入自動轉為大寫，避免 00981a 抓不到
symbol = st.sidebar.text_input("股票/ETF 代號", value="00981A").upper().strip()
refresh_rate = st.sidebar.slider("刷新間隔 (秒)", 1.0, 5.0, 2.0, step=0.5)

run_monitor = st.sidebar.toggle("🚀 啟動監控", value=False)

st.title(f"📊 {symbol} 即時行情監控")

# --- 3. 強化版偵測函式 ---
@st.cache_data(ttl=600)
def get_valid_market_path(target_symbol, key):
    """
    針對 ETF 與一般股進行市場別交叉偵測
    """
    # 測試順序：上市(含ETF) -> 上櫃
    test_markets = ["twse", "tpex"]
    headers = {"X-API-KEY": key}
    
    for mkt in test_markets:
        # Fugle V1.0 標準路徑
        url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{mkt}:{target_symbol}"
        try:
            r = requests.get(url, headers=headers, timeout=3)
            if r.status_code == 200:
                return mkt
        except:
            continue
    return None

# --- 4. 介面佈局 (保留 2:3 專業配置) ---
col1, col2 = st.columns([2, 3])
with col1:
    st.subheader("📢 最佳五檔 (Orderbook)")
    orderbook_area = st.empty()
with col2:
    st.subheader("⚡ 即時成交明細 (Ticks)")
    details_area = st.empty()

# --- 5. 主執行邏輯 ---
if run_monitor:
    if not api_key:
        st.sidebar.error("❌ 請輸入 API KEY")
    else:
        # 進行市場偵測
        market = get_valid_market_path(symbol, api_key)
        
        if not market:
            st.sidebar.error(f"❌ 找不到 {symbol}。提示：ETF 請確保代號正確，且目前為開盤時間。")
        else:
            st.sidebar.success(f"✅ 連線成功: {market.upper()}")
            tick_history = []
            session = requests.Session()
            session.headers.update({"X-API-KEY": api_key})

            while run_monitor:
                try:
                    # 統一呼叫 API
                    ob_url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/orderbook/{market}:{symbol}"
                    qt_url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{market}:{symbol}"
                    
                    ob_res = session.get(ob_url, timeout=2)
                    qt_res = session.get(qt_url, timeout=2)

                    # A. 渲染五檔
                    if ob_res.status_code == 200:
                        ob = ob_res.json()
                        df_asks = pd.DataFrame(ob.get('asks', [])).sort_values('price', ascending=False)
                        df_bids = pd.DataFrame(ob.get('bids', [])).sort_values('price', ascending=False)
                        
                        if not df_asks.empty or not df_bids.empty:
                            df_asks.columns, df_bids.columns = ['賣價', '賣量'], ['買價', '買量']
                            orderbook_area.table(
                                pd.concat([df_asks, df_bids], axis=0).reset_index(drop=True).style
                                .format("{:.2f}", subset=['賣價', '買價'])
                                .bar(subset=['賣量'], color='#FF4B4B', vmin=0)
                                .bar(subset=['買量'], color='#00C853', vmin=0)
                            )
                        else:
                            orderbook_area.info("暫無五檔掛單資料")

                    # B. 渲染成交
                    if qt_res.status_code == 200:
                        quote = qt_res.json()
                        p = quote.get('lastPrice')
                        v = quote.get('lastSize')
                        if p is not None:
                            new_tick = {
                                "時間": datetime.now().strftime("%H:%M:%S"),
                                "成交價": f"{p:.2f}",
                                "量": int(v)
                            }
                            # 偵測變動才更新
                            if not tick_history or (new_tick['成交價'] != tick_history[0]['成交價'] or new_tick['量'] != tick_history[0]['量']):
                                tick_history.insert(0, new_tick)
                            details_area.dataframe(pd.DataFrame(tick_history[:25]), use_container_width=True)

                except Exception as e:
                    st.sidebar.warning("連線重試中...")
                
                time.sleep(refresh_rate)
else:
    st.info("👈 請開啟側邊欄的『啟動監控』開關。")
