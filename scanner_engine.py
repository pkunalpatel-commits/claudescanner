"""Orchestrates auth, instrument master, ATM selection, subscriptions, snapshots, scanning and alerts."""
import threading, time
from datetime import datetime
import settings as S
from alert_engine import AlertEngine
from atm_strike_manager import select_strikes
from dhan_auth import DhanClient
from dhan_market_feed import MarketFeed
from expiry_manager import pick_expiries
from instrument_master import InstrumentMaster
from oi_calculation_engine import build_row, is_cross
from subscription_manager import SubscriptionManager
from timeframe_engine import Calendar, SeriesStore, baseline, IST


class Scanner:
    def __init__(self, st, db, log):
        self.st, self.db, self.log = st, db, log
        self.cal = Calendar(st["holidays"]); self.client = DhanClient(st)
        self.im = InstrumentMaster(db, log); self.store = SeriesStore(db, st["retention_days"])
        self.feed = MarketFeed(self._on_tick); self.subs = SubscriptionManager(self.feed)
        self.alerts = AlertEngine(st, db, log)
        self.state, self.under, self.contracts = {}, {}, {}
        self.table, self.mtf, self.armed = {}, [], {}
        self.msg = "Starting"; self.ready = False; self.need_auth = True; self.running = False
        self.loading = False; self.alert_after = 0; self.profile = {}; self.dbq = []; self.last_flush = time.time()

    # ---------- lifecycle ----------
    def start(self):
        self.running = True
        threading.Thread(target=self._load_im, daemon=True).start()
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self.running = False; self.feed.stop_all(); self._flush()

    def reconfigure(self, reauth=False):
        self.cal = Calendar(self.st["holidays"]); self.store.days = self.st["retention_days"]
        if reauth: self.need_auth = True

    def _load_im(self):
        self.loading = True; self.msg = "Loading instrument master..."
        try: self.im.refresh(); self.msg = "Instruments: %d stocks" % len(self.im.by)
        except Exception as e: self.log.exception("IM"); self.msg = "Instrument master error: %s" % e
        self.loading = False

    def _connect(self):
        try:
            self.profile = self.client.validate()
            self.feed.configure(self.st["client_id"], self.st["access_token"]); self.subs.reset()
            self.need_auth = False; self.alert_after = time.time() + 60
            self.msg = "Connected. Data plan: %s" % self.profile.get("dataPlan", "?")
        except Exception as e:
            self.msg = str(e); self.log.warning("auth: %s", e); time.sleep(10)

    def _loop(self):
        lm = ls = 0
        while self.running:
            try:
                if self.need_auth: self._connect()
                if not self.loading and time.time() - self.im.loaded_at > 6 * 3600:
                    threading.Thread(target=self._load_im, daemon=True).start()
                self.ready = (not self.need_auth) and bool(self.im.by)
                now = time.time()
                if self.ready:
                    if now - lm >= 5: self._manage(); lm = now
                    if now - ls >= 5: self._sample(); ls = now
                    self._scan()
            except Exception: self.log.exception("loop")
            time.sleep(2)

    # ---------- feed ----------
    def _on_tick(self, seg, sid, d):
        now = time.time()
        if seg == "NSE_EQ":
            if "ltp" in d: self.under[sid] = (d["ltp"], now)
            return
        s = self.state.setdefault(sid, {}); s.update(d)
        if "ltp" in d: s["ts"] = now

    def _symbols(self):
        st = self.st
        return self.im.symbols() if st["all_stocks"] else [s for s in st["stocks"] if s in self.im.by]

    def _manage(self):
        st, now = self.st, datetime.now(IST); syms = self._symbols()
        miss = [self.im.uid(s) for s in syms if self.im.uid(s) not in self.under]
        if miss:
            try:
                for k, v in self.client.ltp_map("NSE_EQ", miss).items(): self.under[k] = (v, time.time())
            except Exception as e: self.log.warning("underlying snapshot: %s", e); self.msg = str(e)
        desired, meta = set(), {}
        for s in syms:
            uid = self.im.uid(s); p = self.under.get(uid)
            if not p: continue
            desired.add(("NSE_EQ", uid))
            for e in pick_expiries(self.im, s, st["expiry_slots"], now):
                ch = self.im.chain(s, e); sel = select_strikes(ch["strikes"], p[0], st["n_ce"], st["n_pe"])
                for ot in ("CE", "PE"):
                    for k, dist in sel[ot]:
                        sid = ch[ot].get(k)
                        if sid:
                            meta[sid] = dict(secid=sid, sym=s, expiry=e, strike=k, type=ot, dist=dist,
                                             dist_val=k - sel["atm"], lot=ch["lot"], atm=sel["atm"])
                            desired.add(("NSE_FNO", sid))
        self.contracts = meta
        for sid in meta: self.store.ensure(sid)
        self.store.prune(set(meta)); self.subs.sync(desired)

    def _sample(self):
        now = time.time(); dt = datetime.now(IST)
        if not (self.cal.is_td(dt.date()) and self.cal.o(dt.date()) <= dt <= self.cal.c(dt.date()).replace(minute=31)): return
        every = int(self.st["db_interval"])
        for sid in list(self.contracts):
            c = self.state.get(sid); ser = self.store.get(sid)
            if ser is None or not c or c.get("oi") is None or c.get("ltp") is None: continue
            atp, vol = c.get("atp") or 0, c.get("vol") or 0
            if ser.add(now, c["ltp"], c["oi"], vol, atp, every):
                self.dbq.append((int(now), sid, c["ltp"], c["oi"], vol, atp, atp * vol))
        if now - self.last_flush >= every: self._flush()

    def _flush(self):
        q, self.dbq = self.dbq, []; self.last_flush = time.time()
        try: self.db.add_snapshots(q); self.db.purge(self.st["retention_days"])
        except Exception: self.log.exception("flush")

    # ---------- scan ----------
    def _scan(self):
        st = self.st; now = time.time(); dt = datetime.now(IST); insess = self.cal.in_session(dt)
        tfs = [t for t in S.TF_NAMES if t in st["timeframes"]]
        table = {t: {} for t in tfs}
        for sid, meta in list(self.contracts.items()):
            cur = self.state.get(sid)
            if not cur or cur.get("oi") is None or cur.get("ltp") is None: continue
            ser = self.store.get(sid); fp = {"prev_oi": cur.get("prev_oi"), "prev_close": cur.get("prev_close")}
            stale = insess and now - cur.get("ts", 0) > st["stale_secs"]
            for tf in tfs:
                r = build_row(meta, cur, baseline(ser, tf, dt, self.cal, fp), tf)
                th = float(st["thresholds"].get(tf, 10)); r["th"] = th; r["stale"] = stale; r["ts"] = cur.get("ts", now)
                r["cross"] = is_cross(r, th, st["direction"], float(st["min_abs_oi"]))
                table[tf][sid] = r
        self.table = table; self._mtf(tfs); self._alert(table, now)

    def _mtf(self, tfs):
        mt = {}
        for tf in tfs:
            for sid, r in self.table[tf].items():
                mt.setdefault(sid, {"meta": self.contracts.get(sid, r), "cells": {}})["cells"][tf] = (r["oi_pct"], r["cross"])
        out = [e for e in mt.values() if any(c for _, c in e["cells"].values())]
        out.sort(key=lambda e: -max(abs(p) for p, c in e["cells"].values() if c and p is not None))
        self.mtf = out

    def _alert(self, table, now):
        if not self.st["alerts_on"]: return
        fired = 0
        for tf, rows in table.items():
            for sid, r in rows.items():
                k = (sid, tf)
                if r["cross"]:
                    sign = 1 if r["oi_chg"] > 0 else -1
                    if self.armed.get(k) != sign:          # duplicate prevention: once per crossing
                        self.armed[k] = sign
                        if now >= self.alert_after: self.alerts.fire(r, loud=fired < 3); fired += 1
                elif k in self.armed and (r["oi_pct"] is None or abs(r["oi_pct"]) < 0.8 * r["th"]):
                    del self.armed[k]

    # ---------- queries for UI ----------
    def query(self, tf, sort, side, text, only, limit):
        keys = {"oi_pct": lambda r: r["oi_pct"], "oi_pos": lambda r: r["oi_chg"], "oi_neg": lambda r: -r["oi_chg"],
                "turnover": lambda r: r["turnover"] or -1, "notional": lambda r: r["x"],
                "ltp_pct": lambda r: r["ltp_pct"] if r["ltp_pct"] is not None else -1e9}
        txt = [t.strip().upper() for t in text.split(",") if t.strip()]
        rows = [r for r in self.table.get(tf, {}).values() if r["oi_pct"] is not None
                and (side == "ALL" or r["type"] == side) and (not only or r["cross"])
                and (not txt or any(r["sym"].startswith(t) for t in txt))]
        rows.sort(key=keys.get(sort, keys["oi_pct"]), reverse=True)
        return rows[:limit]

    def status_text(self):
        dt = datetime.now(IST); mk = "OPEN" if self.cal.in_session(dt) else "CLOSED"
        stale = sum(1 for t in list(self.table.values())[:1] for r in t.values() if r["stale"])
        return "%s | %s | contracts %d | subs %d | mkt %s | stale %d" % (
            self.msg, self.feed.state(), len(self.contracts), len(self.subs.cur), mk, stale)
