"""OI change, OI gain %, LTP change %, LTP x change OI, OI notional. Safe against zero/missing baselines."""
from turnover_engine import window


def pct(cur, prev):
    if cur is None or prev is None or prev == 0: return None
    return (cur - prev) / prev * 100.0


def build_row(meta, cur, base, tf):
    ltp, oi = cur["ltp"], cur["oi"]
    r = dict(meta); r.update(tf=tf, ltp=ltp, oi=oi, prev_oi=None, oi_chg=None, oi_pct=None, prev_ltp=None,
                             ltp_chg=None, ltp_pct=None, x=None, notional=None, turnover=window(cur, base, tf),
                             turnover_kind="est")
    if base:
        r["prev_oi"] = base["oi"]; r["oi_chg"] = oi - base["oi"]; r["oi_pct"] = pct(oi, base["oi"])
        pl = base.get("ltp")
        if pl: r["prev_ltp"] = pl; r["ltp_chg"] = ltp - pl; r["ltp_pct"] = pct(ltp, pl)
        r["x"] = ltp * r["oi_chg"]                              # LTP x change in OI
        r["notional"] = r["x"] * meta.get("lot", 1)             # LTP x change in OI x lot size
    return r


def is_cross(r, th, direction, min_abs):
    p = r["oi_pct"]
    if p is None or abs(r["oi_chg"]) < min_abs: return False
    if direction == "pos": return p >= th
    if direction == "neg": return p <= -th
    return abs(p) >= th


def price_ok(lp, gt, lt):
    """LTP % filter: keep when LTP change % is greater than `gt` and less than `lt` (None = off)."""
    if gt is None and lt is None: return True
    if lp is None: return False
    return (gt is None or lp > gt) and (lt is None or lp < lt)


def _n(v, d=-1e18): return d if v is None else v

SORT_KEYS = {
    "oi_pct": lambda r: _n(r["oi_pct"]), "abs_oi": lambda r: abs(_n(r["oi_pct"], 0)),
    "oi_chg": lambda r: _n(r["oi_chg"]), "turnover": lambda r: _n(r["turnover"]),
    "notional": lambda r: _n(r["notional"]), "x": lambda r: _n(r["x"]), "ltp_pct": lambda r: _n(r["ltp_pct"]),
    "ltp": lambda r: r["ltp"], "oi": lambda r: _n(r["oi"]), "prev_oi": lambda r: _n(r["prev_oi"]),
    "dist": lambda r: r["dist"], "strike": lambda r: r["strike"], "expiry": lambda r: r["expiry"],
    "type": lambda r: r["type"], "tf": lambda r: r["tf"], "ts": lambda r: r.get("ts", 0),
    "slot": lambda r: r.get("slot", ""), "alert_ts": lambda r: r.get("alert_ts", 0),
    "stock": lambda r: (r["sym"], r["strike"], r["type"], r.get("ts", 0)),
}


def sort_rows(rows, key, order="desc"):
    return sorted(rows, key=SORT_KEYS.get(key, SORT_KEYS["oi_pct"]), reverse=(order != "asc"))
