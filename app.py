import streamlit as st
import pandas as pd
import datetime
import time
import requests
import yfinance as yf

# --- 1. 配置與核心初始化 ---
API_KEY = "MWI2Y2NlMTYtZmNjNy00NGJmLWFkMTYtNDVjZjk2MjJkNzFhIDA1YTliNzZhLWI0NzItNGYxMS1iYTIxLWYyN2ZkNjgzNzI5YQ=="

st.set_page_config(page_title="專業操盤戰情室 | 終極版", layout="wide", initial_sidebar_state="expanded")

# 狀態持久化：確保數據即便在 Rerun 時也不會清空
if 'price_stats' not in st.session_state: st.session_state.price_stats = {}
if 'trade_history' not in st.session_state: st.session_state.trade_history = []
if 'order_alerts' not in st.session_state: st.session_state.order_alerts = []
if 'last_books_raw' not in st.session_state: st.session_state.last_books_raw = None
if 'mkt_cache' not in st.session_state: 
    st.session_state.mkt_cache = {k: {"p": "--", "pct": "0.00"} for k in ["台指期", "加權指數", "TSM(ADR)", "日經 225", "恒生指數", "標普 500"]}

# --- 2. 數據引擎：解決 0 數據問題 ---

def get_market_sync():
    """多代號輪詢機制，確保台指期必定有值"""
    # 針對台指期進行多重探測
    tx_symbols = ["WTX=F", "TX=F", "^TWII"] # 備選名單
    found_tx = False
    
    # 全球指標清單
    targets = {
        "加權指數": "^TWII", 
        "TSM(ADR)": "TSM", 
        "日經 225": "^N225", 
        "恒生指數": "^HSI", 
        "標普 500": "^GSPC"
    }

    # 1. 優先處理台指期
    for sym in tx_symbols:
        try:
            t = yf.Ticker(sym)
            df = t.history(period="1d")
            if not df.empty and df['Close'].iloc[-1] > 0:
                p = df['Close'].iloc[-1]
                prev = t.info.get('previousClose', p)
                pct = ((p - prev) / prev) * 100
                st.session_state.mkt_cache["台指期"] = {"p": f"{p:.0f}", "pct": f"{pct:.2f}"}
                found_tx = True
                break
        except: continue
    
    # 2. 處理其他指標
    for label, sym in targets.items():
        try:
            t = yf.Ticker(sym)
            df = t.history(period="1d")
            if not df.empty:
                p = df['Close'].iloc[-1]
                prev = t.info.get('previousClose', p)
                pct = ((p - prev) / prev) * 100
                st.session_state.mkt_cache[label] = {
                    "p": f"{p:.2f}" if "." in label or "ADR" in label else f"{p:.0f}",
                    "pct": f"{pct:.2f}"
                }
        except: pass
    return st.session_state.mkt_cache

def fetch_stock_snapshot(symbol):
    """Fugle REST API 備援請求"""
    url = f"https://api.fugle.tw/marketdata/v1.0/stock/snapshot/quotes/{symbol}"
    headers = {"X-API-KEY": API_KEY}
    try:
        resp = requests.get(url, headers=headers, timeout=3)
        return resp.json() if resp.status_code == 200 else None
    except: return None

# --- 3. UI 渲染 (保證所有功能區塊恆常存在) ---

st.markdown(f"### 🚀 專業操盤手實時戰情室 | <small>穩定監控中</small>", unsafe_allow_html=True)

# 指數區塊 (即便是 0 也要顯示最後快取)
mkt = get_market_sync()
idx_cols = st.columns(6)
for i, label in enumerate(["台指期", "加權指數", "TSM(ADR)", "日經 225", "恒生指數", "標普 500"]):
    with idx_cols[i]:
        st.metric(label, mkt[label]["p"], f"{mkt[label]['pct']}%")

# 側邊欄配置
with st.sidebar:
    st.header("🎯 系統控制")
    target_stock = st.text_input("監控個股", value="2330").upper()
    monitor_on = st.toggle("啟動實時更新", value=True)
    st.divider()
    alert_qty = st.number_input("大單異動閥值", value=50)
    if st.button("🗑️ 重置統計", use_container_width=True):
        st.session_state.price_stats = {}
        st.session_state.trade_history = []
        st.session_state.order_alerts = []
        st.session_state.last_books_raw = None
        st.rerun()

# 佈局定義：確保版面不因數據而閃爍
col_left, col_mid, col_right = st.columns([1, 1.2, 0.8])

with col_left:
    st.subheader("🏛️ 五檔掛單")
    book_placeholder = st.empty()
    st.subheader("⚠️ 主力異動監控")
    alert_placeholder = st.empty()

with col_mid:
    st.subheader("📈 多空量能分布")
    chart_placeholder = st.empty()
    metric_placeholder = st.empty()
    table_placeholder = st.empty()

with col_right:
    st.subheader("🔔 即時明細")
    trade_placeholder = st.empty()

# --- 4. 監控迴圈邏輯 ---

if monitor_on:
    snap = fetch_stock_snapshot(target_stock)
    
    if snap:
        # A. 五檔與主力監控邏輯
        bids = {x['price']: x['size'] for x in snap.get('bids', [])}
        asks = {x['price']: x['size'] for x in snap.get('asks', [])}
        
        if st.session_state.last_books_raw:
            old_b, old_a = st.session_state.last_books_raw['b'], st.session_state.last_books_raw['a']
            # 賣盤(壓單)
            for p, s in asks.items():
                if p in old_a and abs(s - old_a[p]) >= alert_qty:
                    tag = "🔴 壓單增加" if s > old_a[p] else "⚪ 壓力撤單"
                    st.session_state.order_alerts.insert(0, f"{datetime.datetime.now().strftime('%H:%M:%S')} | {p} | {tag} {abs(s-old_a[p])}張")
            # 買盤(支撐)
            for p, s in bids.items():
                if p in old_b and abs(s - old_b[p]) >= alert_qty:
                    tag = "🟢 支撐增加" if s > old_b[p] else "⚪ 支撐撤單"
                    st.session_state.order_alerts.insert(0, f"{datetime.datetime.now().strftime('%H:%M:%S')} | {p} | {tag} {abs(s-old_b[p])}張")
        st.session_state.last_books_raw = {'b': bids, 'a': asks}

        # B. 多空計量邏輯
        lp, lv = snap.get('lastPrice'), snap.get('lastSize')
        if lp:
            ps = str(lp)
            if ps not in st.session_state.price_stats: st.session_state.price_stats[ps] = {'買入': 0, '賣出': 0}
            # 以買一價判斷買賣方力量
            b1 = snap.get('bids', [{}])[0].get('price', 0)
            if lp >= b1: st.session_state.price_stats[ps]['買入'] += lv
            else: st.session_state.price_stats[ps]['賣出'] += lv
            st.session_state.trade_history.insert(0, f"{datetime.datetime.now().strftime('%H:%M:%S')} | {lp} | {lv}張")

        # C. 渲染數據到 Placeholder (防止 UI 消失)
        b_df = pd.DataFrame(snap.get('bids', [])).rename(columns={'price':'買價','size':'買量'})
        a_df = pd.DataFrame(snap.get('asks', [])).rename(columns={'price':'賣價','size':'賣量'})
        book_placeholder.dataframe(pd.concat([b_df, a_df], axis=1), hide_index=True, use_container_width=True)
        alert_placeholder.code("\n".join(st.session_state.order_alerts[:15]))

        if st.session_state.price_stats:
            df = pd.DataFrame.from_dict(st.session_state.price_stats, orient='index').sort_index(ascending=False)
            chart_placeholder.bar_chart(df, color=["#FF4B4B", "#00CC96"])
            t_buy, t_sell = df['買入'].sum(), df['賣出'].sum()
            metric_placeholder.metric("多空淨力道", f"{int(t_buy - t_sell)} 張", f"買 {int(t_buy)} / 賣 {int(t_sell)}")
            table_placeholder.dataframe(df, use_container_width=True)

        trade_placeholder.code("\n".join(st.session_state.trade_history[:35]))

    time.sleep(2)
    st.rerun()
