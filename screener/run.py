"""Scheduled run: refresh NSE data, run every screen, publish the dashboard data, send alerts.

    python -m screener.run

To add a screen: create screener/screen_<name>.py with ID, TITLE, DESCRIPTION, RULES and run(ctx),
then add it to SCREENS below.
"""
import csv
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

from . import nse
from . import screen_breakout, screen_bulk_deals, screen_corporate_actions, screen_fundamentals, screen_narrative

SCREENS = [screen_breakout, screen_fundamentals, screen_corporate_actions, screen_narrative, screen_bulk_deals]

ROOT = Path(__file__).resolve().parent.parent
DATA, DOCS = ROOT / "data", ROOT / "docs"
PRICES, W52 = DATA / "prices", DATA / "w52"
IST = timezone(timedelta(hours=5, minutes=30))
KEEP_DAYS = 65            # trading days of price history kept
MAX_PRICE_FETCHES = 70    # per run, so a first run backfills in one go
SPARK_DAYS = 60


def load(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, ValueError):
        return default


def save(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))


# ---------------- data refresh ----------------

def refresh_stock_list(state, log):
    stocks = load(DATA / "stocks.json", {})
    if stocks and state.get("stocks_date", "") >= (date.today() - timedelta(days=7)).isoformat():
        return stocks
    try:
        fresh = nse.stock_list()
        if fresh:
            save(DATA / "stocks.json", fresh)
            state["stocks_date"] = date.today().isoformat()
            log.append(f"Stock list: {len(fresh)} symbols")
            return fresh
    except nse.Blocked as e:
        log.append(f"Stock list not refreshed ({e})")
    return stocks


def refresh_prices(state, log, now):
    PRICES.mkdir(parents=True, exist_ok=True)
    have = {p.stem for p in PRICES.glob("*.csv")}
    holidays = set(state.get("holidays", []))
    today = now.date()
    days, d = [], today
    while len(days) < KEEP_DAYS + 25:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    fetched = 0
    for d in days:
        iso = d.isoformat()
        if iso in have or iso in holidays:
            continue
        if d == today and now.hour < 18:          # today's file is published in the evening
            continue
        if fetched >= MAX_PRICE_FETCHES or len(have) >= KEEP_DAYS and iso < min(have):
            break
        fetched += 1
        try:
            rows = nse.bhav(d)
        except nse.Missing:
            if d < today:
                holidays.add(iso)
            continue
        except nse.Blocked as e:
            log.append(f"Prices: NSE refused this run ({e}); will retry next run")
            break
        with open(PRICES / f"{iso}.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(nse.PRICE_FIELDS)
            w.writerows(rows)
        have.add(iso)
    for old in sorted(have)[:-KEEP_DAYS]:
        (PRICES / f"{old}.csv").unlink(missing_ok=True)
        have.discard(old)
    state["holidays"] = sorted(h for h in holidays if h >= (today - timedelta(days=200)).isoformat())
    log.append(f"Prices: {len(have)} trading days stored ({fetched} files requested this run)")


def load_prices():
    px = {}
    for p in sorted(PRICES.glob("*.csv")):
        day = {}
        with open(p, newline="") as f:
            for r in csv.DictReader(f):
                row = {k: (float(v) if v not in ("", None) and k not in ("symbol", "series") else v or None)
                       for k, v in r.items()}
                day[r["symbol"]] = row
        px[p.stem] = day
    return px


def refresh_w52(dates, log):
    W52.mkdir(parents=True, exist_ok=True)
    out = {}
    for d in dates[-5:]:
        f = W52 / f"{d}.json"
        if not f.exists():
            try:
                data = nse.week52(date.fromisoformat(d))
                save(f, {s: v[0] for s, v in data.items() if v[1] == d})
            except nse.Missing:
                save(f, {})
            except (nse.Blocked, StopIteration) as e:
                log.append(f"52-week file for {d} not read ({e})")
                continue
        out[d] = load(f, {})
    for f in W52.glob("*.json"):
        if f.stem not in dates[-5:]:
            f.unlink()
    return out


def refresh_feeds(state, log, name_to_sym, today):
    filings = load(DATA / "filings.json", [])
    actions = load(DATA / "corp_actions.json", [])
    old = DATA / "flagged.json"                      # migrate the first version's store
    if old.exists():
        import re as _re
        for a in load(old, []):
            m = _re.search(r"\s+-\s+Ex-Date:\s*(.+)$", a.get("company", ""), _re.I)
            item = {"id": a["id"], "feed": a.get("feed", ""), "company": a["company"][:m.start()] if m else a["company"],
                    "ex_date": nse._date(m.group(1)) if m else "", "text": a.get("headline", ""),
                    "date": a.get("date", ""), "link": a.get("pdf") or a.get("page", "")}
            (actions if item["feed"] == "corporate_actions" else filings).append(item)
        old.unlink()
    seen = {a["id"] for a in filings} | {a["id"] for a in actions}
    ok = 0
    for feed in nse.RSS:
        try:
            items = nse.rss(feed)
        except (nse.Blocked, nse.Missing, ValueError) as e:
            log.append(f"Feed {feed}: not read ({e})")
            continue
        ok += 1
        new = 0
        for it in items:
            if it["id"] in seen:
                continue
            seen.add(it["id"])
            if feed == "corporate_actions":
                actions.append(it)
                new += 1
            elif screen_narrative.flags_for(it["text"]):
                filings.append(it)
                new += 1
        log.append(f"Feed {feed}: {len(items)} items, {new} new kept")
    for a in filings + actions:                      # attach NSE symbols by company name
        if not a.get("symbol"):
            a["symbol"] = name_to_sym.get(nse.norm_name(a["company"]), "")
    cutoff = (today - timedelta(days=400)).isoformat()
    filings = [a for a in filings if a.get("date", "") >= cutoff]
    actions = [a for a in actions if (a.get("ex_date") or a.get("date", "")) >= (today - timedelta(days=10)).isoformat()]
    save(DATA / "filings.json", filings)
    save(DATA / "corp_actions.json", actions)
    return filings, actions, ok


def refresh_deals(log):
    store = load(DATA / "deals.json", [])
    try:
        new = nse.deals()
    except (nse.Blocked, nse.Missing) as e:
        log.append(f"Bulk/block deals not read ({e})")
        new = []
    keys = {(d["date"], d["symbol"], d["client"], d["side"], d["qty"], d["kind"]) for d in store}
    for d in new:
        k = (d["date"], d["symbol"], d["client"], d["side"], d["qty"], d["kind"])
        if k not in keys:
            store.append(d)
            keys.add(k)
    keep = sorted({d["date"] for d in store if d.get("date")})[-15:]
    store = [d for d in store if d.get("date") in keep]
    save(DATA / "deals.json", store)
    if new:
        log.append(f"Deals: {len(new)} today, {len(store)} stored")
    return store


# ---------------- alerts ----------------

def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def telegram(text):
    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return False
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=20, data={
            "chat_id": chat, "text": text[:4000], "parse_mode": "HTML", "disable_web_page_preview": "true"})
        return True
    except requests.RequestException:
        return False


# ---------------- main ----------------

def main():
    t0 = time.time()
    now = datetime.now(IST)
    today = now.date()
    state = load(DATA / "state.json", {})
    log, status = [], {}

    stocks = refresh_stock_list(state, log)
    name_to_sym = {nse.norm_name(n): s for s, n in stocks.items()}
    refresh_prices(state, log, now)
    px = load_prices()
    dates = sorted(px)
    w52 = refresh_w52(dates, log) if dates else {}
    filings, actions, feeds_ok = refresh_feeds(state, log, name_to_sym, today)
    deals = refresh_deals(log)
    status["prices"] = f"{dates[0]} to {dates[-1]}" if dates else "none yet"
    status["feeds"] = f"{feeds_ok}/{len(nse.RSS)} read"

    ctx = {"today": today, "dates": dates, "px": px, "w52_new_highs": w52,
           "last_price": px[dates[-1]] if dates else {}, "filings": filings,
           "corp_actions": actions, "deals": deals,
           "fundamentals": {p.stem: load(p, {}) for p in (DATA / "fundamentals").glob("*.json")}}
    fstored = len(ctx["fundamentals"])
    status["fundamentals"] = f"{fstored} stocks" if fstored else "first nightly fetch pending"

    stocks_out, screens_out = {}, []
    for scr in SCREENS:
        try:
            hits = scr.run(ctx) if (dates or scr.ID not in ("breakout",)) else []
        except Exception as e:                       # one broken screen must not stop the others
            log.append(f"Screen {scr.ID} failed: {type(e).__name__}: {e}")
            hits = []
        latest = max((h["date"] for h in hits), default="")
        screens_out.append({"id": scr.ID, "title": scr.TITLE, "description": scr.DESCRIPTION,
                            "rules": scr.RULES, "count": len({h["symbol"] for h in hits})})
        for h in hits:
            s = stocks_out.setdefault(h["symbol"], {"symbol": h["symbol"], "hits": {}, "events": []})
            prev = s["hits"].get(scr.ID)
            if not prev or h["date"] > prev["date"]:
                s["hits"][scr.ID] = {k: h[k] for k in ("score", "tags", "summary", "metrics", "date", "alert")}
                s["hits"][scr.ID]["alert_key"] = h.get("alert_key", h["date"])
            for e in h.get("events", []):
                s["events"].append({**e, "screen": scr.ID})

    # price context for every stock shown
    spark_dates = dates[-SPARK_DAYS:]
    last = ctx["last_price"]
    for sym, s in stocks_out.items():
        s["matched"] = sym in stocks
        s["name"] = stocks.get(sym) or sym.title()
        r = last.get(sym)
        if r and r.get("close"):
            hist = [px[d][sym]["volume"] for d in dates[-21:-1] if sym in px[d] and px[d][sym]["volume"]]
            s.update(close=r["close"], series=r["series"],
                     chg=round((r["close"] / r["prev"] - 1) * 100, 2) if r.get("prev") else None,
                     vol_x=round(r["volume"] / (sum(hist) / len(hist)), 1) if hist and r.get("volume") else None,
                     deliv=r.get("deliv_pct"),
                     turnover_cr=round((r.get("turnover_lacs") or 0) / 100, 2))
        s["spark"] = {"c": [px[d][sym]["close"] if sym in px[d] else None for d in spark_dates],
                      "v": [px[d][sym]["volume"] if sym in px[d] else None for d in spark_dates]}
        s["events"].sort(key=lambda e: e.get("date", ""), reverse=True)
        s["events"] = s["events"][:30]
        s["score"] = max(h["score"] for h in s["hits"].values())
        s["last"] = max(h["date"] for h in s["hits"].values())

    # alerts: each screen hit once
    sent = set(state.get("alerted", []))
    lines = []
    for sym, s in sorted(stocks_out.items(), key=lambda kv: -kv[1]["score"]):
        for sid, h in s["hits"].items():
            key = f"{sid}:{sym}:{h.pop('alert_key', h['date'])}"
            if h["alert"] and key not in sent:
                sent.add(key)
                title = next(x["title"] for x in screens_out if x["id"] == sid)
                lines.append(f"<b>{esc(s['name'])}</b> ({sym}) · {esc(title)}\n{esc(h['summary'])}")
    state["alerted"] = sorted(sent)[-8000:]
    if lines:
        telegram("📈 <b>Screen Desk</b>\n\n" + "\n\n".join(lines[:20]) +
                 (f"\n\n+{len(lines) - 20} more on the dashboard" if len(lines) > 20 else ""))

    save(DATA / "state.json", state)
    save(DOCS / "data.json", {
        "generated": now.strftime("%Y-%m-%d %H:%M IST"), "status": status, "log": log,
        "alerts_sent": len(lines), "screens": screens_out, "spark_dates": spark_dates,
        "stocks": sorted(stocks_out.values(), key=lambda s: (-s["score"], s["symbol"])),
    })
    print("\n".join(log))
    print(f"Done in {time.time() - t0:.0f}s · " + " · ".join(f"{x['title']}: {x['count']}" for x in screens_out)
          + f" · {len(lines)} alerts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
