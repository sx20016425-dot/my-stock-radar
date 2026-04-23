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
MAX_BOOK_HISTORY = 240
MAX_SIGNAL_EVENTS = 80
UUID_PAIR_PATTERN = re.compile(r"^[0-9a-fA-F-]{36}\s+[0-9a-fA-F-]{36}$")
BENCHMARK_SYMBOLS = [
    {"label": "台灣加權指數", "symbol": "^TWII", "note": "現貨指數參考"},
    {"label": "日經225", "symbol": "^N225", "note": "現貨指數參考"},
    {"label": "恆生指數", "symbol": "^HSI", "note": "現貨指數參考"},
    {"label": "韓國KOSPI", "symbol": "^KS11", "note": "現貨指數參考"},
    {"label": "那指期貨參考", "symbol": "NQ=F", "note": "期貨參考"},
    {"label": "標普期貨參考", "symbol": "ES=F", "note": "期貨參考"},
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
        return decoded, "偵測到 Base64 包裝格式，已自動解碼後使用"
