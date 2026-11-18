"""Fetch corporate announcements from BSE's public API (the same one bseindia.com uses)."""
import time
from datetime import date

import requests

API = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.bseindia.com/",
    "Origin": "https://www.bseindia.com",
}


class BSEError(Exception):
    pass


def _get(session, params, tries=4):
    last = None
    for attempt in range(tries):
        try:
            r = session.get(API, params=params, headers=HEADERS, timeout=30)
            if r.status_code == 200 and r.text.strip().startswith("{"):
                return r.json()
            last = f"HTTP {r.status_code}: {r.text[:120]!r}"
        except (requests.RequestException, ValueError) as e:
            last = str(e)
        time.sleep(2 * (attempt + 1))
    raise BSEError(last)


def announcements_for_day(day: date, session=None, pause=0.6):
    """Every announcement filed on BSE on one calendar day (all companies, all categories)."""
    session = session or requests.Session()
    ds = day.strftime("%Y%m%d")
    rows, page = [], 1
    while True:
        data = _get(session, {
            "pageno": page, "strCat": "-1", "strPrevDate": ds, "strScrip": "",
            "strSearch": "P", "strToDate": ds, "strType": "C", "subcategory": "-1",
        })
        table = data.get("Table") or []
        rows.extend(table)
        total = 0
        try:
            total = int((data.get("Table1") or [{}])[0].get("ROWCNT") or 0)
        except (TypeError, ValueError):
            pass
        if not table or (total and len(rows) >= total) or page > 200:
            break
        page += 1
        time.sleep(pause)
    return rows


def normalise(row):
    """Keep only the fields we use, with stable names."""
    att = (row.get("ATTACHMENTNAME") or "").strip()
    scrip = str(row.get("SCRIP_CD") or "").strip()
    return {
        "id": str(row.get("NEWSID") or ""),
        "scrip": scrip,
        "company": (row.get("SLONGNAME") or "").strip(),
        "headline": " ".join(((row.get("HEADLINE") or "") + " " + (row.get("NEWSSUB") or "")).split()),
        "category": (row.get("CATEGORYNAME") or "").strip(),
        "subcategory": (row.get("SUBCATNAME") or "").strip(),
        "date": (row.get("NEWS_DT") or row.get("DT_TM") or "")[:10],
        "pdf": f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{att}" if att else "",
        "page": f"https://www.bseindia.com/stock-share-price/x/x/{scrip}/corp-announcements/" if scrip else "",
    }
