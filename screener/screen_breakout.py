"""Volume breakout: price breaks out on heavy volume with real delivery buying."""

ID = "breakout"
TITLE = "Volume breakout"
DESCRIPTION = "Price breaks above its recent range on unusually heavy volume, with most shares taken for delivery."

P = {
    "lookback": 20,        # trading days for the range and the average volume
    "vol_mult": 2.0,       # today's volume vs the 20-day average
    "deliv_min": 50.0,     # delivery %, so it is not just intraday churn
    "turnover_cr": 1.0,    # minimum traded value in ₹ crore, to skip illiquid names
    "sessions": 5,         # show hits from the last 5 trading sessions
}
RULES = [
    "Close above the highest high of the previous 20 sessions, or a new 52-week high",
    "Volume at least 2× its 20-day average",
    "Delivery at least 50% of traded volume",
    "Traded value at least ₹1 crore; main board (EQ) and SME series only",
]


def run(ctx):
    dates, px, w52 = ctx["dates"], ctx["px"], ctx["w52_new_highs"]
    hits = []
    for k in range(max(P["lookback"], len(dates) - P["sessions"]), len(dates)):
        day, prior = dates[k], dates[k - P["lookback"]:k]
        new_highs = w52.get(day, {})
        for sym, r in px[day].items():
            if r["series"] not in ("EQ", "SM", "ST") or not r["close"] or not r["volume"]:
                continue
            if (r["turnover_lacs"] or 0) < P["turnover_cr"] * 100 or (r["deliv_pct"] or 0) < P["deliv_min"]:
                continue
            hist = [px[d][sym] for d in prior if sym in px[d]]
            if len(hist) < P["lookback"] * 0.75:
                continue
            avg_vol = sum(h["volume"] or 0 for h in hist) / len(hist)
            if not avg_vol or r["volume"] < P["vol_mult"] * avg_vol:
                continue
            hi20 = max(h["high"] or 0 for h in hist)
            is52 = sym in new_highs
            if not (r["close"] > hi20 or is52):
                continue
            if r["prev"] and r["close"] <= r["prev"]:
                continue
            vx = r["volume"] / avg_vol
            score = 5 + (2 if is52 else 0) + (vx >= 3) + (vx >= 5) + ((r["deliv_pct"] or 0) >= 65)
            tags = (["52-week high"] if is52 else ["20-day breakout"]) + [f"{vx:.1f}× volume",
                                                                         f"{r['deliv_pct']:.0f}% delivery"]
            hits.append({
                "symbol": sym, "date": day, "score": min(score, 10), "tags": tags,
                "summary": " · ".join(tags),
                "metrics": {"vol_x": round(vx, 1), "deliv_pct": r["deliv_pct"],
                            "breakout_level": hi20, "turnover_cr": round((r["turnover_lacs"] or 0) / 100, 1)},
                "alert": day == dates[-1],
            })
    return hits
