import streamlit as st
import pandas as pd
import datetime
import time
import requests
import yfinance as yf

# --- 1. 專業版樣式注入 (Custom CSS) ---
st.set_page_config(page_title="Alpha-Trader Terminal", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
    <style>
    .main { background-color: #0E1117; }
    div[data-testid="stMetricValue"] { font-size: 24px; font-weight: 700; color: #FFFFFF; }
    div[data-testid="stMetricDelta"] { font-size: 14px; }
    .stCodeBlock { border-radius: 8px; border: 1px solid #30363D; }
    .stDataFrame { border: 1px solid #30363D; border-radius: 8px; }
    h3 { color: #8B949E; font-size: 16px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; }
    .status-tag { padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 核心初始化 ---
API_KEY = "MWI2Y2NlMTYtZmNjNy00NGJmLWFkMTYtNDVjZjk2MjJkNzFhIDA1YTliNzZhLWI0NzItNGYxMS1iYTIxLWYyN2ZkNjgzNzI5YQ=="

# 狀態管理
for key, val in {
    'price_stats': {}, 'trade_history': [], 'order_alerts': [], 
    'last_books_raw': None, 'mkt_cache': {k: {"p": "--", "pct": "0.00"} for k in ["台指期", "加權指數", "TSM(ADR)", "日經 225", "恒生指數", "標普 500"]}
}.items():
    if key not in st.session_state: st.session_state[key] = val

# --- 3. 高效能數據引擎 ---

def get_market_sync():
    """多線程思維：確保大盤與期貨數據不跳 0"""
    tx_symbols = ["WTX=F", "TX=F", "^TWII"]
    targets = {"加權指數": "^TWII", "TSM(ADR)": "TSM", "日經 225": "^N225", "恒生指數": "^HSI", "標普 500": "^GSPC"}
    
    # 台指期專屬邏輯
    for sym in tx_symbols:
        try:
            t = yf.Ticker(sym)
            df = t.history(period="1d")
            if not df.empty and df['Close'].iloc[-1] > 0:
                p, pct = df['Close'].iloc[-1], ((df['Close'].iloc[-1] - t.info.get('previousClose', df['Close'].iloc[-1])) / t.info.get('previousClose', 1)) * 100
                st.session_state.mkt_cache["台指期"] = {"p": f"{p:.0f}", "pct": f"{pct:.2f}"}
                break
        except: continue
        
    for label, sym in targets.items():
        try:
            t = yf.Ticker(sym); df = t.history(period="1d")
            if not df.empty:
                p = df['Close'].iloc[-1]
                pct = ((p - t.info.get('previousClose', p)) / t.info.get('previousClose', 1)) * 100
                st.session_state.mkt_cache[label] = {"p": f"{p:.2f}" if "ADR" in label or "500" in label else f"{p:.0f}", "pct": f"{pct:.2f}"}
        except: pass
    return st.session_state.mkt_cache

def fetch_snapshot(symbol):
    url = f"https://api.fugle.tw/marketdata/v1.0/stock/snapshot/quotes/{symbol}"
    try:
        resp = requests.get(url, headers={"X-API-KEY": API_KEY}, timeout=3)
        return resp.json() if resp.status_code == 200 else None
    except: return None

# --- 4. App 佈局設計 ---

# Header Section
st.markdown("## ⚡ Alpha-Trader <span style='color:#58A6FF'>Terminal</span>", unsafe_allow_html=True)

# 指數看板 (Dashboard)
mkt = get_market_sync()
idx_row = st.columns(6)
for i, label in enumerate(["台指期", "加權指數", "TSM(ADR)", "日經 225", "恒生指數", "標普 500"]):
    with idx_row[i]:
        color = "#FF4B4B" if "-" in mkt[label]["pct"] else "#00CC96"
        st.metric(label, mkt[label]["p"], f"{mkt[label]['pct']}%", delta_color="normal")

st.divider()

# 側邊監控中心
with st.sidebar:
    st.header("⚙️ SYSTEM CONFIG")
    target_stock = st.text_input("TICKER", value="2330").upper()
    monitor_on = st.toggle("LIVE DATA FEED", value=True)
    st.divider()
    alert_qty = st.number_input("BLOCK TRADE THRESHOLD", value=50)
    if st.button("RESET ALL DATA"):
        st.session_state.price_stats = {}; st.session_state.trade_history = []; st.session_state.order_alerts = []; st.session_state.last_books_raw = None; st.rerun()
    
    if monitor_on:
        st.markdown("<span class='status-tag' style='background:#1F6745; color:#00FF00'>● CONNECTED</span>", unsafe_allow_html=True)
    else:
        st.markdown("<span class='status-tag' style='background:#442222; color:#FF4444'>● DISCONNECTED</span>", unsafe_allow_html=True)

# 核心數據區 (Core Data View)
col_main, col_side = st.columns([2.2, 0.8])

with col_main:
    # 第一排：五檔與分價
    c1, c2 = st.columns([1, 1.2])
    with c1:
        st.subheader("🏛️ ORDER BOOK")
        book_ui = st.empty()
    with c2:
        st.subheader("📈 PRICE PROFILE")
        chart_ui = st.empty()
        metric_ui = st.empty()
    
    # 第二排：主力異動 (滿版顯示增加氣勢)
    st.subheader("🚨 INSTITUTIONAL MOVES (ORDER FLOW ALERTS)")
    alert_ui = st.empty()

with col_side:
    st.subheader("🔔 TIME & SALES")
    trade_ui = st.empty()

# --- 5. 執行監控與分析 ---

if monitor_on:
    snap = fetch_snapshot(target_stock)
    if snap:
        # A. 數據計算邏輯
        bids = {x['price']: x['size'] for x in snap.get('bids', [])}
        asks = {x['price']: x['size'] for x in snap.get('asks', [])}
        
        if st.session_state.last_books_raw:
            old_b, old_a = st.session_state.last_books_raw['b'], st.session_state.last_books_raw['a']
            for p, s in asks.items():
                if p in old_a and abs(s - old_a[p]) >= alert_qty:
                    st.session_state.order_alerts.insert(0, f"[{datetime.datetime.now().strftime('%H:%M:%S')}] PRICE {p} | {'🔴 ADD' if s > old_a[p] else '⚪ CANCEL'} PRESSURE: {abs(s-old_a[p])} LOTS")
            for p, s in bids.items():
                if p in old_b and abs(s - old_b[p]) >= alert_qty:
                    st.session_state.order_alerts.insert(0, f"[{datetime.datetime.now().strftime('%H:%M:%S')}] PRICE {p} | {'🟢 ADD' if s > old_b[p] else '⚪ CANCEL'} SUPPORT: {abs(s-old_b[p])} LOTS")
        st.session_state.last_books_raw = {'b': bids, 'a': asks}

        lp, lv = snap.get('lastPrice'), snap.get('lastSize')
        if lp:
            ps = str(lp)
            if ps not in st.session_state.price_stats: st.session_state.price_stats[ps] = {'B': 0, 'S': 0}
            b1 = snap.get('bids', [{}])[0].get('price', 0)
            if lp >= b1: st.session_state.price_stats[ps]['B'] += lv
            else: st.session_state.price_stats[ps]['S'] += lv
            st.session_state.trade_history.insert(0, f"{datetime.datetime.now().strftime('%H:%M:%S')} | {lp} | {lv}張")

        # B. 渲染 UI
        b_df = pd.DataFrame(snap.get('bids', [])).rename(columns={'price':'BUY','size':'VOL_B'})
        a_df = pd.DataFrame(snap.get('asks', [])).rename(columns={'price':'SELL','size':'VOL_S'})
        book_ui.dataframe(pd.concat([b_df, a_df], axis=1), hide_index=True, use_container_width=True)
        
        if st.session_state.price_stats:
            df = pd.DataFrame.from_dict(st.session_state.price_stats, orient='index').sort_index(ascending=False)
            chart_ui.bar_chart(df, color=["#FF4B4B", "#00CC96"], height=250)
            tb, ts = df['B'].sum(), df['S'].sum()
            metric_ui.metric("NET BUYING FORCE", f"{int(tb - ts)} 張", f"Accumulated: {int(tb+ts)}", delta_color="inverse")
        
        alert_ui.code("\n".join(st.session_state.order_alerts[:10]), language="bash")
        trade_ui.code("\n".join(st.session_state.trade_history[:40]), language="python")

    time.sleep(2)
    st.rerun()
