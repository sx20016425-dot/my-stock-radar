import streamlit as st
import pandas as pd
import datetime
import time
import requests
import yfinance as yf

# --- 1. 專業介面配置 ---
st.set_page_config(page_title="Alpha-Trader Terminal", layout="wide", initial_sidebar_state="collapsed")

# 注入百萬美金質感的 Dark Mode CSS
st.markdown("""
    <style>
    .main { background-color: #0E1117; }
    [data-testid="stMetricValue"] { font-size: 28px !important; font-weight: 800 !important; color: #58A6FF !important; }
    .stCodeBlock { border: 1px solid #30363D !important; background-color: #161B22 !important; }
    .stMetric { background: #161B22; padding: 15px; border-radius: 10px; border: 1px solid #30363D; }
    h3 { color: #8B949E; font-size: 14px !important; letter-spacing: 2px; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 狀態管理 (數據持久化) ---
API_KEY = "MWI2Y2NlMTYtZmNjNy00NGJmLWFkMTYtNDVjZjk2MjJkNzFhIDA1YTliNzZhLWI0NzItNGYxMS1iYTIxLWYyN2ZkNjgzNzI5YQ=="

for key, val in {
    'price_stats': {}, 'trade_history': [], 'order_alerts': [], 
    'last_books_raw': None, 
    'mkt_cache': {k: {"p": "--", "pct": "0.00"} for k in ["台指期", "加權指數", "TSM(ADR)", "日經 225", "標普 500"]}
}.items():
    if key not in st.session_state: st.session_state[key] = val

# --- 3. 數據引擎：富果期貨 + 全球指標 ---

def get_market_data():
    """整合富果期貨數據與全球指標"""
    # A. 抓取台指期 (Fugle 期貨 API)
    # 代號說明: TXFR 代表台指期近月連續合約
    tx_url = "https://api.fugle.tw/marketdata/v1.0/futures/snapshot/quotes/TXFR"
    try:
        resp = requests.get(tx_url, headers={"X-API-KEY": API_KEY}, timeout=2)
        if resp.status_code == 200:
            d = resp.json()
            p = d.get('lastPrice', 0)
            pct = d.get('changePercent', 0)
            if p > 0:
                st.session_state.mkt_cache["台指期"] = {"p": f"{p:.0f}", "pct": f"{pct:.2f}"}
    except: pass

    # B. 抓取全球指標 (yfinance)
    targets = {"加權指數": "^TWII", "TSM(ADR)": "TSM", "日經 225": "^N225", "標普 500": "^GSPC"}
    for label, sym in targets.items():
        try:
            t = yf.Ticker(sym); df = t.history(period="1d")
            if not df.empty:
                p = df['Close'].iloc[-1]
                pct = ((p - t.info.get('previousClose', p)) / t.info.get('previousClose', 1)) * 100
                st.session_state.mkt_cache[label] = {"p": f"{p:.2f}" if "ADR" in label or "500" in label else f"{p:.0f}", "pct": f"{pct:.2f}"}
        except: pass
    return st.session_state.mkt_cache

def fetch_stock(symbol):
    url = f"https://api.fugle.tw/marketdata/v1.0/stock/snapshot/quotes/{symbol}"
    try:
        resp = requests.get(url, headers={"X-API-KEY": API_KEY}, timeout=2)
        return resp.json() if resp.status_code == 200 else None
    except: return None

# --- 4. App 佈局渲染 ---

st.markdown("## ⚡ Alpha-Trader <span style='color:#58A6FF'>Terminal v2.0</span>", unsafe_allow_html=True)

# Dashboard: 指數看板
mkt = get_market_data()
idx_row = st.columns(5)
for i, label in enumerate(["台指期", "加權指數", "TSM(ADR)", "日經 225", "標普 500"]):
    with idx_row[i]:
        st.metric(label, mkt[label]["p"], f"{mkt[label]['pct']}%")

st.divider()

# 側邊欄配置
with st.sidebar:
    st.header("⚙️ SYSTEM")
    target_stock = st.text_input("TICKER", value="2330").upper()
    monitor_on = st.toggle("LIVE FEED", value=True)
    alert_qty = st.number_input("BLOCK TRADE", value=50)
    if st.button("RESET"):
        st.session_state.price_stats = {}; st.session_state.trade_history = []; st.session_state.order_alerts = []; st.session_state.last_books_raw = None; st.rerun()

# 核心數據區 (簡化為兩大區塊)
col_left, col_right = st.columns([2, 1])

with col_left:
    # 第一排：五檔與主力異動
    c1, c2 = st.columns([1, 1])
    with c1:
        st.subheader("🏛️ ORDER BOOK")
        book_ui = st.empty()
    with c2:
        st.subheader("🚨 FLOW ALERTS")
        alert_ui = st.empty()
    
    # 第二排：分價量能
    st.subheader("📈 PRICE PROFILE & FORCE")
    chart_ui = st.empty()
    metric_ui = st.empty()

with col_right:
    st.subheader("🔔 TIME & SALES")
    trade_ui = st.empty()

# --- 5. 實時運算邏輯 ---

if monitor_on:
    snap = fetch_stock(target_stock)
    if snap:
        # A. 五檔與主力監控
        bids = {x['price']: x['size'] for x in snap.get('bids', [])}
        asks = {x['price']: x['size'] for x in snap.get('asks', [])}
        
        if st.session_state.last_books_raw:
            old_b, old_a = st.session_state.last_books_raw['b'], st.session_state.last_books_raw['a']
            for p, s in asks.items():
                if p in old_a and abs(s - old_a[p]) >= alert_qty:
                    tag = "🔴 SELL-ADD" if s > old_a[p] else "⚪ SELL-CLR"
                    st.session_state.order_alerts.insert(0, f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {p} | {tag} {abs(s-old_a[p])}")
            for p, s in bids.items():
                if p in old_b and abs(s - old_b[p]) >= alert_qty:
                    tag = "🟢 BUY-ADD" if s > old_b[p] else "⚪ BUY-CLR"
                    st.session_state.order_alerts.insert(0, f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {p} | {tag} {abs(s-old_b[p])}")
        st.session_state.last_books_raw = {'b': bids, 'a': asks}

        # B. 多空力道
        lp, lv = snap.get('lastPrice'), snap.get('lastSize')
        if lp:
            ps = str(lp); b1 = snap.get('bids', [{}])[0].get('price', 0)
            if ps not in st.session_state.price_stats: st.session_state.price_stats[ps] = {'B': 0, 'S': 0}
            if lp >= b1: st.session_state.price_stats[ps]['B'] += lv
            else: st.session_state.price_stats[ps]['S'] += lv
            st.session_state.trade_history.insert(0, f"{datetime.datetime.now().strftime('%H:%M:%S')} | {lp} | {lv}張")

        # C. 渲染介面
        b_df = pd.DataFrame(snap.get('bids', [])).rename(columns={'price':'BUY','size':'V_B'})
        a_df = pd.DataFrame(snap.get('asks', [])).rename(columns={'price':'SELL','size':'V_S'})
        book_ui.dataframe(pd.concat([b_df, a_df], axis=1), hide_index=True, use_container_width=True)
        
        alert_ui.code("\n".join(st.session_state.order_alerts[:12]), language="bash")
        
        if st.session_state.price_stats:
            df = pd.DataFrame.from_dict(st.session_state.price_stats, orient='index').sort_index(ascending=False)
            chart_ui.bar_chart(df, color=["#FF4B4B", "#00CC96"], height=200)
            tb, ts = df['B'].sum(), df['S'].sum()
            metric_ui.metric("NET BUYING FORCE", f"{int(tb - ts)} 張", f"Total Mkt Vol: {int(tb+ts)}")
            
        trade_ui.code("\n".join(st.session_state.trade_history[:45]), language="python")

    time.sleep(2); st.rerun()
