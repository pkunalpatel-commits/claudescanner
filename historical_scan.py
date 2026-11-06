"""Historical scan from Dhan intraday (1-minute, with OI) history.
Modes: Peak (best window in range), Date-wise (best per date), Time-wise (best per time slot of the session).
Filters: date range, time-of-day window, LTP % greater/less than. Baselines use the live scanner's trading-time rules."""
import bisect
from datetime import datetime
from oi_calculation_engine import pct, is_cross, price_ok
from settings import TF_SECS
from timeframe_engine import IST

F = "%Y-%m-%d %H:%M:%S"
OPEN_SEC = 9 * 3600 + 15 * 60


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


def scan_contract(meta, bars, cal, tf, start, end, th, direction, min_abs, opt):
    """Returns a list of result rows (1 for Peak, 1 per date for Date-wise, 1 per slot for Time-wise)."""
    ts, ltp, oi, cum = bars; secs = TF_SECS[tf]; cands = []
    tfrom, tto, mode, slot = opt["tfrom"], opt["tto"], opt["mode"], opt["slot"]
    gt, lt = opt.get("gt"), opt.get("lt")

    def add(i, j):
        p = pct(oi[i], oi[j])
        if p is not None and price_ok(pct(ltp[i], ltp[j]), gt, lt): cands.append((i, j, p))

    if tf == "1D":                                           # end-of-day OI vs previous trading day's end-of-day OI
        days = sorted({datetime.fromtimestamp(t - 1, IST).date() for t in ts})
        eod = lambda d: bisect.bisect_right(ts, cal.c(d).timestamp() + 1) - 1
        for d in days:
            if d < start or d > end: continue
            i, j = eod(d), eod(cal.prev_td(d))
            if j >= 0 and i > j and datetime.fromtimestamp(ts[j] - 1, IST).date() == cal.prev_td(d): add(i, j)
    else:
        lo = bisect.bisect_left(ts, cal.o(start).timestamp()); hi = bisect.bisect_right(ts, cal.c(end).timestamp() + 61)
        for i in range(lo, hi):
            dt = datetime.fromtimestamp(ts[i], IST)
            if not (tfrom <= dt.time() <= tto): continue       # time-of-day window
            target = cal.shift_back(dt, secs).timestamp()
            j = bisect.bisect_right(ts, target) - 1
            if j >= 0 and target - ts[j] <= 120 and j < i: add(i, j)

    groups = {}
    for i, j, p in cands:
        dt = datetime.fromtimestamp(ts[i] - 1, IST)
        if mode == "Date-wise": k = dt.date().isoformat()
        elif mode == "Time-wise" and tf != "1D": k = int((dt.hour * 3600 + dt.minute * 60 - OPEN_SEC) // slot)
        else: k = 0
        key = p if direction == "pos" else (-p if direction == "neg" else abs(p))
        if k not in groups or key > groups[k][0]: groups[k] = (key, i, j, p)
    out = []
    for k in sorted(groups, key=str):
        _, i, j, p = groups[k]; chg = oi[i] - oi[j]; r = dict(meta)
        label = "-"
        if mode == "Time-wise" and tf != "1D":
            a = OPEN_SEC + k * slot; b = min(a + slot, 15 * 3600 + 30 * 60); label = "%02d:%02d-%02d:%02d" % (a // 3600, a % 3600 // 60, b // 3600, b % 3600 // 60)
        r.update(tf=tf, ltp=ltp[i], prev_ltp=ltp[j], ltp_chg=ltp[i] - ltp[j], ltp_pct=pct(ltp[i], ltp[j]), oi=oi[i], prev_oi=oi[j],
                 oi_chg=chg, oi_pct=p, x=ltp[i] * chg, notional=ltp[i] * chg * meta.get("lot", 1), turnover=cum[i] - cum[j],
                 turnover_kind="est", ts=ts[i], stale=False, th=th, slot=label)
        r["cross"] = is_cross(r, th, direction, min_abs); out.append(r)
    return out
