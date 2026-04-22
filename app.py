import streamlit as st
import pandas as pd
import datetime
import time
import requests
import yfinance as yf

# --- 1. 專業介面配置 ---
st.set_page_config(page_title="Alpha-Trader Terminal", layout="wide", initial_sidebar_state="collapsed")

# 注入專業交易員風格 CSS
st.markdown("""
    <style>
    .main { background-color: #0D1117; }
    .stMetric { background: #161B22; padding: 15px; border-radius: 10px; border: 1px solid #30363D; }
    [data-testid="stMetricValue"] { font-size: 26px !important; color: #58A6FF !important; }
    .stCodeBlock { border: 1px solid #30363D !important; background-color: #010409 !important; }
    h3 { color: #C9D1D9; font-size: 14px !important; font-weight: 600; letter-spacing: 1px; }
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

# --- 3. 數據引擎：修復台指期與加權指數核心 ---

def update_global_dashboard():
    """全面修正：分流請求台指期、加權與全球指標"""
    headers = {"X-API-KEY": API_KEY}
    
    # A. 台指期 (TXFR - 期貨專用路徑)
    try:
        url_txf = "https://api.fugle.tw/marketdata/v1.0/futures/snapshot/quotes/TXFR"
        r = requests.get(url_txf, headers=headers, timeout=3)
        if r.status_code == 200:
            d = r.json()
            st.session_state.mkt_cache["台指期"] = {"p": f"{d.get('lastPrice', 0):.0f}", "pct": f"{d.get('changePercent', 0):.2f}"}
    except: pass

    # B. 加權指數 (IX0001 - 指數/個股路徑)
    try:
        url_tse = "https://api.fugle.tw/marketdata/v1.0/stock/snapshot/quotes/IX0001"
        r = requests.get(url_tse, headers=headers, timeout=3)
        if r.status_code == 200:
            d = r.json()
            st.session_state.mkt_cache["加權指數"] = {"p": f"{d.get('lastPrice', 0):.0f}", "pct": f"{d.get('changePercent', 0):.2f}"}
    except: pass

    # C. 全球指標 (Yahoo Finance)
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

# --- 4. 戰情室版面渲染 ---

st.markdown("## ⚡ Alpha-Trader Terminal <small>v3.5 Final</small>", unsafe_allow_html=True)

# 指數看板
update_global_dashboard()
mkt = st.session_state.mkt_cache
idx_row = st.columns(5)
for i, label in enumerate(["台指期", "加權指數", "TSM(ADR)", "日經 225", "標普 500"]):
    with idx_row[i]:
        st.metric(label, mkt[label]["p"], f"{mkt[label]['pct']}%")

st.divider()

# 控制欄位
with st.sidebar:
    st.header("🎛️ 系統控制")
    target_stock = st.text_input("監控代號", value="2330").upper()
    monitor_on = st.toggle("實時監控系統", value=True)
    alert_qty = st.number_input("主力大單閥值", value=50)
    if st.button("🗑️ 重置數據"):
        st.session_state.price_stats = {}; st.session_state.trade_history = []; st.session_state.order_alerts = []; st.session_state.last_books_raw = None; st.rerun()

# 功能佈局
col_left, col_right = st.columns([2.1, 0.9])

with col_left:
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("🏛️ ORDER BOOK (L2)")
        book_ui = st.empty()
    with c2:
        st.subheader("🚨 FLOW ALERTS")
        alert_ui = st.empty()
    
    st.subheader("📊 PRICE-FORCE ANALYSIS")
    chart_ui = st.empty()
    force_ui = st.empty()

with col_right:
    st.subheader("🔔 TIME & SALES")
    trade_ui = st.empty()

# --- 5. 高頻監控邏輯 ---

if monitor_on:
    stock_url = f"https://api.fugle.tw/marketdata/v1.0/stock/snapshot/quotes/{target_stock}"
    try:
        resp = requests.get(stock_url, headers={"X-API-KEY": API_KEY}, timeout=2)
        if resp.status_code == 200:
            snap = resp.json()
            
            # A. 五檔與主力監控
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

            # B. 多空力道
            lp, lv = snap.get('lastPrice'), snap.get('lastSize')
            if lp:
                ps = str(lp); b1 = snap.get('bids', [{}])[0].get('price', 0)
                if ps not in st.session_state.price_stats: st.session_state.price_stats[ps] = {'B': 0, 'S': 0}
                if lp >= b1: st.session_state.price_stats[ps]['B'] += lv
                else: st.session_state.price_stats[ps]['S'] += lv
                st.session_state.trade_history.insert(0, f"{datetime.datetime.now().strftime('%H:%M:%S')} | {lp} | {lv}張")

            # C. 渲染
            b_df = pd.DataFrame(snap.get('bids', [])).rename(columns={'price':'BUY','size':'VOL'})
            a_df = pd.DataFrame(snap.get('asks', [])).rename(columns={'price':'SELL','size':'VOL'})
            book_ui.dataframe(pd.concat([b_df, a_df], axis=1), hide_index=True, use_container_width=True)
            alert_ui.code("\n".join(st.session_state.order_alerts[:14]), language="bash")

            if st.session_state.price_stats:
                df = pd.DataFrame.from_dict(st.session_state.price_stats, orient='index').sort_index(ascending=False)
                chart_ui.bar_chart(df, color=["#FF4B4B", "#00CC96"], height=250)
                tb, ts = df['B'].sum(), df['S'].sum()
                force_ui.metric("NET FORCE (買-賣)", f"{int(tb-ts)} 張", f"累積總量 {int(tb+ts)}")

            trade_ui.code("\n".join(st.session_state.trade_history[:50]), language="python")

    except: pass
    
    time.sleep(2)
    st.rerun()
