import base64
import binascii
import csv
import os
import re
import threading
import time
from collections.abc import Mapping
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
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
MAX_BOOK_HISTORY = 300
MAX_TRADE_HISTORY = 2000
MAX_SIGNAL_EVENTS = 100
BENCHMARK_STALE_SECONDS = 300
UUID_PAIR_PATTERN = re.compile(r"^[0-9a-fA-F-]{36}\s+[0-9a-fA-F-]{36}$")
TOP_LEVEL_MONITOR_COUNT = 3
LEVEL_ABS_DELTA_THRESHOLD = 300
LEVEL_RATIO_UP_THRESHOLD = 1.8
LEVEL_RATIO_DOWN_THRESHOLD = 0.45

APP_DIR = Path(__file__).resolve().parent
DATA_LOG_DIR = APP_DIR / "data_logs"
TICK_LOG_DIR = DATA_LOG_DIR / "ticks"
BOOK_LOG_DIR = DATA_LOG_DIR / "books"
SIGNAL_LOG_DIR = DATA_LOG_DIR / "signals"

ORDER_BOOK_HEIGHT = 250
TRADE_TAPE_HEIGHT = 280
SIGNAL_PANEL_HEIGHT = 280
OPEN_PANEL_HEIGHT = 180
SUMMARY_PANEL_HEIGHT = 180

BENCHMARK_SYMBOLS = [
    {"label": "?啁???", "symbol": "^TWII", "note": "?曇疏???},
    {"label": "?亦?225", "symbol": "^N225", "note": "?曇疏???},
    {"label": "???", "symbol": "^HSI", "note": "?曇疏???},
    {"label": "??KOSPI", "symbol": "^KS11", "note": "?曇疏???},
    {"label": "????疏??, "symbol": "NQ=F", "note": "?疏??},
    {"label": "璅?疏??, "symbol": "ES=F", "note": "?疏??},
]

LOGIN_HELP_TEXT = "隢撓?乩??貊??亙????撽????⊥??亦???鞈???


def inject_custom_css() -> None:
    st.markdown(
        """
        <style>
        [data-baseweb="tab-list"] button {
            font-size: 18px !important;
            font-weight: 700 !important;
            min-height: 48px !important;
            padding: 10px 18px !important;
        }
        [data-testid="stMetricValue"] {
            font-size: 1.8rem !important;
        }
        .panel-title {
            font-size: 1.2rem;
            font-weight: 700;
            margin-bottom: 0.6rem;
        }
        .panel-shell {
            border: 1px solid rgba(128,128,128,0.25);
            border-radius: 14px;
            padding: 0.85rem 0.95rem 0.55rem 0.95rem;
            background: rgba(255,255,255,0.02);
            min-height: 100%;
        }
        .placeholder-box {
            height: 170px;
            display: flex;
            align-items: center;
            justify-content: center;
            text-align: center;
            border: 1px dashed rgba(128,128,128,0.35);
            border-radius: 12px;
            color: rgba(250,250,250,0.7);
            background: rgba(255,255,255,0.02);
            padding: 0.8rem;
        }
        .placeholder-box.tall {
            height: 215px;
        }
        .placeholder-box.medium {
            height: 150px;
        }
        .login-shell {
            max-width: 520px;
            margin: 4rem auto 0 auto;
            border: 1px solid rgba(128,128,128,0.25);
            border-radius: 18px;
            padding: 1.2rem 1.2rem 1rem 1.2rem;
            background: rgba(255,255,255,0.03);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def now_taipei() -> datetime:
    return datetime.now(TAIPEI_TZ)


def today_taipei_str() -> str:
    return now_taipei().strftime("%Y%m%d")


def ensure_log_dirs() -> None:
    for path in (DATA_LOG_DIR, TICK_LOG_DIR, BOOK_LOG_DIR, SIGNAL_LOG_DIR):
        path.mkdir(parents=True, exist_ok=True)


def append_csv_row(path: Path, fieldnames: list[str], row: dict[str, Any]) -> None:
    ensure_log_dirs()
    file_exists = path.exists()
    with path.open("a", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow({key: row.get(key, "") for key in fieldnames})


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
            return ts.strftime("%H:%M:%S")
        return ts.tz_convert(TAIPEI_TZ).strftime("%H:%M:%S")
    except Exception:
        return "-"


def benchmark_age_seconds(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        ts = value if isinstance(value, pd.Timestamp) else pd.Timestamp(value)
        if ts.tzinfo is None:
            ts = ts.tz_localize(TAIPEI_TZ)
        else:
            ts = ts.tz_convert(TAIPEI_TZ)
        return max(0.0, (now_taipei() - ts.to_pydatetime()).total_seconds())
    except Exception:
        return None


def normalize_symbols(raw: str) -> list[str]:
    parts = [item.strip() for item in raw.replace(";", ",").replace("嚗?, ",").split(",")]
    return [item for item in parts if item]


def mask_secret(value: str | None) -> str:
    if not value:
        return "?芣?靘?
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def normalize_fugle_api_key(raw_key: str | None) -> tuple[str | None, str]:
    if not raw_key:
        return None, "?芣?靘?API key"

    raw_key = raw_key.strip()
    try:
        decoded = base64.b64decode(raw_key, validate=True).decode("utf-8").strip()
    except (binascii.Error, UnicodeDecodeError):
        return raw_key, "雿輻?? API key"

    if UUID_PAIR_PATTERN.match(decoded):
        return raw_key, "?菜葫??Base64 憭?嚗?靘?Fugle 摰?辣?寧靽??? API key嚗??圾蝣?

    return raw_key, "雿輻?? API key"


def get_raw_api_key() -> tuple[str | None, str]:
    if "FUGLE_API_KEY" in st.secrets:
        return st.secrets["FUGLE_API_KEY"], "Streamlit secrets"
    env_value = os.getenv("FUGLE_API_KEY")
    if env_value:
        return env_value, "?啣?霈"
    return None, "?芾???


def get_access_key_config() -> tuple[set[str], str]:
    raw = None
    source = "?芾身摰?
    if "ACCESS_KEYS" in st.secrets:
        raw = st.secrets["ACCESS_KEYS"]
        source = "Streamlit secrets"
    else:
        env_value = os.getenv("ACCESS_KEYS")
        if env_value:
            raw = env_value
            source = "?啣?霈"

    allowed_keys: set[str] = set()
    if isinstance(raw, (list, tuple)):
        allowed_keys = {str(item).strip() for item in raw if str(item).strip()}
    elif isinstance(raw, Mapping):
        allowed_keys = {
            str(key).strip()
            for key, value in raw.items()
            if str(key).strip() and str(value).strip().lower() in {"active", "enabled", "true", "1", "yes"}
        }
    elif hasattr(raw, "items"):
        allowed_keys = {
            str(key).strip()
            for key, value in raw.items()
            if str(key).strip() and str(value).strip().lower() in {"active", "enabled", "true", "1", "yes"}
        }
    elif isinstance(raw, str):
        parts = [item.strip() for item in raw.replace(";", ",").replace("\n", ",").split(",")]
        allowed_keys = {item for item in parts if item}

    return allowed_keys, source


def get_admin_access_key_config() -> tuple[set[str], str]:
    raw = None
    source = "?芾身摰?
    if "ADMIN_ACCESS_KEYS" in st.secrets:
        raw = st.secrets["ADMIN_ACCESS_KEYS"]
        source = "Streamlit secrets"
    else:
        env_value = os.getenv("ADMIN_ACCESS_KEYS")
        if env_value:
            raw = env_value
            source = "?啣?霈"

    admin_keys: set[str] = set()
    if isinstance(raw, (list, tuple)):
        admin_keys = {str(item).strip() for item in raw if str(item).strip()}
    elif isinstance(raw, Mapping):
        admin_keys = {
            str(key).strip()
            for key, value in raw.items()
            if str(key).strip() and str(value).strip().lower() in {"active", "enabled", "true", "1", "yes"}
        }
    elif hasattr(raw, "items"):
        admin_keys = {
            str(key).strip()
            for key, value in raw.items()
            if str(key).strip() and str(value).strip().lower() in {"active", "enabled", "true", "1", "yes"}
        }
    elif isinstance(raw, str):
        parts = [item.strip() for item in raw.replace(";", ",").replace("\n", ",").split(",")]
        admin_keys = {item for item in parts if item}

    return admin_keys, source


def mask_access_key(value: str) -> str:
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:3]}***{value[-2:]}"


def is_logged_in() -> bool:
    return bool(st.session_state.get("access_granted"))


def is_admin() -> bool:
    return st.session_state.get("access_role") == "admin"


def logout() -> None:
    st.session_state["access_granted"] = False
    st.session_state["access_key_value"] = ""
    st.session_state["access_key_masked"] = ""
    st.session_state["access_role"] = ""


def render_login_gate() -> None:
    allowed_keys, source = get_access_key_config()
    if not allowed_keys:
        st.error("撠閮剖? ACCESS_KEYS嚗瘜??函?仿?霅?)
        st.stop()

    st.markdown('<div class="login-shell">', unsafe_allow_html=True)
    st.title("?∠巨?琿??餃")
    st.caption(LOGIN_HELP_TEXT)
    with st.form("access_gate_form", clear_on_submit=False):
        input_key = st.text_input("?餃摨?", type="password", placeholder="隢撓?亙祟?賊?????)
        submitted = st.form_submit_button("?脣蝟餌絞", use_container_width=True)

    if submitted:
        cleaned = input_key.strip()
        if cleaned in allowed_keys:
            st.session_state["access_granted"] = True
            st.session_state["access_key_value"] = cleaned
            st.session_state["access_key_masked"] = mask_access_key(cleaned)
            st.rerun()
        else:
            st.error("?餃摨??⊥?嚗?蝣箄??臬?箔??貊??????)

    st.caption(f"摨?靘?嚗source}嚗??典??嚗len(allowed_keys)}")
    st.markdown("</div>", unsafe_allow_html=True)
    st.stop()

def render_login_gate() -> None:
    allowed_keys, source = get_access_key_config()
    admin_keys, admin_source = get_admin_access_key_config()
    if not allowed_keys:
        st.error("撠閮剖? ACCESS_KEYS嚗瘜??函?仿?霅?)
        st.stop()

    st.markdown('<div class="login-shell">', unsafe_allow_html=True)
    st.title("?∠巨?琿??餃")
    st.caption(LOGIN_HELP_TEXT)
    with st.form("access_gate_form", clear_on_submit=False):
        input_key = st.text_input("?餃摨?", type="password", placeholder="隢撓?亙祟?賊?????)
        submitted = st.form_submit_button("?脣蝟餌絞", use_container_width=True)

    if submitted:
        cleaned = input_key.strip()
        if cleaned in admin_keys:
            st.session_state["access_granted"] = True
            st.session_state["access_key_value"] = cleaned
            st.session_state["access_key_masked"] = mask_access_key(cleaned)
            st.session_state["access_role"] = "admin"
            st.rerun()
        elif cleaned in allowed_keys:
            st.session_state["access_granted"] = True
            st.session_state["access_key_value"] = cleaned
            st.session_state["access_key_masked"] = mask_access_key(cleaned)
            st.session_state["access_role"] = "user"
            st.rerun()
        else:
            st.error("?餃摨??⊥?嚗?蝣箄??臬?箔??貊??????)

    st.caption(f"摨?靘?嚗source}嚗??典??嚗len(allowed_keys)}")
    if admin_keys:
        st.caption(f"蝞∠?摨?靘?嚗admin_source}嚗??函恣???嚗len(admin_keys)}")
    st.markdown("</div>", unsafe_allow_html=True)
    st.stop()


def book_totals(levels: list[dict[str, Any]]) -> tuple[float, int]:
    total_size = sum(int(level.get("size", 0) or 0) for level in levels[:5])
    near3_size = sum(int(level.get("size", 0) or 0) for level in levels[:3])
    return float(total_size), int(near3_size)


def book_level_map(levels: list[dict[str, Any]]) -> dict[float, int]:
    result: dict[float, int] = {}
    for level in levels[:5]:
        price = level.get("price")
        size = level.get("size")
        if price in (None, ""):
            continue
        result[float(price)] = int(size or 0)
    return result


def safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except Exception:
        return None


def summarise_book(book: dict[str, Any] | None) -> dict[str, Any] | None:
    if not book:
        return None

    bids = book.get("bids", [])
    asks = book.get("asks", [])
    bid_total, bid_near3 = book_totals(bids)
    ask_total, ask_near3 = book_totals(asks)

    return {
        "time": float(book.get("time") or now_taipei().timestamp()),
        "bid_total": bid_total,
        "ask_total": ask_total,
        "bid_near3_ratio": 0.0 if bid_total == 0 else bid_near3 / bid_total,
        "ask_near3_ratio": 0.0 if ask_total == 0 else ask_near3 / ask_total,
        "best_bid": float(bids[0]["price"]) if bids else None,
        "best_ask": float(asks[0]["price"]) if asks else None,
        "bid_map": book_level_map(bids),
        "ask_map": book_level_map(asks),
    }


def build_book_from_quote(symbol: str, quote_data: dict[str, Any] | None) -> dict[str, Any] | None:
    if not quote_data:
        return None
    bids = quote_data.get("bids", [])
    asks = quote_data.get("asks", [])
    if not bids and not asks:
        return None
    return {
        "symbol": symbol,
        "bids": bids,
        "asks": asks,
        "time": quote_data.get("lastUpdated") or quote_data.get("closeTime") or quote_data.get("openTime"),
    }


def build_trade_from_quote(quote_data: dict[str, Any] | None) -> dict[str, Any] | None:
    if not quote_data:
        return None
    trade = quote_data.get("lastTrade")
    if trade:
        merged = dict(trade)
        merged["volume"] = quote_data.get("total", {}).get("tradeVolume")
        return merged
    if quote_data.get("lastPrice") is None:
        return None
    return {
        "price": quote_data.get("lastPrice"),
        "size": quote_data.get("lastSize"),
        "volume": quote_data.get("total", {}).get("tradeVolume"),
        "time": quote_data.get("lastUpdated") or quote_data.get("closeTime"),
        "serial": quote_data.get("serial"),
    }


def build_snapshot_from_quote(symbol: str, quote_data: dict[str, Any] | None) -> dict[str, Any]:
    book = build_book_from_quote(symbol, quote_data)
    last_trade = build_trade_from_quote(quote_data)
    trade_history = [last_trade] if last_trade else []
    signal_events: list[SignalEvent] = []
    if quote_data and quote_data.get("isClose"):
        signal_events.append(
            SignalEvent(
                event_type="close_snapshot",
                side="?嗥",
                message=f"{symbol} ?桀?憿舐內?嗥敹怎嚗?銝剜?畾萄惇甇?虜?瘜?,
                score=0.35,
            )
        )

    return {
        "book": book,
        "last_trade": last_trade,
        "trades": trade_history,
        "signal_events": signal_events,
        "book_summary": summarise_book(book),
        "open_trade": None,
        "session_high": quote_data.get("highPrice") if quote_data else None,
        "session_low": quote_data.get("lowPrice") if quote_data else None,
        "trade_history": trade_history,
        "quote_data": quote_data,
    }


def classify_severity(score: float) -> str:
    if score >= 0.85:
        return "擃?
    if score >= 0.6:
        return "銝?
    return "雿?


def score_to_bias(score: float) -> str:
    if score >= 1.4:
        return "??"
    if score <= -1.4:
        return "?征"
    return "銝剜?


@dataclass
class SignalEvent:
    event_type: str
    side: str
    message: str
    score: float
    created_at: datetime = field(default_factory=now_taipei)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class SymbolState:
    book: dict[str, Any] | None = None
    last_trade: dict[str, Any] | None = None
    trades: deque = field(default_factory=lambda: deque(maxlen=MAX_RECENT_TRADES))
    book_history: deque = field(default_factory=lambda: deque(maxlen=MAX_BOOK_HISTORY))
    trade_history: deque = field(default_factory=lambda: deque(maxlen=MAX_TRADE_HISTORY))
    signal_events: deque = field(default_factory=lambda: deque(maxlen=MAX_SIGNAL_EVENTS))
    signal_cooldowns: dict[str, float] = field(default_factory=dict)
    last_processed_trade_serial: Any = None
    open_trade: dict[str, Any] | None = None
    session_high: float | None = None
    session_low: float | None = None


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
        ensure_log_dirs()

    def tick_log_path(self, symbol: str) -> Path:
        return TICK_LOG_DIR / f"{today_taipei_str()}_{symbol}_ticks.csv"

    def book_log_path(self, symbol: str) -> Path:
        return BOOK_LOG_DIR / f"{today_taipei_str()}_{symbol}_books.csv"

    def signal_log_path(self, symbol: str) -> Path:
        return SIGNAL_LOG_DIR / f"{today_taipei_str()}_{symbol}_signals.csv"

    def persist_trade_tick(self, symbol: str, trade: dict[str, Any]) -> None:
        append_csv_row(
            self.tick_log_path(symbol),
            ["logged_at", "symbol", "trade_time", "price", "size", "bid", "ask", "volume", "serial"],
            {
                "logged_at": now_taipei().strftime("%Y-%m-%d %H:%M:%S"),
                "symbol": symbol,
                "trade_time": trade.get("time"),
                "price": trade.get("price"),
                "size": trade.get("size"),
                "bid": trade.get("bid"),
                "ask": trade.get("ask"),
                "volume": trade.get("volume"),
                "serial": trade.get("serial"),
            },
        )

    def persist_book_summary(self, symbol: str, summary: dict[str, Any]) -> None:
        append_csv_row(
            self.book_log_path(symbol),
            ["logged_at", "symbol", "book_time", "bid_total", "ask_total", "bid_near3_ratio", "ask_near3_ratio", "best_bid", "best_ask"],
            {
                "logged_at": now_taipei().strftime("%Y-%m-%d %H:%M:%S"),
                "symbol": symbol,
                "book_time": summary.get("time"),
                "bid_total": summary.get("bid_total"),
                "ask_total": summary.get("ask_total"),
                "bid_near3_ratio": round(float(summary.get("bid_near3_ratio", 0.0)), 6),
                "ask_near3_ratio": round(float(summary.get("ask_near3_ratio", 0.0)), 6),
                "best_bid": summary.get("best_bid"),
                "best_ask": summary.get("best_ask"),
            },
        )

    def persist_signal_event(self, symbol: str, event: SignalEvent) -> None:
        append_csv_row(
            self.signal_log_path(symbol),
            ["logged_at", "symbol", "event_time", "event_type", "side", "score", "severity", "message", "extra"],
            {
                "logged_at": now_taipei().strftime("%Y-%m-%d %H:%M:%S"),
                "symbol": symbol,
                "event_time": event.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "event_type": event.event_type,
                "side": event.side,
                "score": round(event.score, 4),
                "severity": classify_severity(event.score),
                "message": event.message,
                "extra": str(event.extra),
            },
        )

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
                self.error_message = f"WebSocket ??憭望?嚗exc}"
                self.last_status_message = "WebSocket ??靘?"
            self.connection_ready.clear()
            self.auth_ready.clear()

    def _handle_connect(self) -> None:
        with self.lock:
            self.connected = True
            self.last_status_message = "WebSocket 撌脣遣蝡?蝑?撽?"
            if self.error_message == "甇?撱箇? WebSocket ???嚗?蝔?:
                self.error_message = None
        self.connection_ready.set()

    def _handle_disconnect(self, code: Any, message: Any) -> None:
        with self.lock:
            self.connected = False
            self.authenticated = False
            self.error_message = f"???銝剜嚗code} {message}"
            self.last_status_message = "WebSocket 撌脖葉??
        self.connection_ready.clear()
        self.auth_ready.clear()

    def _handle_error(self, error: Any) -> None:
        with self.lock:
            self.error_message = f"銵?鞈??航炊嚗error}"
            self.last_status_message = "?嗅 error 鈭辣"

    def _emit_signal(
        self,
        symbol: str,
        state: SymbolState,
        event_type: str,
        side: str,
        message: str,
        score: float,
        extra: dict[str, Any] | None = None,
        cooldown_seconds: int = 8,
    ) -> None:
        now_ts = now_taipei().timestamp()
        cooldown_key = f"{event_type}:{side}"
        if now_ts - state.signal_cooldowns.get(cooldown_key, 0) < cooldown_seconds:
            return

        event = SignalEvent(event_type=event_type, side=side, message=message, score=score, extra=extra or {})
        state.signal_cooldowns[cooldown_key] = now_ts
        state.signal_events.appendleft(event)
        self.persist_signal_event(symbol, event)

    def _analyse_order_book_change(self, symbol: str, state: SymbolState, current_trade: dict[str, Any] | None = None) -> None:
        if len(state.book_history) < 2:
            return

        prev = state.book_history[-2]
        curr = state.book_history[-1]
        current_book = state.book or {}
        current_bids = current_book.get("bids", [])
        current_asks = current_book.get("asks", [])
        bid_delta = curr["bid_total"] - prev["bid_total"]
        ask_delta = curr["ask_total"] - prev["ask_total"]

        if prev["bid_total"] > 0:
            if curr["bid_total"] >= prev["bid_total"] * 1.6 and bid_delta >= 500:
                score = min(0.95, 0.55 + abs(bid_delta) / max(prev["bid_total"], 1))
                self._emit_signal(symbol, state, "bid_stack_up", "鞎瑞", f"{symbol} 鞎瑞鈭?蝮賡??啣虜憓? {int(bid_delta):,}嚗?隡澆????踵??, score, {"bid_delta": bid_delta})
            if curr["bid_total"] <= prev["bid_total"] * 0.55 and abs(bid_delta) >= 500:
                score = min(0.95, 0.55 + abs(bid_delta) / max(prev["bid_total"], 1))
                self._emit_signal(symbol, state, "bid_pull", "鞎瑞", f"{symbol} 鞎瑞鈭?蝮賡?敹恍?撠?{int(abs(bid_delta)):,}嚗?隡潭?柴?, score, {"bid_delta": bid_delta})

        if prev["ask_total"] > 0:
            if curr["ask_total"] >= prev["ask_total"] * 1.6 and ask_delta >= 500:
                score = min(0.95, 0.55 + abs(ask_delta) / max(prev["ask_total"], 1))
                self._emit_signal(symbol, state, "ask_stack_up", "鞈?", f"{symbol} 鞈?鈭?蝮賡??啣虜憓? {int(ask_delta):,}嚗?隡澆??斗??柴?, score, {"ask_delta": ask_delta})
            if curr["ask_total"] <= prev["ask_total"] * 0.55 and abs(ask_delta) >= 500:
                score = min(0.95, 0.55 + abs(ask_delta) / max(prev["ask_total"], 1))
                self._emit_signal(symbol, state, "ask_pull", "鞈?", f"{symbol} 鞈?鈭?蝮賡?敹恍?撠?{int(abs(ask_delta)):,}嚗?隡潭?柴?, score, {"ask_delta": ask_delta})

        bid_ratio_jump = curr["bid_near3_ratio"] - prev["bid_near3_ratio"]
        ask_ratio_jump = curr["ask_near3_ratio"] - prev["ask_near3_ratio"]

        if bid_ratio_jump >= 0.18 and curr["bid_near3_ratio"] >= 0.62:
            self._emit_signal(symbol, state, "bid_front_loaded", "鞎瑞", f"{symbol} 鞎瑞??瑼?瘥?擃 {curr['bid_near3_ratio']:.0%}嚗??寞?交?憿舫?銝准?, min(0.9, 0.45 + bid_ratio_jump * 2), {"bid_near3_ratio": curr["bid_near3_ratio"]})
        if ask_ratio_jump >= 0.18 and curr["ask_near3_ratio"] >= 0.62:
            self._emit_signal(symbol, state, "ask_front_loaded", "鞈?", f"{symbol} 鞈???瑼?瘥?擃 {curr['ask_near3_ratio']:.0%}嚗??寡都憯?銝准?, min(0.9, 0.45 + ask_ratio_jump * 2), {"ask_near3_ratio": curr["ask_near3_ratio"]})

        for idx in range(TOP_LEVEL_MONITOR_COUNT):
            prev_bid_size = int(prev["bid_map"].get(safe_float(current_bids[idx].get("price")) if idx < len(current_bids) else None, 0))
            curr_bid_level = current_bids[idx] if idx < len(current_bids) else {}
            curr_bid_size = int(curr_bid_level.get("size", 0) or 0)
            curr_bid_price = curr_bid_level.get("price")
            bid_level_delta = curr_bid_size - prev_bid_size

            if curr_bid_price not in (None, ""):
                if prev_bid_size > 0 and curr_bid_size >= prev_bid_size * LEVEL_RATIO_UP_THRESHOLD and bid_level_delta >= LEVEL_ABS_DELTA_THRESHOLD:
                    self._emit_signal(
                        symbol,
                        state,
                        f"bid_level_{idx + 1}_stack_up",
                        "鞎瑞",
                        f"{symbol} 鞎暍idx + 1} ({curr_bid_price}) ??????{bid_level_delta:,}嚗?隡潮?????,
                        min(0.95, 0.5 + abs(bid_level_delta) / max(prev_bid_size, 1)),
                        {"level": f"鞎暍idx + 1}", "price": curr_bid_price, "delta": bid_level_delta},
                    )
                if prev_bid_size >= LEVEL_ABS_DELTA_THRESHOLD and curr_bid_size <= prev_bid_size * LEVEL_RATIO_DOWN_THRESHOLD and abs(bid_level_delta) >= LEVEL_ABS_DELTA_THRESHOLD:
                    self._emit_signal(
                        symbol,
                        state,
                        f"bid_level_{idx + 1}_pull",
                        "鞎瑞",
                        f"{symbol} 鞎暍idx + 1} ({curr_bid_price}) ??翰??撠?{abs(bid_level_delta):,}嚗?隡潮??賢??,
                        min(0.95, 0.5 + abs(bid_level_delta) / max(prev_bid_size, 1)),
                        {"level": f"鞎暍idx + 1}", "price": curr_bid_price, "delta": bid_level_delta},
                    )

            prev_ask_size = int(prev["ask_map"].get(safe_float(current_asks[idx].get("price")) if idx < len(current_asks) else None, 0))
            curr_ask_level = current_asks[idx] if idx < len(current_asks) else {}
            curr_ask_size = int(curr_ask_level.get("size", 0) or 0)
            curr_ask_price = curr_ask_level.get("price")
            ask_level_delta = curr_ask_size - prev_ask_size

            if curr_ask_price not in (None, ""):
                if prev_ask_size > 0 and curr_ask_size >= prev_ask_size * LEVEL_RATIO_UP_THRESHOLD and ask_level_delta >= LEVEL_ABS_DELTA_THRESHOLD:
                    self._emit_signal(
                        symbol,
                        state,
                        f"ask_level_{idx + 1}_stack_up",
                        "鞈?",
                        f"{symbol} 鞈ㄌidx + 1} ({curr_ask_price}) ??????{ask_level_delta:,}嚗?隡潮?憯??,
                        min(0.95, 0.5 + abs(ask_level_delta) / max(prev_ask_size, 1)),
                        {"level": f"鞈ㄌidx + 1}", "price": curr_ask_price, "delta": ask_level_delta},
                    )
                if prev_ask_size >= LEVEL_ABS_DELTA_THRESHOLD and curr_ask_size <= prev_ask_size * LEVEL_RATIO_DOWN_THRESHOLD and abs(ask_level_delta) >= LEVEL_ABS_DELTA_THRESHOLD:
                    self._emit_signal(
                        symbol,
                        state,
                        f"ask_level_{idx + 1}_pull",
                        "鞈?",
                        f"{symbol} 鞈ㄌidx + 1} ({curr_ask_price}) ??翰??撠?{abs(ask_level_delta):,}嚗?隡潮??賢??,
                        min(0.95, 0.5 + abs(ask_level_delta) / max(prev_ask_size, 1)),
                        {"level": f"鞈ㄌidx + 1}", "price": curr_ask_price, "delta": ask_level_delta},
                    )

        if current_trade is None:
            return

        trade_price = float(current_trade.get("price") or 0)
        trade_size = int(current_trade.get("size") or 0)
        if trade_price <= 0 or trade_size <= 0:
            return

        prev_best_bid = prev["best_bid"]
        prev_best_ask = prev["best_ask"]

        if prev_best_ask is not None and trade_price >= prev_best_ask:
            prev_size = prev["ask_map"].get(trade_price)
            curr_size = curr["ask_map"].get(trade_price)
            if prev_size is not None and curr_size is not None and curr_size >= prev_size:
                self._emit_signal(symbol, state, "ask_replenish_after_trade", "鞈?", f"{symbol} ?漱??{trade_price:.2f} ?漱敺?鞈??雿皜?憓??撮鋆??, 0.78, {"price": trade_price, "trade_size": trade_size})

        if prev_best_bid is not None and trade_price <= prev_best_bid:
            prev_size = prev["bid_map"].get(trade_price)
            curr_size = curr["bid_map"].get(trade_price)
            if prev_size is not None and curr_size is not None and curr_size >= prev_size:
                self._emit_signal(symbol, state, "bid_replenish_after_trade", "鞎瑞", f"{symbol} ?漱??{trade_price:.2f} ?漱敺?鞎瑞?雿皜?憓??撮鋆??, 0.78, {"price": trade_price, "trade_size": trade_size})

    def _update_opening_state(self, symbol: str, state: SymbolState, trade: dict[str, Any]) -> None:
        trade_price = float(trade.get("price") or 0)
        if trade_price <= 0:
            return

        if state.open_trade is None:
            state.open_trade = trade
            self._emit_signal(symbol, state, "opening_trade", "?", f"{symbol} 撌脰??洵銝蝑??斗?鈭歹??寞 {trade_price:.2f}??, 0.5, {"open_price": trade_price}, cooldown_seconds=3600)

        state.session_high = trade_price if state.session_high is None else max(state.session_high, trade_price)
        state.session_low = trade_price if state.session_low is None else min(state.session_low, trade_price)

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
                self.last_status_message = "API key 撽???"
            self.auth_ready.set()
            self._flush_pending_subscriptions()
            return

        if event == "heartbeat":
            with self.lock:
                self.last_event_at = now_taipei()
                self.last_status_message = "?嗅 heartbeat"
            return

        if event == "error":
            error_data = payload.get("data", {})
            error_message = error_data.get("message") or str(error_data) or "?芰?航炊"
            with self.lock:
                self.error_message = f"Fugle 撽????梢隤歹?{error_message}"
                self.last_status_message = "?嗅 error 鈭辣"
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
            self.last_status_message = f"?嗅 {channel} 鞈?"

            if channel == "books":
                state.book = data
                summary = summarise_book(data)
                if summary:
                    state.book_history.append(summary)
                    self.persist_book_summary(symbol, summary)
                    self._analyse_order_book_change(symbol, state, state.last_trade)

            elif channel == "trades":
                state.last_trade = data
                serial = data.get("serial")
                if serial != state.last_processed_trade_serial:
                    state.last_processed_trade_serial = serial
                    state.trades.appendleft(data)
                    state.trade_history.append(
                        {
                            "time": float(data.get("time") or now_taipei().timestamp()),
                            "price": float(data.get("price") or 0),
                            "size": int(data.get("size") or 0),
                            "serial": serial,
                        }
                    )
                    self.persist_trade_tick(symbol, data)
                    self._update_opening_state(symbol, state, data)
                    self._analyse_order_book_change(symbol, state, data)

    def _safe_subscribe(self, channel: str, symbol: str) -> bool:
        if self.stock is None:
            return False
        try:
            self.stock.subscribe({"channel": channel, "symbol": symbol})
            return True
        except Exception as exc:
            with self.lock:
                self.connected = False
                self.error_message = f"閮憭望?嚗channel} {symbol} - {exc}"
                self.last_status_message = "?閮???憭?
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
                    if key not in self.subscriptions:
                        self.pending_subscriptions.add(key)

        if self.stock is None:
            with self.lock:
                if self.error_message is None:
                    self.error_message = "甇?????Fugle SDK嚗?蝔?
                    self.last_status_message = "蝑? SDK 撱箇? stock client"
            return

        if not self.connection_ready.wait(timeout=1.0):
            with self.lock:
                if self.error_message is None:
                    self.error_message = "甇?撱箇? WebSocket ???嚗?蝔?
                    self.last_status_message = "蝑? WebSocket connect"
            return

        if not self.auth_ready.wait(timeout=2.0):
            with self.lock:
                if self.error_message is None:
                    self.error_message = "WebSocket 撌脤??嚗?撠摰? API 撽???
                    self.last_status_message = "蝑? authenticated 鈭辣"
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
                    "signal_events": list(state.signal_events),
                    "book_summary": state.book_history[-1] if state.book_history else None,
                    "open_trade": state.open_trade,
                    "session_high": state.session_high,
                    "session_low": state.session_low,
                    "trade_history": list(state.trade_history),
                    "quote_data": None,
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


def build_mock_snapshot(symbols: list[str]) -> dict[str, dict[str, Any]]:
    snapshots: dict[str, dict[str, Any]] = {}
    base_prices = {"2330": 812.0, "2317": 149.5, "0050": 193.2, "2454": 1220.0}

    for idx, symbol in enumerate(symbols):
        base = base_prices.get(symbol, 100.0 + idx * 10)
        bids = [{"price": round(base - 0.5 - i * 0.5, 2), "size": 100 * (i + 1)} for i in range(5)]
        asks = [{"price": round(base + 0.5 + i * 0.5, 2), "size": 120 * (i + 1)} for i in range(5)]
        trades = deque(
            [
                {
                    "time": now_taipei().timestamp() - (9 - i),
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
        trade_history = deque(
            [{"time": item["time"], "price": item["price"], "size": item["size"], "serial": item["serial"]} for item in trades],
            maxlen=MAX_TRADE_HISTORY,
        )
        book = {"symbol": symbol, "bids": bids, "asks": asks, "time": now_taipei().timestamp()}
        summary = summarise_book(book)
        signal_events = deque(maxlen=MAX_SIGNAL_EVENTS)
        if idx % 2 == 0:
            signal_events.appendleft(SignalEvent("bid_stack_up", "鞎瑞", f"{symbol} 鞎瑞餈??葉嚗內蝭???, 0.74))
        else:
            signal_events.appendleft(SignalEvent("ask_pull", "鞈?", f"{symbol} 鞈?鈭?敹恍?撠?蝷箇?閮???, 0.68))

        snapshots[symbol] = {
            "book": book,
            "trades": list(trades),
            "last_trade": trades[0],
            "signal_events": list(signal_events),
            "book_summary": summary,
            "open_trade": trades[-1],
            "session_high": max(item["price"] for item in trades),
            "session_low": min(item["price"] for item in trades),
            "trade_history": list(trade_history),
            "quote_data": None,
        }

    return snapshots


@st.cache_data(ttl=15, show_spinner=False)
def test_rest_quote(api_key: str, symbol: str) -> dict[str, Any]:
    if RestClient is None:
        return {"ok": False, "message": "RestClient 銝?剁?fugle-marketdata 憟辣?航?芣迤蝣箏?鋆?, "data": None}

    try:
        client = RestClient(api_key=api_key)
        quote = client.stock.intraday.quote(symbol=symbol)
        return {"ok": True, "message": f"REST 皜祈岫??嚗歇?? {symbol} ?勗??, "data": quote}
    except Exception as exc:
        return {"ok": False, "message": f"REST 皜祈岫憭望?嚗exc}", "data": None}


@st.cache_data(ttl=5, show_spinner=False)
def fetch_benchmark_data() -> dict[str, Any]:
    if yf is None:
        return {"ok": False, "message": "yfinance 憟辣?芸?鋆??⊥?頛?函????, "items": []}

    items: list[dict[str, Any]] = []
    failures: list[str] = []

    for config in BENCHMARK_SYMBOLS:
        label = config["label"]
        symbol = config["symbol"]
        note = config["note"]
        try:
            ticker = yf.Ticker(symbol)
            history = ticker.history(period="2d", interval="1m", auto_adjust=False, prepost=True)
            if history.empty:
                history = ticker.history(period="5d", interval="1d", auto_adjust=False)

            close_series = history["Close"].dropna()
            if close_series.empty:
                raise ValueError("?亦?寞鞈?")

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
            age_seconds = benchmark_age_seconds(timestamp)

            items.append(
                {
                    "label": label,
                    "symbol": symbol,
                    "note": note,
                    "price": round(last_price, 2),
                    "change": round(change, 2),
                    "change_pct": round(change_pct, 2),
                    "time": format_benchmark_time(timestamp),
                    "age_seconds": age_seconds,
                    "stale": False if age_seconds is None else age_seconds >= BENCHMARK_STALE_SECONDS,
                }
            )
        except Exception as exc:
            failures.append(f"{label}: {exc}")
            items.append(
                {
                    "label": label,
                    "symbol": symbol,
                    "note": note,
                    "price": None,
                    "change": None,
                    "change_pct": None,
                    "time": "-",
                    "age_seconds": None,
                    "stale": True,
                }
            )

    message = "?函?????交???
    if failures:
        message = "?典??函?????亙仃??" + " | ".join(failures[:3])
    return {"ok": len(failures) < len(BENCHMARK_SYMBOLS), "message": message, "items": items}


def update_index_shock_signals(benchmark_result: dict[str, Any]) -> list[SignalEvent]:
    if "index_signal_history" not in st.session_state:
        st.session_state.index_signal_history = deque(maxlen=120)
    if "index_signal_events" not in st.session_state:
        st.session_state.index_signal_events = deque(maxlen=20)
    if "index_signal_cooldowns" not in st.session_state:
        st.session_state.index_signal_cooldowns = {}

    twii_item = next((item for item in benchmark_result.get("items", []) if item.get("symbol") == "^TWII"), None)
    if not twii_item or twii_item.get("price") is None or twii_item.get("stale"):
        return list(st.session_state.index_signal_events)

    now_ts = now_taipei().timestamp()
    st.session_state.index_signal_history.append({"time": now_ts, "price": float(twii_item["price"])})
    history = list(st.session_state.index_signal_history)
    if len(history) < 2:
        return list(st.session_state.index_signal_events)

    recent_15s = [item for item in history if now_ts - item["time"] <= 15]
    if len(recent_15s) >= 2:
        base_price = recent_15s[0]["price"]
        latest_price = recent_15s[-1]["price"]
        change_pct = 0.0 if base_price == 0 else (latest_price - base_price) / base_price * 100
        cooldown_key = "twii_shock"
        last_emitted = st.session_state.index_signal_cooldowns.get(cooldown_key, 0.0)

        if abs(change_pct) >= 0.35 and now_ts - last_emitted >= 20:
            direction = "??" if change_pct > 0 else "?征"
            st.session_state.index_signal_events.appendleft(
                SignalEvent(
                    event_type="twii_shock",
                    side="憭抒",
                    message=f"?啁??? 15 蝘???{change_pct:+.2f}%嚗之?文?暹?憿?{direction} ?啣???,
                    score=min(0.95, 0.6 + abs(change_pct)),
                    extra={"change_pct": change_pct},
                )
            )
            st.session_state.index_signal_cooldowns[cooldown_key] = now_ts

    return list(st.session_state.index_signal_events)


def calc_symbol_signal_score(symbol_data: dict[str, Any], index_events: list[SignalEvent]) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    for event in symbol_data.get("signal_events", [])[:5]:
        if event.side == "鞎瑞":
            score += event.score
        elif event.side == "鞈?":
            score -= event.score
        reasons.append(event.message)

    open_trade = symbol_data.get("open_trade")
    last_trade = symbol_data.get("last_trade")
    session_high = symbol_data.get("session_high")
    session_low = symbol_data.get("session_low")

    if open_trade and last_trade:
        open_price = float(open_trade.get("price") or 0)
        last_price = float(last_trade.get("price") or 0)
        if open_price > 0 and last_price > 0:
            intraday_move_pct = (last_price - open_price) / open_price * 100
            if intraday_move_pct >= 1.2:
                score += 0.8
                reasons.append(f"?曉?詨??銝撞 {intraday_move_pct:.2f}%??)
            elif intraday_move_pct <= -1.2:
                score -= 0.8
                reasons.append(f"?曉?詨??銝? {abs(intraday_move_pct):.2f}%??)

    if last_trade and session_high and session_low:
        last_price = float(last_trade.get("price") or 0)
        if session_high and last_price >= session_high * 0.997:
            score += 0.35
            reasons.append("?寞?亥??支葉擃???)
        if session_low and last_price <= session_low * 1.003:
            score -= 0.35
            reasons.append("?寞?亥??支葉雿???)

    for event in index_events[:2]:
        change_pct = float(event.extra.get("change_pct", 0.0))
        if change_pct > 0:
            score += 0.4
        elif change_pct < 0:
            score -= 0.4
        reasons.append(event.message)

    return score, reasons[:6]


def render_sidebar_benchmark_section(benchmark_result: dict[str, Any]) -> None:
    st.markdown("---")
    st.subheader("?函????)
    st.caption("甇文??箏?????航?箏辣?脣?對??漱???單??漱??)

    for item in benchmark_result.get("items", []):
        price = item.get("price")
        change = item.get("change")
        change_pct = item.get("change_pct")
        if price is None:
            price_text = "-"
            delta = "鞈??怎撩"
        else:
            sign = "+" if change is not None and change > 0 else ""
            delta = f"{sign}{change:,.2f} ({sign}{change_pct:.2f}%)" if change is not None and change_pct is not None else "-"
            price_text = f"{price:,.2f}"

        st.metric(item.get("label", "-"), price_text, delta=delta)
        st.caption(f"?敺??{item.get('time', '-')} | {item.get('symbol', '-')}")
        if item.get("stale"):
            age_text = f"{int(item['age_seconds'])} 蝘? if item.get("age_seconds") is not None else "?芰"
            st.caption(f"靘??芣?堆?{age_text}")
        st.caption(item.get("note", "??))

    if benchmark_result.get("message"):
        st.caption(benchmark_result["message"])


def render_index_signal_panel(benchmark_result: dict[str, Any], index_events: list[SignalEvent]) -> None:
    st.markdown('<div class="panel-title">憭抒?啣??內</div>', unsafe_allow_html=True)
    twii_item = next((item for item in benchmark_result.get("items", []) if item.get("symbol") == "^TWII"), None)

    cols = st.columns(4)
    if twii_item and twii_item.get("price") is not None:
        price_text = f"{twii_item['price']:,.2f}"
        change = float(twii_item.get("change") or 0)
        change_pct = float(twii_item.get("change_pct") or 0)
        sign = "+" if change > 0 else ""
        delta_text = f"{sign}{change:,.2f} ({sign}{change_pct:.2f}%)"
        cols[0].metric("?啁???", price_text, delta=delta_text)
        cols[1].metric("?敺??, twii_item.get("time", "-"))
        cols[2].metric("鞈????, "靘??芣?? if twii_item.get("stale") else "?湔銝?)
        cols[3].metric("鈭辣??, len(index_events))
    else:
        cols[0].metric("?啁???", "-")
        cols[1].metric("?敺??, "-")
        cols[2].metric("鞈????, "?∟???)
        cols[3].metric("鈭辣??, len(index_events))

    if not index_events:
        render_empty_box("?桀?撠?菜葫?啣???甈??貊??＊?亥???, medium=True)
        return

    rows = [
        {
            "??": event.created_at.strftime("%H:%M:%S"),
            "撘瑕漲": classify_severity(event.score),
            "?批捆": event.message,
        }
        for event in index_events[:5]
    ]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, height=180)


def render_empty_box(message: str, tall: bool = False, medium: bool = False) -> None:
    css_class = "placeholder-box"
    if tall:
        css_class += " tall"
    if medium:
        css_class += " medium"
    st.markdown(f'<div class="{css_class}">{message}</div>', unsafe_allow_html=True)


def render_order_book(symbol: str, book: dict[str, Any] | None) -> None:
    st.markdown(f'<div class="panel-title">{symbol} 鈭?憪眺憪都</div>', unsafe_allow_html=True)
    if not book:
        render_empty_box("撠?嗅鈭?鞈???, tall=True)
        return

    bids = book.get("bids", [])
    asks = book.get("asks", [])
    rows = []
    for idx in range(max(len(bids), len(asks), 5)):
        bid = bids[idx] if idx < len(bids) else {}
        ask = asks[idx] if idx < len(asks) else {}
        rows.append({"憪眺??: bid.get("size", ""), "憪眺??: bid.get("price", ""), "憪都??: ask.get("price", ""), "憪都??: ask.get("size", "")})
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, height=ORDER_BOOK_HEIGHT)
    st.caption(f"?湔??嚗format_fugle_time(book.get('time'))}")


def render_trade_summary(symbol: str, trade: dict[str, Any] | None, quote_data: dict[str, Any] | None) -> None:
    st.markdown(f'<div class="panel-title">{symbol} ??唳?鈭?/div>', unsafe_allow_html=True)
    if not trade:
        render_empty_box("撠?嗅?漱鞈???, medium=True)
        return

    cols = st.columns(4)
    cols[0].metric("?漱??, trade.get("price", "-"))
    cols[1].metric("?漱??, trade.get("size", "-"))
    cols[2].metric("蝝舐???, trade.get("volume", "-"))
    cols[3].metric("??", format_fugle_time(trade.get("time")))
    if quote_data and quote_data.get("isClose"):
        st.caption("?桀?憿舐內?嗥敹怎??)


def render_trade_tape(trades: list[dict[str, Any]]) -> None:
    st.markdown('<div class="panel-title">?單??漱?敦</div>', unsafe_allow_html=True)
    if not trades:
        render_empty_box("撠?嗅?單??漱?敦??, tall=True)
        return

    def fmt_price(value: Any) -> str:
        if value in (None, ""):
            return "-"
        try:
            return f"{float(value):.2f}"
        except Exception:
            return str(value)

    rows = []
    for item in list(trades)[:20]:
        bid = item.get("bid")
        ask = item.get("ask")
        price = item.get("price")
        side = "neutral"
        if price is not None and ask is not None and price >= ask:
            side = "outer"
        elif price is not None and bid is not None and price <= bid:
            side = "inner"

        rows.append(
            {
                "??": format_fugle_time(item.get("time")),
                "鞎瑕": fmt_price(bid),
                "鞈?": fmt_price(ask),
                "?漱?寞": fmt_price(price),
                "?賊?": item.get("size"),
                "_side": side,
            }
        )

    df = pd.DataFrame(rows)

    def style_trade_row(row: pd.Series) -> list[str]:
        side = row.get("_side")
        styles = [""] * len(row)
        color = ""
        if side == "outer":
            color = "color: #ff4d4f; font-weight: 700;"
        elif side == "inner":
            color = "color: #34c759; font-weight: 700;"

        columns = list(row.index)
        for target_col in ("?漱?寞", "?賊?"):
            if target_col in columns:
                styles[columns.index(target_col)] = color
        return styles

    styled = df.style.apply(style_trade_row, axis=1).hide(axis="columns", subset=["_side"])
    st.dataframe(styled, width="stretch", hide_index=True, height=TRADE_TAPE_HEIGHT)


def render_signal_panel(symbol: str, signal_events: list[SignalEvent]) -> None:
    st.markdown(f'<div class="panel-title">{symbol} ?啣虜閮?</div>', unsafe_allow_html=True)
    if not signal_events:
        render_empty_box("?桀?撠?菜葫?唳?憿舐?鈭???鈭斤撣詻?, tall=True)
        return

    rows = [
        {
            "??": event.created_at.strftime("%H:%M:%S"),
            "?孵?": event.side,
            "憿?": event.event_type,
            "撘瑕漲": classify_severity(event.score),
            "?批捆": event.message,
        }
        for event in signal_events[:8]
    ]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, height=SIGNAL_PANEL_HEIGHT)


def build_price_volume_distribution(trade_history: list[dict[str, Any]]) -> pd.DataFrame:
    distribution: dict[float, dict[str, Any]] = {}
    for item in trade_history:
        price = safe_float(item.get("price"))
        size = int(item.get("size") or 0)
        if price is None or size <= 0:
            continue
        bucket = distribution.setdefault(price, {"?漱?賊?": 0, "?漱蝑": 0})
        bucket["?漱?賊?"] += size
        bucket["?漱蝑"] += 1

    if not distribution:
        return pd.DataFrame()

    rows = [
        {
            "?漱??: f"{price:.2f}",
            "?漱?賊?": values["?漱?賊?"],
            "?漱蝑": values["?漱蝑"],
        }
        for price, values in sorted(distribution.items(), key=lambda item: item[0], reverse=True)
    ]
    return pd.DataFrame(rows)


def render_book_summary(summary: dict[str, Any] | None, trade_history: list[dict[str, Any]]) -> None:
    st.markdown('<div class="panel-title">鈭?蝯???</div>', unsafe_allow_html=True)
    cols = st.columns(4)
    if not summary:
        cols[0].metric("鞎瑞蝮賡?", "-")
        cols[1].metric("鞈?蝮賡?", "-")
        cols[2].metric("鞎瑕?銝???", "-")
        cols[3].metric("鞈??銝???", "-")
        render_empty_box("撠蝝舐?頞喳?鈭?蝯???, medium=True)
        return
    cols[0].metric("鞎瑞蝮賡?", f"{int(summary['bid_total']):,}")
    cols[1].metric("鞈?蝮賡?", f"{int(summary['ask_total']):,}")
    cols[2].metric("鞎瑕?銝???", f"{summary['bid_near3_ratio']:.0%}")
    cols[3].metric("鞈??銝???", f"{summary['ask_near3_ratio']:.0%}")
    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
    st.markdown('<div class="panel-title" style="font-size:1.05rem;">?嗆?漱????/div>', unsafe_allow_html=True)
    distribution_df = build_price_volume_distribution(trade_history)
    if distribution_df.empty:
        render_empty_box("撠蝝舐?頞喳????漱鞈???, medium=True)
        return
    st.dataframe(distribution_df, width="stretch", hide_index=True, height=220)


def render_opening_panel(symbol: str, symbol_data: dict[str, Any]) -> None:
    st.markdown(f'<div class="panel-title">{symbol} ?餈質馱</div>', unsafe_allow_html=True)
    open_trade = symbol_data.get("open_trade")
    last_trade = symbol_data.get("last_trade")
    session_high = symbol_data.get("session_high")
    session_low = symbol_data.get("session_low")

    cols = st.columns(4)
    if not open_trade:
        cols[0].metric("?蝚砌?蝑?, "-")
        cols[1].metric("?桀??詨??", "-")
        cols[2].metric("?支葉擃?", f"{session_high:,.2f}" if session_high else "-")
        cols[3].metric("?支葉雿?", f"{session_low:,.2f}" if session_low else "-")
        st.markdown("<div style='height: 18px;'></div>", unsafe_allow_html=True)
        return

    open_price = float(open_trade.get("price") or 0)
    last_price = float(last_trade.get("price") or 0) if last_trade else 0
    move_pct = 0.0 if open_price == 0 or last_price == 0 else (last_price - open_price) / open_price * 100
    cols[0].metric("?蝚砌?蝑?, f"{open_price:,.2f}")
    cols[1].metric("?桀??詨??", f"{move_pct:+.2f}%")
    cols[2].metric("?支葉擃?", f"{session_high:,.2f}" if session_high else "-")
    cols[3].metric("?支葉雿?", f"{session_low:,.2f}" if session_low else "-")
    st.markdown("<div style='height: 18px;'></div>", unsafe_allow_html=True)


def render_decision_panel(symbol: str, symbol_data: dict[str, Any], index_events: list[SignalEvent]) -> None:
    st.markdown(f'<div class="panel-title">{symbol} 蝬??斗</div>', unsafe_allow_html=True)
    score, reasons = calc_symbol_signal_score(symbol_data, index_events)
    bias = score_to_bias(score)
    cols = st.columns(3)
    cols[0].metric("蝬??", f"{score:+.2f}")
    cols[1].metric("?斗", bias)
    cols[2].metric("靘???, len(reasons))
    if not reasons:
        render_empty_box("?桀?鞈?銝雲嚗??芸耦??蝣箇?憭征閫撖?隢?, medium=True)
        return
    st.dataframe(pd.DataFrame([{"隤芣?": reason} for reason in reasons]), width="stretch", hide_index=True, height=OPEN_PANEL_HEIGHT)


def render_tick_record_panel(symbol: str, trade_history: list[dict[str, Any]]) -> None:
    st.markdown(f'<div class="panel-title">{symbol} ???閮?</div>', unsafe_allow_html=True)
    if not trade_history:
        render_empty_box("撠??蝝舐????漱蝝??, tall=True)
        return
    rows = [{"??": format_fugle_time(item.get("time")), "?漱??: item.get("price"), "?漱??: item.get("size"), "摨?": item.get("serial")} for item in trade_history[:50]]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, height=TRADE_TAPE_HEIGHT)


def render_log_panel(symbols: list[str]) -> None:
    st.subheader("鞈??賢蝝??)
    st.caption(f"???漱??瑼?閬?閮??神?伐?{DATA_LOG_DIR}")
    today = today_taipei_str()
    rows = []
    for symbol in symbols:
        tick_path = TICK_LOG_DIR / f"{today}_{symbol}_ticks.csv"
        book_path = BOOK_LOG_DIR / f"{today}_{symbol}_books.csv"
        signal_path = SIGNAL_LOG_DIR / f"{today}_{symbol}_signals.csv"
        rows.append(
            {
                "?∠巨": symbol,
                "??瑼?: tick_path.name,
                "鈭?瑼?: book_path.name,
                "閮?瑼?: signal_path.name,
                "??撌脣遣蝡?: "?? if tick_path.exists() else "??,
                "鈭?撌脣遣蝡?: "?? if book_path.exists() else "??,
                "閮?撌脣遣蝡?: "?? if signal_path.exists() else "??,
            }
        )
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def resolve_market_source(mode: str, api_key: str | None, symbols: list[str]) -> dict[str, Any]:
    if mode == "蝷箇?鞈?":
        return {
            "source_name": "蝷箇?鞈?",
            "using_demo": True,
            "snapshots": build_mock_snapshot(symbols),
            "status": {
                "connected": False,
                "authenticated": False,
                "error_message": None,
                "last_event_at": now_taipei(),
                "last_status_message": "蝷箇?璅∪?",
                "subscriptions": 0,
                "pending_subscriptions": 0,
            },
            "rest_result": {"ok": False, "message": "蝷箇?璅∪?銝??瑁? REST 皜祈岫??, "data": None},
            "rest_snapshots": {},
            "diagnostic_note": "?桀?撘瑕雿輻蝷箇?鞈?嚗???? Fugle??,
            "store": None,
        }

    if not api_key:
        return {
            "source_name": "蝷箇?鞈?",
            "using_demo": True,
            "snapshots": build_mock_snapshot(symbols),
            "status": {
                "connected": False,
                "authenticated": False,
                "error_message": "?芣?靘?Fugle API key??,
                "last_event_at": now_taipei(),
                "last_status_message": "?芸????喟內蝭芋撘?,
                "subscriptions": 0,
                "pending_subscriptions": 0,
            },
            "rest_result": {"ok": False, "message": "?芣?靘?API key嚗歇?寧蝷箇?鞈???, "data": None},
            "rest_snapshots": {},
            "diagnostic_note": "撠閮剖? Fugle API key嚗?甇支誑蝷箇?鞈?????,
            "store": None,
        }

    if RestClient is None or WebSocketClient is None:
        return {
            "source_name": "蝷箇?鞈?",
            "using_demo": True,
            "snapshots": build_mock_snapshot(symbols),
            "status": {
                "connected": False,
                "authenticated": False,
                "error_message": "fugle-marketdata 憟辣?芸?鋆?,
                "last_event_at": now_taipei(),
                "last_status_message": "?芸????喟內蝭芋撘?,
                "subscriptions": 0,
                "pending_subscriptions": 0,
            },
            "rest_result": {"ok": False, "message": "fugle-marketdata 憟辣?芸?鋆?, "data": None},
            "rest_snapshots": {},
            "diagnostic_note": "蝻箏? Fugle SDK嚗?甇支誑蝷箇?鞈?????,
            "store": None,
        }

    rest_snapshots: dict[str, dict[str, Any]] = {}
    primary_rest_result = test_rest_quote(api_key, symbols[0])

    if not primary_rest_result.get("ok"):
        fallback_label = "Fugle嚗?霅仃???寧蝷箇?鞈?嚗? if mode == "?芸?" else "Fugle嚗?霅仃??"
        return {
            "source_name": fallback_label,
            "using_demo": True,
            "snapshots": build_mock_snapshot(symbols),
            "status": {
                "connected": False,
                "authenticated": False,
                "error_message": primary_rest_result.get("message"),
                "last_event_at": now_taipei(),
                "last_status_message": "REST 撽?憭望?嚗??單?銝脫?",
                "subscriptions": 0,
                "pending_subscriptions": 0,
            },
            "rest_result": primary_rest_result,
            "rest_snapshots": {},
            "diagnostic_note": "Fugle REST 撌脣仃???迨銝??岫?擃??賜?甇餃 WebSocket 銝???內蝭??????Ｚ?閮??Ｘ??,
            "store": None,
        }

    rest_snapshots[symbols[0]] = build_snapshot_from_quote(symbols[0], primary_rest_result.get("data"))
    for symbol in symbols[1:]:
        extra_result = test_rest_quote(api_key, symbol)
        if extra_result.get("ok"):
            rest_snapshots[symbol] = build_snapshot_from_quote(symbol, extra_result.get("data"))

    store = get_store(api_key)
    store.subscribe_symbols(symbols)
    return {
        "source_name": "Fugle",
        "using_demo": False,
        "snapshots": rest_snapshots,
        "status": store.status(),
        "rest_result": primary_rest_result,
        "rest_snapshots": rest_snapshots,
        "diagnostic_note": "Fugle REST 撽???嚗歇??單?銝脫?璅∪?嚗?嗥敺?冽嚗?Ｘ?雿輻 REST 敹怎憛怠??,
        "store": store,
    }


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


st.set_page_config(page_title="?啗?單?????, page_icon=":bar_chart:", layout="wide")
inject_custom_css()
ensure_log_dirs()

if "access_granted" not in st.session_state:
    st.session_state["access_granted"] = False
if "access_key_masked" not in st.session_state:
    st.session_state["access_key_masked"] = ""
if "access_role" not in st.session_state:
    st.session_state["access_role"] = ""

if not is_logged_in():
    render_login_gate()

st.title("?啗?單?????)
st.caption("雿輻 Streamlit 鋆賭???∩?瑼?鞎瑕?鞈???鈭扎??方蕭頩扎撣貉????支葉鞈??賢?????)

with st.sidebar:
    st.success(f"撌脩?伐?{st.session_state.get('access_key_masked', '-')}")
    st.caption("???" if is_admin() else "?????")
    if st.button("?餃", use_container_width=True):
        logout()
        st.rerun()
    st.markdown("---")
    st.header("??閮剖?")
    symbols_raw = st.text_input("?∠巨隞?Ⅳ", value=", ".join(DEFAULT_SYMBOLS), help="隢????嚗?憒?2330, 2317")
    symbols = normalize_symbols(symbols_raw) or DEFAULT_SYMBOLS
    refresh_seconds = st.slider("?瑟蝘", min_value=1, max_value=10, value=1)
    source_mode = st.selectbox("鞈?皞芋撘?, ["?芸?", "Fugle", "蝷箇?鞈?"], index=0)
    st.caption("Fugle ?祥?寞????望?嚗??蟡其誨蝣潭???雿輻 books ??trades ?拙??)

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
    st.warning("?桀?雿輻蝷箇?鞈?璅∪?? Fugle 撽???敺?????啣????)

status_cols = st.columns(6)
status_cols[0].metric("璅∪?", "蝷箇?" if using_demo else "?單?")
status_cols[1].metric("鞈?皞?, market_state["source_name"])
status_cols[2].metric("???", "撌脤??" if status.get("connected") else "?芷??")
status_cols[3].metric("撽?", "??" if status.get("authenticated") else "?芸???)
status_cols[4].metric("撌脰???, status.get("subscriptions", 0))
status_cols[5].metric("?敺?隞?, status["last_event_at"].strftime("%H:%M:%S") if status.get("last_event_at") else "-")

if status.get("error_message"):
    st.error(status["error_message"])

render_log_panel(symbols)
if is_admin():
    with st.expander("????"):
        st.write(f"API key ???{api_key_source}")
        st.write(f"API key ???{mask_secret(raw_api_key)}")
        st.write(f"API key ???{api_key_note}")
        st.write(f"??????{source_mode}")
        st.write(f"??????{market_state['source_name']}")
        st.write(f"?????{'??' if using_demo else '??'}")
        st.write(f"?????{'???' if status.get('connected') else '???'}")
        st.write(f"?????{'??' if status.get('authenticated') else '???'}")
        st.write(f"?????{status.get('last_status_message') or '-'}")
        st.write(f"?????{status.get('error_message') or '-'}")
        st.write(f"?????{market_state['diagnostic_note']}")
        st.write(f"???????{DATA_LOG_DIR}")
    with st.expander("REST ??"):
        st.write(f"?????{symbols[0] if symbols else DEFAULT_SYMBOLS[0]}")
        st.write(f"?????{'??' if rest_result.get('ok') else '??'}")
        st.write(f"???{rest_result.get('message')}")
        if rest_result.get("ok") and rest_result.get("data"):
            st.json(rest_result["data"])
tabs = st.tabs(symbols)
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

with st.expander("?函蔡隤芣?"):
    st.markdown(
        """
        - ?祉頂蝯曹???∩?瑼??鈭扎??方蕭頩扎撣貉????函????踴?        - ??Fugle 撽?憭望???蝟餌絞???內蝭????踹??游??Ｗ仃??        - ?支葉???漱??瑼?閬??啣虜閮???甇亙神??`data_logs`嚗靘踹?蝥? replay ??皜研?        - ?交?文? WebSocket ?⊥?冽嚗頂蝯望?雿輻 REST quote 敹怎憛怠鈭????唳?鈭扎?        - ?函???雿輻 Yahoo Finance ?????航?箏辣?脣?對?銝遣霅啁?乩??箔漱????        - ?啣虜閮?撅祈?????嚗?銝剛??拙霈嚗?隞?”靽??抒?鞎瑁都撱箄降??        """
    )
