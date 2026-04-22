import streamlit as st
import pandas as pd
import datetime
import time
import requests
import yfinance as yf

# --- 1. 專業介面配置 ---
st.set_page_config(page_title="Alpha-Trader Terminal v5.0", layout="wide", initial_sidebar_state="collapsed")

# 注入專業交易員風格 CSS，強制維持版面結構
st.markdown("""
    <style>
    .main { background-color: #0D1117; }
    .stMetric { background: #161B22; padding: 15px; border-radius: 10px; border: 1px solid #30363D; }
    [data-testid="stMetricValue"] { font-size: 26px !important; color: #58A6FF !important; }
    .stCodeBlock { border: 1px solid #30363D !important; background-color: #010409 !important; min-height: 200px; }
    .data-container { background-color: #161B22; border: 1px solid #30363D; border-radius: 8px; padding: 10px; margin-bottom: 20px; }
    h3 { color: #8B949E; font-size: 14px !important; font-weight: 600; letter-spacing: 1px; margin-bottom: 12px; border-left: 3px solid #58A6FF; padding-left: 8px; }
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

# --- 3. 獨立數據模組 ---

def update_top_bar():
    """強制更新頂部狀態欄"""
    headers = {"X-API-KEY": API_KEY}
    # 台指期
    try:
        r = requests.get("https://api.fugle.tw/marketdata/v1.0/futures/snapshot/quotes/TXFR", headers=headers, timeout=2)
        if r.status_code == 200:
            d = r.json()
            st.session_state.mkt_cache["台指期"] = {"p": f"{d.get('lastPrice', 0):.0f}", "pct": f"{d.get('changePercent', 0):.2f}"}
    except: pass
    # 加權
    try:
        r = requests.get("https://api.fugle.tw/marketdata/v1.0/stock/snapshot/quotes/IX0001", headers=headers, timeout=2)
        if r.status_code == 200:
            d = r.json()
            st.session_state.mkt_cache["加權指數"] = {"p": f"{d.get('lastPrice', 0):.0f}", "pct": f"{d.get('changePercent', 0):.2f}"}
    except: pass
    # 全球
    targets = {"TSM(ADR)": "TSM", "日經 225": "^N225", "標普 500": "^GSPC"}
    for label, sym in targets.items():
        try:
            t = yf.Ticker(sym); df = t.history(period="1d")
            if not df.empty:
                p = df['Close'].iloc[-1]
                pct = ((p - t.info.get('previousClose', p)) / t.info.get('previousClose', 1)) * 100
                st.session_state.mkt_cache[label] = {"p": f"{p:.2f}" if "ADR" in label else f"{p:.0f}", "pct": f"{pct:.2f}"}
        except: pass

# --- 4. 戰情室版面渲染 ---

st.markdown("## 🏛️ Alpha-Trader <span style='color:#58A6FF'>Professional Terminal</span>", unsafe_allow_html=True)

# A. 狀態欄 (頂部看板)
update_top_bar()
mkt = st.session_state.mkt_cache
idx_row = st.columns(5)
for i, label in enumerate(["台指期", "加權指數", "TSM(ADR)", "日經 225", "標普 500"]):
    with idx_row[i]:
        st.metric(label, mkt[label]["p"], f"{mkt[label]['pct']}%")

st.divider()

# B. 側邊控制
with st.sidebar:
    st.header("⚙️ 系統設定")
    target_stock = st.text_input("監控代號", value="2330").upper()
    monitor_on = st.toggle("啟動 LIVE DATA", value=True)
    alert_qty = st.number_input("大單閥值 (張)", value=50)
    if st.button("🗑️ 重置數據統計"):
        st.session_state.price_stats = {}; st.session_state.trade_history = []; st.session_state.order_alerts = []; st.session_state.last_books_raw = None; st.rerun()

# C. 核心三區塊佈局 (強制維持框架)
col_l, col_r = st.columns([2.2, 0.8])

with col_l:
    # 第一排：五檔與異動
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("<h3>🏛️ 五檔即時報價 (LEVEL 2)</h3>", unsafe_allow_html=True)
        book_placeholder = st.empty() # 即使沒數據也要佔位
        # 初始狀態顯示空表格
        book_placeholder.dataframe(pd.DataFrame(columns=['買價','買量','賣價','賣量']), use_container_width=True)
    
    with c2:
        st.markdown("<h3>🚨 主力大單異動監控</h3>", unsafe_allow_html=True)
        alert_placeholder = st.empty()
        alert_placeholder.code("等待數據接入...", language="bash")
    
    # 第二排：多空力道
    st.markdown("<h3>📊 多空力道計量與分價統計</h3>", unsafe_allow_html=True)
    chart_placeholder = st.empty()
    force_placeholder = st.empty()

with col_r:
    st.markdown("<h3>🔔 即時成交明細</h3>", unsafe_allow_html=True)
    trade_placeholder = st.empty()
    trade_placeholder.code("Ready to connect...", language="python")

# --- 5. 監控與運算邏輯 ---

if monitor_on:
    stock_url = f"https://api.fugle.tw/marketdata/v1.0/stock/snapshot/quotes/{target_stock}"
    try:
        resp = requests.get(stock_url, headers={"X-API-KEY": API_KEY}, timeout=2)
        if resp.status_code == 200:
            snap = resp.json()
            
            # 1. 五檔掛單處理 (強制格式化欄位)
            bids = snap.get('bids', [])
            asks = snap.get('asks', [])
            b_df = pd.DataFrame(bids).rename(columns={'price':'買價','size':'買量'})
            a_df = pd.DataFrame(asks).rename(columns={'price':'賣價','size':'賣量'})
            # 拼接成對稱的五檔版面
            full_book = pd.concat([b_df, a_df], axis=1)
            book_placeholder.dataframe(full_book, hide_index=True, use_container_width=True)

            # 2. 主力異動邏輯 (掛單數對比)
            b_dict = {x['price']: x['size'] for x in bids}
            a_dict = {x['price']: x['size'] for x in asks}
            if st.session_state.last_books_raw:
                old_b, old_a = st.session_state.last_books_raw['b'], st.session_state.last_books_raw['a']
                for p, s in a_dict.items():
                    if p in old_a and abs(s - old_a[p]) >= alert_qty:
                        tag = "🔴 壓單增加" if s > old_a[p] else "⚪ 壓力撤除"
                        st.session_state.order_alerts.insert(0, f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {p} | {tag} {abs(s-old_a[p])}張")
                for p, s in b_dict.items():
                    if p in old_b and abs(s - old_b[p]) >= alert_qty:
                        tag = "🟢 支撐增加" if s > old_b[p] else "⚪ 支撐撤除"
                        st.session_state.order_alerts.insert(0, f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {p} | {tag} {abs(s-old_b[p])}張")
            st.session_state.last_books_raw = {'b': b_dict, 'a': a_dict}
            alert_placeholder.code("\n".join(st.session_state.order_alerts[:15]), language="bash")

            # 3. 成交明細與多空力道
            lp, lv = snap.get('lastPrice'), snap.get('lastSize')
            if lp:
                ps = str(lp); b1 = bids[0].get('price', 0) if bids else 0
                if ps not in st.session_state.price_stats: st.session_state.price_stats[ps] = {'B': 0, 'S': 0}
                if lp >= b1: st.session_state.price_stats[ps]['B'] += lv
                else: st.session_state.price_stats[ps]['S'] += lv
                st.session_state.trade_history.insert(0, f"{datetime.datetime.now().strftime('%H:%M:%S')} | 價:{lp} | 量:{lv}張")
            
            trade_placeholder.code("\n".join(st.session_state.trade_history[:50]), language="python")

            if st.session_state.price_stats:
                df = pd.DataFrame.from_dict(st.session_state.price_stats, orient='index').sort_index(ascending=False)
                chart_placeholder.bar_chart(df, color=["#FF4B4B", "#00CC96"], height=250)
                tb, ts = df['B'].sum(), df['S'].sum()
                force_placeholder.metric("NET BUYING FORCE (買-賣)", f"{int(tb-ts)} 張", f"累積總量 {int(tb+ts)}")

    except Exception as e:
        # 即使報錯，也要維持 Placeholder 不變
        pass
    
    time.sleep(2)
    st.rerun()
