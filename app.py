import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime

# --- 1. 專業介面配置 ---
st.set_page_config(page_title="富股即時監控", layout="wide")

# --- 2. 側邊欄設定 ---
st.sidebar.header("⚡ 監控設定")
input_key = st.sidebar.text_input("Fugle API Key", type="password")
# 自動抓取 Key 的最後一段（避免空格干擾）
api_key = input_key.strip().split(' ')[-1] if input_key else ""

symbol = st.sidebar.text_input("代號 (如 00981A)", value="00981A").upper().strip()
refresh_rate = st.sidebar.slider("刷新間隔 (秒)", 1.0, 5.0, 2.0)

run_monitor = st.sidebar.toggle("🚀 啟動即時監控", value=False)

st.title(f"📊 {symbol} 行情監控系統")
log_area = st.empty() # 訊息回報區

# --- 3. 核心抓取函式 (針對 404 修正路徑) ---
def fetch_fugle_smart(resource, target_symbol, key):
    # 對於 00981A，Fugle V1.0 的標準 ID 格式通常是 TSE:00981A
    # 這裡我們嘗試兩組最可能的 ID 格式
    test_ids = [f"TSE:{target_symbol}", f"twse:{target_symbol}"]
    
    headers = {"X-API-KEY": key}
    for tid in test_ids:
        url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/{resource}/{tid}"
        try:
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                return res.json()
            # 如果是 401 則直接報錯，不繼續測路徑
            elif res.status_code == 401:
                log_area.error("❌ API Key 驗證失敗：請確認 Key 是否正確（建議只填入後半段帶有 == 的字串）")
                return "AUTH_ERROR"
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

# --- 5. 執行監控 ---
if run_monitor:
    if not api_key:
        st.error("請在左側輸入 API KEY")
    else:
        tick_history = []
        while run_monitor:
            ob = fetch_fugle_smart("orderbook", symbol, api_key)
            qt = fetch_fugle_smart("quote", symbol, api_key)

            if ob == "AUTH_ERROR": break

            # A. 渲染五檔
            if ob and 'bids' in ob:
                log_area.success(f"📡 數據傳輸中... {datetime.now().strftime('%H:%M:%S')}")
                asks = pd.DataFrame(ob['asks']).sort_values('price', ascending=False)
                bids = pd.DataFrame(ob['bids']).sort_values('price', ascending=False)
                if not asks.empty:
                    asks.columns, bids.columns = ['賣價', '賣量'], ['買價', '買量']
                    ob_placeholder.table(pd.concat([asks, bids], axis=0).reset_index(drop=True).style
                        .format("{:.2f}", subset=['賣價', '買價'])
                        .bar(subset=['賣量'], color='#FF4B4B').bar(subset=['買量'], color='#00C853'))

            # B. 渲染明細
            if qt:
                p, v = qt.get('lastPrice'), qt.get('lastSize')
                if p:
                    new_tick = {"時間": datetime.now().strftime("%H:%M:%S"), "價格": f"{p:.2f}", "量": int(v)}
                    if not tick_history or new_tick['時間'] != tick_history[0]['時間']:
                        tick_history.insert(0, new_tick)
                    qt_placeholder.dataframe(pd.DataFrame(tick_history[:25]), use_container_width=True)
            
            time.sleep(refresh_rate)
