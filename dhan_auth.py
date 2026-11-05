"""DhanHQ v2 REST: auth validation, token renewal, Market Quote snapshots (1 req/sec limit)."""
import threading, time
import requests

BASE = "https://api.dhan.co/v2"


class DhanError(Exception):
    pass


class DhanClient:
    def __init__(self, st):
        self.st = st; self._last = 0.0; self._lk = threading.Lock(); self._hlast = 0.0; self._hlk = threading.Lock()

    def headers(self):
        return {"access-token": self.st["access_token"].strip(), "client-id": self.st["client_id"].strip(),
                "Content-Type": "application/json", "Accept": "application/json"}

    def validate(self):
        if not self.st["client_id"].strip() or not self.st["access_token"].strip():
            raise DhanError("Enter Client ID and Access Token in Settings")
        r = requests.get(BASE + "/profile", headers=self.headers(), timeout=15)
        if r.status_code != 200:
            raise DhanError("Auth failed (HTTP %s): %s" % (r.status_code, r.text[:150]))
        return r.json()   # contains tokenValidity, dataPlan, dataValidity ...

    def renew(self):
        """Renew a 24h web-generated token (only works while the token is still valid)."""
        h = {"access-token": self.st["access_token"].strip(), "dhanClientId": self.st["client_id"].strip()}
        r = requests.get(BASE + "/RenewToken", headers=h, timeout=15)
        j = r.json() if r.status_code == 200 else {}
        tok = j.get("accessToken") or j.get("access_token")
        if not tok:
            raise DhanError("Renew failed (HTTP %s): %s" % (r.status_code, r.text[:150]))
        return tok

    def quote(self, payload, endpoint="ltp"):
        """POST /marketfeed/{ltp|ohlc|quote}. payload={"NSE_EQ":[ids],...}. Max 1000 ids, 1 req/s."""
        for attempt in range(3):
            with self._lk:
                wait = 1.1 - (time.time() - self._last)
                if wait > 0: time.sleep(wait)
                self._last = time.time()
                r = requests.post("%s/marketfeed/%s" % (BASE, endpoint), json=payload,
                                  headers=self.headers(), timeout=20)
            if r.status_code == 429: time.sleep(2 * (attempt + 1)); continue
            if r.status_code != 200: raise DhanError("Quote HTTP %s: %s" % (r.status_code, r.text[:150]))
            return r.json().get("data", {})
        raise DhanError("Quote rate-limited")

    def ltp_map(self, segment, ids):
        out = {}
        for i in range(0, len(ids), 1000):
            d = self.quote({segment: [int(x) for x in ids[i:i + 1000]]}, "ltp").get(segment, {})
            for k, v in d.items():
                if v and v.get("last_price") is not None: out[str(k)] = float(v["last_price"])
        return out

    def intraday(self, secid, frm, to, interval="1"):
        """POST /charts/intraday with oi=true for an NSE_FNO stock option. Data API limit ~5 req/s."""
        body = {"securityId": str(secid), "exchangeSegment": "NSE_FNO", "instrument": "OPTSTK",
                "interval": str(interval), "oi": True, "fromDate": frm, "toDate": to}
        for attempt in range(3):
            with self._hlk:
                wait = 0.25 - (time.time() - self._hlast)
                if wait > 0: time.sleep(wait)
                self._hlast = time.time()
                r = requests.post(BASE + "/charts/intraday", json=body, headers=self.headers(), timeout=25)
            if r.status_code == 429: time.sleep(2 * (attempt + 1)); continue
            if r.status_code != 200: raise DhanError("History HTTP %s: %s" % (r.status_code, r.text[:120]))
            return r.json()
        raise DhanError("History rate-limited")
