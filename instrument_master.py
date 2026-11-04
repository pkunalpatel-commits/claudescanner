"""Downloads Dhan's detailed instrument master and builds NSE stock-option chains. Nothing hardcoded."""
import csv, datetime, time
import requests

URL = "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"


def _date(s):
    s = (s or "").strip()[:10]
    for f in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try: return datetime.datetime.strptime(s, f).date().isoformat()
        except ValueError: pass
    return None


class InstrumentMaster:
    def __init__(self, db, log=None):
        self.db = db; self.log = log; self.by = {}; self.loaded_at = 0

    def refresh(self, force=False):
        n = self.db.q("SELECT COUNT(*) FROM instruments")[0][0]
        age = time.time() - float(self.db.meta("im_ts", 0))
        if force or n == 0 or age > 20 * 3600:
            try: self._download()
            except Exception:
                if n == 0: raise
                if self.log: self.log.exception("Instrument master download failed; using cached copy")
        self.load()

    def _download(self):
        r = requests.get(URL, stream=True, timeout=90); r.raise_for_status(); r.encoding = "utf-8"
        rows = []
        for x in csv.DictReader(r.iter_lines(decode_unicode=True)):
            if x.get("EXCH_ID") != "NSE" or x.get("INSTRUMENT") != "OPTSTK": continue
            ot = (x.get("OPTION_TYPE") or "").strip()
            exp = _date(x.get("SM_EXPIRY_DATE"))
            sym = (x.get("UNDERLYING_SYMBOL") or "").strip()
            if ot not in ("CE", "PE") or not exp or not sym: continue
            rows.append((x["SECURITY_ID"].strip(), sym, x["UNDERLYING_SECURITY_ID"].split(".")[0].strip(), exp,
                         float(x["STRIKE_PRICE"]), ot, int(float(x.get("LOT_SIZE") or 0))))
        if not rows: raise RuntimeError("No NSE OPTSTK rows found; instrument master format may have changed")
        self.db.replace_instruments(rows); self.db.set_meta("im_ts", time.time())
        if self.log: self.log.info("Instrument master: %d stock option contracts", len(rows))

    def load(self):
        by = {}
        for secid, sym, uid, exp, strike, ot, lot in self.db.instruments():
            s = by.setdefault(sym, {"uid": uid, "lot": lot, "exp": {}})
            e = s["exp"].setdefault(exp, {"strikes": set(), "CE": {}, "PE": {}, "lot": lot})
            e["strikes"].add(strike); e[ot][strike] = secid
        for s in by.values():
            for e in s["exp"].values(): e["strikes"] = sorted(e["strikes"])
        self.by = by; self.loaded_at = time.time()

    def symbols(self): return sorted(self.by)
    def uid(self, sym): return self.by[sym]["uid"]
    def expiries(self, sym): return sorted(self.by[sym]["exp"])
    def chain(self, sym, exp): return self.by[sym]["exp"][exp]
