import base64
import binascii
import os
import re
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
import zoneinfo

import pandas as pd
import streamlit as st

try:
    from fugle_marketdata import RestClient, WebSocketClient
except ImportError:
    RestClient = None
    WebSocketClient = None

try:
    import yfinance as yf
except ImportError:
    yf = None


TAIPEI_TZ = zoneinfo.ZoneInfo("Asia/Taipei")
DEFAULT_SYMBOLS = ["2330", "2317"]
MAX_RECENT_TRADES = 50
UUID_PAIR_PATTERN = re.compile(r"^[0-9a-fA-F-]{36}\s+[0-9a-fA-F-]{36}$")
BENCHMARK_SYMBOLS = [
    {"label": "台指期貨", "symbol": "IX0126.TW"},
    {"label": "日本", "symbol": "^N225"},
    {"label": "香港", "symbol": "^HSI"},
    {"label": "韓國", "symbol": "^KS11"},
    {"label": "那斯達克", "symbol": "^IXIC"},
    {"label": "標普500", "symbol": "^GSPC"},
]


def now_taipei() -> datetime:
    return datetime.now(TAIPEI_TZ)


def format_fugle_time(value: Any) -> str:
    if value in (None, ""):
        return "-"

    try:
        timestamp = float(value)
        if timestamp > 10_000_000_000_000:
            timestamp /= 1_000_000
        elif timestamp > 10_000_000_000:
            timestamp /= 1_000
        return datetime.fromtimestamp(timestamp, TAIPEI_TZ).strftime("%H:%M:%S")
    except Exception:
        return str(value)


def format_benchmark_time(value: Any) -> str:
    if value in (None, ""):
        return "-"

    try:
        ts = value if isinstance(value, pd.Timestamp) else pd.Timestamp(value)
        if ts.tzinfo is None:
            return ts.strftime("%H:%M")
        return ts.tz_convert(TAIPEI_TZ).strftime("%H:%M")
    except Exception:
        return "-"


def normalize_symbols(raw: str) -> list[str]:
    parts = [item.strip() for item in raw.replace(";", ",").split(",")]
    return [item for item in parts if item]


def mask_secret(value: str | None) -> str:
    if not value:
        return "未提供"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def normalize_fugle_api_key(raw_key: str | None) -> tuple[str | None, str]:
    if not raw_key:
        return None, "未提供 API key"

    raw_key = raw_key.strip()
    try:
        decoded = base64.b64decode(raw_key, validate=True).decode("utf-8").strip()
    except (binascii.Error, UnicodeDecodeError):
        return raw_key, "使用原始 API key"

    if UUID_PAIR_PATTERN.match(decoded):
        return decoded, "偵測到 Base64 包裝格式，已自動解碼後使用"

    return raw_key, "使用原始 API key"


def build_mock_snapshot(symbols: list[str]) -> dict[str, dict[str, Any]]:
    snapshots: dict[str, dict[str, Any]] = {}
    base_prices = {
        "2330": 812.0,
        "2317": 149.5,
        "0050": 193.2,
        "2454": 1220.0,
    }
    for idx, symbol in enumerate(symbols):
        base = base_prices.get(symbol, 100.0 + idx * 10)
        bids = [{"price": round(base - 0.5 - i * 0.5, 2), "size": 100 * (i + 1)} for i in range(5)]
        asks = [{"price": round(base + 0.5 + i * 0.5, 2), "size": 120 * (i + 1)} for i in range(5)]
        trades = deque(
            [
                {
                    "time": now_taipei().timestamp(),
                    "price": round(base + (i % 3 - 1) * 0.5, 2),
                    "size": 100 * (i + 1),
                    "bid": bids[0]["price"],
                    "ask": asks[0]["price"],
                    "volume": 1000 + i * 100,
                    "serial": i + 1,
                }
                for i in range(10)
            ],
            maxlen=MAX_RECENT_TRADES,
        )
        snapshots[symbol] = {
            "book": {"symbol": symbol, "bids": bids, "asks": asks, "time": now_taipei().timestamp()},
            "trades": trades,
            "last_trade": trades[-1],
        }
    return snapshots


@st.cache_data(ttl=15, show_spinner=False)
def test_rest_quote(api_key: str, symbol: str) -> dict[str, Any]:
    if RestClient is None:
        return {
            "ok": False,
            "message": "RestClient 不可用，fugle-marketdata 套件可能未正確安裝。",
            "data": None,
        }

    try:
        client = RestClient(api_key=api_key)
        quote = client.stock.intraday.quote(symbol=symbol)
        return {
            "ok": True,
            "message": f"REST 測試成功：已取得 {symbol} 報價。",
            "data": quote,
        }
    except Exception as exc:
        return {
            "ok": False,
            "message": f"REST 測試失敗：{exc}",
            "data": None,
        }


@st.cache_data(ttl=30, show_spinner=False)
def fetch_benchmark_data() -> dict[str, Any]:
    if yf is None:
        return {
            "ok": False,
            "message": "yfinance 套件未安裝，無法載入全球指數。",
            "items": [],
        }

    items: list[dict[str, Any]] = []
    failures: list[str] = []

    for config in BENCHMARK_SYMBOLS:
        label = config["label"]
        symbol = config["symbol"]
        try:
            ticker = yf.Ticker(symbol)
            history = ticker.history(period="2d", interval="1m", auto_adjust=False, prepost=True)
            if history.empty:
                history = ticker.history(period="5d", interval="1d", auto_adjust=False)

            close_series = history["Close"].dropna()
            if close_series.empty:
                raise ValueError("查無價格資料")

            last_price = float(close_series.iloc[-1])
            previous_close = None
            fast_info = getattr(ticker, "fast_info", None)
            if fast_info:
                previous_close = fast_info.get("previousClose") or fast_info.get("previous_close")

            if previous_close in (None, 0):
                previous_close = float(close_series.iloc[-2]) if len(close_series) >= 2 else last_price

            change = last_price - float(previous_close)
            change_pct = 0.0 if previous_close == 0 else (change / float(previous_close)) * 100
            timestamp = close_series.index[-1]

            items.append(
                {
                    "label": label,
                    "symbol": symbol,
                    "price": round(last_price, 2),
                    "change": round(change, 2),
                    "change_pct": round(change_pct, 2),
                    "time": format_benchmark_time(timestamp),
                }
            )
        except Exception as exc:
            failures.append(f"{label}: {exc}")
            items.append(
                {
                    "label": label,
                    "symbol": symbol,
                    "price": None,
                    "change": None,
                    "change_pct": None,
                    "time": "-",
                }
            )

    message = "全球指數載入成功。"
    if failures:
        message = "部分全球指數載入失敗：" + " | ".join(failures[:3])

    return {
        "ok": len(failures) < len(BENCHMARK_SYMBOLS),
        "message": message,
        "items": items,
    }


@dataclass
class SymbolState:
    book: dict[str, Any] | None = None
    last_trade: dict[str, Any] | None = None
    trades: deque = field(default_factory=lambda: deque(maxlen=MAX_RECENT_TRADES))


class FugleRealtimeStore:
    def __init__(self, api_key: str | None):
        self.api_key = api_key
        self.lock = threading.Lock()
        self.connection_ready = threading.Event()
        self.auth_ready = threading.Event()
        self.states: dict[str, SymbolState] = defaultdict(SymbolState)
        self.subscriptions: set[tuple[str, str]] = set()
        self.pending_subscriptions: set[tuple[str, str]] = set()
        self.started = False
        self.connected = False
        self.authenticated = False
        self.error_message: str | None = None
        self.last_event_at: datetime | None = None
        self.last_status_message: str | None = None
        self.client = None
        self.stock = None

    def ensure_started(self) -> None:
        if self.started or not self.api_key or WebSocketClient is None:
            return

        self.started = True
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        try:
            self.client = WebSocketClient(api_key=self.api_key)
            self.stock = self.client.stock
            self.stock.on("connect", self._handle_connect)
            self.stock.on("disconnect", self._handle_disconnect)
            self.stock.on("error", self._handle_error)
            self.stock.on("message", self._handle_message)
            self.stock.connect()
        except Exception as exc:
            with self.lock:
                self.connected = False
                self.authenticated = False
                self.error_message = f"WebSocket 啟動失敗：{exc}"
                self.last_status_message = "WebSocket 啟動例外"
            self.connection_ready.clear()
            self.auth_ready.clear()

    def _handle_connect(self) -> None:
        with self.lock:
            self.connected = True
            self.last_status_message = "WebSocket 已建立，等待驗證"
            if self.error_message == "正在建立 WebSocket 連線，請稍候。":
                self.error_message = None
        self.connection_ready.set()

    def _handle_disconnect(self, code: Any, message: Any) -> None:
        with self.lock:
            self.connected = False
            self.authenticated = False
            self.error_message = f"連線中斷：{code} {message}"
            self.last_status_message = "WebSocket 已中斷"
        self.connection_ready.clear()
        self.auth_ready.clear()

    def _handle_error(self, error: Any) -> None:
        with self.lock:
            self.error_message = f"行情資料錯誤：{error}"
            self.last_status_message = "收到 error 事件"

    def _handle_message(self, message: Any) -> None:
        payload = message
        if isinstance(message, str):
            try:
                import json
                payload = json.loads(message)
            except Exception:
                return

        event = payload.get("event")

        if event == "authenticated":
            with self.lock:
                self.authenticated = True
                self.error_message = None
                self.last_status_message = "API key 驗證成功"
            self.auth_ready.set()
            self._flush_pending_subscriptions()
            return

        if event == "heartbeat":
            with self.lock:
                self.last_event_at = now_taipei()
                self.last_status_message = "收到 heartbeat"
            return

        if event == "error":
            error_data = payload.get("data", {})
            error_message = error_data.get("message") or str(error_data) or "未知錯誤"
            with self.lock:
                self.error_message = f"Fugle 驗證或訂閱錯誤：{error_message}"
                self.last_status_message = "收到 error 事件"
                if "Invalid authentication credentials" in error_message:
                    self.authenticated = False
            self.auth_ready.clear()
            return

        if event != "data":
            return

        channel = payload.get("channel")
        data = payload.get("data", {})
        symbol = data.get("symbol")
        if not symbol:
            return

        with self.lock:
            state = self.states[symbol]
            self.last_event_at = now_taipei()
            self.last_status_message = f"收到 {channel} 資料"
            if channel == "books":
                state.book = data
            elif channel == "trades":
                state.last_trade = data
                state.trades.appendleft(data)

    def _safe_subscribe(self, channel: str, symbol: str) -> bool:
        if self.stock is None:
            return False

        try:
            self.stock.subscribe({"channel": channel, "symbol": symbol})
            return True
        except Exception as exc:
            with self.lock:
                self.connected = False
                self.error_message = f"訂閱失敗：{channel} {symbol} - {exc}"
                self.last_status_message = "送出訂閱時發生例外"
            self.connection_ready.clear()
            self.auth_ready.clear()
            return False

    def _flush_pending_subscriptions(self) -> None:
        with self.lock:
            if not self.connected or not self.authenticated:
                return
            pending_items = list(self.pending_subscriptions)

        for channel, symbol in pending_items:
            if self._safe_subscribe(channel, symbol):
                with self.lock:
                    self.pending_subscriptions.discard((channel, symbol))
                    self.subscriptions.add((channel, symbol))
            else:
                break

    def subscribe_symbols(self, symbols: list[str]) -> None:
        if not self.api_key or WebSocketClient is None:
            return

        self.ensure_started()
        for symbol in symbols:
            for channel in ("books", "trades"):
                key = (channel, symbol)
                with self.lock:
                    if key in self.subscriptions:
                        continue
                    self.pending_subscriptions.add(key)

        if self.stock is None:
            with self.lock:
                if self.error_message is None:
                    self.error_message = "正在初始化 Fugle SDK，請稍候。"
                    self.last_status_message = "等待 SDK 建立 stock client"
            return

        if not self.connection_ready.wait(timeout=1.0):
            with self.lock:
                if self.error_message is None:
                    self.error_message = "正在建立 WebSocket 連線，請稍候。"
                    self.last_status_message = "等待 WebSocket connect"
            return

        if not self.auth_ready.wait(timeout=2.0):
            with self.lock:
                if self.error_message is None:
                    self.error_message = "WebSocket 已連線，但尚未完成 API 驗證。"
                    self.last_status_message = "等待 authenticated 事件"
            return

        self._flush_pending_subscriptions()

    def snapshot(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        with self.lock:
            result: dict[str, dict[str, Any]] = {}
            for symbol in symbols:
                state = self.states[symbol]
                result[symbol] = {
                    "book": state.book,
                    "last_trade": state.last_trade,
                    "trades": list(state.trades),
                }
            return result

    def status(self) -> dict[str, Any]:
        with self.lock:
            return {
                "connected": self.connected,
                "authenticated": self.authenticated,
                "error_message": self.error_message,
                "last_event_at": self.last_event_at,
                "last_status_message": self.last_status_message,
                "subscriptions": len(self.subscriptions),
                "pending_subscriptions": len(self.pending_subscriptions),
            }


@st.cache_resource
def get_store(api_key: str | None) -> FugleRealtimeStore:
    store = FugleRealtimeStore(api_key)
    store.ensure_started()
    return store


def render_order_book(symbol: str, book: dict[str, Any] | None) -> None:
    st.subheader(f"{symbol} 五檔委買委賣")
    if not book:
        st.info("尚未收到五檔資料。")
        return

    bids = book.get("bids", [])
    asks = book.get("asks", [])
    rows = []
    for idx in range(max(len(bids), len(asks), 5)):
        bid = bids[idx] if idx < len(bids) else {}
        ask = asks[idx] if idx < len(asks) else {}
        rows.append(
            {
                "委買量": bid.get("size", ""),
                "委買價": bid.get("price", ""),
                "委賣價": ask.get("price", ""),
                "委賣量": ask.get("size", ""),
            }
        )
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    st.caption(f"更新時間：{format_fugle_time(book.get('time'))}")


def render_trade_summary(symbol: str, trade: dict[str, Any] | None) -> None:
    st.subheader(f"{symbol} 最新成交")
    if not trade:
        st.info("尚未收到成交資料。")
        return

    cols = st.columns(4)
    cols[0].metric("成交價", trade.get("price", "-"))
    cols[1].metric("成交量", trade.get("size", "-"))
    cols[2].metric("累積量", trade.get("volume", "-"))
    cols[3].metric("時間", format_fugle_time(trade.get("time")))


def render_trade_tape(trades: list[dict[str, Any]]) -> None:
    st.subheader("即時成交明細")
    if not trades:
        st.info("尚未收到即時成交明細。")
        return

    trade_rows = list(trades)[:20]
    rows = [
        {
            "時間": format_fugle_time(item.get("time")),
            "成交價": item.get("price"),
            "成交量": item.get("size"),
            "買價": item.get("bid"),
            "賣價": item.get("ask"),
            "累積量": item.get("volume"),
            "序號": item.get("serial"),
        }
        for item in trade_rows
    ]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def get_raw_api_key() -> tuple[str | None, str]:
    if "FUGLE_API_KEY" in st.secrets:
        return st.secrets["FUGLE_API_KEY"], "Streamlit secrets"
    env_value = os.getenv("FUGLE_API_KEY")
    if env_value:
        return env_value, "環境變數"
    return None, "未載入"


def render_sidebar_benchmark_section(benchmark_result: dict[str, Any]) -> None:
    st.markdown("---")
    st.subheader("全球指數")
    st.caption("國際市場參考，可能為延遲報價。")

    for item in benchmark_result.get("items", []):
        label = item.get("label", "-")
        price = item.get("price")
        change = item.get("change")
        change_pct = item.get("change_pct")
        symbol = item.get("symbol", "-")
        timestamp = item.get("time", "-")

        if price is None:
            price_text = "-"
            delta = "資料暫缺"
        else:
            sign = "+" if change is not None and change > 0 else ""
            delta = f"{sign}{change:,.2f} ({sign}{change_pct:.2f}%)" if change is not None and change_pct is not None else "-"
            price_text = f"{price:,.2f}"

        st.metric(label, price_text, delta=delta)
        st.caption(f"{timestamp} | {symbol}")

    if benchmark_result.get("message"):
        st.caption(benchmark_result["message"])


st.set_page_config(page_title="台股即時監控台", page_icon=":bar_chart:", layout="wide")

st.title("台股即時監控台")
st.caption("使用 Streamlit 製作的台股五檔委買委賣與即時成交明細監控頁面。")

with st.sidebar:
    st.header("監控設定")
    symbols_raw = st.text_input("股票代碼", value=", ".join(DEFAULT_SYMBOLS), help="請用逗號分隔，例如：2330, 2317")
    symbols = normalize_symbols(symbols_raw) or DEFAULT_SYMBOLS
    refresh_seconds = st.slider("刷新秒數", min_value=1, max_value=10, value=1)
    st.caption("Fugle 免費方案有訂閱數限制，每個股票代碼會同時使用 books 與 trades 兩個頻道。")

raw_api_key, api_key_source = get_raw_api_key()
api_key, api_key_note = normalize_fugle_api_key(raw_api_key)
using_mock = not api_key or WebSocketClient is None
benchmark_result = fetch_benchmark_data()

with st.sidebar:
    render_sidebar_benchmark_section(benchmark_result)

if using_mock:
    st.warning("目前為示範模式。請在 Streamlit secrets 設定 FUGLE_API_KEY 後切換為即時行情。")
    snapshots = build_mock_snapshot(symbols)
    status = {
        "connected": False,
        "authenticated": False,
        "error_message": None if WebSocketClient is not None else "尚未安裝 fugle-marketdata 套件。",
        "last_event_at": now_taipei(),
        "last_status_message": "示範模式",
        "subscriptions": 0,
        "pending_subscriptions": 0,
    }
    rest_result = {
        "ok": False,
        "message": "示範模式下不執行 REST 測試。",
        "data": None,
    }
else:
    store = get_store(api_key)
    store.subscribe_symbols(symbols)
    snapshots = store.snapshot(symbols)
    status = store.status()
    rest_result = test_rest_quote(api_key, symbols[0])

status_cols = st.columns(6)
status_cols[0].metric("模式", "即時" if not using_mock else "示範")
status_cols[1].metric("連線", "已連線" if status.get("connected") else "未連線")
status_cols[2].metric("驗證", "成功" if status.get("authenticated") else "未完成")
status_cols[3].metric("已訂閱", status.get("subscriptions", 0))
status_cols[4].metric("待訂閱", status.get("pending_subscriptions", 0))
status_cols[5].metric(
    "最後事件",
    status["last_event_at"].strftime("%H:%M:%S") if status.get("last_event_at") else "-",
)

if status.get("error_message"):
    st.error(status["error_message"])

with st.expander("連線診斷"):
    st.write(f"API key 來源：{api_key_source}")
    st.write(f"API key 狀態：{mask_secret(raw_api_key)}")
    st.write(f"API key 處理：{api_key_note}")
    st.write(f"目前模式：{'即時' if not using_mock else '示範'}")
    st.write(f"連線狀態：{'已連線' if status.get('connected') else '未連線'}")
    st.write(f"驗證狀態：{'成功' if status.get('authenticated') else '未完成'}")
    st.write(f"狀態訊息：{status.get('last_status_message') or '-'}")
    st.write(f"錯誤訊息：{status.get('error_message') or '-'}")

with st.expander("REST 測試"):
    st.write(f"測試標的：{symbols[0] if symbols else DEFAULT_SYMBOLS[0]}")
    st.write(f"測試結果：{'成功' if rest_result.get('ok') else '失敗'}")
    st.write(f"訊息：{rest_result.get('message')}")
    if rest_result.get("ok") and rest_result.get("data"):
        st.json(rest_result["data"])

tabs = st.tabs(symbols)
for tab, symbol in zip(tabs, symbols):
    with tab:
        if not using_mock:
            current_snapshots = store.snapshot([symbol])
            symbol_data = current_snapshots.get(symbol, {})
        else:
            symbol_data = snapshots.get(symbol, {})

        left_col, right_col = st.columns([1, 1])
        with left_col:
            render_order_book(symbol, symbol_data.get("book"))
        with right_col:
            render_trade_summary(symbol, symbol_data.get("last_trade"))
        render_trade_tape(symbol_data.get("trades", []))

if refresh_seconds > 0:
    time.sleep(refresh_seconds)
    st.rerun()

with st.expander("部署說明"):
    st.markdown(
        """
        - 本系統使用官方 `fugle-marketdata` Python SDK 串接台股即時行情。
        - 原始碼可放在 GitHub，並由 Streamlit Community Cloud 直接部署。
        - 若你要對外公開此服務，請先確認行情資料的授權與使用規範是否符合需求。
        """
    )
