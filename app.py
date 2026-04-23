import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime

# --- 1. 專業風格佈局 ---
st.set_page_config(page_title="富股即時監控", layout="wide")

# --- 2. 側邊欄設定 ---
st.sidebar.header("⚡ 監控設定")
input_key = st.sidebar.text_input("Fugle API Key", type="password", help="請嘗試只輸入後半段帶有 == 的部分")
# 自動清理 Key：如果使用者貼了整串，自動抓最後一段
api_key = input_key.strip().split(' ')[-1] if input_key else ""

symbol = st.sidebar.text_input("代號", value="00981A").upper().strip()
refresh_rate = st.sidebar.slider("刷新頻率 (秒)", 1.0, 5.0, 2.0)

run_monitor = st.sidebar.toggle("🚀 啟動即時監控", value=False)

st.title(f"📊 {symbol} 行情即時追蹤")
error_log = st.empty() # 用於顯示報錯訊息

# --- 3. 核心抓取函式 ---
def fetch_fugle(resource, target_symbol, key):
    # ETF (00981A) 必須強制指定 twse 市場
    url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/{resource}/twse:{target_symbol}"
    headers = {"X-API-KEY": key}
    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            return res.json()
        elif res.status_code == 401:
            error_log.error("❌ API Key 驗證失敗：請檢查 Key 是否正確（建議只填入後半段）")
        elif res.status_code == 403:
            error_log.error("❌ 權限不足：您的 Key 可能未開通此功能或額度已滿")
        else:
            error_log.warning(f"⚠️ 伺服器回傳錯誤代碼: {res.status_code}")
    except Exception as e:
        error_log.error(f"📡 連線發生異常: {e}")
    return None

# --- 4. 介面佈局 ---
col1, col2 = st.columns([2, 3])
with col1:
    st.subheader("📢 最佳五檔")
    ob_area = st.empty()
with col2:
    st.subheader("⚡ 即時成交")
    qt_area = st.empty()

# --- 5. 主程式執行 ---
if run_monitor:
    if not api_key:
        st.error("請在左側輸入 API KEY")
    else:
        tick_history = []
        while run_monitor:
            # 抓取數據
            ob_data = fetch_fugle("orderbook", symbol, api_key)
            qt_data = fetch_fugle("quote", symbol, api_key)

            # A. 渲染五檔
            if ob_data and 'bids' in ob_data:
                error_log.empty() # 成功拿到資料就清除錯誤
                asks = pd.DataFrame(ob_data['asks']).sort_values('price', ascending=False)
                bids = pd.DataFrame(ob_data['bids']).sort_values('price', ascending=False)
                if not asks.empty:
                    asks.columns, bids.columns = ['賣價', '賣量'], ['買價', '買量']
                    ob_area.table(pd.concat([asks, bids], axis=0).reset_index(drop=True).style
                        .format("{:.2f}", subset=['賣價', '買價'])
                        .bar(subset=['賣量'], color='#FF4B4B').bar(subset=['買量'], color='#00C853'))

            # B. 渲染明細
            if qt_data:
                p, v = qt_data.get('lastPrice'), qt_data.get('lastSize')
                if p:
                    new_tick = {"時間": datetime.now().strftime("%H:%M:%S"), "價格": f"{p:.2f}", "量": int(v)}
                    if not tick_history or new_tick['時間'] != tick_history[0]['時間']:
                        tick_history.insert(0, new_tick)
                    qt_area.dataframe(pd.DataFrame(tick_history[:25]), use_container_width=True)
            
            time.sleep(refresh_rate)
