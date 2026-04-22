import streamlit as st
import pandas as pd
import datetime
import time
import requests
import yfinance as yf
import plotly.graph_objects as go

# --- 1. 專業介面配置 ---
st.set_page_config(page_title="Alpha-Trader Terminal v3.0", layout="wide")

# 專業黑標質感 CSS
st.markdown("""
    <style>
    .main { background-color: #0D1117; }
    .stMetric { background: #161B22; padding: 15px; border-radius: 10px; border: 1px solid #30363D; }
    [data-testid="stMetricValue"] { font-size: 26px !important; color: #58A6FF !important; }
    .stCodeBlock { border: 1px solid #30363D !important; background-color: #010409 !important; }
    h3 { color: #C9D1D9; font-size: 15px !important; font-weight: 600; letter-spacing: 1px; margin-bottom: 10px; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 核心初始化 ---
API_KEY = "MWI2Y2NlMTYtZmNjNy00NGJmLWFkMTYtNDVjZjk2MjJkNzFhIDA1YTliNzZhLWI0NzItNGYxMS1iYTIxLWYyN2ZkNjgzNzI5YQ=="

# 狀態持久化
if 'price_stats' not in st.session_state: st.session_state.price_stats = {}
if 'trade_history' not in st.session_state: st.session_state.trade_history = []
if 'order_alerts' not in st.session_state: st.session_state.order_alerts = []
if 'last_books_raw' not in st.session_state: st.session_state.last_books_raw = None
if 'mkt_cache' not in st.session_state:
    st.session_state.mkt_cache = {k: {"p": "--", "pct": "0.00"} for k in ["台指期", "加權指數", "TSM(ADR)", "日經 225", "標普 500"]}

# --- 3. 數據引擎：富果期貨 + 指數 ---

def get_market_data():
    """同步抓取台指期(Fugle)、加權(Fugle)與全球(Yahoo)"""
    # A. 台指期 (TXFR)
    try:
        tx_resp = requests.get("https://api.fugle.tw/marketdata/v1.0/futures/snapshot/quotes/TXFR", 
                              headers={"X-API-KEY": API_KEY}, timeout=2)
        if tx_resp.status_code == 200:
            d = tx_resp.json()
            st.session_state.mkt_cache["台指期"] = {"p": f"{d.get('lastPrice', 0):.0f}", "pct": f"{d.get('changePercent', 0):.2f}"}
    except: pass

    # B. 加權指數 (IX0001)
    try:
        ix_resp = requests.get("https://api.fugle.tw/marketdata/v1.0/stock/snapshot/quotes/IX0001", 
                              headers={"X-API-KEY": API_KEY}, timeout=2)
        if ix_resp.status_code == 200:
            d = ix_resp.json()
            st.session_state.mkt_cache["加權指數"] = {"p": f"{d.get('lastPrice', 0):.0f}", "pct": f"{d.get('changePercent', 0):.2f}"}
    except: pass

    # C. 全球指標
    targets = {"TSM(ADR)": "TSM", "日經 225": "^N225", "標普 500": "^GSPC"}
    for label, sym in targets.items():
        try:
            t = yf.Ticker(sym); df = t.history(period="1d")
            if not df.empty:
                p = df['Close'].iloc[-1]
                prev = t.info.get('previousClose', p)
                pct = ((p - prev) / prev) * 100
                st.session_state.mkt_cache[label] = {"p": f"{p:.2f}" if "ADR" in label or "500" in label else f"{p:.0f}", "pct": f"{pct:.2f}"}
        except: pass
    return st.session_state.mkt_cache

# --- 4. 戰情室版面 ---

st.title("🏛️ Alpha-Trader Premium Terminal")

# 看板
mkt = get_market_data()
idx_row = st.columns(5)
for i, label in enumerate(["台指期", "加權指數", "TSM(ADR)", "日經 225", "標普 500"]):
    with idx_row[i]:
        st.metric(label, mkt[label]["p"], f"{mkt[label]['pct']}%")

st.divider()

# 側邊欄
with st.sidebar:
    st.header("🎛️ 戰情設定")
    target_stock = st.text_input("監控標的 (個股)", value="2330").upper()
    monitor_on = st.toggle("啟動高頻輪詢", value=True)
    alert_qty = st.number_input("大單閾值 (張)", value=50)
    if st.button("🗑️ 重置所有統計"):
        st.session_state.price_stats = {}; st.session_state.trade_history = []; st.session_state.order_alerts = []; st.session_state.last_books_raw = None; st.rerun()

# 佈局定義
col_left, col_right = st.columns([2.2, 0.8])

with col_left:
    u1, u2 = st.columns(2)
    with u1:
        st.subheader("🏛️ ORDER BOOK (LEVEL 2)")
        book_ui = st.empty()
    with u2:
        st.subheader("🚨 INSTITUTIONAL ORDER FLOW")
        alert_ui = st.empty()
    
    st.subheader("📊 PRICE PROFILE & NET FORCE")
    chart_ui = st.empty()
    force_ui = st.empty()

with col_right:
    st.subheader("🔔 TIME & SALES")
    trade_ui = st.empty()

# --- 5. 核心監控循環 ---

if monitor_on:
    url = f"https://api.fugle.tw/marketdata/v1.0/stock/snapshot/quotes/{target_stock}"
    resp = requests.get(url, headers={"X-API-KEY": API_KEY}, timeout=2)
    if resp.status_code == 200:
        snap = resp.json()
        
        # A. 五檔分析
        bids = {x['price']: x['size'] for x in snap.get('bids', [])}
        asks = {x['price']: x['size'] for x in snap.get('asks', [])}
        if st.session_state.last_books_raw:
            old_b, old_a = st.session_state.last_books_raw['b'], st.session_state.last_books_raw['a']
            for p, s in asks.items():
                if p in old_a and abs(s - old_a[p]) >= alert_qty:
                    tag = "🔴 壓單增加" if s > old_a[p] else "⚪ 壓力撤除"
                    st.session_state.order_alerts.insert(0, f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {p} | {tag} {abs(s-old_a[p])}張")
            for p, s in bids.items():
                if p in old_b and abs(s - old_b[p]) >= alert_qty:
                    tag = "🟢 支撐增加" if s > old_b[p] else "⚪ 支撐撤除"
                    st.session_state.order_alerts.insert(0, f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {p} | {tag} {abs(s-old_b[p])}張")
        st.session_state.last_books_raw = {'b': bids, 'a': asks}

        # B. 多空計量
        lp, lv = snap.get('lastPrice'), snap.get('lastSize')
        if lp:
            ps = str(lp); b1 = snap.get('bids', [{}])[0].get('price', 0)
            if ps not in st.session_state.price_stats: st.session_state.price_stats[ps] = {'B': 0, 'S': 0}
            if lp >= b1: st.session_state.price_stats[ps]['B'] += lv
            else: st.session_state.price_stats[ps]['S'] += lv
            st.session_state.trade_history.insert(0, f"{datetime.datetime.now().strftime('%H:%M:%S')} | {lp} | {lv}張")

        # C. 渲染 UI
        b_df = pd.DataFrame(snap.get('bids', [])).rename(columns={'price':'買價','size':'買量'})
        a_df = pd.DataFrame(snap.get('asks', [])).rename(columns={'price':'賣價','size':'賣量'})
        book_ui.dataframe(pd.concat([b_df, a_df], axis=1), hide_index=True, use_container_width=True)
        alert_ui.code("\n".join(st.session_state.order_alerts[:14]), language="bash")

        if st.session_state.price_stats:
            df = pd.DataFrame.from_dict(st.session_state.price_stats, orient='index').sort_index(ascending=False)
            
            # 使用 Plotly 繪製更專業的圖表
            fig = go.Figure()
            fig.add_trace(go.Bar(y=df.index, x=df['B'], name='主動買', orientation='h', marker_color='#FF4B4B'))
            fig.add_trace(go.Bar(y=df.index, x=df['S'], name='主動賣', orientation='h', marker_color='#00CC96'))
            fig.update_layout(barmode='stack', height=300, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', 
                              font_color='white', margin=dict(l=0, r=0, t=0, b=0))
            chart_ui.plotly_chart(fig, use_container_width=True)
            
            tb, ts = df['B'].sum(), df['S'].sum()
            force_ui.metric("NET FORCE (買-賣)", f"{int(tb-ts)} 張", f"總量 {int(tb+ts)}")

        trade_ui.code("\n".join(st.session_state.trade_history[:50]), language="python")

    time.sleep(2); st.rerun()
