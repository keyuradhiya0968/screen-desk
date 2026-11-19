"""Read NSE's official public RSS feeds (listed on nseindia.com/rss-feed).

Each feed only holds the most recent filings, so the daily job runs several times a day
and keeps its own history of the filings that hit a flag.
"""
import hashlib
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime

import requests

BASE = "https://nsearchives.nseindia.com/content/RSS/"
FEEDS = {
    "announcements": "Online_announcements.xml",
    "corporate_actions": "Corporate_action.xml",
    "board_meetings": "Board_Meetings.xml",
    "offer_documents": "Offer_Documents.xml",
    "related_party": "Related_Party_Trans.xml",
}
HEADERS = {"User-Agent": "screen-desk/1.0 (personal RSS reader)",
           "Accept": "application/rss+xml, application/xml, text/xml"}

_DATE_FORMATS = ("%d-%b-%Y %H:%M:%S", "%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z",
                 "%d-%b-%Y", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M:%S")
_TAGS = re.compile(r"<[^>]+>")


def _date(s):
    s = (s or "").strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    m = re.search(r"\d{4}-\d{2}-\d{2}", s)
    return m.group(0) if m else ""


def _text(el, tag):
    x = el.find(tag)
    return " ".join(_TAGS.sub(" ", (x.text or "") if x is not None else "").split())


def fetch(feed_id, session=None, tries=3):
    """Return the feed's items as dicts. Raises RuntimeError if NSE does not answer."""
    session = session or requests.Session()
    url = BASE + FEEDS[feed_id]
    last = ""
    for attempt in range(tries):
        try:
            r = session.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 200 and b"<rss" in r.content[:500]:
                break
            last = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            last = str(e)
        time.sleep(3 * (attempt + 1))
    else:
        raise RuntimeError(f"{feed_id}: NSE did not answer ({last})")

    root = ET.fromstring(r.content)
    items = []
    for it in root.iter("item"):
        company = _text(it, "title")
        desc = _text(it, "description")
        link = _text(it, "link")
        pub = _text(it, "pubDate")
        uid = hashlib.sha1(f"{feed_id}|{company}|{desc}|{pub}".encode()).hexdigest()[:16]
        items.append({
            "id": uid,
            "feed": feed_id,
            "scrip": company.upper(),          # NSE feeds carry the company name, not a code
            "company": company,
            "headline": desc[:400] or company,
            "subcategory": feed_id.replace("_", " "),
            "date": _date(pub),
            "pdf": link if link.lower().endswith(".pdf") else "",
            "page": link,
        })
    return items
