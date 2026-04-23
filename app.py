import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime

# --- 1. 專業風格佈局 ---
st.set_page_config(page_title="富股即時監控", layout="wide")

# --- 2. 側邊欄設定 ---
st.sidebar.header("⚡ 監控設定")
raw_key = st.sidebar.text_input("Fugle API Key", type="password", help="請輸入單一段 Key，不要包含空格")
# 自動處理 Key：去除空格與換行
api_key = raw_key.strip().split(' ')[-1] if raw_key else ""

symbol = st.sidebar.text_input("代號", value="00981A").upper().strip()
refresh_rate = st.sidebar.slider("刷新頻率 (秒)", 1.0, 5.0, 2.0)

run_monitor = st.sidebar.toggle("🚀 啟動監控", value=False)

st.title(f"📊 {symbol} 行情即時追蹤")

# --- 3. 核心抓取函式 ---
def fetch_fugle_data(resource, target_symbol, key):
    # 嘗試三種最可能的路徑組合
    urls = [
        f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/{resource}/twse:{target_symbol}",
        f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/{resource}/tpex:{target_symbol}",
        f"https://api.fugle.tw/marketdata/v1/stock/intraday/{resource}?symbolId={target_symbol}&apiToken={key}"
    ]
    
    for url in urls:
        try:
            # 同時發送 Header 驗證
            headers = {"X-API-KEY": key, "Accept": "application/json"}
            res = requests.get(url, headers=headers, timeout=3)
            if res.status_code == 200:
                data = res.json()
                return data['data'].get(resource) if 'data' in data else data
        except:
            continue
    return None

# --- 4. 介面佈局 ---
col1, col2 = st.columns([2, 3])
with col1:
    st.subheader("📢 最佳五檔")
    ob_placeholder = st.empty()
with col2:
    st.subheader("⚡ 即時成交")
    qt_placeholder = st.empty()

# --- 5. 主程式 ---
if run_monitor:
    if not api_key:
        st.sidebar.warning("⚠️ 請輸入正確的 API Key")
    else:
        tick_history = []
        while run_monitor:
            ob = fetch_fugle_data("orderbook", symbol, api_key)
            qt = fetch_fugle_data("quote", symbol, api_key)

            if ob:
                asks = pd.DataFrame(ob.get('asks', [])).sort_values('price', ascending=False)
                bids = pd.DataFrame(ob.get('bids', [])).sort_values('price', ascending=False)
                if not asks.empty:
                    asks.columns, bids.columns = ['賣價', '賣量'], ['買價', '買量']
                    ob_placeholder.table(pd.concat([asks, bids], axis=0).reset_index(drop=True).style
                        .format("{:.2f}", subset=['賣價', '買價'])
                        .bar(subset=['賣量'], color='#FF4B4B').bar(subset=['買量'], color='#00C853'))
            
            if qt:
                p, v = qt.get('lastPrice'), qt.get('lastSize')
                if p:
                    new_tick = {"時間": datetime.now().strftime("%H:%M:%S"), "成交價": f"{p:.2f}", "量": int(v)}
                    if not tick_history or new_tick['時間'] != tick_history[0]['時間']:
                        tick_history.insert(0, new_tick)
                    qt_placeholder.dataframe(pd.DataFrame(tick_history[:25]), use_container_width=True)
            
            time.sleep(refresh_rate)
