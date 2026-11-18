"""Screens = named sets of flags with points. Data: NSE's official RSS feeds.

To add a new screen later, add flags to FLAGS (if needed) and a new entry to SCREENS.
Every flag is matched against the announcement headline + subject + category text,
so every point a stock gets can be traced to a specific BSE filing.
"""
import re

# flag id -> (label shown on dashboard, regex)
FLAGS = {
    "name_change": ("Name change",
        r"change (of|in) (the )?name|name change|new name of the company"),
    "control_change": ("Open offer / change in control",
        r"open offer|change (in|of) (control|management)|takeover|letter of offer"),
    "preferential": ("Preferential issue / warrants",
        r"preferential|warrants?\b"),
    "rights": ("Rights issue",
        r"rights issue|rights entitlement|issue of equity shares on rights|\brights \d+\s*:\s*\d+"),
    "order_loi": ("Order / LOI / MoU",
        r"letter of intent|\bloi\b|\bmou\b|memorandum of understanding|purchase order|work order|"
        r"bagging/receiving of orders|receiving of orders|"
        r"(bags?|bagged|receive[sd]?|secure[sd]?|wins?|won|award(ed)?)\b.{0,40}\b(order|contract)"),
    "price_query": ("Exchange price/volume query",
        r"(clarification|sought).{0,80}(price|volume) movement|movement in (the )?(price|volume)|"
        r"spurt in (price|volume)"),
    "merger": ("Merger / amalgamation",
        r"amalgamation|scheme of arrangement|\bmerger\b"),
    "fund_raise": ("Fund-raising approval",
        r"fund ?raising|raising of funds|qualified institutions placement|\bqip\b"),
    "split_bonus": ("Split / bonus",
        r"sub-?division|stock split|split of (equity )?shares|face value split|bonus (issue|shares)|\bbonus \d+\s*:\s*\d+"),
}

BUZZWORDS = r"\b(aero|aer|drone|defen[cs]e|ai|robot\w*|quantum|green|solar|ev|electric|energy|" \
            r"hydrogen|semicon\w*|chip|space|digital|tech\w*|data|cyber|infra\w*)\b"

SCREENS = {
    "narrative": {
        "title": "Narrative / operator",
        "description": "Shell-style pattern: takeover, buzzword rename, cheap equity to promoters, "
                       "order headlines, exchange price queries. Built from the Aerpace case.",
        "lookback_days": 365,
        "threshold": 5,
        "points": {
            "name_change": 2, "control_change": 2, "preferential": 2, "price_query": 2,
            "rights": 1, "order_loi": 1, "merger": 1, "split_bonus": 1, "fund_raise": 1,
        },
        # extra point when the company renamed itself AND the current name has a buzzword
        "buzz_rename_bonus": 1,
    },
}

_COMPILED = {k: re.compile(v[1], re.I) for k, v in FLAGS.items()}
_BUZZ = re.compile(BUZZWORDS, re.I)

# Routine filings that mention keywords but mean nothing (e.g. "trading window", ESOP allotments)
_NOISE = re.compile(r"trading window|closure of trading|\besop\b|employee stock|"
                    r"newspaper (publication|advertisement)|loss of share certificate|"
                    r"duplicate share|investor (meet|presentation)|analyst", re.I)


def flags_for(ann):
    text = f"{ann['headline']} {ann['subcategory']}"
    if _NOISE.search(text):
        return []
    return [k for k, rx in _COMPILED.items() if rx.search(text)]


def has_buzzword(name):
    return bool(_BUZZ.search(name or ""))
