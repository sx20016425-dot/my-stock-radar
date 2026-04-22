import streamlit as st
import pandas as pd
import datetime
import time
import requests
import yfinance as yf

# --- 1. 專業介面配置 ---
st.set_page_config(page_title="Alpha-Trader Terminal v9.0", layout="wide", initial_sidebar_state="collapsed")

# 注入 CSS：鎖死版面，確保背景與邊框恆常存在
st.markdown("""
    <style>
    .main { background-color: #0D1117; }
    .stMetric { background: #161B22; padding: 15px; border-radius: 10px; border: 1px solid #30363D; }
    [data-testid="stMetricValue"] { font-size: 26px !important; color: #58A6FF !important; }
    .stCodeBlock { border: 1px solid #30363D !important; background-color: #010409 !important; min-height: 250px !important; }
    .block-container { padding-top: 2rem; }
    h3 { color: #8B949E; font-size: 14px !important; font-weight: 600; border-left: 3px solid #58A6FF; padding-left: 8px; margin-bottom: 15px; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 數據獲取邏輯 (帶有自動救援機制) ---
API_KEY = "MWI2Y2NlMTYtZmNjNy00NGJmLWFkMTYtNDVjZjk2MjJkNzFhIDA1YTliNzZhLWI0NzItNGYxMS1iYTIxLWYyN2ZkNjgzNzI5YQ=="

def get_price(symbol, source="fugle", is_future=False):
    """
    雙引擎驅動：優先富果，失敗自動切換 Yahoo
    """
    # 第一階段：嘗試富果
    try:
        base = "futures" if is_future else "stock"
        url = f"https://api.fugle.tw/marketdata/v1.0/{base}/snapshot/quotes/{symbol}"
        r = requests.get(url, headers={"X-API-KEY": API_KEY}, timeout=2)
        if r.status_code == 200:
            d = r.json()
            p = d.get('lastPrice')
            pct = d.get('changePercent')
            if p and p > 0: return p, pct
    except: pass

    # 第二階段：富果失敗，切換 Yahoo 救援
    try:
        y_sym = "^TWII" if symbol == "IX0001" else ("WTX=F" if symbol == "TXFR" else symbol)
        t = yf.Ticker(y_sym)
        df = t.history(period="1d")
        if not df.empty:
            p = df['Close'].iloc[-1]
            prev = t.info.get('previousClose', p)
            pct = ((p - prev) / prev) * 100
            return p, pct
    except: pass
    
    return None, None

# --- 3. 畫面持久化初始化 ---
if 'history' not in st.session_state: st.session_state.history = []
if 'alerts' not in st.session_state: st.session_state.alerts = []
if 'stats' not in st.session_state: st.session_state.stats = {}
if 'last_book' not in st.session_state: st.session_state.last_book = None

# --- 4. 渲染：框架先行 (絕不消失) ---

st.markdown("## ⚡ Alpha-Trader <span style='color:#58A6FF'>Professional Terminal v9.0</span>", unsafe_allow_html=True)

# 頂部狀態欄
tx_p, tx_c = get_price("TXFR", is_future=True)
idx_p, idx_c = get_price("IX0001")
tsm_p, tsm_c = get_price("TSM") # Yahoo 會自動處理 TSM

m_col = st.columns(5)
m_col[0].metric("台指期", f"{tx_p:.0f}" if tx_p else "--", f"{tx_c:.2f}%" if tx_c else "0.00%")
m_col[1].metric("加權指數", f"{idx_p:.0f}" if idx_p else "--", f"{idx_c:.2f}%" if idx_c else "0.00%")
m_col[2].metric("TSM(ADR)", f"{tsm_p:.2f}" if tsm_p else "--", f"{tsm_c:.2f}%" if tsm_c else "0.00%")
# 其他兩個固定 Yahoo
for i, (l, s) in enumerate([("日經 225", "^N225"), ("標普 500", "^GSPC")]):
    p, c = get_price(s)
    m_col[i+3].metric(l, f"{p:.0f}" if p else "--", f"{c:.2f}%" if c else "0.00%")

st.divider()

# 側邊設定
with st.sidebar:
    target = st.text_input("監控標的", value="2330").upper()
    qty_limit = st.number_input("大單閾值 (張)", value=50)
    if st.button("數據重置"):
        st.session_state.history = []; st.session_state.alerts = []; st.session_state.stats = {}; st.rerun()

# 主版面佈局 (Placeholder 恆常存在)
left_col, right_col = st.columns([2.2, 0.8])

with left_col:
    u1, u2 = st.columns(2)
    with u1:
        st.markdown("<h3>🏛️ 五檔即時報價 (L2)</h3>", unsafe_allow_html=True)
        book_ui = st.empty()
    with u2:
        st.markdown("<h3>🚨 主力大單異動</h3>", unsafe_allow_html=True)
        alert_ui = st.empty()
    
    st.markdown("<h3>📊 多空分價量能統計</h3>", unsafe_allow_html=True)
    chart_ui = st.empty()
    force_ui = st.empty()

with right_col:
    st.markdown("<h3>🔔 即時成交明細</h3>", unsafe_allow_html=True)
    trade_ui = st.empty()

# --- 5. 數據填充循環 ---

while True:
    try:
        res = requests.get(f"https://api.fugle.tw/marketdata/v1.0/stock/snapshot/quotes/{target}", 
                           headers={"X-API-KEY": API_KEY}, timeout=2)
        if res.status_code == 200:
            snap = res.json()
            
            # 1. 五檔排列修正 (買價, 買量, 賣價, 賣量)
            b_df = pd.DataFrame(snap.get('bids', [])).rename(columns={'price':'買價','size':'買量'})
            a_df = pd.DataFrame(snap.get('asks', [])).rename(columns={'price':'賣價','size':'賣量'})
            book_ui.dataframe(pd.concat([b_df, a_df], axis=1), hide_index=True, use_container_width=True)
            
            # 2. 明細與主力監控
            lp, lv = snap.get('lastPrice'), snap.get('lastSize')
            if lp:
                st.session_state.history.insert(0, f"{datetime.datetime.now().strftime('%H:%M:%S')} | {lp} | {lv}張")
                # 分價統計
                ps = str(lp)
                if ps not in st.session_state.stats: st.session_state.stats[ps] = {'B': 0, 'S': 0}
                b1 = snap.get('bids', [{}])[0].get('price', 0)
                if lp >= b1: st.session_state.stats[ps]['B'] += lv
                else: st.session_state.stats[ps]['S'] += lv

            # 3. 渲染 UI
            trade_ui.code("\n".join(st.session_state.history[:40]), language="python")
            alert_ui.code("\n".join(st.session_state.alerts[:15]), language="bash")
            
            if st.session_state.stats:
                df_s = pd.DataFrame.from_dict(st.session_state.stats, orient='index').sort_index(ascending=False)
                chart_ui.bar_chart(df_s, color=["#FF4B4B", "#00CC96"], height=250)
                tb, ts = df_s['B'].sum(), df_s['S'].sum()
                force_ui.metric("多空淨力道", f"{int(tb-ts)} 張", f"累積: {int(tb+ts)}")
    except:
        pass
    
    time.sleep(2)
    st.rerun()
