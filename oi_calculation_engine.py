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
