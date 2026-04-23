import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime

# --- 1. 介面設定 (保留專業佈局) ---
st.set_page_config(page_title="富果極速監控", layout="wide")
st.markdown("<style>.stTable {font-size: 1.1rem !important;}</style>", unsafe_allow_html=True)

# --- 2. 側邊欄設定 ---
st.sidebar.header("⚡ 監控設定")
default_key = st.secrets.get("FUGLE_API_KEY", "")
api_key = st.sidebar.text_input("Fugle API Key", value=default_key, type="password")
symbol = st.sidebar.text_input("股票代號", value="2330")
refresh_rate = st.sidebar.slider("刷新間隔 (秒)", 0.5, 5.0, 1.0, step=0.1)

# 使用 Toggle 開關取代 Button，這在 Streamlit 中處理長時迴圈更穩定
run_monitor = st.sidebar.toggle("🚀 啟動監控", value=False)

st.title(f"📊 {symbol} 即時行情監控")

# --- 3. 診斷與路徑設定 ---
@st.cache_data(ttl=600)
def get_valid_market(target_symbol, key):
    """測試上市或上櫃路徑是否有效"""
    for mkt in ["twse", "tpex"]:
        url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{mkt}:{target_symbol}"
        try:
            r = requests.get(url, headers={"X-API-KEY": key}, timeout=3)
            if r.status_code == 200: return mkt
        except: continue
    return None

# --- 4. 介面佈局 ---
col1, col2 = st.columns([2, 3])
with col1:
    st.subheader("📢 最佳五檔")
    orderbook_area = st.empty()
with col2:
    st.subheader("⚡ 即時成交")
    details_area = st.empty()

# --- 5. 主執行邏輯 ---
if run_monitor:
    if not api_key:
        st.sidebar.error("❌ 請先輸入 API KEY")
    else:
        # 第一步：偵測市場 (twse 或 tpex)
        market = get_valid_market(symbol, api_key)
        
        if not market:
            st.sidebar.error(f"❌ 找不到 {symbol} 的資料，請確認代號正確或已開盤")
        else:
            st.sidebar.success(f"✅ 已連線至 {market.upper()}")
            tick_history = []
            
            # 使用 Session 提升速度
            session = requests.Session()
            session.headers.update({"X-API-KEY": api_key})

            # 進入監控迴圈
            while run_monitor:
                try:
                    # 同步抓取五檔與行情
                    base_url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday"
                    ob_res = session.get(f"{base_url}/orderbook/{market}:{symbol}", timeout=2)
                    qt_res = session.get(f"{base_url}/quote/{market}:{symbol}", timeout=2)

                    # 渲染五檔
                    if ob_res.status_code == 200:
                        ob = ob_res.json()
                        df_asks = pd.DataFrame(ob['asks']).sort_values('price', ascending=False)
                        df_bids = pd.DataFrame(ob['bids']).sort_values('price', ascending=False)
                        df_asks.columns, df_bids.columns = ['賣價', '賣量'], ['買價', '買量']
                        
                        orderbook_area.table(
                            pd.concat([df_asks, df_bids], axis=0).reset_index(drop=True).style
                            .format("{:.2f}", subset=['賣價', '買價'])
                            .bar(subset=['賣量'], color='#FF4B4B', vmin=0)
                            .bar(subset=['買量'], color='#00C853', vmin=0)
                        )

                    # 渲染成交明細
                    if qt_res.status_code == 200:
                        quote = qt_res.json()
                        p, v = quote.get('lastPrice'), quote.get('lastSize')
                        if p:
                            new_tick = {
                                "時間": datetime.now().strftime("%H:%M:%S"),
                                "成交價": f"{p:.2f}",
                                "量": int(v)
                            }
                            # 只有當資料真的變動時才更新 UI，節省效能
                            if not tick_history or (new_tick['成交價'] != tick_history[0]['成交價'] or new_tick['量'] != tick_history[0]['量']):
                                tick_history.insert(0, new_tick)
                            details_area.dataframe(pd.DataFrame(tick_history[:25]), use_container_width=True)

                except Exception as e:
                    # 發生錯誤時在側邊欄靜默提示，不中斷程式
                    st.sidebar.warning(f"連線不穩: {str(e)[:20]}...")
                
                # 關鍵：這會讓 Streamlit 重新檢查 Toggle 狀態並刷新畫面
                time.sleep(refresh_rate)
else:
    st.info("👈 請在側邊欄點擊『啟動監控』開關以開始追蹤行情。")
