import streamlit as st
import pandas as pd
import datetime
import time
import requests
import yfinance as yf

# --- 1. 專業介面配置 ---
st.set_page_config(page_title="Alpha-Trader Terminal v8.0", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #0D1117; }
    .stMetric { background: #161B22; padding: 15px; border-radius: 10px; border: 1px solid #30363D; }
    [data-testid="stMetricValue"] { font-size: 26px !important; color: #58A6FF !important; }
    .stCodeBlock { border: 1px solid #30363D !important; background-color: #010409 !important; }
    h3 { color: #8B949E; font-size: 14px !important; font-weight: 600; border-left: 3px solid #58A6FF; padding-left: 8px; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 核心初始化 ---
API_KEY = "MWI2Y2NlMTYtZmNjNy00NGJmLWFkMTYtNDVjZjk2MjJkNzFhIDA1YTliNzZhLWI0NzItNGYxMS1iYTIxLWYyN2ZkNjgzNzI5YQ=="

if 'mkt_cache' not in st.session_state:
    st.session_state.mkt_cache = {k: {"p": "--", "pct": "0.00"} for k in ["台指期", "加權指數", "TSM(ADR)", "日經 225", "標普 500"]}

# --- 3. 數據救援引擎 (確保指數絕不掛點) ---

def fetch_fugle_realtime(symbol, is_futures=False):
    """精準區分期貨與指數路徑"""
    headers = {"X-API-KEY": API_KEY}
    base = "futures" if is_futures else "stock"
    url = f"https://api.fugle.tw/marketdata/v1.0/{base}/snapshot/quotes/{symbol}"
    try:
        r = requests.get(url, headers=headers, timeout=2)
        if r.status_code == 200:
            d = r.json()
            return {"p": d.get('lastPrice'), "pct": d.get('changePercent')}
    except: return None
    return None

def fetch_yahoo_fallback(symbol):
    """當富果 API 沒數據時，自動切換 Yahoo 備援"""
    try:
        t = yf.Ticker(symbol)
        df = t.history(period="1d")
        if not df.empty:
            p = df['Close'].iloc[-1]
            prev = t.info.get('previousClose', p)
            pct = ((p - prev) / prev) * 100
            return {"p": p, "pct": pct}
    except: return None
    return None

def sync_all_indices():
    # A. 台指期 (優先 Fugle TXFR, 失敗則轉 Yahoo WTX=F)
    res = fetch_fugle_realtime("TXFR", is_futures=True)
    if not res or res['p'] is None: res = fetch_yahoo_fallback("WTX=F")
    if res: st.session_state.mkt_cache["台指期"] = {"p": f"{res['p']:.0f}", "pct": f"{res['pct']:.2f}"}

    # B. 加權指數 (優先 Fugle IX0001, 失敗則轉 Yahoo ^TWII)
    res = fetch_fugle_realtime("IX0001")
    if not res or res['p'] is None: res = fetch_yahoo_fallback("^TWII")
    if res: st.session_state.mkt_cache["加權指數"] = {"p": f"{res['p']:.0f}", "pct": f"{res['pct']:.2f}"}

    # C. 全球指標 (直接使用 Yahoo)
    global_map = {"TSM(ADR)": "TSM", "日經 225": "^N225", "標普 500": "^GSPC"}
    for label, sym in global_map.items():
        res = fetch_yahoo_fallback(sym)
        if res: st.session_state.mkt_cache[label] = {"p": f"{res['p']:.2f}" if "ADR" in label else f"{res['p']:.0f}", "pct": f"{res['pct']:.2f}"}

# --- 4. UI 框架渲染 ---

st.markdown("## 🏛️ Alpha-Trader <span style='color:#58A6FF'>Professional Terminal v8.0</span>", unsafe_allow_html=True)

# 頂部狀態列
sync_all_indices()
idx_cols = st.columns(5)
for i, label in enumerate(["台指期", "加權指數", "TSM(ADR)", "日經 225", "標普 500"]):
    idx_cols[i].metric(label, st.session_state.mkt_cache[label]["p"], f"{st.session_state.mkt_cache[label]['pct']}%")

st.divider()

# 核心功能區佈局
col_l, col_r = st.columns([2.2, 0.8])

with col_l:
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("<h3>🏛️ 五檔即時報價 (買價/買量/賣價/賣量)</h3>", unsafe_allow_html=True)
        book_ui = st.empty()
    with c2:
        st.markdown("<h3>🚨 主力大單異動</h3>", unsafe_allow_html=True)
        alert_ui = st.empty()
    
    st.markdown("<h3>📊 多空分價與成交走勢</h3>", unsafe_allow_html=True)
    chart_ui = st.empty()
    force_ui = st.empty()

with col_r:
    st.markdown("<h3>🔔 即時成交明細</h3>", unsafe_allow_html=True)
    trade_ui = st.empty()

# --- 5. 監控循環 ---

target_no = st.sidebar.text_input("監控代碼", value="2330").upper()
monitor_on = st.sidebar.toggle("啟動即時傳輸", value=True)

if monitor_on:
    try:
        # 獲取個股 Snapshot
        r = requests.get(f"https://api.fugle.tw/marketdata/v1.0/stock/snapshot/quotes/{target_no}", 
                         headers={"X-API-KEY": API_KEY}, timeout=2)
        if r.status_code == 200:
            snap = r.json()
            
            # 1. 修正五檔顯示 (對稱排列)
            bids = pd.DataFrame(snap.get('bids', [])).rename(columns={'price':'買價','size':'買量'})
            asks = pd.DataFrame(snap.get('asks', [])).rename(columns={'price':'賣價','size':'賣量'})
            book_ui.dataframe(pd.concat([bids, asks], axis=1), hide_index=True, use_container_width=True)
            
            # 2. 更新明細與力道
            lp, lv = snap.get('lastPrice'), snap.get('lastSize')
            if lp:
                trade_txt = f"{datetime.datetime.now().strftime('%H:%M:%S')} | {lp} | {lv}張"
                st.session_state.setdefault('trades', []).insert(0, trade_txt)
                trade_ui.code("\n".join(st.session_state['trades'][:40]), language="python")
    except: pass
    
    time.sleep(2)
    st.rerun()
