"""Bulk and block deals: who is buying or selling large blocks."""

ID = "bulk_deals"
TITLE = "Bulk & block deals"
DESCRIPTION = "Large trades disclosed by NSE over the last 10 sessions, netted per stock."

SESSIONS = 10
MIN_VALUE_CR = 1.0
RULES = ["Bulk deals (≥0.5% of shares in a day) and block deals from NSE's daily files",
         "Buys and sells netted per stock over the last 10 sessions",
         "Listed when net value is at least ₹1 crore either way; net buyers score higher"]


def run(ctx):
    days = sorted({d["date"] for d in ctx["deals"] if d.get("date")})[-SESSIONS:]
    by = {}
    for d in ctx["deals"]:
        if d.get("date") not in days or not d.get("value_cr"):
            continue
        s = by.setdefault(d["symbol"], {"buy": 0.0, "sell": 0.0, "events": [], "buyers": set(), "sellers": set()})
        side = "buy" if d["side"].startswith("BUY") else "sell"
        s[side] += d["value_cr"]
        (s["buyers"] if side == "buy" else s["sellers"]).add(d["client"].title())
        s["events"].append({"date": d["date"],
                            "text": f"{d['kind'].title()} {side}: {d['client'].title()} · "
                                    f"{d['qty']:,.0f} shares @ ₹{d['price']:,.2f} (₹{d['value_cr']:,.2f} cr)",
                            "link": ""})
    hits = []
    for sym, s in by.items():
        net = s["buy"] - s["sell"]
        if abs(net) < MIN_VALUE_CR:
            continue
        score = (9 if net >= 25 else 8 if net >= 10 else 7 if net >= 5 else 6) if net > 0 else 2
        tags = [f"Net {'buy' if net > 0 else 'sell'} ₹{abs(net):,.1f} cr"]
        who = s["buyers"] if net > 0 else s["sellers"]
        tags.append(", ".join(sorted(who)[:2]) + (f" +{len(who) - 2}" if len(who) > 2 else ""))
        s["events"].sort(key=lambda e: e["date"], reverse=True)
        hits.append({"symbol": sym, "date": s["events"][0]["date"], "score": score, "tags": tags,
                     "summary": " · ".join(tags),
                     "metrics": {"net_cr": round(net, 2), "buy_cr": round(s["buy"], 2), "sell_cr": round(s["sell"], 2)},
                     "events": s["events"][:20], "alert": False})
    return hits
