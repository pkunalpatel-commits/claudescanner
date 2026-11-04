"""Turnover. Dhan's feed has no trade-level data, so turnover is ESTIMATED as ATP x cumulative volume
(day VWAP x volume); window turnover = difference between now and the timeframe baseline."""


def cumulative(cur):
    a, v = cur.get("atp"), cur.get("vol")
    return a * v if a and v else None


def window(cur, base, tf):
    c = cumulative(cur)
    if c is None: return None
    if tf == "1D": return c
    if not base or not base.get("atp") or not base.get("vol"): return None
    d = c - base["atp"] * base["vol"]
    return d if d >= 0 else None
