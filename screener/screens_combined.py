"""Combined recipes: a stock must be on one technical AND one fundamental screen at the same time.

These are the alerts worth acting on, so a recipe alerts when its technical signal is from the latest session.
Add a recipe by adding a line below; the dashboard also lets you pair any two screens by hand.
"""

RECIPES = [
    {"id": "quality_breakout", "title": "Quality breakout", "tech": "breakout", "fund": "quality",
     "why": "A high-quality business breaking out on heavy, delivery-backed volume."},
    {"id": "quality_pullback", "title": "Quality on a dip", "tech": "pullback", "fund": "quality",
     "why": "A quality compounder in an uptrend, pulling back quietly to its 20-day average."},
    {"id": "growth_near_high", "title": "Growth near highs", "tech": "near_high", "fund": "growth",
     "why": "Fast-growing earnings with the price pressing against its 52-week high."},
    {"id": "growth_leaders", "title": "Growth leaders", "tech": "rs_leaders", "fund": "growth",
     "why": "Fast growth that the market is already rewarding: top-decile relative strength."},
    {"id": "value_accumulation", "title": "Value being accumulated", "tech": "accumulation", "fund": "value",
     "why": "Cheap, profitable companies where delivery buying is rising while the price is flat."},
    {"id": "penny_accumulation", "title": "Clean penny, quiet buying", "tech": "accumulation", "fund": "penny",
     "why": "Small, genuinely profitable companies with delivery accumulation (story stocks excluded)."},
    {"id": "turnaround_breakout", "title": "Turnaround breakout", "tech": "breakout", "fund": "turnaround",
     "why": "A business back in profit, with the price breaking out to confirm it."},
    {"id": "quality_base", "title": "Quality in a tight base", "tech": "base", "fund": "quality",
     "why": "A quality business coiling near its highs on drying volume."},
]


def match(stocks, recipe):
    """Symbols on both screens of a recipe."""
    return [s for s, st in stocks.items() if recipe["tech"] in st["hits"] and recipe["fund"] in st["hits"]]
