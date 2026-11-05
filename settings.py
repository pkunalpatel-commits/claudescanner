"""Persistent user settings (JSON). All thresholds/filters are configurable defaults, not fixed rules."""
import copy, json, os, threading

DEFAULT_TF = [("1m", 60, 5), ("2m", 120, 5), ("3m", 180, 7), ("5m", 300, 10), ("10m", 600, 10),
              ("15m", 900, 12), ("30m", 1800, 15), ("1H", 3600, 15), ("2H", 7200, 18),
              ("3H", 10800, 18), ("4H", 14400, 20), ("1D", None, 25)]
TF_NAMES = [t[0] for t in DEFAULT_TF]
TF_SECS = {t[0]: t[1] for t in DEFAULT_TF}

DEFAULTS = {
    "client_id": "", "access_token": "",
    "stocks": [], "all_stocks": False,
    "expiry_slots": [0],              # 0=current, 1=next, 2=third ...
    "n_ce": 3, "n_pe": 3,             # ATM +/- N, independent CE / PE
    "timeframes": ["5m", "15m", "1D"],
    "thresholds": {n: t for n, _, t in DEFAULT_TF},
    "direction": "both",              # both | pos | neg
    "min_abs_oi": 0,
    "show_tf": "5m", "sort": "oi_pct", "side": "ALL", "text": "", "only_crossing": True,
    "retention_days": 5, "db_interval": 60, "stale_secs": 60, "max_rows": 120,
    "auto_backfill": True,
    "alerts_on": True, "sound_on": True, "notify_on": True,
    "holidays": [],                   # YYYY-MM-DD, NSE trading holidays (user maintained)
    "presets": {},
}
PRESET_KEYS = ["expiry_slots", "n_ce", "n_pe", "timeframes", "thresholds", "direction",
               "min_abs_oi", "side", "only_crossing"]


class Settings:
    def __init__(self, folder):
        os.makedirs(folder, exist_ok=True)
        self.path = os.path.join(folder, "settings.json")
        self.lock = threading.RLock()
        self.d = copy.deepcopy(DEFAULTS)
        try:
            with open(self.path) as f:
                saved = json.load(f)
            th = dict(self.d["thresholds"]); th.update(saved.get("thresholds", {}))
            self.d.update(saved); self.d["thresholds"] = th
        except Exception:
            pass

    def __getitem__(self, k): return self.d[k]
    def __setitem__(self, k, v): self.d[k] = v
    def get(self, k, default=None): return self.d.get(k, default)

    def save(self):
        with self.lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.d, f, indent=1)
            os.replace(tmp, self.path)

    def save_preset(self, name):
        self.d["presets"][name] = copy.deepcopy({k: self.d[k] for k in PRESET_KEYS}); self.save()

    def load_preset(self, name):
        p = self.d["presets"].get(name)
        if p: self.d.update(copy.deepcopy(p)); self.save()

    def reset_filters(self):
        self.d.update(direction="both", min_abs_oi=0, side="ALL", text="", only_crossing=True); self.save()
