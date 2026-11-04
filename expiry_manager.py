"""Expiry selection (current / next / any slot) with automatic roll-over."""
from timeframe_engine import CLOSE


def active_expiries(im, sym, now):
    today = now.date().isoformat(); out = []
    for e in im.expiries(sym):
        if e > today or (e == today and now.time() < CLOSE): out.append(e)
    return out


def pick_expiries(im, sym, slots, now):
    ex = active_expiries(im, sym, now)
    return [ex[i] for i in sorted(set(slots)) if 0 <= i < len(ex)]
