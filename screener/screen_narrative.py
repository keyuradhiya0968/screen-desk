"""Narrative / operator pattern, built from the Aerpace case (name change no longer counts)."""
import re
from datetime import timedelta

ID = "narrative"
TITLE = "Narrative / operator"
DESCRIPTION = "Filings that often come with story-driven stocks: control changes, cheap equity to promoters, order headlines, exchange volume queries."

LOOKBACK_DAYS = 365
THRESHOLD = 5
FLAGS = {  # id: (label, points, pattern)
    "control_change": ("Open offer / control change", 2,
                       r"open offer|change (in|of) (control|management)|takeover|letter of offer|post offer"),
    "preferential": ("Preferential issue / warrants", 2, r"preferential|warrants?\b"),
    "price_query": ("Exchange price/volume query", 2,
                    r"(significant|spurt|increase) in (the )?(price|volume)|movement in (the )?(price|volume)|"
                    r"clarification.{0,60}(price|volume)"),
    "rights": ("Rights issue", 1, r"rights issue|rights entitlement|\brights \d+\s*:\s*\d+"),
    "order_loi": ("Order / contract / MoU", 1,
                  r"letter of intent|\bloi\b|\bmou\b|memorandum of understanding|work order|purchase order|"
                  r"bagging/receiving of orders|receiving of orders|(new|turnkey) contract|"
                  r"(bags?|bagged|receive[sd]?|secure[sd]?|wins?|won|award(ed)?)\b.{0,40}\b(order|contract)"),
    "merger": ("Merger / amalgamation", 1, r"amalgamation|scheme of arrangement|\bmerger\b"),
    "fund_raise": ("Fund-raising approval", 1, r"fund ?raising|raising of funds|qualified institutions placement|\bqip\b"),
    "split_bonus": ("Split / bonus", 1, r"sub-?division|stock split|face value split|bonus (issue|shares)|\bbonus \d+\s*:\s*\d+"),
}
RULES = [f"{v[0]}: {v[1]} point{'s' if v[1] > 1 else ''}" for v in FLAGS.values()] + [
    "Each type counts once per stock over the last 365 days; listed from 2 points, alert at 5"]

_RX = {k: re.compile(v[2], re.I) for k, v in FLAGS.items()}
_NOISE = re.compile(r"trading window|\besop\b|employee stock|newspaper (publication|advertisement)|"
                    r"loss of share certificate|duplicate share|investor (meet|presentation)|analyst", re.I)


def flags_for(text):
    if _NOISE.search(text or ""):
        return []
    return [k for k, rx in _RX.items() if rx.search(text or "")]


def run(ctx):
    start = (ctx["today"] - timedelta(days=LOOKBACK_DAYS)).isoformat()
    by = {}
    for a in ctx["filings"]:
        if a.get("date", "") < start:
            continue
        f = [x for x in flags_for(a["text"]) if x in FLAGS]
        if not f:
            continue
        s = by.setdefault(a.get("symbol") or a["company"], {"flags": set(), "events": []})
        s["flags"].update(f)
        s["events"].append({"date": a["date"], "text": a["text"], "link": a.get("link", ""),
                            "tags": [FLAGS[x][0] for x in f]})
    hits = []
    for sym, s in by.items():
        score = sum(FLAGS[f][1] for f in s["flags"])
        if score < 2:
            continue
        s["events"].sort(key=lambda e: e["date"], reverse=True)
        tags = [FLAGS[f][0] for f in sorted(s["flags"], key=lambda f: -FLAGS[f][1])]
        hits.append({"symbol": sym, "date": s["events"][0]["date"], "score": min(score, 10), "tags": tags,
                     "summary": " · ".join(tags), "metrics": {"points": score, "filings": len(s["events"])},
                     "events": s["events"][:20], "alert": score >= THRESHOLD})
    return hits
