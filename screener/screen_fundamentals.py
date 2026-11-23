"""Fundamentally good: a points scorecard from annual statements (Yahoo Finance, free).

Built for long holding periods: decent-to-good on most measures, not perfect on all.
"""

ID = "fundamentals"
TITLE = "Fundamentally good"
DESCRIPTION = ("Quality, growth, cash conversion, balance sheet and valuation from the last 3–4 annual reports. "
               "Free Yahoo data: check the annual report before acting.")

P = {
    "roce_min": 15.0, "roe_min": 12.0,          # % average over the years available
    "growth_min": 12.0,                          # % a year, sales and profit
    "cfo_pat_min": 0.7,                          # cash from operations ÷ profit, summed over the years
    "de_max": 0.5, "icr_min": 4.0,               # debt-to-equity, interest cover (times)
    "peg_max": 1.5, "pe_max": 40.0,
    "list_from": 6, "alert_from": 8,             # points out of 10
}
RULES = [
    "Quality (3 pts): ROCE ≥ 15% (2) and ROE ≥ 12% (1), averaged over the years available",
    "Growth (2 pts): sales growth ≥ 12% a year (1); profit growth ≥ 12% a year and not lagging sales badly (1)",
    "Cash (2 pts): cash from operations ≥ 70% of profit over the period (2), or ≥ 40% (1)",
    "Balance sheet (2 pts): debt-to-equity ≤ 0.5 (1); interest covered ≥ 4× or no debt (1)",
    "Valuation (1 pt): PEG ≤ 1.5, or P/E ≤ 40 where growth is unclear",
    "Listed from 6 points; alert when a stock first reaches 8. Needs at least 3 years of data",
    "Not covered (no free source): promoter holding and pledges",
]


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _cagr(first, last, years):
    if first is None or last is None or first <= 0 or last <= 0 or years <= 0:
        return None
    return ((last / first) ** (1 / years) - 1) * 100


def metrics(f, close):
    yrs = len(f.get("years") or [])
    rev, ni, ebit = f["revenue"], f["net_income"], f["ebit"]
    roce = _avg([e / (a - c) * 100 if e is not None and a and c is not None and a - c > 0 else None
                 for e, a, c in zip(ebit, f["assets"], f["cur_liab"])])
    roe = _avg([n / q * 100 if n is not None and q and q > 0 else None for n, q in zip(ni, f["equity"])])
    span = yrs - 1
    sales_g = _cagr(rev[0], rev[-1], span) if yrs >= 3 else None
    profit_g = _cagr(ni[0], ni[-1], span) if yrs >= 3 else None
    cfo_sum = sum(x for x in f["cfo"] if x is not None) if any(x is not None for x in f["cfo"]) else None
    ni_sum = sum(x for x in ni if x is not None) if any(x is not None for x in ni) else None
    cfo_pat = cfo_sum / ni_sum if cfo_sum is not None and ni_sum and ni_sum > 0 else None
    eq, debt = f["equity"][-1] if f["equity"] else None, f["debt"][-1] if f["debt"] else None
    de = (debt or 0) / eq if eq and eq > 0 else None
    interest = abs(f["interest"][-1]) if f["interest"] and f["interest"][-1] else 0
    icr = (ebit[-1] / interest) if interest and ebit and ebit[-1] is not None else (None if debt else float("inf"))
    shares = f["shares"][-1] if f["shares"] else None
    profit = f.get("ttm_net_income") or (ni[-1] if ni else None)
    mcap = close * shares if close and shares else None
    pe = mcap / profit if mcap and profit and profit > 0 else None
    peg = pe / profit_g if pe and profit_g and profit_g > 0 else None
    rec_days = [r / v * 365 if r is not None and v else None for r, v in zip(f["receivables"], rev)]
    return {"years": yrs, "roce": roce, "roe": roe, "sales_cagr": sales_g, "profit_cagr": profit_g,
            "cfo_pat": cfo_pat, "de": de, "icr": icr, "pe": pe, "peg": peg,
            "mcap_cr": mcap / 1e7 if mcap else None,
            "debtor_days": rec_days[-1] if rec_days else None,
            "debtor_days_then": rec_days[0] if rec_days else None}


def score(m):
    pts, tags = 0, []
    if m["roce"] is not None and m["roce"] >= P["roce_min"]:
        pts += 2; tags.append(f"ROCE {m['roce']:.0f}%")
    if m["roe"] is not None and m["roe"] >= P["roe_min"]:
        pts += 1
    if m["sales_cagr"] is not None and m["sales_cagr"] >= P["growth_min"]:
        pts += 1; tags.append(f"sales +{m['sales_cagr']:.0f}%/yr")
    if (m["profit_cagr"] is not None and m["profit_cagr"] >= P["growth_min"]
            and (m["sales_cagr"] is None or m["profit_cagr"] >= m["sales_cagr"] * 0.6)):
        pts += 1; tags.append(f"profit +{m['profit_cagr']:.0f}%/yr")
    if m["cfo_pat"] is not None:
        if m["cfo_pat"] >= P["cfo_pat_min"]:
            pts += 2; tags.append(f"cash {m['cfo_pat']:.1f}× profit")
        elif m["cfo_pat"] >= 0.4:
            pts += 1
    if m["de"] is not None and m["de"] <= P["de_max"]:
        pts += 1; tags.append("low debt" if m["de"] > 0.05 else "debt-free")
    if m["icr"] is not None and m["icr"] >= P["icr_min"]:
        pts += 1
    if (m["peg"] is not None and m["peg"] <= P["peg_max"]) or (m["peg"] is None and m["pe"] and m["pe"] <= P["pe_max"]):
        pts += 1; tags.append(f"PEG {m['peg']:.1f}" if m["peg"] else f"P/E {m['pe']:.0f}")
    return pts, tags


def run(ctx):
    hits = []
    for sym, f in ctx.get("fundamentals", {}).items():
        if f.get("empty") or len(f.get("years") or []) < 3:
            continue
        close = (ctx["last_price"].get(sym) or {}).get("close")
        try:
            m = metrics(f, close)
            pts, tags = score(m)
        except (TypeError, ZeroDivisionError, IndexError, KeyError):
            continue
        if pts < P["list_from"]:
            continue
        if m["debtor_days"] and m["debtor_days_then"] and m["debtor_days"] > m["debtor_days_then"] * 1.3:
            tags.append("debtor days rising")
        show = {k: round(v, 2) for k, v in m.items() if isinstance(v, (int, float)) and v != float("inf")}
        if m["icr"] == float("inf"):
            show["icr"] = "no interest"
        show["data_asof"] = f.get("asof", "")
        hits.append({"symbol": sym, "date": f.get("asof", ""), "score": pts, "tags": tags,
                     "summary": " · ".join(tags), "metrics": show, "alert": pts >= P["alert_from"],
                     "alert_key": "quality"})       # alert once, when a stock first reaches the alert level
    return hits
