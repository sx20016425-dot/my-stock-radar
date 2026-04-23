import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime

# --- 1. 介面與樣式 ---
st.set_page_config(page_title="富果極速監控-診斷版", layout="wide")
st.markdown("<style>.stTable {font-size: 1.1rem !important;}</style>", unsafe_allow_html=True)

# --- 2. 側邊欄與 API Key 檢查 ---
st.sidebar.header("⚡ 監控設定")
# 優先嘗試 secrets，沒有就留空
default_key = st.secrets.get("FUGLE_API_KEY", "")
api_key = st.sidebar.text_input("Fugle API Key", value=default_key, type="password")
symbol = st.sidebar.text_input("股票/ETF 代號", value="2330").upper().strip()
refresh_rate = st.sidebar.slider("刷新間隔 (秒)", 1.0, 5.0, 2.0)

run_monitor = st.sidebar.toggle("🚀 啟動監控", value=False)

st.title(f"📊 {symbol} 即時行情監控")

# --- 3. 核心抓取函式 (加入強制診斷) ---
def fetch_raw_data(resource, mkt, target_symbol):
    """
    直接發送請求並回傳原始結果與狀態碼
    """
    # 這是 Fugle V1.0 最標準的正式路徑格式
    url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/{resource}/{mkt}:{target_symbol}"
    headers = {"X-API-KEY": api_key}
    try:
        res = requests.get(url, headers=headers, timeout=5)
        return res.status_code, res.json() if res.status_code == 200 else res.text
    except Exception as e:
        return 999, str(e)

# --- 4. 介面佈局 ---
col1, col2 = st.columns([2, 3])
with col1:
    st.subheader("📢 最佳五檔")
    orderbook_area = st.empty()
with col2:
    st.subheader("⚡ 成交明細")
    details_area = st.empty()

# --- 5. 執行監控與診斷 ---
if run_monitor:
    if not api_key:
        st.error("❌ 尚未輸入 API KEY")
    else:
        # 初始診斷：先確認 2330 能不能抓到市場
        with st.spinner("正在診斷連線狀態..."):
            mkt_found = None
            for m in ["twse", "tpex"]:
                code, _ = fetch_raw_data("quote", m, symbol)
                if code == 200:
                    mkt_found = m
                    break
            
            if not mkt_found:
                # 診斷失敗，印出詳細原因
                test_code, test_msg = fetch_raw_data("quote", "twse", symbol)
                st.error(f"❌ 無法連線至 Fugle API")
                st.info(f"診斷訊息：狀態碼 {test_code}")
                st.code(test_msg) # 這會印出 Fugle 官方的回應，例如 "Invalid API Key" 或 "Quota Exceeded"
                st.stop()
            
            st.sidebar.success(f"✅ 連線成功：市場 {mkt_found.upper()}")
            
        # 進入監控迴圈
        tick_history = []
        session = requests.Session()
        session.headers.update({"X-API-KEY": api_key})

        while run_monitor:
            # 抓取五檔
            ob_code, ob_data = fetch_raw_data("orderbook", mkt_found, symbol)
            # 抓取成交
            qt_code, qt_data = fetch_raw_data("quote", mkt_found, symbol)

            if ob_code == 200:
                df_asks = pd.DataFrame(ob_data.get('asks', [])).sort_values('price', ascending=False)
                df_bids = pd.DataFrame(ob_data.get('bids', [])).sort_values('price', ascending=False)
                if not df_asks.empty:
                    df_asks.columns, df_bids.columns = ['賣價', '賣量'], ['買價', '買量']
                    orderbook_area.table(
                        pd.concat([df_asks, df_bids], axis=0).reset_index(drop=True).style
                        .format("{:.2f}", subset=['賣價', '買價'])
                        .bar(subset=['賣量'], color='#FF4B4B', vmin=0).bar(subset=['買量'], color='#00C853', vmin=0)
                    )

            if qt_code == 200:
                p, v = qt_data.get('lastPrice'), qt_data.get('lastSize')
                if p:
                    new_tick = {"時間": datetime.now().strftime("%H:%M:%S"), "成交價": f"{p:.2f}", "量": int(v)}
                    if not tick_history or (new_tick['成交價'] != tick_history[0]['成交價'] or new_tick['量'] != tick_history[0]['量']):
                        tick_history.insert(0, new_tick)
                    details_area.dataframe(pd.DataFrame(tick_history[:25]), use_container_width=True)
            
            time.sleep(refresh_rate)
