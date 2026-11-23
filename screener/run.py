"""Scheduled run: refresh NSE data, run every screen, publish the dashboard data, send alerts.

    python -m screener.run

Screens live in four groups (the dashboard's tabs):
  technical    screener/screens_technical.py     price, volume, delivery
  fundamental  screener/screens_fundamental.py   annual and quarterly statements (nightly fetch)
  combined     screener/screens_combined.py      recipes: one technical + one fundamental screen
  events       screen_corporate_actions.py, screen_narrative.py, screen_bulk_deals.py
To add a screen, add a class to the right file and list it in that file's SCREENS.
"""
import csv
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import requests

from . import nse, screens_combined, screens_fundamental, screens_technical
from . import screen_bulk_deals, screen_corporate_actions, screen_narrative
from .tech import History, rs_ranks

GROUPS = [
    {"id": "technical", "title": "Technical", "blurb": "Price, volume and delivery signals"},
    {"id": "fundamental", "title": "Fundamental", "blurb": "Business quality, growth and price"},
    {"id": "combined", "title": "Combined", "blurb": "Stocks on a technical and a fundamental screen at once"},
    {"id": "events", "title": "Events", "blurb": "Corporate actions, filings and large deals"},
]
EVENT_SCREENS = [screen_corporate_actions, screen_narrative, screen_bulk_deals]

ROOT = Path(__file__).resolve().parent.parent
DATA, DOCS = ROOT / "data", ROOT / "docs"
PRICES, W52 = DATA / "prices", DATA / "w52"
IST = timezone(timedelta(hours=5, minutes=30))
KEEP_DAYS = 260           # trading days of price history kept (about a year)
MAX_PRICE_FETCHES = 220   # per run, so the backfill to a year takes one or two runs
SPARK_DAYS = 120


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
    state["holidays"] = sorted(h for h in holidays if h >= (today - timedelta(days=420)).isoformat())
    log.append(f"Prices: {len(have)} trading days stored ({fetched} files requested this run)")


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

def _r(x, nd=2):
    return None if x is None or (isinstance(x, float) and x != x) else round(float(x), nd)


def run_group(group, screens, ctx, log, stocks_out, screens_out):
    for scr in screens:
        try:
            hits = scr.run(ctx)
        except Exception as e:                       # one broken screen must not stop the others
            log.append(f"Screen {scr.ID} failed: {type(e).__name__}: {e}")
            hits = []
        screens_out.append({"id": scr.ID, "group": group, "title": scr.TITLE, "description": scr.DESCRIPTION,
                            "rules": scr.RULES, "count": len({h["symbol"] for h in hits})})
        for h in hits:
            s = stocks_out.setdefault(h["symbol"], {"symbol": h["symbol"], "hits": {}, "events": []})
            prev = s["hits"].get(scr.ID)
            if not prev or h["date"] > prev["date"]:
                s["hits"][scr.ID] = {k: h[k] for k in ("score", "tags", "summary", "metrics", "date", "alert")}
                s["hits"][scr.ID]["alert_key"] = h.get("alert_key", h["date"])
            for e in h.get("events", []):
                s["events"].append({**e, "screen": scr.ID})
    return stocks_out


def main():
    t0 = time.time()
    now = datetime.now(IST)
    today = now.date()
    state = load(DATA / "state.json", {})
    log, status = [], {}

    # ---- data
    stocks = refresh_stock_list(state, log)
    name_to_sym = {nse.norm_name(n): s for s, n in stocks.items()}
    refresh_prices(state, log, now)
    H = History(PRICES)
    dates = H.dates
    w52 = refresh_w52(dates, log) if dates else {}
    filings, actions, feeds_ok = refresh_feeds(state, log, name_to_sym, today)
    deals = refresh_deals(log)
    rs = rs_ranks(H) if dates else {}
    last_price = {s: {"close": float(H.C[i, -1])} for i, s in enumerate(H.syms) if not np.isnan(H.C[i, -1])}
    fm = {}
    for p in (DATA / "fundamentals").glob("*.json"):
        f = load(p, {})
        try:
            m = screens_fundamental.metrics(f, (last_price.get(p.stem) or {}).get("close"))
        except (TypeError, KeyError, IndexError, ZeroDivisionError):
            m = None
        if m:
            fm[p.stem] = m
    status["prices"] = f"{dates[0]} to {dates[-1]} ({len(dates)} days)" if dates else "none yet"
    status["feeds"] = f"{feeds_ok}/{len(nse.RSS)} read"
    status["fundamentals"] = f"{len(fm)} stocks" if fm else "first nightly fetch pending"

    ctx = {"today": today, "H": H, "dates": dates, "rs": rs, "w52_new_highs": w52, "last_price": last_price,
           "filings": filings, "corp_actions": actions, "deals": deals, "fm": fm}

    # ---- screens: events first, because the penny screen excludes story stocks
    stocks_out, screens_out = {}, []
    run_group("events", EVENT_SCREENS, ctx, log, stocks_out, screens_out)
    ctx["narrative_syms"] = {s for s, st in stocks_out.items() if "narrative" in st["hits"]}
    screens_technical._LISTED.clear()
    screens_technical._LISTED.update(stocks)
    if dates:
        run_group("technical", screens_technical.SCREENS, ctx, log, stocks_out, screens_out)
    if fm:
        run_group("fundamental", screens_fundamental.SCREENS, ctx, log, stocks_out, screens_out)
    order = {g["id"]: k for k, g in enumerate(GROUPS)}
    screens_out.sort(key=lambda x: order[x["group"]])
    recipes = []
    for rc in screens_combined.RECIPES:
        syms = screens_combined.match(stocks_out, rc)
        recipes.append({**rc, "count": len(syms)})

    # ---- per-stock context for the table and the side panel
    spark_dates = dates[-SPARK_DAYS:]
    for sym, s in stocks_out.items():
        s["matched"] = sym in stocks
        s["name"] = stocks.get(sym) or sym.title()
        i = H.idx.get(sym)
        if i is not None and not np.isnan(H.C[i, -1]):
            c, prev, v = H.C[i, -1], H.PREV[i, -1], H.V[i, -1]
            avg = H.mean(H.V[i], 20, H.T - 2, 0.6)
            s.update(series=H.series[i], close=_r(c), chg=_r((c / prev - 1) * 100) if prev and prev == prev else None,
                     vol_x=_r(v / avg, 1) if avg and v == v else None, deliv=_r(H.DP[i, -1], 1),
                     turnover_cr=_r(H.TO[i, -1] / 100, 2), rs=rs.get(sym))
            c_arr = H.C[i, -SPARK_DAYS:]
            m50 = [H.mean(H.C[i], 50, H.T - SPARK_DAYS + k if H.T >= SPARK_DAYS else k, 0.8) for k in range(len(c_arr))]
            s["spark"] = {"c": [_r(x) for x in c_arr], "v": [None if x != x else int(x) for x in H.V[i, -SPARK_DAYS:]],
                          "m50": [_r(x) for x in m50]}
        m = fm.get(sym)
        if m:
            s["fund"] = {k: _r(m[k]) for k in ("mcap_cr", "pe", "pb", "roce", "roe", "sales_cagr", "profit_cagr",
                                               "de", "div_yield", "cfo_pat")}
        s["events"].sort(key=lambda e: e.get("date", ""), reverse=True)
        s["events"] = s["events"][:30]
        s["score"] = max(h["score"] for h in s["hits"].values())

    # ---- alerts: single screens that carry an alert, plus recipes whose technical signal is from the latest session
    sent = set(state.get("alerted", []))
    title = {x["id"]: x["title"] for x in screens_out}
    lines = []
    for sym, s in sorted(stocks_out.items(), key=lambda kv: -kv[1]["score"]):
        for sid, h in s["hits"].items():
            key = f"{sid}:{sym}:{h.pop('alert_key')}"
            if h["alert"] and key not in sent:
                sent.add(key)
                lines.append(f"<b>{esc(s['name'])}</b> ({sym}) · {esc(title[sid])}\n{esc(h['summary'])}")
    for rc in recipes:
        for sym in screens_combined.match(stocks_out, rc):
            th = stocks_out[sym]["hits"][rc["tech"]]
            key = f"recipe:{rc['id']}:{sym}:{th['date']}"
            if dates and th["date"] == dates[-1] and key not in sent:
                sent.add(key)
                fh = stocks_out[sym]["hits"][rc["fund"]]
                lines.insert(0, f"⭐ <b>{esc(stocks_out[sym]['name'])}</b> ({sym}) · {esc(rc['title'])}\n"
                                f"{esc(th['summary'])}\n{esc(fh['summary'])}")
    state["alerted"] = sorted(sent)[-12000:]
    if lines:
        telegram("📈 <b>Screen Desk</b>\n\n" + "\n\n".join(lines[:20]) +
                 (f"\n\n+{len(lines) - 20} more on the dashboard" if len(lines) > 20 else ""))

    payload = {"groups": GROUPS, "screens": screens_out, "recipes": recipes, "spark_dates": spark_dates,
               "stocks": sorted(stocks_out.values(), key=lambda s: (-s["score"], s["symbol"]))}
    # Only rewrite the dashboard file when the results changed, so the repository does not grow
    # by a full copy every two hours when nothing new happened.
    import hashlib
    digest = hashlib.sha1(json.dumps([payload, status], sort_keys=True, default=str).encode()).hexdigest()
    if digest != state.get("data_hash") or not (DOCS / "data.json").exists():
        state["data_hash"] = digest
        save(DOCS / "data.json", {"generated": now.strftime("%Y-%m-%d %H:%M IST"), "status": status, "log": log,
                                  "alerts_sent": len(lines), **payload})
    else:
        log.append("No change in results; dashboard file left as is")
    save(DATA / "state.json", state)
    print("\n".join(log))
    print(f"Done in {time.time() - t0:.0f}s · " + " · ".join(f"{x['title']}: {x['count']}" for x in screens_out)
          + " · " + " · ".join(f"{r['title']}: {r['count']}" for r in recipes) + f" · {len(lines)} alerts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
