"""SQLite storage: instruments, timestamped snapshots (LTP/OI/volume/turnover est.), alerts."""
import json, os, sqlite3, threading, time

SCHEMA = """
CREATE TABLE IF NOT EXISTS instruments(secid TEXT PRIMARY KEY, symbol TEXT, under_id TEXT,
  expiry TEXT, strike REAL, otype TEXT, lot INTEGER);
CREATE INDEX IF NOT EXISTS ix_inst ON instruments(symbol, expiry);
CREATE TABLE IF NOT EXISTS snapshots(ts INTEGER, secid TEXT, ltp REAL, oi INTEGER, vol INTEGER,
  atp REAL, turnover REAL);
CREATE INDEX IF NOT EXISTS ix_snap ON snapshots(secid, ts);
CREATE INDEX IF NOT EXISTS ix_snap_ts ON snapshots(ts);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS alerts(ts REAL, data TEXT);
"""


class Database:
    def __init__(self, folder):
        os.makedirs(folder, exist_ok=True)
        self.con = sqlite3.connect(os.path.join(folder, "oi_scanner.db"), check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock:
            self.con.execute("PRAGMA journal_mode=WAL")
            self.con.execute("PRAGMA synchronous=NORMAL")
            self.con.executescript(SCHEMA)

    def q(self, sql, args=(), many=False):
        with self.lock:
            cur = self.con.executemany(sql, args) if many else self.con.execute(sql, args)
            rows = cur.fetchall(); self.con.commit(); return rows

    def replace_instruments(self, rows):
        with self.lock:
            self.con.execute("DELETE FROM instruments")
            self.con.executemany("INSERT OR REPLACE INTO instruments VALUES (?,?,?,?,?,?,?)", rows)
            self.con.commit()

    def instruments(self):
        return self.q("SELECT secid,symbol,under_id,expiry,strike,otype,lot FROM instruments")

    def meta(self, k, default=None):
        r = self.q("SELECT v FROM meta WHERE k=?", (k,)); return r[0][0] if r else default

    def set_meta(self, k, v): self.q("INSERT OR REPLACE INTO meta VALUES (?,?)", (k, str(v)))

    def add_snapshots(self, rows):
        if rows: self.q("INSERT INTO snapshots VALUES (?,?,?,?,?,?,?)", rows, many=True)

    def load_series(self, secid, since):
        return self.q("SELECT ts,ltp,oi,vol,atp FROM snapshots WHERE secid=? AND ts>=? ORDER BY ts",
                      (secid, int(since)))

    def purge(self, days): self.q("DELETE FROM snapshots WHERE ts<?", (int(time.time() - days * 86400),))

    def add_alert(self, rec): self.q("INSERT INTO alerts VALUES (?,?)", (rec.get("alert_ts", time.time()), json.dumps(rec)))

    def recent_alerts(self, n=300):
        return [json.loads(r[0]) for r in self.q("SELECT data FROM alerts ORDER BY ts DESC LIMIT ?", (n,))]
