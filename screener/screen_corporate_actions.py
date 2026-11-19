"""Corporate actions: dividends, splits, bonus and rights, with the last day you can still buy."""
import re
from datetime import date, timedelta

ID = "corporate_actions"
TITLE = "Corporate actions"
DESCRIPTION = "Upcoming dividends, splits, bonus and rights issues, shown only while there is still time to buy."

P = {
    "div_yield_alert": 3.0,   # alert on dividends yielding at least this % of the last close
    "min_days_left": 2,       # alert only if at least this many trading days remain to buy
}
RULES = [
    "Ex-date still ahead; the last day to buy is the trading day before the ex-date (T+1 settlement)",
    "Dividend yield = dividend per share ÷ last close; alert at 3% or more",
    "Alert only when at least 2 trading days are left to buy",
    "Rights issues show the discount of the issue price to the market price",
    "Trading days count weekdays only; exchange holidays are not yet excluded",
]


def _weekdays_between(a: date, b: date):
    """Weekdays from a to b inclusive."""
    n, d = 0, a
    while d <= b:
        n += d.weekday() < 5
        d += timedelta(days=1)
    return n


def _prev_weekday(d: date):
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def parse(text):
    """Pull the action type and numbers out of NSE's PURPOSE text."""
    t = text.upper()
    m = re.search(r"PURPOSE:(.*?)(\||$)", t)
    purpose = (m.group(1) if m else t).strip()
    fv = re.search(r"FACE VALUE:\s*([\d.]+)", t)
    fv = float(fv.group(1)) if fv else None
    out = {"purpose": purpose.title(), "face_value": fv}
    divs = re.findall(r"DIVIDEND\s*-?\s*R[SE]\.?\s*([\d.]+)", purpose)
    if divs:
        out.update(kind="Dividend", dividend=round(sum(float(x) for x in divs), 2))
        return out
    m = re.search(r"BONUS\s*(\d+)\s*:\s*(\d+)", purpose)
    if m:
        out.update(kind="Bonus", ratio=f"{m.group(1)}:{m.group(2)}")
        return out
    m = re.search(r"RIGHTS\s*(\d+)\s*:\s*(\d+)(?:.*?PREMIUM\s*R[SE]\.?\s*([\d.]+))?", purpose)
    if m:
        prem = float(m.group(3)) if m.group(3) else 0.0
        out.update(kind="Rights", ratio=f"{m.group(1)}:{m.group(2)}",
                   issue_price=round(prem + (fv or 0), 2) if m.group(3) or fv else None)
        return out
    if "SPLIT" in purpose or "SUB-DIVISION" in purpose or "SUB DIVISION" in purpose:
        m = re.search(r"FROM\s*R[SE]\.?\s*([\d.]+).*?TO\s*R[SE]\.?\s*([\d.]+)", purpose)
        out.update(kind="Split", ratio=f"₹{m.group(1)} → ₹{m.group(2)}" if m else "")
        return out
    if "BUY BACK" in purpose or "BUYBACK" in purpose:
        out.update(kind="Buyback")
        return out
    if "DEMERGER" in purpose:
        out.update(kind="Demerger")
        return out
    out.update(kind="Other")
    return out


def run(ctx):
    today, last_px = ctx["today"], ctx["last_price"]
    hits = []
    for a in ctx["corp_actions"]:
        if not a.get("ex_date"):
            continue
        sym = a.get("symbol") or a["company"]
        ex = date.fromisoformat(a["ex_date"])
        if ex < today:
            continue
        info = parse(a["text"])
        last_buy = _prev_weekday(ex)
        days_left = _weekdays_between(today, last_buy) if last_buy >= today else 0
        close = (last_px.get(sym) or {}).get("close")
        tags, score, alert, metrics = [info["kind"]], 4, False, {"ex_date": a["ex_date"],
                                                                  "last_buy": last_buy.isoformat(),
                                                                  "days_left": days_left}
        if info["kind"] == "Dividend":
            metrics["dividend"] = info["dividend"]
            y = round(info["dividend"] / close * 100, 2) if close else None
            metrics["yield_pct"] = y
            tags.append(f"₹{info['dividend']:g}/share" + (f" · {y:.1f}% yield" if y is not None else ""))
            score = 8 if (y or 0) >= P["div_yield_alert"] else 6 if (y or 0) >= 1.5 else 4
            alert = (y or 0) >= P["div_yield_alert"] and days_left >= P["min_days_left"]
        elif info["kind"] == "Rights":
            ip = info.get("issue_price")
            disc = round((1 - ip / close) * 100, 1) if ip and close else None
            metrics.update(ratio=info["ratio"], issue_price=ip, discount_pct=disc)
            tags.append(f"{info['ratio']} @ ₹{ip:g}" if ip else info["ratio"])
            if disc is not None:
                tags.append(f"{abs(disc):.0f}% {'below' if disc >= 0 else 'above'} market")
            score = 6 if (disc or 0) >= 20 else 5
        elif info["kind"] in ("Bonus", "Split"):
            metrics["ratio"] = info.get("ratio", "")
            if info.get("ratio"):
                tags.append(info["ratio"])
            score = 5
        tags.append("last buy " + last_buy.strftime("%d %b") if days_left else "ex-date tomorrow; too late")
        hits.append({
            "symbol": sym, "date": a["ex_date"], "score": score, "tags": tags,
            "summary": " · ".join(tags), "metrics": metrics, "alert": alert,
            "events": [{"date": a.get("date", ""), "text": info["purpose"], "link": a.get("link", "")}],
        })
    return hits
