"""Daily run: fetch new BSE announcements, backfill history, score screens, publish, alert.

Run locally or in GitHub Actions:  python -m screener.run
"""
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

from . import bse
from .screens import FLAGS, SCREENS, flags_for, has_buzzword

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DOCS = ROOT / "docs"
IST = timezone(timedelta(hours=5, minutes=30))

BACKFILL_DAYS = int(os.environ.get("BACKFILL_DAYS_PER_RUN", "45"))
MAX_MINUTES = float(os.environ.get("MAX_MINUTES", "50"))
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


def fetch_days(days, flagged, log, session, deadline):
    """Fetch each day, keep only announcements that hit at least one flag."""
    known = {a["id"] for a in flagged}
    done = []
    for day in days:
        if time.time() > deadline:
            log.append(f"Stopped at time limit before {day}")
            break
        try:
            rows = bse.announcements_for_day(day, session)
        except bse.BSEError as e:
            log.append(f"{day}: BSE did not answer ({e})")
            break
        hits = 0
        for row in rows:
            a = bse.normalise(row)
            if not a["id"] or a["id"] in known:
                continue
            f = flags_for(a)
            if f:
                a["flags"] = f
                if not a["date"]:
                    a["date"] = day.isoformat()
                flagged.append(a)
                known.add(a["id"])
                hits += 1
        log.append(f"{day}: {len(rows)} filings read, {hits} flagged")
        done.append(day)
    return done


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
                "events": [{k: a[k] for k in ("date", "headline", "pdf", "flags")} for a in c["events"][:25]],
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
            fresh = [e for e in r["events"]
                     if (today - d(e["date"])).days <= ALERT_RECENT_DAYS
                     and f"{sid}:{r['scrip']}:{e['date']}:{e['headline'][:60]}" not in sent]
            for e in fresh:
                sent.add(f"{sid}:{r['scrip']}:{e['date']}:{e['headline'][:60]}")
            if fresh:
                lines = [f"<b>{esc(r['company'])}</b> ({r['scrip']}) · {esc(res['title'])} score "
                         f"<b>{r['score']}</b>"]
                for e in fresh[:3]:
                    link = f' <a href="{e["pdf"]}">filing</a>' if e["pdf"] else ""
                    lines.append(f"• {e['date']}: {esc(e['headline'][:160])}{link}")
                msgs.append("\n".join(lines))
    state["alerted"] = sorted(sent)[-5000:]
    return msgs


def main():
    t0 = time.time()
    deadline = t0 + MAX_MINUTES * 60
    today = datetime.now(IST).date()
    flagged = load(DATA / "flagged.json", [])
    state = load(DATA / "state.json", {})
    log, session = [], requests.Session()

    newest = d(state["newest"]) if state.get("newest") else today - timedelta(days=4)
    forward = [newest + timedelta(days=i) for i in range(1, (today - newest).days + 1)]
    got = fetch_days(forward, flagged, log, session, deadline)
    if got:
        state["newest"] = max(got).isoformat()
        state.setdefault("oldest", min(got).isoformat())

    target = today - timedelta(days=HISTORY_DAYS)
    oldest = d(state["oldest"]) if state.get("oldest") else today
    back = [oldest - timedelta(days=i) for i in range(1, BACKFILL_DAYS + 1)]
    back = [x for x in back if x >= target]
    got_back = fetch_days(back, flagged, log, session, deadline) if back else []
    if got_back:
        state["oldest"] = min(got_back).isoformat()

    cutoff = today - timedelta(days=HISTORY_DAYS + 30)
    flagged = [a for a in flagged if a.get("date") and d(a["date"]) >= cutoff]

    results = score(flagged, today)
    failed = any("did not answer" in line for line in log)
    msgs = alerts(results, state, today)
    if msgs:
        telegram("🔎 <b>New screen hits</b>\n\n" + "\n\n".join(msgs[:15]))
    if failed and not got:
        telegram("⚠️ Screener run could not reach BSE today. Dashboard shows the last good data.")

    coverage_days = (d(state["newest"]) - d(state["oldest"])).days + 1 if state.get("oldest") else 0
    save(DATA / "flagged.json", flagged)
    save(DATA / "state.json", state)
    save(DOCS / "data.json", {
        "generated": datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"),
        "coverage": {"from": state.get("oldest"), "to": state.get("newest"),
                     "days": coverage_days, "target_days": HISTORY_DAYS},
        "status": "error" if failed and not got else "ok",
        "log": log[-60:], "alerts_sent": len(msgs),
        "flag_labels": {k: v[0] for k, v in FLAGS.items()} | {"buzz_rename": "Buzzword rename"},
        "screens": results,
    })
    print("\n".join(log))
    print(f"Done in {time.time() - t0:.0f}s, {len(msgs)} alerts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
