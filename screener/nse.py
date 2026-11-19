"""Everything that talks to NSE. Only public files NSE publishes for download:
RSS feeds, the daily price + delivery file, the 52-week high/low file, bulk/block deals
and the list of listed stocks. Polite pace (about one request a second) and retries,
because NSE sometimes refuses a whole run; the next run usually gets through.
"""
import csv
import hashlib
import io
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime

import requests

ARCHIVE = "https://nsearchives.nseindia.com"
RSS = {
    "announcements": "/content/RSS/Online_announcements.xml",
    "corporate_actions": "/content/RSS/Corporate_action.xml",
    "board_meetings": "/content/RSS/Board_Meetings.xml",
    "offer_documents": "/content/RSS/Offer_Documents.xml",
}
HEADERS = {"User-Agent": "screen-desk/1.0 (personal research)", "Accept": "*/*"}
PAUSE = 1.2


class Blocked(Exception):
    """NSE refused (403) or did not answer. Usually temporary."""


class Missing(Exception):
    """File does not exist (404), e.g. a market holiday or not yet published."""


_session = requests.Session()
_last = [0.0]


def get(path, tries=3):
    url = path if path.startswith("http") else ARCHIVE + path
    err = ""
    for attempt in range(tries):
        wait = PAUSE - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            r = _session.get(url, headers=HEADERS, timeout=40)
        except requests.RequestException as e:
            err = type(e).__name__
        else:
            if r.status_code == 404:
                raise Missing(url)
            if r.status_code == 200 and r.content and b"Access Denied" not in r.content[:400]:
                return r.content
            err = f"HTTP {r.status_code}"
        time.sleep(4 * (attempt + 1))
    raise Blocked(f"{url.rsplit('/', 1)[-1]}: {err}")


# ---------- helpers ----------

_SUFFIX = re.compile(r"\b(limited|ltd|ltd\.|pvt|private|the|india|co|company|corporation|corp|inc)\b")


def norm_name(name):
    """Normalise a company name so RSS names can be matched to NSE symbols."""
    s = (name or "").lower().replace("&", " and ")
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = _SUFFIX.sub(" ", s)
    return " ".join(s.split())


def _num(x):
    try:
        return float(str(x).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _date(s):
    s = (s or "").strip()
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y", "%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%d", "%d %b %Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def _csv(content):
    text = content.decode("utf-8", "replace").lstrip("﻿")
    rows = list(csv.reader(io.StringIO(text)))
    return [[c.strip() for c in r] for r in rows if any(c.strip() for c in r)]


# ---------- stock list ----------

def stock_list():
    """symbol -> company name, for main board and SME."""
    out = {}
    for path in ("/content/equities/EQUITY_L.csv", "/emerge/corporates/content/SME_EQUITY_L.csv"):
        try:
            rows = _csv(get(path))
        except Missing:
            continue
        head = [h.upper() for h in rows[0]]
        si = head.index("SYMBOL")
        ni = next(i for i, h in enumerate(head) if "NAME" in h)
        for r in rows[1:]:
            if len(r) > max(si, ni) and r[si]:
                out[r[si]] = r[ni]
    return out


# ---------- RSS ----------

_TAGS = re.compile(r"<[^>]+>")


def _txt(el, tag):
    x = el.find(tag)
    return " ".join(_TAGS.sub(" ", (x.text or "") if x is not None else "").split())


def rss(feed):
    root = ET.fromstring(get(RSS[feed]))
    items = []
    for it in root.iter("item"):
        title, desc, link, pub = (_txt(it, t) for t in ("title", "description", "link", "pubDate"))
        company, ex_date = title, ""
        m = re.search(r"\s+-\s+Ex-Date:\s*(.+)$", title, re.I)
        if m:                                   # corporate actions: "COMPANY - Ex-Date: 27-Nov-2026"
            company, ex_date = title[:m.start()].strip(), _date(m.group(1))
        items.append({
            "id": hashlib.sha1(f"{feed}|{title}|{desc}|{pub}".encode()).hexdigest()[:16],
            "feed": feed, "company": company, "ex_date": ex_date,
            "text": desc[:600] or title, "date": _date(pub),
            "link": link if link.startswith("http") else "",
        })
    return items


# ---------- daily price + delivery ----------

PRICE_FIELDS = ["symbol", "series", "open", "high", "low", "close", "prev", "volume", "turnover_lacs",
                "trades", "deliv_qty", "deliv_pct"]


def bhav(day: date):
    """One trading day's prices and delivery for every stock. Raises Missing on holidays."""
    rows = _csv(get(f"/products/content/sec_bhavdata_full_{day:%d%m%Y}.csv"))
    head = [h.upper() for h in rows[0]]
    ix = {h: i for i, h in enumerate(head)}
    out = []
    for r in rows[1:]:
        g = lambda k: r[ix[k]] if k in ix and ix[k] < len(r) else ""
        series = g("SERIES")
        if series not in ("EQ", "BE", "BZ", "SM", "ST"):
            continue
        out.append([g("SYMBOL"), series, _num(g("OPEN_PRICE")), _num(g("HIGH_PRICE")), _num(g("LOW_PRICE")),
                    _num(g("CLOSE_PRICE")), _num(g("PREV_CLOSE")), _num(g("TTL_TRD_QNTY")),
                    _num(g("TURNOVER_LACS")), _num(g("NO_OF_TRADES")), _num(g("DELIV_QTY")), _num(g("DELIV_PER"))])
    if not out:
        raise Missing("empty price file")
    return out


def week52(day: date):
    """symbol -> (adjusted 52-week high, its date, adjusted 52-week low, its date)."""
    rows = _csv(get(f"/content/CM_52_wk_High_low_{day:%d%m%Y}.csv"))
    start = next(i for i, r in enumerate(rows) if r and r[0].upper().strip('"') == "SYMBOL")
    head = [h.upper() for h in rows[start]]
    out = {}
    for r in rows[start + 1:]:
        if len(r) < 6 or r[1] not in ("EQ", "BE", "BZ", "SM", "ST"):
            continue
        out[r[0]] = (_num(r[2]), _date(r[3]), _num(r[4]), _date(r[5]))
    return out


# ---------- bulk / block deals (today's file only) ----------

def deals():
    out = []
    for kind, path in (("bulk", "/content/equities/bulk.csv"), ("block", "/content/equities/block.csv")):
        rows = _csv(get(path))
        for r in rows[1:]:
            if len(r) < 7 or r[0].upper().startswith("NO RECORDS"):
                continue
            qty, price = _num(r[5]), _num(r[6])
            out.append({"kind": kind, "date": _date(r[0].title()), "symbol": r[1], "name": r[2],
                        "client": r[3], "side": r[4].upper()[:4], "qty": qty, "price": price,
                        "value_cr": round(qty * price / 1e7, 2) if qty and price else None})
    return out
