"""
fetch_prices.py
每日股價爬蟲 — 使用 yfinance
輸出：data/prices.json（給網站用）、data/prices.csv（備份用）

用法：
  python fetch_prices.py          # 抓取並輸出
  python fetch_prices.py --test   # 只測試第一支股票
"""

import yfinance as yf
import pandas as pd
import numpy as np
import json
import csv
import sys
import logging
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger(__name__)

OUTPUT_DIR = Path("data")
OUTPUT_DIR.mkdir(exist_ok=True)

STOCKS = [
    # ── 美股 ──
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
    ("ASX",    "ASX"),
    ("AMZN",   "Amazon"),
    ("LLY",    "Eli Lilly"),
    ("ASML",   "ASML Holding"),
    ("LRCX",   "Lam Research"),
    ("AVGO",   "Broadcom"),
    ("GEV",    "GE Vernova"),
    ("ETN",    "Eaton Corp"),
    ("NEE",    "NextEra Energy"),
    ("QQQ",    "Nasdaq 100 ETF"),
    ("QLD",    "2x Nasdaq ETF"),
    ("VOO",    "S&P 500 ETF"),
    ("SSO",    "2x S&P 500 ETF"),
    ("LEU",    "Centrus Energy"),
    ("ORCL",   "Oracle"),
    ("USAR",   "USAR"),
    ("UUUU",   "Energy Fuels"),
    ("GLD",    "SPDR Gold ETF"),
    ("B",      "Barnes Group"),
    ("AEM",    "Agnico Eagle"),
    ("COHR",   "Coherent Corp"),
    ("LITE",   "Lumentum"),
    ("APLD",   "Applied Digital"),
    ("CRWD",   "CrowdStrike"),
    ("IONQ",   "IonQ"),
    ("AMD",    "AMD"),
    ("OKLO",   "Oklo"),
    ("SNOW",   "Snowflake"),
    ("VRT",    "Vertiv"),
    ("NBIS",   "Nebius Group"),
    ("UNH",    "UnitedHealth"),
    ("NFLX",   "Netflix"),
    ("CRWV",   "CoreWeave"),
    ("MRVL",   "Marvell Technology"),
    # ── 台股上市 (.TW) ──
    ("2330.TW",   "台積電"),
    ("3711.TW",   "日月光控股"),
    ("6285.TW",   "啟碁"),
    ("0050.TW",   "元大台灣50"),
    ("00631L.TW", "元大台灣50正2"),
    ("00675L.TW", "富邦臺灣加權正2"),
    ("00662.TW",  "富邦NASDAQ"),
    ("00924.TW",  "復華S&P500成長"),
    ("00935.TW",  "野村台灣新科技50"),
    ("2327.TW",   "國巨"),
    ("2377.TW",   "微星"),
    ("2308.TW",   "台達電"),
    ("2357.TW",   "華碩"),
    ("3413.TW",   "京鼎"),
    ("8996.TW",   "高力"),
    ("7769.TW",   "鴻勁"),
    ("2301.TW",   "光寶科"),
    ("4958.TW",   "臻鼎"),
    ("2383.TW",   "台光電"),
    ("2404.TW",   "漢唐"),
    ("2408.TW",   "南亞科"),
    ("3037.TW",   "欣興"),
    ("2313.TW",   "華通"),
    ("2912.TW",   "統一超"),
    ("006208.TW", "富邦台灣采吉50"),
    ("3481.TW",   "群創"),
    # ── 台股上櫃 (.TWO) ──
    ("3211.TWO",  "順達"),
    ("8299.TWO",  "群聯"),
    ("3680.TWO",  "家登"),
    ("5274.TWO",  "信驊"),
    ("4979.TWO",  "華星光"),
    ("1785.TWO",  "光陽科"),
    ("5347.TWO",  "世界"),
    ("3293.TWO",  "鈊象"),
    ("4541.TWO",  "晟田"),
    ("4931.TWO",  "新盛力"),
]

HISTORY_DAYS = 35


# ── 工具函式 ──────────────────────────────────────────
def pct(new_val, old_val):
    if old_val is None or old_val == 0 or (isinstance(old_val, float) and np.isnan(old_val)):
        return None
    return round((new_val - old_val) / old_val * 100, 2)

def safe_float(val):
    if val is None:
        return None
    try:
        v = float(val)
        return None if np.isnan(v) else round(v, 2)
    except Exception:
        return None

def safe_int(val):
    if val is None:
        return None
    try:
        v = int(val)
        return None if v == 0 else v
    except Exception:
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

def format_market_cap(val):
    if val is None:
        return None
    if val >= 1e12: return f"{val/1e12:.2f}T"
    if val >= 1e9:  return f"{val/1e9:.1f}B"
    if val >= 1e6:  return f"{val/1e6:.0f}M"
    return str(val)

def get_col(raw, field, symbol):
    try:
        if (field, symbol) in raw.columns:
            return raw[(field, symbol)].dropna()
        return raw[field].dropna()
    except Exception:
        return pd.Series(dtype=float)

def calc_status(change_10d_pct):
    if change_10d_pct is None:
        return "觀察中"
    return "觸發加碼" if change_10d_pct <= -10.0 else "觀察中"

def calc_alert(current_price, ma10_minus5):
    if current_price is None or ma10_minus5 is None:
        return "OBS"
    return "Alert" if current_price < ma10_minus5 else "OBS"


# ── 批次抓取 ──────────────────────────────────────────
def fetch_all(stocks, test_mode=False):
    symbols  = [s[0] for s in stocks]
    name_map = dict(stocks)

    log.info(f"下載 {len(symbols)} 支股票（{HISTORY_DAYS}日）...")
    raw = yf.download(symbols, period=f"{HISTORY_DAYS}d",
                      auto_adjust=True, progress=False)

    log.info(f"下載 {len(symbols)} 支股票（1年，52週高低）...")
    raw1y = yf.download(symbols, period="1y",
                        auto_adjust=True, progress=False)

    log.info("抓取 info（PE、市值）...")
    info_map = {}
    for sym in symbols:
        try:
            info_map[sym] = yf.Ticker(sym).info
        except Exception:
            info_map[sym] = {}

    results = []
    for symbol in symbols:
        name = name_map[symbol]
        try:
            closes  = get_col(raw,   "Close",  symbol)
            highs   = get_col(raw,   "High",   symbol)
            lows    = get_col(raw,   "Low",    symbol)
            volumes = get_col(raw,   "Volume", symbol)
            c1y     = get_col(raw1y, "Close",  symbol)

            if closes.empty or len(closes) < 2:
                log.warning(f"  {symbol}: 資料不足")
                results.append(_empty(symbol, name))
                continue

            info = info_map.get(symbol, {})

            current   = safe_float(closes.iloc[-1])
            p10d      = safe_float(closes.iloc[-11]) if len(closes) >= 11 else None
            p20d      = safe_float(closes.iloc[-21]) if len(closes) >= 21 else None
            chg10     = pct(current, p10d)
            chg20     = pct(current, p20d)
            ma10      = safe_float(closes.iloc[-10:].mean()) if len(closes) >= 10 else None
            ma10_m5   = round(ma10 * 0.95, 2) if ma10 else None
            dist_ma10 = pct(current, ma10)
            rsi       = calc_rsi(closes)
            day_high  = safe_float(highs.iloc[-1])   if not highs.empty   else None
            day_low   = safe_float(lows.iloc[-1])    if not lows.empty    else None
            vol_today = safe_int(volumes.iloc[-1])   if not volumes.empty else None
            vol_avg   = safe_int(volumes.mean())     if not volumes.empty else None
            vol_ratio = round(vol_today / vol_avg, 2) if vol_today and vol_avg else None
            w52_high  = safe_float(c1y.max())        if not c1y.empty     else None
            w52_low   = safe_float(c1y.min())        if not c1y.empty     else None
            pe        = safe_float(info.get("trailingPE"))
            mkt_cap   = format_market_cap(info.get("marketCap"))

            daily = {}
            for n in range(1, 8):
                pn   = safe_float(closes.iloc[-(n+1)]) if len(closes) >= n+1 else None
                prev = safe_float(closes.iloc[-(n+2)]) if len(closes) >= n+2 else None
                daily[f"day{n}_price"]  = pn
                daily[f"day{n}_change"] = pct(pn, prev)

            row = {
                "symbol": symbol, "name": name,
                "current": current,
                "price_10d": p10d,   "change_10d": chg10,
                "price_20d": p20d,   "change_20d": chg20,
                "ma10": ma10,        "ma10_5pct": ma10_m5,
                "status": calc_status(chg10),
                "alert":  calc_alert(current, ma10_m5),
                "dist_ma10": dist_ma10,
                "rsi":       rsi,
                "day_high":  day_high,  "day_low":   day_low,
                "vol_today": vol_today, "vol_avg":   vol_avg, "vol_ratio": vol_ratio,
                "w52_high":  w52_high,  "w52_low":   w52_low,
                "pe": pe, "mkt_cap": mkt_cap,
                **daily,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            }
            results.append(row)

            if test_mode:
                _print_row(row)
                break

        except Exception as e:
            log.error(f"  {symbol} 錯誤：{e}")
            results.append(_empty(symbol, name))

    return results


def _empty(symbol, name):
    row = {"symbol": symbol, "name": name,
           "current": None, "price_10d": None, "change_10d": None,
           "price_20d": None, "change_20d": None,
           "ma10": None, "ma10_5pct": None,
           "status": "觀察中", "alert": "OBS",
           "dist_ma10": None, "rsi": None,
           "day_high": None, "day_low": None,
           "vol_today": None, "vol_avg": None, "vol_ratio": None,
           "w52_high": None, "w52_low": None,
           "pe": None, "mkt_cap": None,
           "updated_at": datetime.now().isoformat(timespec="seconds")}
    for n in range(1, 8):
        row[f"day{n}_price"] = None
        row[f"day{n}_change"] = None
    return row


def _print_row(r):
    print(f"\n{'='*55}\n  {r['symbol']} {r['name']}\n{'='*55}")
    print(f"  現價:        {r['current']}")
    print(f"  10日變動:    {r['change_10d']}%   20日: {r['change_20d']}%")
    print(f"  10日均:      {r['ma10']}   -5%: {r['ma10_5pct']}")
    print(f"  距10日均:    {r['dist_ma10']}%")
    print(f"  狀態:        {r['status']}   低於10日: {r['alert']}")
    print(f"  RSI:         {r['rsi']}")
    print(f"  今日高/低:   {r['day_high']} / {r['day_low']}")
    print(f"  量/均量/量比:{r['vol_today']} / {r['vol_avg']} / {r['vol_ratio']}")
    print(f"  52週高/低:   {r['w52_high']} / {r['w52_low']}")
    print(f"  PE / 市值:   {r['pe']} / {r['mkt_cap']}")
    for n in range(1, 8):
        print(f"  前{n}日: {r[f'day{n}_price']}  ({r[f'day{n}_change']}%)")


def save_json(data, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"updated_at": datetime.now().isoformat(timespec="seconds"),
                   "count": len(data), "stocks": data},
                  f, ensure_ascii=False, indent=2)
    log.info(f"  ✅ JSON：{path}")


def save_csv(data, path):
    if not data: return
    headers = ["股票代碼","股票名稱","現價","10日前","10日%","20日前","20日%",
               "10日均","10日均-5%","狀態","低於10日","距10日均%","RSI",
               "今日高","今日低","成交量","均量","量比",
               "52週高","52週低","本益比","市值",
               "前1日","前1日%","前2日","前2日%","前3日","前3日%",
               "前4日","前4日%","前5日","前5日%","前6日","前6日%","前7日","前7日%","更新時間"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(headers)
        for r in data:
            w.writerow([r["symbol"],r["name"],r["current"],
                        r["price_10d"],r["change_10d"],r["price_20d"],r["change_20d"],
                        r["ma10"],r["ma10_5pct"],r["status"],r["alert"],
                        r["dist_ma10"],r["rsi"],r["day_high"],r["day_low"],
                        r["vol_today"],r["vol_avg"],r["vol_ratio"],
                        r["w52_high"],r["w52_low"],r["pe"],r["mkt_cap"],
                        r["day1_price"],r["day1_change"],r["day2_price"],r["day2_change"],
                        r["day3_price"],r["day3_change"],r["day4_price"],r["day4_change"],
                        r["day5_price"],r["day5_change"],r["day6_price"],r["day6_change"],
                        r["day7_price"],r["day7_change"],r["updated_at"]])
    log.info(f"  ✅ CSV：{path}")


def main():
    test_mode = "--test" in sys.argv
    if test_mode:
        log.info("=== 測試模式（只跑 TSM）===")
        fetch_all(STOCKS[:1], test_mode=True)
    else:
        log.info(f"=== 開始抓取 {len(STOCKS)} 支股票 ===")
        results = fetch_all(STOCKS)
        save_json(results, OUTPUT_DIR / "prices.json")
        save_csv(results,  OUTPUT_DIR / "prices.csv")
        log.info(f"=== 完成！共 {len(results)} 筆 ===")


if __name__ == "__main__":
    main()
