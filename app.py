import base64
import binascii
import csv
import json
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
    {"label": "台灣加權指數", "symbol": "^TWII", "note": "現貨指數參考"},
    {"label": "日經225", "symbol": "^N225", "note": "現貨指數參考"},
    {"label": "恆生指數", "symbol": "^HSI", "note": "現貨指數參考"},
    {"label": "韓國KOSPI", "symbol": "^KS11", "note": "現貨指數參考"},
    {"label": "那指期貨參考", "symbol": "NQ=F", "note": "期貨參考"},
    {"label": "標普期貨參考", "symbol": "ES=F", "note": "期貨參考"},
]

SYMBOL_NAME_HINTS = {
    "2330": "台積電",
    "2317": "鴻海",
    "2454": "聯發科",
    "0050": "元大台灣50",
    "0056": "元大高股息",
}

LOGIN_HELP_TEXT = "請輸入你核發的登入序號。只有通過審核的序號才能進入監控頁。"


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
    parts = [item.strip() for item in raw.replace(";", ",").replace("，", ",").split(",")]
    return [item for item in parts if item]
