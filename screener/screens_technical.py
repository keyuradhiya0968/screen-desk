"""Technical screens: price, volume and delivery only. Liquid stocks only (≥ ₹1 crore a day)."""
import numpy as np

GROUP = "technical"
LIQ_LACS = 100.0          # ₹1 crore average daily traded value
SERIES = ("EQ", "SM", "ST")


_LISTED = set()          # filled by run.py: companies in NSE's equity list (keeps ETFs out)


def _base(H, i):
    return H.series[i] in SERIES and (not _LISTED or H.syms[i] in _LISTED) and H.liquid(i, LIQ_LACS)


def _hit(sym, date, score, tags, metrics, alert=False):
    return {"symbol": sym, "date": date, "score": int(max(1, min(10, score))), "tags": tags,
            "summary": " · ".join(tags), "metrics": metrics, "alert": alert}


def _hi52(H, i):
    return H.maxv(H.H[i], 250)


# ------------------------------------------------------------------ 1
class Breakout:
    ID, TITLE = "breakout", "Volume breakout"
    DESCRIPTION = "Price breaks above its recent range on unusually heavy volume, with most shares taken for delivery."
    RULES = ["All technical screens: companies only (no ETFs), average traded value ≥ ₹1 crore a day",
             "Close above the highest high of the previous 20 sessions, or a new 52-week high",
             "Volume at least 2× its 20-day average; delivery at least 50%",
             "Close higher than the previous day; hits from the last 5 sessions are shown"]

    def run(self, ctx):
        H, w52 = ctx["H"], ctx["w52_new_highs"]
        out = []
        for i, sym in enumerate(H.syms):
            if not _base(H, i):
                continue
            for k in range(max(21, H.T - 5), H.T):
                c, v, dp = H.C[i, k], H.V[i, k], H.DP[i, k]
                if np.isnan(c) or np.isnan(v) or np.isnan(dp) or dp < 50:
                    continue
                avg = H.mean(H.V[i], 20, k - 1, 0.75)
                hi20 = H.maxv(H.H[i], 20, k - 1)
                if not avg or not hi20 or v < 2 * avg:
                    continue
                prev = H.PREV[i, k]
                if not np.isnan(prev) and c <= prev:
                    continue
                is52 = sym in w52.get(H.dates[k], {})
                if not (c > hi20 or is52):
                    continue
                vx = v / avg
                tags = (["52-week high"] if is52 else ["20-day breakout"]) + [f"{vx:.1f}× volume", f"{dp:.0f}% delivery"]
                out.append(_hit(sym, H.dates[k], 5 + 2 * is52 + (vx >= 3) + (vx >= 5) + (dp >= 65), tags,
                                {"vol_x": round(vx, 1), "deliv_pct": dp, "breakout_level": round(hi20, 2)}))
        return out


# ------------------------------------------------------------------ 2
class NearHigh:
    ID, TITLE = "near_high", "Near 52-week high"
    DESCRIPTION = "Trading just under the 52-week high with volume picking up: candidates to break out next."
    RULES = ["Close within 5% below the highest high of the last 52 weeks (or of the history stored so far)",
             "20-day average volume at least 1.2× the 50-day average",
             "Close above its 50-day average"]

    def run(self, ctx):
        H = ctx["H"]
        out = []
        for i, sym in enumerate(H.syms):
            if not _base(H, i) or H.days_traded(i) < 60:
                continue
            c, hi = H.C[i, -1], _hi52(H, i)
            v20, v50, s50 = H.mean(H.V[i], 20), H.mean(H.V[i], 50), H.mean(H.C[i], 50)
            if not (hi and v20 and v50 and s50) or not (hi * 0.95 <= c < hi) or v20 < 1.2 * v50 or c <= s50:
                continue
            gap = (hi / c - 1) * 100
            tags = [f"{gap:.1f}% below high", f"volume {v20 / v50:.1f}× usual"]
            out.append(_hit(sym, H.dates[-1], 6 + (gap <= 2) + (v20 >= 1.5 * v50), tags,
                            {"high_52w": round(hi, 2), "gap_pct": round(gap, 2), "vol_20_50": round(v20 / v50, 2)}))
        return out


# ------------------------------------------------------------------ 3
class Accumulation:
    ID, TITLE = "accumulation", "Delivery accumulation"
    DESCRIPTION = "Delivery share rising while the price goes nowhere: someone may be quietly building a position."
    RULES = ["10-day average delivery at least 50%, and at least 1.2× its average of the 50 sessions before",
             "Price range over the last 10 sessions within 10%",
             "Volume not drying up: 10-day average at least 0.8× the 50-day average"]

    def run(self, ctx):
        H = ctx["H"]
        out = []
        for i, sym in enumerate(H.syms):
            if not _base(H, i) or H.days_traded(i) < 60:
                continue
            d10, d_before = H.mean(H.DP[i], 10), H.mean(H.DP[i], 50, H.T - 11)
            hi10, lo10 = H.maxv(H.H[i], 10), H.minv(H.L[i], 10)
            v10, v50 = H.mean(H.V[i], 10), H.mean(H.V[i], 50)
            if not (d10 and d_before and hi10 and lo10 and v10 and v50):
                continue
            rng = (hi10 / lo10 - 1) * 100
            if d10 < 50 or d10 < 1.2 * d_before or rng > 10 or v10 < 0.8 * v50:
                continue
            tags = [f"delivery {d10:.0f}% vs {d_before:.0f}% before", f"{rng:.1f}% range in 10 days"]
            out.append(_hit(sym, H.dates[-1], 6 + (d10 >= 1.5 * d_before) + (rng <= 5) + (d10 >= 65), tags,
                            {"deliv_10d": round(d10, 1), "deliv_before": round(d_before, 1), "range_10d_pct": round(rng, 1)}))
        return out


# ------------------------------------------------------------------ 4
class Pullback:
    ID, TITLE = "pullback", "Pullback in uptrend"
    DESCRIPTION = "A stock in a healthy uptrend dipping back to its 20-day average on light volume."
    RULES = ["50-day average above the 200-day average, and close above the 50-day average",
             "Low of the last 3 sessions within 2% of the 20-day average; close not more than 2% below it",
             "Volume over those 3 sessions under 0.8× the 50-day average; 3-month return positive",
             "Needs 200 sessions of history"]

    def run(self, ctx):
        H = ctx["H"]
        out = []
        for i, sym in enumerate(H.syms):
            if not _base(H, i) or H.days_traded(i) < 200:
                continue
            c = H.C[i, -1]
            s20, s50, s200 = H.mean(H.C[i], 20), H.mean(H.C[i], 50), H.mean(H.C[i], 200)
            lo3, v3, v50, r63 = H.minv(H.L[i], 3), H.mean(H.V[i], 3, min_frac=1), H.mean(H.V[i], 50), H.ret(i, 63)
            if not (s20 and s50 and s200 and lo3 and v3 and v50) or r63 is None:
                continue
            if not (s50 > s200 and c > s50 and lo3 <= s20 * 1.02 and c >= s20 * 0.98 and v3 < 0.8 * v50 and r63 > 0):
                continue
            tags = [f"at 20-day avg ₹{s20:,.0f}", f"3-month +{r63:.0f}%", f"volume {v3 / v50:.1f}× usual"]
            out.append(_hit(sym, H.dates[-1], 6 + (r63 >= 15) + (v3 < 0.6 * v50) + (s50 > s200 * 1.1), tags,
                            {"sma20": round(s20, 2), "sma50": round(s50, 2), "sma200": round(s200, 2), "ret_3m": round(r63, 1)}))
        return out


# ------------------------------------------------------------------ 5
class Base:
    ID, TITLE = "base", "Tight base"
    DESCRIPTION = "Price coiling in a narrow range near its highs while volume dries up, often before a move."
    RULES = ["Price range over the last 15 sessions within 10%",
             "10-day average volume at most 0.6× the 50-day average",
             "Close above the 50-day average and within 15% of the 52-week high"]

    def run(self, ctx):
        H = ctx["H"]
        out = []
        for i, sym in enumerate(H.syms):
            if not _base(H, i) or H.days_traded(i) < 60:
                continue
            c = H.C[i, -1]
            hi15, lo15, hi = H.maxv(H.H[i], 15), H.minv(H.L[i], 15), _hi52(H, i)
            v10, v50, s50 = H.mean(H.V[i], 10), H.mean(H.V[i], 50), H.mean(H.C[i], 50)
            if not (hi15 and lo15 and hi and v10 and v50 and s50):
                continue
            rng = (hi15 / lo15 - 1) * 100
            if rng > 10 or v10 > 0.6 * v50 or c <= s50 or c < 0.85 * hi:
                continue
            tags = [f"{rng:.1f}% range in 15 days", f"volume {v10 / v50:.1f}× usual", f"{(hi / c - 1) * 100:.0f}% below high"]
            out.append(_hit(sym, H.dates[-1], 6 + (rng <= 6) + (v10 <= 0.45 * v50) + (c >= 0.95 * hi), tags,
                            {"range_15d_pct": round(rng, 1), "vol_10_50": round(v10 / v50, 2), "high_52w": round(hi, 2)}))
        return out


# ------------------------------------------------------------------ 6
class RSLeaders:
    ID, TITLE = "rs_leaders", "Relative strength leaders"
    DESCRIPTION = "The top 10% of liquid stocks by 3, 6 and 12-month performance, still in an uptrend."
    RULES = ["Relative strength 90 or above (1–99 rank of weighted 3, 6 and 12-month returns among liquid stocks)",
             "Close above its 50-day average and within 25% of its 52-week high",
             "12-month return uses the history stored so far until a full year is available"]

    def run(self, ctx):
        H, rs = ctx["H"], ctx["rs"]
        out = []
        for sym, rank in rs.items():
            i = H.idx[sym]
            if rank < 90 or not _base(H, i):
                continue
            c, s50, hi = H.C[i, -1], H.mean(H.C[i], 50), _hi52(H, i)
            if not (s50 and hi) or c <= s50 or c < 0.75 * hi:
                continue
            r3, r6 = H.ret(i, 63), H.ret(i, 126)
            tags = [f"RS {rank}"] + ([f"3-month +{r3:.0f}%"] if r3 is not None else []) + \
                   ([f"6-month +{r6:.0f}%"] if r6 is not None else [])
            out.append(_hit(sym, H.dates[-1], 6 + (rank >= 95) + (rank >= 98) + (c >= 0.95 * hi), tags,
                            {"rs": rank, "ret_3m": round(r3, 1) if r3 is not None else None,
                             "ret_6m": round(r6, 1) if r6 is not None else None}))
        return out


SCREENS = [Breakout(), NearHigh(), Accumulation(), Pullback(), Base(), RSLeaders()]
