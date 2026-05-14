"""
notify.py — 股價超底警報
每天定時執行，檢查是否有觸發加碼或超底信號，發送 LINE 通知

觸發加碼：10日跌幅 ≤ -10%
超底警報：10日跌幅 ≤ -15% + RSI < 30 + 現價低於10日均-5%
"""

import yfinance as yf
import pandas as pd
import numpy as np
import requests
import json
import logging
from datetime import datetime, timezone, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ── 設定 ─────────────────────────────────────────────
LINE_TOKEN = "fsYPQrWNS8vYhw4Q5NG0C0x8BTnbMWrmQrRMPk3o+XJDfa8WiTaIn23x1Kk4dhpsegmy5SNEz9Jkip4htkHUlgJDba7KuCMTL/cXdC5G9fJwnlA/tkmBG665O+tI6yOVpGxg2RvkICPksibjm5k4+QdB04t89/1O/w1cDnyilFU="

LINE_USERS = [
    "U125ab7e4b9a70a771b51bac84256f985",
    "U502b8ee6cace7467f10c0b78409b6a38",
]

# 超底門檻
TRIGGER_10D      = -10.0   # 觸發加碼：10日跌幅 ≤ -10%
SUPER_10D        = -15.0   # 超底：10日跌幅 ≤ -15%
SUPER_RSI        = 30.0    # 超底：RSI < 30
HISTORY_DAYS     = 40

STOCKS = [
    ("TSM",    "台積電 ADR"),
    ("GOOGL",  "Alphabet"),
    ("AAPL",   "Apple"),
    ("NVDA",   "NVIDIA"),
    ("TSLA",   "Tesla"),
    ("PLTR",   "Palantir"),
    ("META",   "Meta Platforms"),
    ("MSFT",   "Microsoft"),
    ("INTC",   "Intel"),
    ("MU",     "Micron Technology"),
    ("AMZN",   "Amazon"),
    ("LLY",    "Eli Lilly"),
    ("ASML",   "ASML Holding"),
    ("LRCX",   "Lam Research"),
    ("AVGO",   "Broadcom"),
    ("AMD",    "AMD"),
    ("NFLX",   "Netflix"),
    ("ORCL",   "Oracle"),
    ("QQQ",    "Nasdaq 100 ETF"),
    ("VOO",    "S&P 500 ETF"),
    ("GLD",    "SPDR Gold ETF"),
    ("2330.TW",   "台積電"),
    ("2308.TW",   "台達電"),
    ("2377.TW",   "微星"),
    ("0050.TW",   "元大台灣50"),
    ("00631L.TW", "元大台灣50正2"),
    ("2327.TW",   "國巨"),
    ("3711.TW",   "日月光控股"),
    ("6285.TW",   "啟碁"),
    ("8299.TWO",  "群聯"),
    ("5274.TWO",  "信驊"),
]


# ── 工具函式 ──────────────────────────────────────────
def pct(new_val, old_val):
    if old_val is None or old_val == 0:
        return None
    try:
        return round((new_val - old_val) / old_val * 100, 2)
    except:
        return None

def safe_float(val):
    if val is None:
        return None
    try:
        v = float(val)
        return None if np.isnan(v) else round(v, 2)
    except:
        return None

def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    delta = closes.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    rsi   = 100 - (100 / (1 + rs))
    val   = rsi.iloc[-1]
    return round(float(val), 1) if not np.isnan(val) else None

def get_col(raw, field, symbol):
    try:
        if (field, symbol) in raw.columns:
            return raw[(field, symbol)].dropna()
        return raw[field].dropna()
    except:
        return pd.Series(dtype=float)

def is_tw_stock(symbol):
    return symbol.endswith(".TW") or symbol.endswith(".TWO")

def get_taiwan_time():
    return datetime.now(timezone(timedelta(hours=8)))


# ── 分析股票 ──────────────────────────────────────────
def analyze():
    symbols  = [s[0] for s in STOCKS]
    name_map = dict(STOCKS)

    log.info(f"下載 {len(symbols)} 支股票資料...")
    raw = yf.download(symbols, period=f"{HISTORY_DAYS}d",
                      auto_adjust=True, progress=False)

    triggered    = []  # 觸發加碼
    super_bottom = []  # 超底警報

    for symbol in symbols:
        name = name_map[symbol]
        try:
            closes = get_col(raw, "Close", symbol)
            if closes.empty or len(closes) < 11:
                continue

            current  = safe_float(closes.iloc[-1])
            price10d = safe_float(closes.iloc[-11]) if len(closes) >= 11 else None
            chg10    = pct(current, price10d)
            ma10     = safe_float(closes.iloc[-10:].mean()) if len(closes) >= 10 else None
            ma10_m5  = round(ma10 * 0.95, 2) if ma10 else None
            rsi      = calc_rsi(closes)

            if chg10 is None or current is None:
                continue

            # 觸發加碼：10日跌幅 ≤ -10%
            if chg10 <= TRIGGER_10D:
                is_super = (
                    chg10 <= SUPER_10D and
                    rsi is not None and rsi < SUPER_RSI and
                    ma10_m5 is not None and current < ma10_m5
                )

                item = {
                    "symbol":   symbol,
                    "name":     name,
                    "price":    current,
                    "price10d": price10d,
                    "chg10":    chg10,
                    "ma10":     ma10,
                    "ma10_m5":  ma10_m5,
                    "rsi":      rsi,
                    "is_super": is_super,
                    "is_tw":    is_tw_stock(symbol),
                }

                if is_super:
                    super_bottom.append(item)
                    log.info(f"  🚨 超底: {symbol} {name} 10日跌幅={chg10}% RSI={rsi}")
                else:
                    triggered.append(item)
                    log.info(f"  ⚠️  觸發: {symbol} {name} 10日跌幅={chg10}%")

        except Exception as e:
            log.error(f"  {symbol} 錯誤：{e}")

    return triggered, super_bottom


# ── 組合訊息 ──────────────────────────────────────────
def build_message(triggered, super_bottom):
    tw_time  = get_taiwan_time()
    date_str = tw_time.strftime("%Y/%m/%d %H:%M")

    if not triggered and not super_bottom:
        return None

    msg = f"📊 股價提醒\n日期：{date_str}\n"
    msg += "━" * 20 + "\n\n"

    # 超底優先顯示
    if super_bottom:
        msg += "🚨【超底警報】\n"
        msg += "10日跌幅 ≤ -15% + RSI < 30 + 低於均線-5%\n\n"
        for s in super_bottom:
            msg += f"▌{s['symbol']} {s['name']}\n"
            msg += f"現價：{s['price']}\n"
            msg += f"10日前：{s['price10d']}\n"
            msg += f"10日跌幅：{s['chg10']}%\n"
            msg += f"RSI：{s['rsi']}\n"
            msg += f"10日均-5%：{s['ma10_m5']}\n\n"

    # 一般觸發加碼
    if triggered:
        msg += "⚠️【觸發加碼】\n"
        msg += "10日跌幅 ≤ -10%\n\n"
        for s in triggered:
            msg += f"▌{s['symbol']} {s['name']}\n"
            msg += f"現價：{s['price']}\n"
            msg += f"10日前：{s['price10d']}\n"
            msg += f"10日跌幅：{s['chg10']}%\n\n"

    msg += "川普投顧"
    return msg


# ── 發送 LINE ─────────────────────────────────────────
def send_line(message):
    url     = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type":  "application/json",
        "Authorization": f"Bearer {LINE_TOKEN}",
    }

    for user_id in LINE_USERS:
        payload = {
            "to": user_id,
            "messages": [{"type": "text", "text": message}],
        }
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=10)
            if res.status_code == 200:
                log.info(f"  ✅ LINE 發送成功：{user_id[:8]}...")
            else:
                log.error(f"  ❌ LINE 失敗：{res.status_code} {res.text}")
        except Exception as e:
            log.error(f"  ❌ LINE 錯誤：{e}")


# ── 時段判斷 ──────────────────────────────────────────
def should_run():
    """
    判斷現在是否在適當的通知時段
    台股：週一到週五 14:00~14:30（收盤後）
    美股：週二到週六 06:00~06:30（台灣時間，美股收盤後）
    """
    tw  = get_taiwan_time()
    day = tw.weekday()  # 0=週一 ... 6=週日
    h   = tw.hour

    # 週日完全不發
    if day == 6:
        log.info("週日，不發送")
        return False, False

    # 台股時段：週一到週五 14:00~14:30
    run_tw = (day <= 4 and h == 14)

    # 美股時段：週二到週六 06:00~06:30（週六是週五美股收盤後）
    run_us = ((day >= 1 and day <= 4) or day == 5) and h == 6

    return run_tw, run_us


# ── 主程式 ────────────────────────────────────────────
def main():
    log.info("=== 超底警報系統啟動 ===")

    run_tw, run_us = should_run()
    log.info(f"台股時段：{run_tw}  美股時段：{run_us}")

    if not run_tw and not run_us:
        log.info("非通知時段，結束")
        return

    triggered, super_bottom = analyze()

    # 根據時段過濾
    if not run_tw:
        triggered    = [s for s in triggered    if not s["is_tw"]]
        super_bottom = [s for s in super_bottom if not s["is_tw"]]
    if not run_us:
        triggered    = [s for s in triggered    if s["is_tw"]]
        super_bottom = [s for s in super_bottom if s["is_tw"]]

    msg = build_message(triggered, super_bottom)

    if msg:
        log.info("發送通知...")
        log.info(f"\n{msg}")
        send_line(msg)
    else:
        log.info("無觸發項目，不發送")

    log.info("=== 完成 ===")


if __name__ == "__main__":
    main()
