"""Scheduled run: read NSE's official RSS feeds, keep flagged filings, score screens, publish, alert.

Run locally or in GitHub Actions:  python -m screener.run
"""
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

from . import nse_feeds
from .screens import FLAGS, SCREENS, flags_for, has_buzzword

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DOCS = ROOT / "docs"
IST = timezone(timedelta(hours=5, minutes=30))
HISTORY_DAYS = max(s["lookback_days"] for s in SCREENS.values())
ALERT_RECENT_DAYS = 3


def load(path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return default


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False))


def d(s):
    return date.fromisoformat(s)


def score(flagged, today):
    out = {}
    for sid, s in SCREENS.items():
        start = today - timedelta(days=s["lookback_days"])
        by_co = {}
        for a in flagged:
            if not a.get("date") or d(a["date"]) < start:
                continue
            if not any(f in s["points"] for f in a["flags"]):
                continue
            c = by_co.setdefault(a["scrip"], {"scrip": a["scrip"], "company": a["company"],
                                              "page": a["page"], "events": [], "flags": set()})
            c["events"].append(a)
            c["flags"].update(f for f in a["flags"] if f in s["points"])
        rows = []
        for c in by_co.values():
            pts = sum(s["points"][f] for f in c["flags"])
            reasons = sorted(c["flags"], key=lambda f: -s["points"][f])
            if "name_change" in c["flags"] and has_buzzword(c["company"]):
                pts += s.get("buzz_rename_bonus", 0)
                reasons.append("buzz_rename")
            c["events"].sort(key=lambda a: a["date"], reverse=True)
            rows.append({
                "scrip": c["scrip"], "company": c["company"], "page": c["page"], "score": pts,
                "flags": reasons, "last_event": c["events"][0]["date"],
                "events": [{k: a.get(k, "") for k in ("date", "headline", "pdf", "page", "flags")}
                           for a in c["events"][:25]],
            })
        rows.sort(key=lambda r: r["last_event"], reverse=True)
        rows.sort(key=lambda r: r["score"], reverse=True)
        out[sid] = {
            "title": s["title"], "description": s["description"], "threshold": s["threshold"],
            "lookback_days": s["lookback_days"],
            "points": {**s["points"], "buzz_rename": s.get("buzz_rename_bonus", 0)},
            "rows": [r for r in rows if r["score"] >= 2][:400],
        }
    return out


def telegram(text):
    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return False
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=20, data={
            "chat_id": chat, "text": text[:4000], "parse_mode": "HTML",
            "disable_web_page_preview": "true"})
        return True
    except requests.RequestException:
        return False


def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def alerts(results, state, today):
    sent = set(state.get("alerted", []))
    msgs = []
    for sid, res in results.items():
        for r in res["rows"]:
            if r["score"] < res["threshold"]:
                continue
            fresh = []
            for e in r["events"]:
                key = f"{sid}:{r['scrip']}:{e['date']}:{e['headline'][:60]}"
                if (today - d(e["date"])).days <= ALERT_RECENT_DAYS and key not in sent:
                    fresh.append(e)
                    sent.add(key)
            if fresh:
                lines = [f"<b>{esc(r['company'])}</b> · {esc(res['title'])} score <b>{r['score']}</b>"]
                for e in fresh[:3]:
                    link = e.get("pdf") or e.get("page")
                    tail = f' <a href="{link}">filing</a>' if link else ""
                    lines.append(f"• {e['date']}: {esc(e['headline'][:160])}{tail}")
                msgs.append("\n".join(lines))
    state["alerted"] = sorted(sent)[-5000:]
    return msgs


def main():
    t0 = time.time()
    today = datetime.now(IST).date()
    flagged = load(DATA / "flagged.json", [])
    state = load(DATA / "state.json", {})
    known = {a["id"] for a in flagged}
    log, ok_feeds, session = [], 0, requests.Session()

    for feed_id in nse_feeds.FEEDS:
        try:
            items = nse_feeds.fetch(feed_id, session)
        except (RuntimeError, ValueError) as e:   # ValueError covers malformed XML
            log.append(str(e))
            continue
        ok_feeds += 1
        hits = 0
        for a in items:
            if a["id"] in known:
                continue
            f = flags_for(a)
            if f:
                a["flags"] = f
                a["date"] = a["date"] or today.isoformat()
                flagged.append(a)
                known.add(a["id"])
                hits += 1
        dates = sorted(x["date"] for x in items if x["date"])
        span = f"{dates[0]} to {dates[-1]}" if dates else "no dates"
        log.append(f"{feed_id}: {len(items)} filings read ({span}), {hits} new flagged")
        time.sleep(2)

    if ok_feeds:
        state.setdefault("since", today.isoformat())
        state["last_ok"] = datetime.now(IST).strftime("%Y-%m-%d %H:%M")

    cutoff = today - timedelta(days=HISTORY_DAYS + 30)
    flagged = [a for a in flagged if a.get("date") and d(a["date"]) >= cutoff]

    results = score(flagged, today)
    msgs = alerts(results, state, today)
    if msgs:
        telegram("🔎 <b>New screen hits</b>\n\n" + "\n\n".join(msgs[:15]))
    if not ok_feeds:
        telegram("⚠️ Screener run could not reach NSE's feeds. Dashboard shows the last good data.")

    since = state.get("since")
    save(DATA / "flagged.json", flagged)
    save(DATA / "state.json", state)
    save(DOCS / "data.json", {
        "generated": datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"),
        "source": "NSE official RSS feeds",
        "coverage": {"from": since, "to": today.isoformat() if ok_feeds else state.get("last_ok", "")[:10],
                     "days": (today - d(since)).days + 1 if since else 0, "target_days": HISTORY_DAYS},
        "status": "ok" if ok_feeds else "error",
        "log": log, "alerts_sent": len(msgs),
        "flag_labels": {k: v[0] for k, v in FLAGS.items()} | {"buzz_rename": "Buzzword rename"},
        "screens": results,
    })
    print("\n".join(log))
    print(f"Done in {time.time() - t0:.0f}s, {ok_feeds}/{len(nse_feeds.FEEDS)} feeds read, {len(msgs)} alerts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
