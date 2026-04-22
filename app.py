import streamlit as st
import pandas as pd
import datetime
import time
import requests
import yfinance as yf

# --- 1. 專業介面與剛性框架配置 ---
st.set_page_config(page_title="Alpha-Trader Ultimate v13.0", layout="wide", initial_sidebar_state="collapsed")

# 注入 CSS：確保框架恆常存在，即使沒有數據
st.markdown("""
    <style>
    .main { background-color: #0D1117; }
    .stMetric { background: #161B22; padding: 15px; border-radius: 10px; border: 1px solid #30363D; }
    [data-testid="stMetricValue"] { font-size: 24px !important; color: #58A6FF !important; }
    .stCodeBlock { background-color: #010409 !important; border: 1px solid #30363D !important; min-height: 280px !important; }
    h3 { color: #8B949E; font-size: 14px !important; font-weight: 600; border-left: 4px solid #58A6FF; padding-left: 10px; margin: 20px 0 10px 0; }
    .stDataFrame { border: 1px solid #30363D !important; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 核心初始化 ---
API_KEY = "MWI2Y2NlMTYtZmNjNy00NGJmLWFkMTYtNDVjZjk2MjJkNzFhIDA1YTliNzZhLWI0NzItNGYxMS1iYTIxLWYyN2ZkNjgzNzI5YQ=="

# 嚴格校對：所有在 UI 中出現的 Key 必須在初始化時完全對齊
state_defaults = {
    'trades': [],        
    'alerts': [],        
    'stats': {},         
    'last_book': None,   
    'mkt_cache': {
        "台指期": {"p": "--", "pct": "0.00"},
        "加權指數": {"p": "--", "pct": "0.00"},
        "TSM(ADR)": {"p": "--", "pct": "0.00"},
        "日經 225": {"p": "--", "pct": "0.00"},
        "標普 500": {"p": "--", "pct": "0.00"}
    }
}

for key, value in state_defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value

# --- 3. 數據救援引擎 ---

def fetch_market_safe(symbol, is_future=False):
    """雙引擎：Fugle 優先，Yahoo 救援"""
    try:
        path = "futures" if is_future else "stock"
        url = f"https://api.fugle.tw/marketdata/v1.0/{path}/snapshot/quotes/{symbol}"
        r = requests.get(url, headers={"X-API-KEY": API_KEY}, timeout=2)
        if r.status_code == 200:
            d = r.json()
            if d.get('lastPrice'): return d.get('lastPrice'), d.get('changePercent')
    except: pass
    
    try:
        y_map = {"TXFR": "WTX=F", "IX0001": "^TWII"}
        y_sym = y_map.get(symbol, symbol)
        t = yf.Ticker(y_sym)
        df = t.history(period="1d")
        if not df.empty:
            p = df['Close'].iloc[-1]
            prev = t.info.get('previousClose', p)
            return p, ((p - prev) / prev) * 100
    except: pass
    return None, None

def fetch_aronhack_candles(symbol):
    """Aronhack 教學實作：分鐘 K 線數據"""
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    url = f"https://api.fugle.tw/marketdata/v1.0/stock/candles?symbol={symbol}&from={today}&to={today}&fields=open,high,low,close,volume"
    try:
        r = requests.get(url, headers={"X-API-KEY": API_KEY}, timeout=2)
        if r.status_code == 200:
            df = pd.DataFrame(r.json().get('data', []))
            if not df.empty:
                df['date'] = pd.to_datetime(df['date'])
                return df.sort_values('date')
    except: pass
    return pd.DataFrame()

# --- 4. 畫面渲染：絕對框架 ---

st.markdown("## 🏛️ Alpha-Trader <span style='color:#58A6FF'>Ultimate v13.0 (Zero-Leak Edition)</span>", unsafe_allow_html=True)

# A. 頂部看板 (修復 KeyError 並確保數據同步)
m_cols = st.columns(5)
sync_targets = [
    ("台指期", "TXFR", True), 
    ("加權指數", "IX0001", False), 
    ("TSM(ADR)", "TSM", False), 
    ("日經 225", "^N225", False), 
    ("標普 500", "^GSPC", False)
]

for i, (name, sym, fut) in enumerate(sync_targets):
    p, c = fetch_market_safe(sym, is_future=fut)
    if p is not None:
        st.session_state.mkt_cache[name] = {
            "p": f"{p:,.2f}" if ("ADR" in name or "." in str(p)) else f"{p:,.0f}",
            "pct": f"{c:,.2f}"
        }
    # 使用 .get 安全讀取，杜絕 KeyError
    disp = st.session_state.mkt_cache.get(name, {"p": "--", "pct": "0.00"})
    m_cols[i].metric(name, disp["p"], f"{disp['pct']}%")

st.divider()

# B. 側邊控制
with st.sidebar:
    st.header("⚙️ 終端設定")
    target_stock = st.text_input("監控代碼", value="2330").upper()
    monitor_on = st.toggle("啟動 LIVE DATA", value=True)
    qty_limit = st.number_input("大單門檻", value=50)
    if st.button("🗑️ 重置數據"):
        for k in ['trades', 'alerts', 'stats']: st.session_state[k] = [] if k != 'stats' else {}
        st.session_state.last_book = None; st.rerun()

# C. 主工作區 (Placeholder 鎖定)
col_l, col_r = st.columns([2.3, 0.7])

with col_l:
    st.markdown("<h3>📈 盤中分鐘 K 線 (Aronhack 指導)</h3>", unsafe_allow_html=True)
    kline_ui = st.empty()
    
    sub_l, sub_r = st.columns(2)
    with sub_l:
        st.markdown("<h3>🏛️ 五檔即時報價 (對稱排列)</h3>", unsafe_allow_html=True)
        book_ui = st.empty()
        book_ui.dataframe(pd.DataFrame(columns=['買價','買量','賣價','賣量']), use_container_width=True)
    with sub_r:
        st.markdown("<h3>🚨 主力大單異動警告</h3>", unsafe_allow_html=True)
        alert_ui = st.empty()
        alert_ui.code("監控系統準備就緒...", language="bash")
    
    st.markdown("<h3>📊 多空分價量能統計</h3>", unsafe_allow_html=True)
    chart_ui = st.empty()
    force_ui = st.empty()

with col_right:
    st.markdown("<h3>🔔 即時成交明細</h3>", unsafe_allow_html=True)
    trade_ui = st.empty()
    trade_ui.code("Wait for trades...", language="python")

# --- 5. 數據填充循環 ---

if monitor_on:
    try:
        # 1. K 線圖
        df_k = fetch_aronhack_candles(target_stock)
        if not df_k.empty:
            kline_ui.line_chart(df_k.set_index('date')['close'], height=250)

        # 2. 獲取個股即時
        r = requests.get(f"https://api.fugle.tw/marketdata/v1.0/stock/snapshot/quotes/{target_stock}", 
                         headers={"X-API-KEY": API_KEY}, timeout=2)
        if r.status_code == 200:
            snap = r.json()
            
            # 五檔渲染
            bids = pd.DataFrame(snap.get('bids', [])).rename(columns={'price':'買價','size':'買量'})
            asks = pd.DataFrame(snap.get('asks', [])).rename(columns={'price':'賣價','size':'賣量'})
            if not bids.empty or not asks.empty:
                book_ui.dataframe(pd.concat([bids, asks], axis=1), hide_index=True, use_container_width=True)
            
            # 主力監控 (全邏輯回歸)
            curr_b = {x['price']: x['size'] for x in snap.get('bids', [])}
            curr_a = {x['price']: x['size'] for x in snap.get('asks', [])}
            if st.session_state.last_book:
                lb = st.session_state.last_book
                for p, s in curr_a.items():
                    if p in lb['a'] and abs(s - lb['a'][p]) >= qty_limit:
                        tag = "🔴 賣盤壓單" if s > lb['a'][p] else "⚪ 賣壓撤除"
                        st.session_state.alerts.insert(0, f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {p} | {tag} {abs(s-lb['a'][p])}張")
                for p, s in curr_b.items():
                    if p in lb['b'] and abs(s - lb['b'][p]) >= qty_limit:
                        tag = "🟢 買盤支撐" if s > lb['b'][p] else "⚪ 支撐撤除"
                        st.session_state.alerts.insert(0, f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {p} | {tag} {abs(s-lb['b'][p])}張")
            st.session_state.last_book = {'b': curr_b, 'a': curr_a}
            alert_ui.code("\n".join(st.session_state.alerts[:15]), language="bash")

            # 成交明細與分價
            lp, lv = snap.get('lastPrice'), snap.get('lastSize')
            if lp:
                st.session_state.trades.insert(0, f"{datetime.datetime.now().strftime('%H:%M:%S')} | {lp} | {lv}張")
                trade_ui.code("\n".join(st.session_state.trades[:50]), language="python")
                
                ps = str(lp)
                if ps not in st.session_state.stats: st.session_state.stats[ps] = {'B': 0, 'S': 0}
                b1 = snap.get('bids', [{}])[0].get('price', 0)
                if lp >= b1: st.session_state.stats[ps]['B'] += lv
                else: st.session_state.stats[ps]['S'] += lv
                
                df_st = pd.DataFrame.from_dict(st.session_state.stats, orient='index').sort_index(ascending=False)
                chart_ui.bar_chart(df_st, color=["#FF4B4B", "#00CC96"], height=250)
                
                net = df_st['B'].sum() - df_st['S'].sum()
                force_ui.metric("多空淨力道", f"{int(net)} 張", f"今日累計: {int(df_st['B'].sum()+df_st['S'].sum())}")
    except: pass
    
    time.sleep(2)
    st.rerun()
