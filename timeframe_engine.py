"""Trading calendar (NSE 09:15-15:30 IST) + timestamped snapshot series + per-timeframe baselines."""
import bisect, time
from array import array
from datetime import datetime, timedelta, time as dtime, timezone
from settings import TF_SECS

IST = timezone(timedelta(hours=5, minutes=30))
OPEN, CLOSE = dtime(9, 15), dtime(15, 30)


class Calendar:
    def __init__(self, holidays=()): self.h = set(holidays)
    def is_td(self, d): return d.weekday() < 5 and d.isoformat() not in self.h
    def prev_td(self, d):
        d -= timedelta(days=1)
        while not self.is_td(d): d -= timedelta(days=1)
        return d
    def o(self, d): return datetime.combine(d, OPEN, tzinfo=IST)
    def c(self, d): return datetime.combine(d, CLOSE, tzinfo=IST)
    def in_session(self, now):
        d = now.date(); return self.is_td(d) and self.o(d) <= now <= self.c(d)
    def effective(self, now):
        d = now.date()
        if self.is_td(d):
            if now >= self.c(d): return self.c(d)
            if now >= self.o(d): return now
            return self.c(self.prev_td(d))
        while not self.is_td(d): d -= timedelta(days=1)
        return self.c(d)
    def session_date(self, now): return self.effective(now).date()
    def shift_back(self, now, secs):
        """Go back `secs` of *trading* time (skips nights, weekends, holidays)."""
        p = self.effective(now); rem = secs
        for _ in range(30):
            avail = (p - self.o(p.date())).total_seconds()
            if rem <= avail: return p - timedelta(seconds=rem)
            rem -= avail; p = self.c(self.prev_td(p.date()))
        return p


class Series:
    """fine: ~5s snapshots for last ~25 min. coarse: ~60s snapshots kept for the retention window."""
    def __init__(self):
        self.ft, self.fr = [], []
        self.ct, self.cl, self.co, self.cv, self.ca = (array("d") for _ in range(5))

    def _coarse(self, ts, ltp, oi, vol, atp):
        self.ct.append(ts); self.cl.append(ltp); self.co.append(oi); self.cv.append(vol); self.ca.append(atp)

    def add(self, ts, ltp, oi, vol, atp, every):
        self.ft.append(ts); self.fr.append((ts, ltp, oi, vol, atp))
        if len(self.ft) > 400:
            k = bisect.bisect_left(self.ft, ts - 1500); del self.ft[:k]; del self.fr[:k]
        if not self.ct or ts - self.ct[-1] >= every - 1:
            self._coarse(ts, ltp, oi, vol, atp); return True
        return False

    def load(self, rows):
        for ts, ltp, oi, vol, atp in rows: self._coarse(ts, ltp or 0, oi or 0, vol or 0, atp or 0)

    def _rec(self, i): return (self.ct[i], self.cl[i], self.co[i], self.cv[i], self.ca[i])

    def at(self, t, tol=150):
        if self.ft and t >= self.ft[0]: rec = self.fr[bisect.bisect_right(self.ft, t) - 1]
        else:
            i = bisect.bisect_right(self.ct, t) - 1
            if i < 0: return None
            rec = self._rec(i)
        return rec if t - rec[0] <= tol else None

    def before(self, t):
        i = bisect.bisect_left(self.ct, t) - 1
        return self._rec(i) if i >= 0 else None


class SeriesStore:
    def __init__(self, db, days): self.db = db; self.days = days; self.s = {}
    def ensure(self, secid):
        if secid in self.s: return
        s = Series(); s.load(self.db.load_series(secid, time.time() - (self.days + 1) * 86400)); self.s[secid] = s
    def get(self, secid): return self.s.get(secid)
    def prune(self, keep):
        if len(self.s) > 6000:
            for k in [k for k in self.s if k not in keep]: del self.s[k]


def baseline(ser, tf, now, cal, feed_prev):
    """Baseline snapshot for timeframe `tf`. 1D = previous trading day's closing OI."""
    if tf == "1D":
        poi, pcl = feed_prev.get("prev_oi"), feed_prev.get("prev_close")
        if poi is None and ser is not None:
            d = cal.session_date(now); rec = ser.before(cal.o(d).timestamp())
            if rec and datetime.fromtimestamp(rec[0], IST).date() == cal.prev_td(d):
                poi = rec[2]; pcl = pcl if pcl is not None else rec[1]
        return None if poi is None else {"oi": poi, "ltp": pcl, "atp": None, "vol": None}
    if ser is None: return None
    rec = ser.at(cal.shift_back(now, TF_SECS[tf]).timestamp())
    return None if rec is None else {"ts": rec[0], "ltp": rec[1], "oi": rec[2], "vol": rec[3], "atp": rec[4]}
