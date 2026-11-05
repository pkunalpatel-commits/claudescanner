"""Historical scan: peak OI gain/loss per contract for any past date range and timeframe, computed from
Dhan intraday (1-minute, with OI) history. Baselines use the same trading-time rules as the live scanner."""
import bisect
from datetime import datetime
from oi_calculation_engine import pct, is_cross
from settings import TF_SECS
from timeframe_engine import IST

F = "%Y-%m-%d %H:%M:%S"


def load_bars(client, sid, frm, to):
    """Returns (ts, ltp, oi, cum_turnover_est) lists at bar-close times, or None if no data."""
    j = client.intraday(sid, frm.strftime(F), to.strftime(F))
    ts, cl, vol, oi = j.get("timestamp") or [], j.get("close") or [], j.get("volume") or [], j.get("open_interest") or []
    if not ts or len(oi) != len(ts): return None
    T, P, O, C, cum = [], [], [], [], 0.0
    for k in range(len(ts)):
        t0 = float(ts[k])
        if t0 < 1.2e9: t0 += 315513000                      # legacy 1980-based IST epoch
        cum += float(cl[k]) * float(vol[k] or 0)
        T.append(t0 + 60); P.append(float(cl[k])); O.append(float(oi[k] or 0)); C.append(cum)
    return T, P, O, C


def scan_contract(meta, bars, cal, tf, start, end, th, direction, min_abs):
    ts, ltp, oi, cum = bars; secs = TF_SECS[tf]; cands = []
    if tf == "1D":                                           # end-of-day OI vs previous trading day's end-of-day OI
        days = sorted({datetime.fromtimestamp(t - 1, IST).date() for t in ts})
        eod = lambda d: bisect.bisect_right(ts, cal.c(d).timestamp() + 1) - 1
        for d in days:
            if d < start or d > end: continue
            i, j = eod(d), eod(cal.prev_td(d))
            if j >= 0 and i > j and datetime.fromtimestamp(ts[j] - 1, IST).date() == cal.prev_td(d): cands.append((i, j))
    else:
        lo = bisect.bisect_left(ts, cal.o(start).timestamp()); hi = bisect.bisect_right(ts, cal.c(end).timestamp() + 61)
        for i in range(lo, hi):
            target = cal.shift_back(datetime.fromtimestamp(ts[i], IST), secs).timestamp()
            j = bisect.bisect_right(ts, target) - 1
            if j >= 0 and target - ts[j] <= 120 and j < i: cands.append((i, j))
    best = None
    for i, j in cands:
        p = pct(oi[i], oi[j])
        if p is None: continue
        key = p if direction == "pos" else (-p if direction == "neg" else abs(p))
        if best is None or key > best[0]: best = (key, i, j, p)
    if not best: return None
    _, i, j, p = best
    r = dict(meta); chg = oi[i] - oi[j]
    r.update(tf=tf, ltp=ltp[i], prev_ltp=ltp[j], ltp_chg=ltp[i] - ltp[j], ltp_pct=pct(ltp[i], ltp[j]), oi=oi[i], prev_oi=oi[j],
             oi_chg=chg, oi_pct=p, x=ltp[i] * chg, notional=ltp[i] * chg * meta.get("lot", 1), turnover=cum[i] - cum[j],
             turnover_kind="est", ts=ts[i], stale=False, th=th)
    r["cross"] = is_cross(r, th, direction, min_abs)
    return r
