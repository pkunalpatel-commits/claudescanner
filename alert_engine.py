"""Alerts: history (memory + SQLite), Android notification, beep. Duplicate prevention lives in the scanner."""
import time
from collections import deque

_tone = None


class AlertEngine:
    def __init__(self, st, db, log):
        self.st, self.db, self.log = st, db, log
        self.history = deque(db.recent_alerts(300), maxlen=500)

    def fire(self, r, loud=True):
        rec = dict(r); rec["alert_ts"] = time.time()
        self.history.appendleft(rec)
        try: self.db.add_alert(rec)
        except Exception: self.log.exception("alert db")
        if loud and self.st["notify_on"]: self._notify(rec)
        if loud and self.st["sound_on"]: self._beep()

    def clear(self): self.history.clear(); self.db.q("DELETE FROM alerts")

    def _notify(self, r):
        try:
            from plyer import notification
            notification.notify(title="%s %d%s %s" % (r["sym"], r["strike"], r["type"], r["tf"]),
                                message="OI %+.1f%% (%+d)  LTP %.2f" % (r["oi_pct"], r["oi_chg"], r["ltp"]), timeout=8)
        except Exception: pass

    def _beep(self):
        global _tone
        try:
            from jnius import autoclass
            if _tone is None:
                TG, AM = autoclass("android.media.ToneGenerator"), autoclass("android.media.AudioManager")
                _tone = TG(AM.STREAM_NOTIFICATION, 100)
            _tone.startTone(24, 300)   # TONE_PROP_BEEP
        except Exception: pass
