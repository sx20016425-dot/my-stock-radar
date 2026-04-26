def merge_symbol_snapshot(rest_snapshot: dict[str, Any] | None, stream_snapshot: dict[str, Any] | None) -> dict[str, Any]:
    rest_snapshot = rest_snapshot or {}
    stream_snapshot = stream_snapshot or {}
    return {
        "book": stream_snapshot.get("book") or rest_snapshot.get("book"),
        "last_trade": stream_snapshot.get("last_trade") or rest_snapshot.get("last_trade"),
        "trades": stream_snapshot.get("trades") or rest_snapshot.get("trades", []),
        "signal_events": stream_snapshot.get("signal_events") or rest_snapshot.get("signal_events", []),
        "book_summary": stream_snapshot.get("book_summary") or rest_snapshot.get("book_summary"),
        "open_trade": stream_snapshot.get("open_trade") or rest_snapshot.get("open_trade"),
        "session_high": stream_snapshot.get("session_high") or rest_snapshot.get("session_high"),
        "session_low": stream_snapshot.get("session_low") or rest_snapshot.get("session_low"),
        "trade_history": stream_snapshot.get("trade_history") or rest_snapshot.get("trade_history", []),
        "quote_data": stream_snapshot.get("quote_data") or rest_snapshot.get("quote_data"),
    }


def build_symbol_tab_labels(symbols: list[str], rest_snapshots: dict[str, dict[str, Any]], fallback_snapshots: dict[str, dict[str, Any]]) -> list[str]:
    labels: list[str] = []
    for symbol in symbols:
        quote_data = (rest_snapshots.get(symbol) or {}).get("quote_data") or (fallback_snapshots.get(symbol) or {}).get("quote_data") or {}
        name = quote_data.get("name") or SYMBOL_NAME_HINTS.get(symbol, "")
        labels.append(f"{symbol} {name}" if name else symbol)
    return labels


st.set_page_config(page_title="台股即時監控台", page_icon=":bar_chart:", layout="wide")
inject_custom_css()
ensure_log_dirs()

if "access_granted" not in st.session_state:
    st.session_state["access_granted"] = False
if "access_key_masked" not in st.session_state:
    st.session_state["access_key_masked"] = ""
if "access_role" not in st.session_state:
    st.session_state["access_role"] = ""

st.title("台股即時監控台")
st.caption("使用 Streamlit 製作的台股五檔委買委賣、即時成交、開盤追蹤、異常訊號與盤中資料落地監控頁面。")

with st.sidebar:
    st.header("監控設定")
    symbols_raw = st.text_input("股票代碼", value=", ".join(DEFAULT_SYMBOLS), help="請用逗號分隔，例如：2330, 2317")
    symbols = normalize_symbols(symbols_raw) or DEFAULT_SYMBOLS
    refresh_seconds = st.slider("刷新秒數", min_value=0.2, max_value=10.0, value=0.5, step=0.1)
    source_mode = st.selectbox("資料源模式", ["自動", "Fugle", "示範資料"], index=0)
    st.caption("Fugle 免費方案有訂閱數限制，每個股票代碼會同時使用 books 與 trades 兩個頻道。刷新過快可能讓 Streamlit Cloud 比較吃資源。")

raw_api_key, api_key_source = get_raw_api_key()
api_key, api_key_note = normalize_fugle_api_key(raw_api_key)
benchmark_result = fetch_benchmark_data()
index_signal_events = update_index_shock_signals(benchmark_result)
market_state = resolve_market_source(source_mode, api_key, symbols)

with st.sidebar:
    render_sidebar_benchmark_section(benchmark_result)

status = market_state["status"]
rest_result = market_state["rest_result"]
rest_snapshots = market_state["rest_snapshots"]
fallback_snapshots = market_state["snapshots"]
using_demo = market_state["using_demo"]
store = market_state["store"]

if using_demo:
    st.warning("目前使用示範資料模式。當 Fugle 驗證通過後，會自動回到即時行情。")

status_cols = st.columns(6)
status_cols[0].metric("模式", "示範" if using_demo else "即時")
status_cols[1].metric("資料源", market_state["source_name"])
status_cols[2].metric("連線", "已連線" if status.get("connected") else "未連線")
status_cols[3].metric("驗證", "成功" if status.get("authenticated") else "未完成")
status_cols[4].metric("已訂閱", status.get("subscriptions", 0))
status_cols[5].metric("最後事件", status["last_event_at"].strftime("%H:%M:%S") if status.get("last_event_at") else "-")

if status.get("error_message"):
    st.error(status["error_message"])

with st.expander("連線診斷"):
    st.write(f"API key 來源：{api_key_source}")
    st.write(f"API key 狀態：{mask_secret(raw_api_key)}")
    st.write(f"API key 處理：{api_key_note}")
    st.write(f"資料源模式：{source_mode}")
    st.write(f"實際資料源：{market_state['source_name']}")
    st.write(f"目前模式：{'示範' if using_demo else '即時'}")
    st.write(f"連線狀態：{'已連線' if status.get('connected') else '未連線'}")
    st.write(f"驗證狀態：{'成功' if status.get('authenticated') else '未完成'}")
    st.write(f"狀態訊息：{status.get('last_status_message') or '-'}")
    st.write(f"錯誤訊息：{status.get('error_message') or '-'}")
    st.write(f"系統判斷：{market_state['diagnostic_note']}")
    st.write(f"資料落地目錄：{DATA_LOG_DIR}")

with st.expander("REST 測試"):
    st.write(f"測試標的：{symbols[0] if symbols else DEFAULT_SYMBOLS[0]}")
    st.write(f"測試結果：{'成功' if rest_result.get('ok') else '失敗'}")
    st.write(f"訊息：{rest_result.get('message')}")
    if rest_result.get("ok") and rest_result.get("data"):
        st.json(rest_result["data"])

tab_labels = build_symbol_tab_labels(symbols, rest_snapshots, fallback_snapshots)
tabs = st.tabs(tab_labels)
for tab, symbol in zip(tabs, symbols):
    with tab:
        if using_demo:
            symbol_data = fallback_snapshots.get(symbol, {})
        else:
            stream_snapshot = store.snapshot([symbol]).get(symbol, {}) if store is not None else {}
            rest_snapshot = rest_snapshots.get(symbol, {})
            symbol_data = merge_symbol_snapshot(rest_snapshot, stream_snapshot)

        with st.container(border=True):
            render_index_signal_panel(benchmark_result, index_signal_events)

        with st.container(border=True):
            render_signal_panel(symbol, symbol_data.get("signal_events", []))

        with st.container():
            row_one_left, row_one_mid, row_one_right = st.columns([1.2, 1.2, 1.0])

            with row_one_left:
                with st.container(border=True):
                    render_order_book(symbol, symbol_data.get("book"))
            with row_one_mid:
                with st.container(border=True):
                    render_trade_tape(symbol_data.get("trades", []))
            with row_one_right:
                with st.container(border=True):
                    render_decision_panel(symbol, symbol_data, index_signal_events)

        row_two_left, row_two_right = st.columns([1, 1])
        with row_two_left:
            with st.container(border=True):
                render_trade_summary(symbol, symbol_data.get("last_trade"), symbol_data.get("quote_data"))
        with row_two_right:
            with st.container(border=True):
                render_opening_panel(symbol, symbol_data)

        with st.container(border=True):
            render_book_summary(symbol_data.get("book_summary"), symbol_data.get("trade_history", []))

if refresh_seconds > 0:
    time.sleep(refresh_seconds)
    st.rerun()
