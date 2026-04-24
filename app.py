import base64
import binascii
import csv
import os
import re
import threading
import time
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
    {"label": "台灣加權指數", "symbol": "^TWII", "note": "現貨指數參考"},
    {"label": "日經225", "symbol": "^N225", "note": "現貨指數參考"},
    {"label": "恆生指數", "symbol": "^HSI", "note": "現貨指數參考"},
    {"label": "韓國KOSPI", "symbol": "^KS11", "note": "現貨指數參考"},
    {"label": "那指期貨參考", "symbol": "NQ=F", "note": "期貨參考"},
    {"label": "標普期貨參考", "symbol": "ES=F", "note": "期貨參考"},
]


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
    parts = [item.strip() for item in raw.replace(";", ",").replace("，", ",").split(",")]
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
        return raw_key, "偵測到 Base64 外觀，但依 Fugle 官方文件改為保留原始 API key，不先解碼"

    return raw_key, "使用原始 API key"


def get_raw_api_key() -> tuple[str | None, str]:
    if "FUGLE_API_KEY" in st.secrets:
        return st.secrets["FUGLE_API_KEY"], "Streamlit secrets"
    env_value = os.getenv("FUGLE_API_KEY")
    if env_value:
        return env_value, "環境變數"
    return None, "未載入"


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
                side="收盤",
                message=f"{symbol} 目前顯示收盤快照，若非盤中時段屬正常狀況。",
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
        return "高"
    if score >= 0.6:
        return "中"
    return "低"


def score_to_bias(score: float) -> str:
    if score >= 1.4:
        return "偏多"
    if score <= -1.4:
        return "偏空"
    return "中性"


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
                self._emit_signal(symbol, state, "bid_stack_up", "買盤", f"{symbol} 買盤五檔總量異常增加 {int(bid_delta):,}，疑似堆量或承接。", score, {"bid_delta": bid_delta})
            if curr["bid_total"] <= prev["bid_total"] * 0.55 and abs(bid_delta) >= 500:
                score = min(0.95, 0.55 + abs(bid_delta) / max(prev["bid_total"], 1))
                self._emit_signal(symbol, state, "bid_pull", "買盤", f"{symbol} 買盤五檔總量快速減少 {int(abs(bid_delta)):,}，疑似抽單。", score, {"bid_delta": bid_delta})

        if prev["ask_total"] > 0:
            if curr["ask_total"] >= prev["ask_total"] * 1.6 and ask_delta >= 500:
                score = min(0.95, 0.55 + abs(ask_delta) / max(prev["ask_total"], 1))
                self._emit_signal(symbol, state, "ask_stack_up", "賣盤", f"{symbol} 賣盤五檔總量異常增加 {int(ask_delta):,}，疑似壓盤掛單。", score, {"ask_delta": ask_delta})
            if curr["ask_total"] <= prev["ask_total"] * 0.55 and abs(ask_delta) >= 500:
                score = min(0.95, 0.55 + abs(ask_delta) / max(prev["ask_total"], 1))
                self._emit_signal(symbol, state, "ask_pull", "賣盤", f"{symbol} 賣盤五檔總量快速減少 {int(abs(ask_delta)):,}，疑似抽單。", score, {"ask_delta": ask_delta})

        bid_ratio_jump = curr["bid_near3_ratio"] - prev["bid_near3_ratio"]
        ask_ratio_jump = curr["ask_near3_ratio"] - prev["ask_near3_ratio"]

        if bid_ratio_jump >= 0.18 and curr["bid_near3_ratio"] >= 0.62:
            self._emit_signal(symbol, state, "bid_front_loaded", "買盤", f"{symbol} 買盤前三檔占比提高到 {curr['bid_near3_ratio']:.0%}，近價承接明顯集中。", min(0.9, 0.45 + bid_ratio_jump * 2), {"bid_near3_ratio": curr["bid_near3_ratio"]})
        if ask_ratio_jump >= 0.18 and curr["ask_near3_ratio"] >= 0.62:
            self._emit_signal(symbol, state, "ask_front_loaded", "賣盤", f"{symbol} 賣盤前三檔占比提高到 {curr['ask_near3_ratio']:.0%}，近價賣壓集中。", min(0.9, 0.45 + ask_ratio_jump * 2), {"ask_near3_ratio": curr["ask_near3_ratio"]})

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
                        "買盤",
                        f"{symbol} 買{idx + 1} ({curr_bid_price}) 掛單量瞬間增加 {bid_level_delta:,}，疑似逐檔堆量。",
                        min(0.95, 0.5 + abs(bid_level_delta) / max(prev_bid_size, 1)),
                        {"level": f"買{idx + 1}", "price": curr_bid_price, "delta": bid_level_delta},
                    )
                if prev_bid_size >= LEVEL_ABS_DELTA_THRESHOLD and curr_bid_size <= prev_bid_size * LEVEL_RATIO_DOWN_THRESHOLD and abs(bid_level_delta) >= LEVEL_ABS_DELTA_THRESHOLD:
                    self._emit_signal(
                        symbol,
                        state,
                        f"bid_level_{idx + 1}_pull",
                        "買盤",
                        f"{symbol} 買{idx + 1} ({curr_bid_price}) 掛單量快速減少 {abs(bid_level_delta):,}，疑似逐檔抽單。",
                        min(0.95, 0.5 + abs(bid_level_delta) / max(prev_bid_size, 1)),
                        {"level": f"買{idx + 1}", "price": curr_bid_price, "delta": bid_level_delta},
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
                        "賣盤",
                        f"{symbol} 賣{idx + 1} ({curr_ask_price}) 掛單量瞬間增加 {ask_level_delta:,}，疑似逐檔壓單。",
                        min(0.95, 0.5 + abs(ask_level_delta) / max(prev_ask_size, 1)),
                        {"level": f"賣{idx + 1}", "price": curr_ask_price, "delta": ask_level_delta},
                    )
                if prev_ask_size >= LEVEL_ABS_DELTA_THRESHOLD and curr_ask_size <= prev_ask_size * LEVEL_RATIO_DOWN_THRESHOLD and abs(ask_level_delta) >= LEVEL_ABS_DELTA_THRESHOLD:
                    self._emit_signal(
                        symbol,
                        state,
                        f"ask_level_{idx + 1}_pull",
                        "賣盤",
                        f"{symbol} 賣{idx + 1} ({curr_ask_price}) 掛單量快速減少 {abs(ask_level_delta):,}，疑似逐檔抽單。",
                        min(0.95, 0.5 + abs(ask_level_delta) / max(prev_ask_size, 1)),
                        {"level": f"賣{idx + 1}", "price": curr_ask_price, "delta": ask_level_delta},
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
                self._emit_signal(symbol, state, "ask_replenish_after_trade", "賣盤", f"{symbol} 成交價 {trade_price:.2f} 成交後，賣盤同價位未減反增，疑似補單。", 0.78, {"price": trade_price, "trade_size": trade_size})

        if prev_best_bid is not None and trade_price <= prev_best_bid:
            prev_size = prev["bid_map"].get(trade_price)
            curr_size = curr["bid_map"].get(trade_price)
            if prev_size is not None and curr_size is not None and curr_size >= prev_size:
                self._emit_signal(symbol, state, "bid_replenish_after_trade", "買盤", f"{symbol} 成交價 {trade_price:.2f} 成交後，買盤同價位未減反增，疑似補單。", 0.78, {"price": trade_price, "trade_size": trade_size})

    def _update_opening_state(self, symbol: str, state: SymbolState, trade: dict[str, Any]) -> None:
        trade_price = float(trade.get("price") or 0)
        if trade_price <= 0:
            return

        if state.open_trade is None:
            state.open_trade = trade
            self._emit_signal(symbol, state, "opening_trade", "開盤", f"{symbol} 已記錄第一筆開盤成交，價格 {trade_price:.2f}。", 0.5, {"open_price": trade_price}, cooldown_seconds=3600)

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
                    if key not in self.subscriptions:
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
            signal_events.appendleft(SignalEvent("bid_stack_up", "買盤", f"{symbol} 買盤近價掛單集中，示範訊號。", 0.74))
        else:
            signal_events.appendleft(SignalEvent("ask_pull", "賣盤", f"{symbol} 賣盤五檔快速減少，示範訊號。", 0.68))

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
        return {"ok": False, "message": "RestClient 不可用，fugle-marketdata 套件可能未正確安裝。", "data": None}

    try:
        client = RestClient(api_key=api_key)
        quote = client.stock.intraday.quote(symbol=symbol)
        return {"ok": True, "message": f"REST 測試成功：已取得 {symbol} 報價。", "data": quote}
    except Exception as exc:
        return {"ok": False, "message": f"REST 測試失敗：{exc}", "data": None}


@st.cache_data(ttl=5, show_spinner=False)
def fetch_benchmark_data() -> dict[str, Any]:
    if yf is None:
        return {"ok": False, "message": "yfinance 套件未安裝，無法載入全球指數參考。", "items": []}

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

    message = "全球指數參考載入成功。"
    if failures:
        message = "部分全球指數參考載入失敗：" + " | ".join(failures[:3])
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
            direction = "偏多" if change_pct > 0 else "偏空"
            st.session_state.index_signal_events.appendleft(
                SignalEvent(
                    event_type="twii_shock",
                    side="大盤",
                    message=f"台灣加權指數 15 秒變動 {change_pct:+.2f}%，大盤出現明顯 {direction} 異動。",
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
        if event.side == "買盤":
            score += event.score
        elif event.side == "賣盤":
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
                reasons.append(f"現價相對開盤上漲 {intraday_move_pct:.2f}%。")
            elif intraday_move_pct <= -1.2:
                score -= 0.8
                reasons.append(f"現價相對開盤下跌 {abs(intraday_move_pct):.2f}%。")

    if last_trade and session_high and session_low:
        last_price = float(last_trade.get("price") or 0)
        if session_high and last_price >= session_high * 0.997:
            score += 0.35
            reasons.append("價格接近盤中高點。")
        if session_low and last_price <= session_low * 1.003:
            score -= 0.35
            reasons.append("價格接近盤中低點。")

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
    st.subheader("全球指數參考")
    st.caption("此區為參考數據，可能為延遲報價，非交易所即時成交。")

    for item in benchmark_result.get("items", []):
        price = item.get("price")
        change = item.get("change")
        change_pct = item.get("change_pct")
        if price is None:
            price_text = "-"
            delta = "資料暫缺"
        else:
            sign = "+" if change is not None and change > 0 else ""
            delta = f"{sign}{change:,.2f} ({sign}{change_pct:.2f}%)" if change is not None and change_pct is not None else "-"
            price_text = f"{price:,.2f}"

        st.metric(item.get("label", "-"), price_text, delta=delta)
        st.caption(f"最後更新 {item.get('time', '-')} | {item.get('symbol', '-')}")
        if item.get("stale"):
            age_text = f"{int(item['age_seconds'])} 秒" if item.get("age_seconds") is not None else "未知"
            st.caption(f"來源未更新：{age_text}")
        st.caption(item.get("note", "參考"))

    if benchmark_result.get("message"):
        st.caption(benchmark_result["message"])


def render_index_signal_panel(benchmark_result: dict[str, Any], index_events: list[SignalEvent]) -> None:
    st.markdown('<div class="panel-title">大盤異動提示</div>', unsafe_allow_html=True)
    twii_item = next((item for item in benchmark_result.get("items", []) if item.get("symbol") == "^TWII"), None)

    cols = st.columns(4)
    if twii_item and twii_item.get("price") is not None:
        price_text = f"{twii_item['price']:,.2f}"
        change = float(twii_item.get("change") or 0)
        change_pct = float(twii_item.get("change_pct") or 0)
        sign = "+" if change > 0 else ""
        delta_text = f"{sign}{change:,.2f} ({sign}{change_pct:.2f}%)"
        cols[0].metric("台灣加權指數", price_text, delta=delta_text)
        cols[1].metric("最後更新", twii_item.get("time", "-"))
        cols[2].metric("資料狀態", "來源未更新" if twii_item.get("stale") else "更新中")
        cols[3].metric("事件數", len(index_events))
    else:
        cols[0].metric("台灣加權指數", "-")
        cols[1].metric("最後更新", "-")
        cols[2].metric("資料狀態", "無資料")
        cols[3].metric("事件數", len(index_events))

    if not index_events:
        render_empty_box("目前尚未偵測到台灣加權指數的明顯急變。", medium=True)
        return

    rows = [
        {
            "時間": event.created_at.strftime("%H:%M:%S"),
            "強度": classify_severity(event.score),
            "內容": event.message,
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
    st.markdown(f'<div class="panel-title">{symbol} 五檔委買委賣</div>', unsafe_allow_html=True)
    if not book:
        render_empty_box("尚未收到五檔資料。", tall=True)
        return

    bids = book.get("bids", [])
    asks = book.get("asks", [])
    rows = []
    for idx in range(max(len(bids), len(asks), 5)):
        bid = bids[idx] if idx < len(bids) else {}
        ask = asks[idx] if idx < len(asks) else {}
        rows.append({"委買量": bid.get("size", ""), "委買價": bid.get("price", ""), "委賣價": ask.get("price", ""), "委賣量": ask.get("size", "")})
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, height=ORDER_BOOK_HEIGHT)
    st.caption(f"更新時間：{format_fugle_time(book.get('time'))}")


def render_trade_summary(symbol: str, trade: dict[str, Any] | None, quote_data: dict[str, Any] | None) -> None:
    st.markdown(f'<div class="panel-title">{symbol} 最新成交</div>', unsafe_allow_html=True)
    if not trade:
        render_empty_box("尚未收到成交資料。", medium=True)
        return

    cols = st.columns(4)
    cols[0].metric("成交價", trade.get("price", "-"))
    cols[1].metric("成交量", trade.get("size", "-"))
    cols[2].metric("累積量", trade.get("volume", "-"))
    cols[3].metric("時間", format_fugle_time(trade.get("time")))
    if quote_data and quote_data.get("isClose"):
        st.caption("目前顯示收盤快照。")


def render_trade_tape(trades: list[dict[str, Any]]) -> None:
    st.markdown('<div class="panel-title">即時成交明細</div>', unsafe_allow_html=True)
    if not trades:
        render_empty_box("尚未收到即時成交明細。", tall=True)
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
                "時間": format_fugle_time(item.get("time")),
                "買價": fmt_price(bid),
                "賣價": fmt_price(ask),
                "成交價格": fmt_price(price),
                "數量": item.get("size"),
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
        for target_col in ("成交價格", "數量"):
            if target_col in columns:
                styles[columns.index(target_col)] = color
        return styles

    styled = df.style.apply(style_trade_row, axis=1).hide(axis="columns", subset=["_side"])
    st.dataframe(styled, width="stretch", hide_index=True, height=TRADE_TAPE_HEIGHT)


def render_signal_panel(symbol: str, signal_events: list[SignalEvent]) -> None:
    st.markdown(f'<div class="panel-title">{symbol} 異常訊號</div>', unsafe_allow_html=True)
    if not signal_events:
        render_empty_box("目前尚未偵測到明顯的五檔或成交異常。", tall=True)
        return

    rows = [
        {
            "時間": event.created_at.strftime("%H:%M:%S"),
            "方向": event.side,
            "類型": event.event_type,
            "強度": classify_severity(event.score),
            "內容": event.message,
        }
        for event in signal_events[:8]
    ]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, height=SIGNAL_PANEL_HEIGHT)


def render_book_summary(summary: dict[str, Any] | None) -> None:
    st.markdown('<div class="panel-title">五檔結構摘要</div>', unsafe_allow_html=True)
    cols = st.columns(4)
    if not summary:
        cols[0].metric("買盤總量", "-")
        cols[1].metric("賣盤總量", "-")
        cols[2].metric("買前三檔占比", "-")
        cols[3].metric("賣前三檔占比", "-")
        render_empty_box("尚未累積足夠五檔結構。", medium=True)
        return
    cols[0].metric("買盤總量", f"{int(summary['bid_total']):,}")
    cols[1].metric("賣盤總量", f"{int(summary['ask_total']):,}")
    cols[2].metric("買前三檔占比", f"{summary['bid_near3_ratio']:.0%}")
    cols[3].metric("賣前三檔占比", f"{summary['ask_near3_ratio']:.0%}")


def render_opening_panel(symbol: str, symbol_data: dict[str, Any]) -> None:
    st.markdown(f'<div class="panel-title">{symbol} 開盤追蹤</div>', unsafe_allow_html=True)
    open_trade = symbol_data.get("open_trade")
    last_trade = symbol_data.get("last_trade")
    session_high = symbol_data.get("session_high")
    session_low = symbol_data.get("session_low")

    cols = st.columns(4)
    if not open_trade:
        cols[0].metric("開盤第一筆", "-")
        cols[1].metric("目前相對開盤", "-")
        cols[2].metric("盤中高點", f"{session_high:,.2f}" if session_high else "-")
        cols[3].metric("盤中低點", f"{session_low:,.2f}" if session_low else "-")
        st.markdown("<div style='height: 18px;'></div>", unsafe_allow_html=True)
        return

    open_price = float(open_trade.get("price") or 0)
    last_price = float(last_trade.get("price") or 0) if last_trade else 0
    move_pct = 0.0 if open_price == 0 or last_price == 0 else (last_price - open_price) / open_price * 100
    cols[0].metric("開盤第一筆", f"{open_price:,.2f}")
    cols[1].metric("目前相對開盤", f"{move_pct:+.2f}%")
    cols[2].metric("盤中高點", f"{session_high:,.2f}" if session_high else "-")
    cols[3].metric("盤中低點", f"{session_low:,.2f}" if session_low else "-")
    st.markdown("<div style='height: 18px;'></div>", unsafe_allow_html=True)


def render_decision_panel(symbol: str, symbol_data: dict[str, Any], index_events: list[SignalEvent]) -> None:
    st.markdown(f'<div class="panel-title">{symbol} 綜合判斷</div>', unsafe_allow_html=True)
    score, reasons = calc_symbol_signal_score(symbol_data, index_events)
    bias = score_to_bias(score)
    cols = st.columns(3)
    cols[0].metric("綜合分數", f"{score:+.2f}")
    cols[1].metric("判斷", bias)
    cols[2].metric("依據數", len(reasons))
    if not reasons:
        render_empty_box("目前資料不足，尚未形成明確的多空觀察結論。", medium=True)
        return
    st.dataframe(pd.DataFrame([{"說明": reason} for reason in reasons]), width="stretch", hide_index=True, height=OPEN_PANEL_HEIGHT)


def render_tick_record_panel(symbol: str, trade_history: list[dict[str, Any]]) -> None:
    st.markdown(f'<div class="panel-title">{symbol} 開盤逐筆記錄</div>', unsafe_allow_html=True)
    if not trade_history:
        render_empty_box("尚未開始累積逐筆成交紀錄。", tall=True)
        return
    rows = [{"時間": format_fugle_time(item.get("time")), "成交價": item.get("price"), "成交量": item.get("size"), "序號": item.get("serial")} for item in trade_history[:50]]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, height=TRADE_TAPE_HEIGHT)


def render_log_panel(symbols: list[str]) -> None:
    st.subheader("資料落地紀錄")
    st.caption(f"逐筆成交、五檔摘要與訊號會寫入：{DATA_LOG_DIR}")
    today = today_taipei_str()
    rows = []
    for symbol in symbols:
        tick_path = TICK_LOG_DIR / f"{today}_{symbol}_ticks.csv"
        book_path = BOOK_LOG_DIR / f"{today}_{symbol}_books.csv"
        signal_path = SIGNAL_LOG_DIR / f"{today}_{symbol}_signals.csv"
        rows.append(
            {
                "股票": symbol,
                "逐筆檔": tick_path.name,
                "五檔檔": book_path.name,
                "訊號檔": signal_path.name,
                "逐筆已建立": "是" if tick_path.exists() else "否",
                "五檔已建立": "是" if book_path.exists() else "否",
                "訊號已建立": "是" if signal_path.exists() else "否",
            }
        )
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def resolve_market_source(mode: str, api_key: str | None, symbols: list[str]) -> dict[str, Any]:
    if mode == "示範資料":
        return {
            "source_name": "示範資料",
            "using_demo": True,
            "snapshots": build_mock_snapshot(symbols),
            "status": {
                "connected": False,
                "authenticated": False,
                "error_message": None,
                "last_event_at": now_taipei(),
                "last_status_message": "示範模式",
                "subscriptions": 0,
                "pending_subscriptions": 0,
            },
            "rest_result": {"ok": False, "message": "示範模式下不執行 REST 測試。", "data": None},
            "rest_snapshots": {},
            "diagnostic_note": "目前強制使用示範資料，不會連線 Fugle。",
            "store": None,
        }

    if not api_key:
        return {
            "source_name": "示範資料",
            "using_demo": True,
            "snapshots": build_mock_snapshot(symbols),
            "status": {
                "connected": False,
                "authenticated": False,
                "error_message": "未提供 Fugle API key。",
                "last_event_at": now_taipei(),
                "last_status_message": "自動切換至示範模式",
                "subscriptions": 0,
                "pending_subscriptions": 0,
            },
            "rest_result": {"ok": False, "message": "未提供 API key，已改用示範資料。", "data": None},
            "rest_snapshots": {},
            "diagnostic_note": "尚未設定 Fugle API key，因此以示範資料運作。",
            "store": None,
        }

    if RestClient is None or WebSocketClient is None:
        return {
            "source_name": "示範資料",
            "using_demo": True,
            "snapshots": build_mock_snapshot(symbols),
            "status": {
                "connected": False,
                "authenticated": False,
                "error_message": "fugle-marketdata 套件未安裝。",
                "last_event_at": now_taipei(),
                "last_status_message": "自動切換至示範模式",
                "subscriptions": 0,
                "pending_subscriptions": 0,
            },
            "rest_result": {"ok": False, "message": "fugle-marketdata 套件未安裝。", "data": None},
            "rest_snapshots": {},
            "diagnostic_note": "缺少 Fugle SDK，因此以示範資料運作。",
            "store": None,
        }

    rest_snapshots: dict[str, dict[str, Any]] = {}
    primary_rest_result = test_rest_quote(api_key, symbols[0])

    if not primary_rest_result.get("ok"):
        fallback_label = "Fugle（驗證失敗，改用示範資料）" if mode == "自動" else "Fugle（驗證失敗）"
        return {
            "source_name": fallback_label,
            "using_demo": True,
            "snapshots": build_mock_snapshot(symbols),
            "status": {
                "connected": False,
                "authenticated": False,
                "error_message": primary_rest_result.get("message"),
                "last_event_at": now_taipei(),
                "last_status_message": "REST 驗證失敗，未啟用即時串流",
                "subscriptions": 0,
                "pending_subscriptions": 0,
            },
            "rest_result": primary_rest_result,
            "rest_snapshots": {},
            "diagnostic_note": "Fugle REST 已失敗，因此不再嘗試把整體功能綁死在 WebSocket 上，先退回示範資料保留版面與訊號面板。",
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
        "diagnostic_note": "Fugle REST 驗證成功，已啟用即時串流模式；若收盤後無推播，畫面會使用 REST 快照填入。",
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


st.set_page_config(page_title="台股即時監控台", page_icon=":bar_chart:", layout="wide")
inject_custom_css()
ensure_log_dirs()

st.title("台股即時監控台")
st.caption("使用 Streamlit 製作的台股五檔委買委賣、即時成交、開盤追蹤、異常訊號與盤中資料落地監控頁面。")

with st.sidebar:
    st.header("監控設定")
    symbols_raw = st.text_input("股票代碼", value=", ".join(DEFAULT_SYMBOLS), help="請用逗號分隔，例如：2330, 2317")
    symbols = normalize_symbols(symbols_raw) or DEFAULT_SYMBOLS
    refresh_seconds = st.slider("刷新秒數", min_value=1, max_value=10, value=1)
    source_mode = st.selectbox("資料源模式", ["自動", "Fugle", "示範資料"], index=0)
    st.caption("Fugle 免費方案有訂閱數限制，每個股票代碼會同時使用 books 與 trades 兩個頻道。")

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

render_log_panel(symbols)

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
            render_book_summary(symbol_data.get("book_summary"))

if refresh_seconds > 0:
    time.sleep(refresh_seconds)
    st.rerun()

with st.expander("部署說明"):
    st.markdown(
        """
        - 本系統保留台股五檔、即時成交、開盤追蹤、異常訊號與全球指數參考面板。
        - 當 Fugle 驗證失敗時，系統會自動退回示範資料，避免整個頁面失效。
        - 盤中逐筆成交、五檔摘要與異常訊號會同步寫入 `data_logs`，方便後續做 replay 與回測。
        - 若收盤後 WebSocket 無新推播，系統會使用 REST quote 快照填入五檔與最新成交。
        - 全球指數區使用 Yahoo Finance 參考資料，可能為延遲報價，不建議直接作為交易依據。
        - 異常訊號屬規則式監控，適合盤中輔助判讀，不代表保證性的買賣建議。
        """
    )
