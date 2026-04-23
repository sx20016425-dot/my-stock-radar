import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime

# --- 1. 專業風格佈局 (保留 2:3 配置) ---
st.set_page_config(page_title="富果極速監控", layout="wide")
st.markdown("<style>.stTable {font-size: 1.1rem !important;}</style>", unsafe_allow_html=True)

# --- 2. 側邊欄控制 ---
st.sidebar.header("⚡ 監控設定")
# 建議將 API KEY 放在 Streamlit Secrets 中：FUGLE_API_KEY
default_key = st.secrets.get("FUGLE_API_KEY", "")
api_key = st.sidebar.text_input("Fugle API Key", value=default_key, type="password")
symbol = st.sidebar.text_input("股票/ETF 代碼", value="00981A").upper().strip()
refresh_rate = st.sidebar.slider("刷新間隔 (秒)", 1.0, 5.0, 2.0)

run_monitor = st.sidebar.toggle("🚀 啟動即時監控", value=False)

st.title(f"📊 {symbol} 行情即時追蹤")

# --- 3. 核心抓取函式 (相容多版本) ---
def fetch_data(resource, target_symbol, key):
    """
    自動適應 V1.0 與 V1 結構
    """
    # 測試路徑：先測 V1.0 (新版)，再測 V1 (舊版)
    # V1.0 格式需要加上市場別，這裡先嘗試 twse (ETF 通常在 twse)
    urls = [
        f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/{resource}/twse:{target_symbol}",
        f"https://api.fugle.tw/marketdata/v1/stock/intraday/{resource}?symbolId={target_symbol}&apiToken={key}"
    ]
    
    for url in urls:
        try:
            headers = {"X-API-KEY": key}
            res = requests.get(url, headers=headers, timeout=3)
            if res.status_code == 200:
                json_data = res.json()
                # 判斷是否為 V1 結構 (包在 data 裡)
                if 'data' in json_data:
                    return json_data['data'].get(resource)
                return json_data
        except:
            continue
    return None

# --- 4. 介面佈局 ---
col1, col2 = st.columns([2, 3])
with col1:
    st.subheader("📢 最佳五檔 (Orderbook)")
    orderbook_area = st.empty()
with col2:
    st.subheader("⚡ 即時成交明細 (Ticks)")
    details_area = st.empty()

# --- 5. 執行監控 ---
if run_monitor:
    if not api_key:
        st.sidebar.error("❌ 尚未輸入 API KEY")
    else:
        tick_history = []
        status_info = st.sidebar.empty()
        
        while run_monitor:
            # 同步獲取數據
            ob = fetch_data("orderbook", symbol, api_key)
            qt = fetch_data("quote", symbol, api_key)

            # --- A. 處理五檔 ---
            if ob and ('bids' in ob or 'asks' in ob):
                status_info.success(f"📡 連線正常: {datetime.now().strftime('%H:%M:%S')}")
                # 取得買賣單並確保排序
                df_asks = pd.DataFrame(ob.get('asks', [])).sort_values('price', ascending=False).head(5)
                df_bids = pd.DataFrame(ob.get('bids', [])).sort_values('price', ascending=True).tail(5).iloc[::-1]
                
                if not df_asks.empty or not df_bids.empty:
                    df_asks.columns, df_bids.columns = ['賣價', '賣量'], ['買價', '買量']
                    orderbook_area.table(
                        pd.concat([df_asks, df_bids], axis=0).reset_index(drop=True).style
                        .format("{:.2f}", subset=['賣價', '買價'])
                        .bar(subset=['賣量'], color='#FF4B4B', vmin=0)
                        .bar(subset=['買量'], color='#00C853', vmin=0)
                    )
            else:
                orderbook_area.warning("⚠️ 找不到五檔數據，請確認代號或 API 權限")

            # --- B. 處理成交 ---
            if qt:
                p, v = qt.get('lastPrice'), qt.get('lastSize')
                if p:
                    new_tick = {
                        "時間": datetime.now().strftime("%H:%M:%S"),
                        "成交價": f"{p:.2f}",
                        "單量": int(v)
                    }
                    # 偵測變動才更新 UI
                    if not tick_history or (new_tick['成交價'] != tick_history[0]['成交價'] or new_tick['量'] != tick_history[0]['量']):
                        tick_history.insert(0, new_tick)
                    details_area.dataframe(pd.DataFrame(tick_history[:25]), use_container_width=True)
            
            time.sleep(refresh_rate)
else:
    st.info("👈 請開啟側邊欄的『啟動監控』開關。")
