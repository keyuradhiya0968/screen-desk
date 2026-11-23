"""Price history as arrays (stocks × trading days), plus the indicators technical screens share."""
import csv
from pathlib import Path

import numpy as np

FIELDS = {"open": "O", "high": "H", "low": "L", "close": "C", "volume": "V",
          "deliv_pct": "DP", "turnover_lacs": "TO", "prev": "PREV"}


class History:
    """H.C[i, t] is stock i's close on trading day t (NaN when it did not trade)."""

    def __init__(self, price_dir: Path):
        files = sorted(Path(price_dir).glob("*.csv"))
        self.dates = [p.stem for p in files]
        rows_by_day = []
        syms = {}
        for p in files:
            with open(p, newline="") as f:
                rows = list(csv.DictReader(f))
            rows_by_day.append(rows)
            for r in rows:
                syms.setdefault(r["symbol"], len(syms))
        self.syms = list(syms)
        self.idx = syms
        n, t = len(self.syms), len(self.dates)
        for attr in FIELDS.values():
            setattr(self, attr, np.full((n, t), np.nan))
        self.series = [""] * n
        for j, rows in enumerate(rows_by_day):
            for r in rows:
                i = syms[r["symbol"]]
                self.series[i] = r["series"]
                for k, attr in FIELDS.items():
                    v = r.get(k)
                    if v not in ("", None):
                        getattr(self, attr)[i, j] = float(v)
        self.T = t

    # ---- helpers (all on one stock's row; `end` is the day index, inclusive) ----
    @staticmethod
    def mean(a, n, end=None, min_frac=0.8):
        end = len(a) - 1 if end is None else end
        w = a[max(0, end - n + 1):end + 1]
        ok = w[~np.isnan(w)]
        return float(ok.mean()) if len(w) >= n * min_frac and len(ok) >= n * min_frac else None

    @staticmethod
    def maxv(a, n, end=None):
        end = len(a) - 1 if end is None else end
        w = a[max(0, end - n + 1):end + 1]
        return float(np.nanmax(w)) if np.any(~np.isnan(w)) else None

    @staticmethod
    def minv(a, n, end=None):
        end = len(a) - 1 if end is None else end
        w = a[max(0, end - n + 1):end + 1]
        return float(np.nanmin(w)) if np.any(~np.isnan(w)) else None

    def days_traded(self, i):
        return int(np.sum(~np.isnan(self.C[i])))

    def ret(self, i, n):
        """% return over the last n trading days, using the nearest traded closes."""
        c = self.C[i]
        if self.T <= n or np.isnan(c[-1]):
            return None
        past = c[:self.T - n][~np.isnan(c[:self.T - n])]
        return (c[-1] / past[-1] - 1) * 100 if len(past) else None

    def liquid(self, i, min_lacs=100.0):
        """Average daily traded value over 20 sessions ≥ min_lacs (₹ lakh) and traded on the last day."""
        if np.isnan(self.C[i, -1]):
            return False
        avg = self.mean(self.TO[i], 20, min_frac=0.6)
        return avg is not None and avg >= min_lacs


def rs_ranks(H: History, min_lacs=100.0):
    """Relative strength 1–99 among liquid stocks: weighted 3, 6 and 12-month returns."""
    raw = {}
    for i, s in enumerate(H.syms):
        if H.series[i] not in ("EQ", "BE", "SM", "ST") or not H.liquid(i, min_lacs):
            continue
        parts = [(0.4, H.ret(i, 63)), (0.3, H.ret(i, 126)), (0.3, H.ret(i, 250))]
        parts = [(w, r) for w, r in parts if r is not None]
        if not parts:
            continue
        raw[s] = sum(w * r for w, r in parts) / sum(w for w, _ in parts)
    if not raw:
        return {}
    order = sorted(raw, key=raw.get)
    n = len(order)
    return {s: max(1, min(99, int(round(k / max(n - 1, 1) * 98 + 1)))) for k, s in enumerate(order)}
