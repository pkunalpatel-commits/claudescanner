"""Dhan Live Market Feed v2 (binary WebSocket). Auto-reconnect, <=100 instruments per message,
<=5000 instruments per connection, up to 5 connections."""
import json, logging, ssl, struct, threading, time
import websocket

log = logging.getLogger("oi")
SEG = {0: "IDX_I", 1: "NSE_EQ", 2: "NSE_FNO", 3: "NSE_CURRENCY", 4: "BSE_EQ", 5: "MCX_COMM", 7: "BSE_CURRENCY", 8: "BSE_FNO"}
DISCONNECT = {805: "too many connections", 806: "Data API not subscribed", 807: "token expired",
              808: "authentication failed", 809: "invalid token"}
try:
    import certifi
    SSLOPT = {"cert_reqs": ssl.CERT_REQUIRED, "ca_certs": certifi.where()}
except Exception:
    SSLOPT = {}


def parse(b):
    """Returns (segment, security_id, code, fields) or None."""
    if len(b) < 8: return None
    code, _, seg, sid = struct.unpack_from("<BHBI", b, 0)
    u = lambda f, o: struct.unpack_from("<" + f, b, o)[0]
    d = {}
    if code == 2 and len(b) >= 12: d["ltp"] = u("f", 8)
    elif code == 4 and len(b) >= 26: d.update(ltp=u("f", 8), atp=u("f", 18), vol=u("I", 22))
    elif code == 8 and len(b) >= 38: d.update(ltp=u("f", 8), atp=u("f", 18), vol=u("I", 22), oi=u("I", 34))
    elif code == 5 and len(b) >= 12: d["oi"] = u("I", 8)
    elif code == 6 and len(b) >= 16: d.update(prev_close=u("f", 8), prev_oi=u("I", 12))
    elif code == 50 and len(b) >= 10: d["reason"] = u("h", 8)
    return SEG.get(seg, str(seg)), str(sid), code, d


def _mode(seg, sub): return (21 if sub else 22) if seg == "NSE_FNO" else (15 if sub else 16)


class _Conn(threading.Thread):
    def __init__(self, feed):
        super().__init__(daemon=True)
        self.feed = feed; self.items = set(); self.ws = None; self.up = False; self.halt = False

    def run(self):
        delay = 2
        while not self.halt:
            f = self.feed
            url = "wss://api-feed.dhan.co?version=2&token=%s&clientId=%s&authType=2" % (f.token, f.cid)
            self.ws = websocket.WebSocketApp(url, on_open=self._open, on_message=self._msg,
                                             on_error=lambda w, e: log.warning("WS error: %s", e),
                                             on_close=self._close)
            t0 = time.time()
            try: self.ws.run_forever(ping_interval=20, ping_timeout=10, sslopt=SSLOPT)
            except Exception: log.exception("WS crashed")
            self.up = False
            if self.halt: break
            delay = 2 if time.time() - t0 > 60 else min(delay * 2, 60)
            time.sleep(delay)

    def stop(self):
        self.halt = True
        try: self.ws.close()
        except Exception: pass

    def _open(self, ws):
        self.up = True; log.info("WS connected (%d instruments)", len(self.items))
        self.push(list(self.items), True)

    def _close(self, ws, *a): self.up = False

    def _msg(self, ws, msg):
        if not isinstance(msg, (bytes, bytearray)): return
        try: p = parse(bytes(msg))
        except Exception: return
        if not p: return
        seg, sid, code, d = p
        if code == 50:
            log.error("Feed disconnect: %s", DISCONNECT.get(d.get("reason"), d.get("reason")))
            self.feed.last_error = DISCONNECT.get(d.get("reason"), str(d.get("reason")))
        elif d: self.feed.on_tick(seg, sid, d)

    def push(self, items, sub):
        if not self.up or not items: return
        groups = {}
        for seg, sid in items: groups.setdefault(_mode(seg, sub), []).append((seg, sid))
        for mode, lst in groups.items():
            for i in range(0, len(lst), 100):
                ch = lst[i:i + 100]
                msg = {"RequestCode": mode, "InstrumentCount": len(ch),
                       "InstrumentList": [{"ExchangeSegment": s, "SecurityId": x} for s, x in ch]}
                try: self.ws.send(json.dumps(msg))
                except Exception: log.warning("WS send failed"); return
                time.sleep(0.03)


class MarketFeed:
    CAP = 4900; MAXC = 5

    def __init__(self, on_tick):
        self.on_tick = on_tick; self.conns = []; self.cid = ""; self.token = ""; self.last_error = ""

    def configure(self, cid, token):
        self.stop_all(); self.cid = cid.strip(); self.token = token.strip(); self.last_error = ""

    def stop_all(self):
        for c in self.conns: c.stop()
        self.conns = []

    def subscribe(self, items):
        per = {}
        for it in items:
            if any(it in c.items for c in self.conns): continue          # no duplicate subscriptions
            c = next((c for c in self.conns if len(c.items) < self.CAP), None)
            if c is None:
                if len(self.conns) >= self.MAXC: log.warning("Feed capacity reached; dropping %s", it); continue
                c = _Conn(self); self.conns.append(c); c.start()
            c.items.add(it); per.setdefault(c, []).append(it)
        for c, lst in per.items(): c.push(lst, True)

    def unsubscribe(self, items):
        for c in self.conns:
            gone = [i for i in items if i in c.items]
            c.items.difference_update(gone); c.push(gone, False)

    def state(self):
        if not self.conns: return "feed idle"
        up = sum(1 for c in self.conns if c.up)
        return "feed %d/%d up" % (up, len(self.conns)) + (" ERR:" + self.last_error if self.last_error else "")
