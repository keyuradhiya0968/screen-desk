"""Fundamental screens from annual and quarterly statements (Yahoo Finance via yfinance, free).

Yahoo's data is unofficial: every screen is a shortlist to check against the annual report.
"""

GROUP = "fundamental"


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _cagr(first, last, years):
    if first is None or last is None or first <= 0 or last <= 0 or years <= 0:
        return None
    return ((last / first) ** (1 / years) - 1) * 100


def _g(a, b):
    """% change from b to a, only when both are positive."""
    return (a / b - 1) * 100 if a is not None and b and b > 0 and a > 0 else None


def metrics(f, close):
    """Every number the fundamental screens use, from one stock's stored statements."""
    yrs = len(f.get("years") or [])
    if f.get("empty") or yrs < 3:
        return None
    rev, ni, ebit, eq = f["revenue"], f["net_income"], f["ebit"], f["equity"]
    span = yrs - 1
    margin0 = ni[0] / rev[0] if ni[0] is not None and rev[0] else None
    tiny_base = margin0 is None or margin0 < 0.02          # profit growth off a near-zero base is not growth
    roce = _avg([e / (a - c) * 100 if e is not None and a and c is not None and a - c > 0 else None
                 for e, a, c in zip(ebit, f["assets"], f["cur_liab"])])
    roe = _avg([n / q * 100 if n is not None and q and q > 0 else None for n, q in zip(ni, eq)])
    cfo_sum = sum(x for x in f["cfo"] if x is not None) if any(x is not None for x in f["cfo"]) else None
    ni_sum = sum(x for x in ni if x is not None) if any(x is not None for x in ni) else None
    debt, equity = (f["debt"][-1] if f["debt"] else None), (eq[-1] if eq else None)
    interest = abs(f["interest"][-1]) if f["interest"] and f["interest"][-1] else 0
    shares = f["shares"][-1] if f["shares"] else None
    profit = f.get("ttm_net_income") or ni[-1]
    mcap = close * shares if close and shares else None
    divs = [abs(x) for x in (f.get("dividends") or []) if x]
    q_rev, q_ni = f.get("q_revenue") or [], f.get("q_net_income") or []
    m = {
        "years": yrs,
        "roce": roce, "roe": roe,
        "sales_cagr": _cagr(rev[0], rev[-1], span),
        "profit_cagr": None if tiny_base else _cagr(ni[0], ni[-1], span),
        "sales_g1": _g(rev[-1], rev[-2]), "profit_g1": _g(ni[-1], ni[-2]),
        "q_sales_yoy": _g(q_rev[-1], q_rev[-5]) if len(q_rev) >= 5 else None,
        "q_profit_yoy": _g(q_ni[-1], q_ni[-5]) if len(q_ni) >= 5 else None,
        "cfo_pat": cfo_sum / ni_sum if cfo_sum is not None and ni_sum and ni_sum > 0 else None,
        "cfo_sum": cfo_sum,
        "de": (debt or 0) / equity if equity and equity > 0 else None,
        "icr": (ebit[-1] / interest) if interest and ebit[-1] is not None else (None if debt else 99.0),
        "mcap_cr": mcap / 1e7 if mcap else None,
        "pe": mcap / profit if mcap and profit and profit > 0 else None,
        "pb": mcap / equity if mcap and equity and equity > 0 else None,
        "div_yield": divs[-1] / mcap * 100 if divs and mcap and f["dividends"][-1] else None,
        "div_years": len(divs),
        "payout": divs[-1] / ni[-1] * 100 if divs and f["dividends"][-1] and ni[-1] and ni[-1] > 0 else None,
        "profits": ni, "debts": f["debt"], "ttm_profit": profit,
        "asof": f.get("asof", ""),
    }
    m["peg"] = m["pe"] / m["profit_cagr"] if m["pe"] and m["profit_cagr"] and m["profit_cagr"] > 0 else None
    return m


SHOW = ("roce", "roe", "sales_cagr", "profit_cagr", "sales_g1", "profit_g1", "q_sales_yoy", "q_profit_yoy",
        "cfo_pat", "de", "icr", "mcap_cr", "pe", "pb", "peg", "div_yield", "payout", "years", "asof")


def _hit(sym, m, score, tags, alert=False, alert_key=None):
    show = {k: (round(m[k], 2) if isinstance(m[k], float) else m[k]) for k in SHOW if m.get(k) is not None}
    h = {"symbol": sym, "date": m["asof"], "score": int(max(1, min(10, score))), "tags": tags,
         "summary": " · ".join(tags), "metrics": show, "alert": alert}
    if alert_key:
        h["alert_key"] = alert_key
    return h


def _profitable(m, n=3):
    p = [x for x in m["profits"][-n:]]
    return len(p) == n and all(x is not None and x > 0 for x in p)


# ------------------------------------------------------------------ 1
class Quality:
    ID, TITLE = "quality", "Quality compounder"
    DESCRIPTION = "High returns on capital, profits backed by cash, little debt, sensible price."
    RULES = ["10-point scorecard: ROCE ≥ 15% (2), ROE ≥ 12% (1), sales growth ≥ 12%/yr (1),",
             "profit growth ≥ 12%/yr and not lagging sales (1), cash from operations ≥ 70% of profit (2; ≥ 40%: 1),",
             "debt-to-equity ≤ 0.5 (1), interest cover ≥ 4× (1), PEG ≤ 1.5 or P/E ≤ 40 (1)",
             "Listed from 8 points; alert when a stock first reaches 9"]

    def run(self, ctx):
        out = []
        for sym, m in ctx["fm"].items():
            pts, tags = 0, []
            if m["roce"] is not None and m["roce"] >= 15:
                pts += 2; tags.append(f"ROCE {m['roce']:.0f}%")
            if m["roe"] is not None and m["roe"] >= 12:
                pts += 1
            if m["sales_cagr"] is not None and m["sales_cagr"] >= 12:
                pts += 1; tags.append(f"sales +{m['sales_cagr']:.0f}%/yr")
            if m["profit_cagr"] is not None and m["profit_cagr"] >= 12 and \
                    (m["sales_cagr"] is None or m["profit_cagr"] >= 0.6 * m["sales_cagr"]):
                pts += 1; tags.append(f"profit +{m['profit_cagr']:.0f}%/yr")
            if m["cfo_pat"] is not None:
                if 0.7 <= m["cfo_pat"]:
                    pts += 2; tags.append(f"cash {min(m['cfo_pat'], 9.9):.1f}× profit")
                elif m["cfo_pat"] >= 0.4:
                    pts += 1
            if m["de"] is not None and m["de"] <= 0.5:
                pts += 1; tags.append("debt-free" if m["de"] <= 0.05 else "low debt")
            if m["icr"] is not None and m["icr"] >= 4:
                pts += 1
            if (m["peg"] is not None and m["peg"] <= 1.5) or (m["peg"] is None and m["pe"] and m["pe"] <= 40):
                pts += 1; tags.append(f"PEG {m['peg']:.1f}" if m["peg"] else f"P/E {m['pe']:.0f}")
            if pts >= 8:
                out.append(_hit(sym, m, pts, tags, alert=pts >= 9, alert_key="quality9"))
        return out


# ------------------------------------------------------------------ 2
class Growth:
    ID, TITLE = "growth", "Growth"
    DESCRIPTION = "Sales and profits compounding fast over 3 years and still growing fast in the latest year and quarter."
    RULES = ["Sales and profit growth ≥ 15% a year over the period, and ≥ 15% in the latest year",
             "Latest quarter vs the same quarter last year: sales and profit up ≥ 15% (when 5 quarters are available)",
             "ROE ≥ 12%; profitable in each of the last 3 years; growth off a near-zero profit base is ignored"]

    def run(self, ctx):
        out = []
        for sym, m in ctx["fm"].items():
            need = [m["sales_cagr"], m["profit_cagr"], m["sales_g1"], m["profit_g1"], m["roe"]]
            if any(x is None for x in need) or not _profitable(m):
                continue
            if min(m["sales_cagr"], m["profit_cagr"], m["sales_g1"], m["profit_g1"]) < 15 or m["roe"] < 12:
                continue
            qs, qp = m["q_sales_yoy"], m["q_profit_yoy"]
            if qs is not None and qp is not None and (qs < 15 or qp < 15):
                continue
            tags = [f"sales +{m['sales_cagr']:.0f}%/yr", f"profit +{m['profit_cagr']:.0f}%/yr"]
            tags.append(f"latest quarter sales +{qs:.0f}%, profit +{qp:.0f}%" if qs is not None and qp is not None
                        else "no quarterly check")
            score = 6 + (m["sales_cagr"] >= 25) + (m["profit_g1"] >= 25) + (qp is not None and qp >= 25) + \
                    (m["peg"] is not None and m["peg"] <= 1.2)
            out.append(_hit(sym, m, score, tags))
        return out


# ------------------------------------------------------------------ 3
class Value:
    ID, TITLE = "value", "Value"
    DESCRIPTION = "Profitable, decently run businesses priced cheaply on earnings and book value."
    RULES = ["P/E between 3 and 15 (latest 12 months' profit; under 3 usually means a one-off gain or bad data)",
             "Price-to-book ≤ 2.5",
             "ROE ≥ 12% on average; profitable in each of the last 3 years",
             "Cash from operations ≥ 50% of profit; debt-to-equity ≤ 1"]

    def run(self, ctx):
        out = []
        for sym, m in ctx["fm"].items():
            if not (m["pe"] and m["pb"] and m["roe"] is not None and m["cfo_pat"] is not None and m["de"] is not None):
                continue
            if m["pe"] < 3 or m["pe"] > 15 or m["pb"] > 2.5 or m["roe"] < 12 or m["cfo_pat"] < 0.5 or m["de"] > 1 or not _profitable(m):
                continue
            tags = [f"P/E {m['pe']:.1f}", f"P/B {m['pb']:.1f}", f"ROE {m['roe']:.0f}%"]
            if m["div_yield"]:
                tags.append(f"yield {m['div_yield']:.1f}%")
            score = 6 + (m["pe"] <= 10) + (m["pb"] <= 1.5) + (m["roe"] >= 18) + (m["de"] <= 0.3)
            out.append(_hit(sym, m, score, tags))
        return out


# ------------------------------------------------------------------ 4
class Penny:
    ID, TITLE = "penny", "Penny (clean)"
    DESCRIPTION = "Low-priced or small companies that are genuinely profitable and cash-generating, minus story stocks."
    RULES = ["Market cap ≤ ₹1,000 crore, and share price ≤ ₹50 or market cap ≤ ₹500 crore; main board (EQ) only",
             "Profitable in each of the last 3 years; positive cash from operations overall",
             "Debt-to-equity ≤ 0.5, ROE ≥ 10%, sales growing",
             "Excluded: any stock on the Narrative / operator screen"]

    def run(self, ctx):
        out, story = [], ctx["narrative_syms"]
        H = ctx["H"]
        for sym, m in ctx["fm"].items():
            i = H.idx.get(sym)
            close = H.C[i, -1] if i is not None else None
            if i is None or H.series[i] != "EQ" or sym in story or close is None or close != close:
                continue
            mc = m["mcap_cr"]
            if not mc or mc > 1000 or not (close <= 50 or mc <= 500):
                continue
            if not _profitable(m) or not m["cfo_sum"] or m["cfo_sum"] <= 0 or m["de"] is None or m["de"] > 0.5:
                continue
            if m["roe"] is None or m["roe"] < 10 or m["sales_cagr"] is None or m["sales_cagr"] <= 0:
                continue
            tags = [f"₹{close:,.1f}", f"mcap ₹{m['mcap_cr']:,.0f} cr" if m["mcap_cr"] else "mcap n/a",
                    f"ROE {m['roe']:.0f}%", f"sales +{m['sales_cagr']:.0f}%/yr"]
            score = 6 + (m["roe"] >= 15) + (m["sales_cagr"] >= 15) + (m["de"] <= 0.1) + \
                    (m["pe"] is not None and m["pe"] <= 20)
            out.append(_hit(sym, m, score, tags))
        return out


# ------------------------------------------------------------------ 5
class Turnaround:
    ID, TITLE = "turnaround", "Turnaround"
    DESCRIPTION = "Companies that made losses a few years ago and are now profitable, with profit and balance sheet improving."
    RULES = ["A loss in an earlier year; profitable in each of the last 2 years with profit rising",
             "Latest 12 months profitable",
             "Debt flat or falling over 2 years, or debt-to-equity ≤ 0.5"]

    def run(self, ctx):
        out = []
        for sym, m in ctx["fm"].items():
            p, d = m["profits"], m["debts"]
            if len(p) < 3 or any(x is None for x in p[-2:]):
                continue
            if not any(x is not None and x <= 0 for x in p[:-2]) or not (0 < p[-2] < p[-1]):
                continue
            if not m["ttm_profit"] or m["ttm_profit"] <= 0:
                continue
            debt_ok = (len(d) >= 3 and d[-1] is not None and d[-3] is not None and d[-1] <= d[-3]) or \
                      (m["de"] is not None and m["de"] <= 0.5)
            if not debt_ok:
                continue
            tags = ["loss → profit", f"profit up {(p[-1] / p[-2] - 1) * 100:.0f}% last year"]
            if m["de"] is not None:
                tags.append(f"D/E {m['de']:.2f}")
            score = 6 + (p[-1] >= 2 * p[-2]) + (m["de"] is not None and m["de"] <= 0.5) + \
                    (m["cfo_pat"] is not None and m["cfo_pat"] >= 0.7)
            out.append(_hit(sym, m, score, tags))
        return out


# ------------------------------------------------------------------ 6
class Dividend:
    ID, TITLE = "dividend", "Dividend payers"
    DESCRIPTION = "Consistent dividend payers with a decent yield that profits and cash flow comfortably cover."
    RULES = ["Dividend yield ≥ 2.5% (last year's dividends paid ÷ today's market cap)",
             "Dividends paid in at least 3 of the years available",
             "Payout ≤ 80% of profit; profitable in each of the last 3 years"]

    def run(self, ctx):
        out = []
        for sym, m in ctx["fm"].items():
            if not m["div_yield"] or m["div_yield"] < 2.5 or m["div_years"] < 3 or not _profitable(m):
                continue
            if m["payout"] is None or m["payout"] > 80:
                continue
            tags = [f"yield {m['div_yield']:.1f}%", f"payout {m['payout']:.0f}%", f"paid {m['div_years']} years"]
            score = 6 + (m["div_yield"] >= 4) + (m["payout"] <= 50) + (m["roe"] is not None and m["roe"] >= 15) + \
                    (m["de"] is not None and m["de"] <= 0.3)
            out.append(_hit(sym, m, score, tags))
        return out


SCREENS = [Quality(), Growth(), Value(), Penny(), Turnaround(), Dividend()]
