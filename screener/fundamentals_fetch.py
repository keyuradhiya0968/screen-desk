"""Nightly: download annual financial statements from Yahoo Finance (free, via yfinance).

    python -m screener.fundamentals_fetch

Universe: NSE main-board stocks that trade at least ₹0.2 crore a day on average (from our own
price files). Each stock is refreshed about once a week, oldest first, within a time budget,
so Yahoo is not hit too hard. Results go to data/fundamentals/<SYMBOL>.json.

Yahoo's data is unofficial and sometimes incomplete for Indian small caps, so every file
records how many years came back, and the screen marks thin data.
"""
import csv
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRICES, OUT = ROOT / "data" / "prices", ROOT / "data" / "fundamentals"
IST = timezone(timedelta(hours=5, minutes=30))
MIN_TURNOVER_LACS = 20          # ₹0.2 crore average daily traded value (wide enough for small caps)
REFRESH_DAYS = 7
BUDGET_MIN = float(os.environ.get("FUND_BUDGET_MIN", "55"))
PAUSE = 1.0

# Yahoo's row labels change now and then, so each field lists the names to try in order.
ROWS = {
    "revenue": ["Total Revenue", "Operating Revenue"],
    "net_income": ["Net Income", "Net Income Common Stockholders", "Net Income From Continuing Operation Net Minority Interest"],
    "ebit": ["EBIT", "Operating Income"],
    "interest": ["Interest Expense", "Interest Expense Non Operating"],
    "assets": ["Total Assets"],
    "cur_liab": ["Current Liabilities"],
    "equity": ["Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest"],
    "debt": ["Total Debt"],
    "cash": ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"],
    "receivables": ["Accounts Receivable", "Receivables"],
    "shares": ["Ordinary Shares Number", "Share Issued"],
    "cfo": ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"],
    "capex": ["Capital Expenditure"],
    "dividends": ["Cash Dividends Paid", "Common Stock Dividend Paid"],
}


def universe():
    """Main-board symbols with enough average turnover over the stored price days."""
    files = sorted(PRICES.glob("*.csv"))[-20:]
    tot, n = {}, {}
    for p in files:
        with open(p, newline="") as f:
            for r in csv.DictReader(f):
                if r["series"] != "EQ" or not r["turnover_lacs"]:
                    continue
                tot[r["symbol"]] = tot.get(r["symbol"], 0) + float(r["turnover_lacs"])
                n[r["symbol"]] = n.get(r["symbol"], 0) + 1
    return sorted(s for s in tot if n[s] >= len(files) * 0.6 and tot[s] / n[s] >= MIN_TURNOVER_LACS)


def _series(df, names):
    """Values for the first matching row, oldest year first, as floats (None where blank)."""
    if df is None or getattr(df, "empty", True):
        return None, []
    for name in names:
        if name in df.index:
            row = df.loc[name]
            cols = sorted(df.columns)
            vals = []
            for c in cols:
                v = row[c]
                try:
                    v = float(v)
                    vals.append(None if v != v else v)   # NaN -> None
                except (TypeError, ValueError):
                    vals.append(None)
            return [c.strftime("%Y-%m-%d") if hasattr(c, "strftime") else str(c) for c in cols], vals
    return None, []


def fetch_one(yf, symbol):
    t = yf.Ticker(symbol + ".NS")
    statements = {"inc": t.income_stmt, "bal": t.balance_sheet, "cf": t.cashflow}
    out, years = {"symbol": symbol, "asof": date.today().isoformat()}, None
    where = {"revenue": "inc", "net_income": "inc", "ebit": "inc", "interest": "inc",
             "assets": "bal", "cur_liab": "bal", "equity": "bal", "debt": "bal", "cash": "bal",
             "receivables": "bal", "shares": "bal", "cfo": "cf", "capex": "cf", "dividends": "cf"}
    for field, names in ROWS.items():
        cols, vals = _series(statements[where[field]], names)
        if cols and (years is None or len(cols) > len(years)) and where[field] == "inc":
            years = cols
        out[field] = dict(zip(cols, vals)) if cols else {}
    years = years or sorted({y for f in ROWS for y in out[f]})
    out["years"] = years
    for field in ROWS:                                 # align every field to the income-statement years
        out[field] = [out[field].get(y) for y in years]
    out["ttm_net_income"], out["q_dates"], out["q_revenue"], out["q_net_income"] = None, [], [], []
    try:
        q = t.quarterly_income_stmt
        qd, qn = _series(q, ROWS["net_income"])
        qd2, qr = _series(q, ROWS["revenue"])
        out["q_dates"] = qd or qd2 or []
        out["q_net_income"] = qn[-8:]
        out["q_revenue"] = qr[-8:]
        out["q_dates"] = out["q_dates"][-8:]
        out["ttm_net_income"] = sum(qn[-4:]) if len(qn) >= 4 and all(v is not None for v in qn[-4:]) else None
    except Exception:
        pass
    return out


def main():
    try:
        import yfinance as yf
    except ImportError:
        print("yfinance is not installed; add it to the workflow's pip install")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    syms = universe()
    if not syms:
        print("No price history yet; run the daily screens first")
        return 0
    stale = (date.today() - timedelta(days=REFRESH_DAYS)).isoformat()

    def age(s):
        try:
            f = json.loads((OUT / f"{s}.json").read_text())
            return f.get("asof", "") if "q_revenue" in f else ""      # older files lack quarterly data: refetch
        except (FileNotFoundError, ValueError):
            return ""
    todo = sorted((s for s in syms if age(s) < stale), key=age)
    t0, done, empty, fails_in_row = time.time(), 0, 0, 0
    for s in todo:
        if time.time() - t0 > BUDGET_MIN * 60:
            break
        try:
            data = fetch_one(yf, s)
            fails_in_row = 0
        except Exception as e:
            fails_in_row += 1
            print(f"{s}: {type(e).__name__}: {str(e)[:120]}")
            if fails_in_row >= 8:
                print("Yahoo keeps refusing; stopping this run, the rest will be fetched next time")
                break
            time.sleep(PAUSE * 5)
            continue
        if not data["years"] or not any(v is not None for v in data["revenue"]):
            empty += 1
            data["empty"] = True
        (OUT / f"{s}.json").write_text(json.dumps(data, separators=(",", ":")))
        done += 1
        time.sleep(PAUSE)
    for f in OUT.glob("*.json"):                      # drop stocks that left the universe long ago
        if f.stem not in syms and age(f.stem) < (date.today() - timedelta(days=60)).isoformat():
            f.unlink()
    have = len(list(OUT.glob("*.json")))
    print(f"Universe {len(syms)} stocks · fetched {done} this run ({empty} with no data) · "
          f"{have} stored · {len(todo) - done} still due · {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
