"""Kivy UI: Scanner, Multi-TF, Alerts, Settings."""
import datetime, os, threading
import kivy
from kivy.clock import Clock
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen, ScreenManager
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.stencilview import StencilView
from kivy.uix.textinput import TextInput
from kivy.uix.togglebutton import ToggleButton
import settings as S
from oi_calculation_engine import price_ok, sort_rows
from timeframe_engine import IST

MONO = os.path.join(kivy.kivy_data_dir, "fonts", "RobotoMono-Regular.ttf")
if not os.path.exists(MONO): MONO = "Roboto"
GREEN, RED, GREY, YEL, WHITE = "69f0ae", "ff5252", "90a4ae", "ffd740", "ffffff"
SORTS = {"OI Gain %": "oi_pct", "|OI %| abs": "abs_oi", "OI Change": "oi_chg", "Turnover": "turnover", "LTPxChgOI": "notional",
         "LTP %": "ltp_pct", "ATM Dist": "dist", "Strike": "strike", "Stock A-Z": "stock", "LTP": "ltp", "Cur OI": "oi",
         "Prev OI": "prev_oi", "LTPxChg": "x", "Expiry": "expiry", "Call/Put": "type", "Timeframe": "tf", "Updated": "ts", "Slot": "slot"}
# column heading -> sort key (double-tap a heading to sort; double-tap again to flip Asc/Desc)
COL_KEYS = {"Stock": "stock", "Expiry": "expiry", "Strike": "strike", "T": "type", "ATM": "dist", "LTP": "ltp", "LTP%": "ltp_pct",
            "Turn~": "turnover", "CurOI": "oi", "PrevOI": "prev_oi", "ChgOI": "oi_chg", "OI%": "oi_pct", "LTPxChg": "x",
            "Notional": "notional", "TF": "tf", "Upd": "ts", "Slot": "slot", "When": "ts", "Alert@": "alert_ts"}
TEXT_KEYS = {"stock", "expiry", "type", "tf", "slot"}
INV = {v: k for k, v in SORTS.items()}


def fnum(t):
    try: return float(str(t).strip()) if str(t).strip() else None
    except ValueError: return None


def order_button(st):
    b = ToggleButton(text="Asc" if st["order"] == "asc" else "Desc", state="down" if st["order"] == "asc" else "normal", size_hint_x=.6)
    def on(i, v): st["order"] = "asc" if v == "down" else "desc"; i.text = "Asc" if v == "down" else "Desc"
    b.bind(state=on); return b


def sync_order(b, st):
    want = "down" if st["order"] == "asc" else "normal"
    if b.state != want: b.state = want


def tinput(text="", hint="", **k): return TextInput(text=text, hint_text=hint, multiline=False, write_tab=False, **k)


def num(x):
    if x is None: return "-"
    a, s = abs(x), "-" if x < 0 else ""
    if a >= 1e7: return "%s%.2fCr" % (s, a / 1e7)
    if a >= 1e5: return "%s%.2fL" % (s, a / 1e5)
    if a >= 1e3: return "%s%.1fK" % (s, a / 1e3)
    return "%s%.0f" % (s, a)


def p(x): return "-" if x is None else "%+.1f%%" % x
def exp(e): return datetime.date.fromisoformat(e).strftime("%d%b%y").upper()
def hhmm(ts): return datetime.datetime.fromtimestamp(ts, IST).strftime("%H:%M:%S")

COLS = [("Stock", 10, "<"), ("Expiry", 8, "<"), ("Strike", 8, ">"), ("T", 2, "<"), ("ATM", 4, ">"),
        ("LTP", 8, ">"), ("LTP%", 8, ">"), ("Turn~", 9, ">"), ("CurOI", 9, ">"), ("PrevOI", 9, ">"),
        ("ChgOI", 9, ">"), ("OI%", 8, ">"), ("LTPxChg", 9, ">"), ("Notional", 9, ">"), ("TF", 3, "<"), ("Upd", 9, "<")]
def fmt(vals, cols=COLS): return " ".join((str(v)[:w].ljust(w) if a == "<" else str(v)[:w].rjust(w)) for v, (_, w, a) in zip(vals, cols))
HEADER = fmt([c[0] for c in COLS])

def row_line(r):
    return fmt([r["sym"], exp(r["expiry"]), "%g" % r["strike"], r["type"], "%+d" % r["dist"], "%.2f" % r["ltp"],
                p(r["ltp_pct"]), num(r["turnover"]), num(r["oi"]), num(r["prev_oi"]), num(r["oi_chg"]), p(r["oi_pct"]),
                num(r["x"]), num(r["notional"]), r["tf"], hhmm(r["ts"]) + ("*" if r["stale"] else "")])

def row_color(r): return (GREEN if r["oi_chg"] > 0 else RED) if r["cross"] else GREY


class Header(StencilView):
    """Sticky column-heading row. Double-tap a heading to sort by that column (again = flip Asc/Desc)."""
    def __init__(self, table, **kw):
        super().__init__(size_hint_y=None, height=dp(26), **kw); self.table = table
        self.lbl = Label(markup=True, font_name=MONO, font_size=sp(11), size_hint=(None, None), height=dp(26), halign="left", valign="middle")
        self.lbl.bind(size=lambda i, s: setattr(i, "text_size", s)); self.add_widget(self.lbl)
        self.bind(pos=lambda *a: table.sync(), size=lambda *a: table.sync())

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            if touch.is_double_tap and self.table.on_sort:
                t = self.table.col_at(touch.x - self.lbl.x)
                if t: self.table.on_sort(t)
            return True
        return super().on_touch_down(touch)


class Table(BoxLayout):
    def __init__(self, **kw):
        super().__init__(orientation="vertical", **kw)
        self.on_sort = None; self.cols = []; self.pool = []; self.n = -1
        self.head = Header(self)
        self.body = ScrollView(do_scroll_x=True, do_scroll_y=True, bar_width=dp(4))
        self.box = GridLayout(cols=1, size_hint=(None, None)); self.body.add_widget(self.box)
        self.add_widget(self.head); self.add_widget(self.body)
        self.body.bind(scroll_x=lambda *a: self.sync(), size=lambda *a: self.sync())

    def sync(self):
        off = max(0, self.box.width - self.body.width) * self.body.scroll_x
        self.head.lbl.pos = (self.head.x - off, self.head.y); self.head.lbl.width = self.box.width

    def col_at(self, x):
        ch = int(x / (sp(11) * 0.6)); pos = 0
        for t, w, a in self.cols:
            if ch < pos + w + 1: return t
            pos += w + 1
        return None

    def set_lines(self, header, lines, cols=None):
        if cols is not None: self.cols = cols
        need = len(lines)
        while len(self.pool) < need:
            l = Label(markup=True, font_name=MONO, font_size=sp(11), size_hint=(None, None), height=dp(22), halign="left", valign="middle")
            l.bind(size=lambda i, s: setattr(i, "text_size", s)); self.pool.append(l)
        w = (max([len(header)] + [len(t) for t, _ in lines]) + 2) * sp(11) * 0.62
        for l in self.pool[:need]: l.width = w
        self.head.lbl.text = "[b][color=%s]%s[/color][/b]" % (WHITE, header)
        for l, (t, c) in zip(self.pool, lines): l.text = "[color=%s]%s[/color]" % (c, t)
        if need != self.n:
            self.box.clear_widgets()
            for l in self.pool[:need]: self.box.add_widget(l)
            self.n = need
        self.box.width = w; self.box.height = max(need * dp(22), dp(22)); self.sync()


def hdr(cols, cur, order):
    ar = "^" if order == "asc" else "v"
    return fmt([c[0] + (ar if COL_KEYS.get(c[0]) == cur else "") for c in cols], cols)


def toggle_sort(st, skey, cur, key):
    """Returns the new sort key; same column again flips Asc/Desc, a new column starts Desc (text columns Asc)."""
    if cur == key: st["order"] = "desc" if st["order"] == "asc" else "asc"
    else: st["order"] = "asc" if key in TEXT_KEYS else "desc"
    st[skey] = key; return key


def info(title, text):
    Popup(title=title, content=Label(text=text, text_size=(dp(280), None), halign="center"),
          size_hint=(.85, .4)).open()


HCOLS = COLS[:-1] + [("Slot", 11, "<"), ("When", 12, "<")]
HHEADER = fmt([c[0] for c in HCOLS], HCOLS)


def hist_line(r):
    v = [r["sym"], exp(r["expiry"]), "%g" % r["strike"], r["type"], "%+d" % r["dist"], "%.2f" % r["ltp"], p(r["ltp_pct"]),
         num(r["turnover"]), num(r["oi"]), num(r["prev_oi"]), num(r["oi_chg"]), p(r["oi_pct"]), num(r["x"]), num(r["notional"]),
         r["tf"], r.get("slot", "-"), datetime.datetime.fromtimestamp(r["ts"], IST).strftime("%d%b %H:%M").upper()]
    return fmt(v, HCOLS)


def bar(): return BoxLayout(size_hint_y=None, height=dp(40))


class ScannerScreen(Screen):
    def __init__(self, sc, **kw):
        super().__init__(**kw); self.sc = sc; st = sc.st
        root = BoxLayout(orientation="vertical"); b1, b2, b3 = bar(), bar(), bar()
        self.tf = Spinner(text=st["show_tf"], values=S.TF_NAMES)
        self.sort = Spinner(text=INV.get(st["sort"], "OI Gain %"), values=list(SORTS))
        self.side = Spinner(text=st["side"], values=["ALL", "CE", "PE"])
        self.dir = Spinner(text=st["direction"], values=["both", "pos", "neg"])
        self.only = ToggleButton(text="Crossing", state="down" if st["only_crossing"] else "normal")
        self.txt = tinput(st["text"], "stocks: SBIN,INFY")
        self.gt = tinput("" if st["ltp_gt"] is None else str(st["ltp_gt"]), "> %"); self.lt = tinput("" if st["ltp_lt"] is None else str(st["ltp_lt"]), "< %")
        self.ord = order_button(st)
        for w in (self.tf, self.sort, self.side): b1.add_widget(w)
        for w in (self.dir, self.only, self.txt): b2.add_widget(w)
        for w in (Label(text="LTP%>", size_hint_x=.5), self.gt, Label(text="<", size_hint_x=.3), self.lt, self.ord): b3.add_widget(w)
        for w in (self.tf, self.sort, self.side, self.dir, self.txt, self.gt, self.lt): w.bind(text=self.changed)
        self.only.bind(state=self.changed); self.ord.bind(state=self.changed)
        self.table = Table(); self.table.on_sort = self.sort_by
        [root.add_widget(w) for w in (b1, b2, b3, self.table)]; self.add_widget(root)

    def sort_by(self, title):
        key = COL_KEYS.get(title); st = self.sc.st
        if not key: return
        toggle_sort(st, "sort", st["sort"], key); self.sort.text = INV.get(key, self.sort.text); self.refresh()

    def changed(self, *a):
        st = self.sc.st
        st["show_tf"] = self.tf.text; st["sort"] = SORTS[self.sort.text]; st["side"] = self.side.text
        st["direction"] = self.dir.text; st["only_crossing"] = self.only.state == "down"; st["text"] = self.txt.text
        st["ltp_gt"], st["ltp_lt"] = fnum(self.gt.text), fnum(self.lt.text)
        self.refresh()

    def refresh(self):
        st = self.sc.st; sync_order(self.ord, st)
        self.tf.values = [t for t in S.TF_NAMES if t in st["timeframes"]] or S.TF_NAMES
        rows = self.sc.query(st["show_tf"], st["sort"], st["side"], st["text"], st["only_crossing"], int(st["max_rows"]),
                             st["order"], st["ltp_gt"], st["ltp_lt"])
        self.table.set_lines(hdr(COLS, st["sort"], st["order"]), [(row_line(r), row_color(r)) for r in rows], COLS)


class MtfScreen(Screen):
    def __init__(self, sc, **kw):
        super().__init__(**kw); self.sc = sc; self.col = None
        root = BoxLayout(orientation="vertical"); b = bar(); self.ord = order_button(sc.st)
        b.add_widget(Label(text="Double-tap a heading to sort")); b.add_widget(self.ord)
        self.table = Table(); self.table.on_sort = self.sort_by; root.add_widget(b); root.add_widget(self.table); self.add_widget(root)

    def sort_by(self, title):
        st = self.sc.st
        if self.col == title: st["order"] = "desc" if st["order"] == "asc" else "asc"
        else: self.col = title; st["order"] = "asc" if title in ("Stock", "Contract") else "desc"
        self.refresh()

    def refresh(self):
        st = self.sc.st; sync_order(self.ord, st); tfs = [t for t in S.TF_NAMES if t in st["timeframes"]]
        ar = "^" if st["order"] == "asc" else "v"
        cols = [("Stock", 10, "<"), ("Contract", 15, "<")] + [(t, 8, ">") for t in tfs]
        txt = [t.strip().upper() for t in st["text"].split(",") if t.strip()]
        items = [e for e in self.sc.mtf if not ((st["side"] != "ALL" and e["meta"]["type"] != st["side"])
                 or (txt and not any(e["meta"]["sym"].startswith(t) for t in txt)))]
        def key(e):
            if self.col == "Stock": return (e["meta"]["sym"], e["meta"]["strike"])
            if self.col == "Contract": return (e["meta"]["sym"], e["meta"]["strike"], e["meta"]["type"])
            if self.col in tfs: v = e["cells"].get(self.col, (None,))[0]; return -1e18 if v is None else v
            return max(abs(pp) for pp, c in e["cells"].values() if c and pp is not None)
        items.sort(key=key, reverse=(st["order"] != "asc"))
        lines = []
        for e in items:
            m = e["meta"]
            cells = [(p(e["cells"][t][0]) + ("!" if e["cells"][t][1] else "")) if t in e["cells"] else "-" for t in tfs]
            lines.append((fmt([m["sym"], "%g%s %s" % (m["strike"], m["type"], exp(m["expiry"])[:5])] + cells, cols), YEL))
        head = fmt([c[0] + (ar if c[0] == self.col else "") for c in cols], cols)
        self.table.set_lines(head, lines[:int(st["max_rows"])], cols)


class HistoryScreen(Screen):
    """Historical scan: date range + time window + mode (Peak / Date-wise / Time-wise) + LTP% filters + sort."""
    def __init__(self, sc, **kw):
        super().__init__(**kw); self.sc = sc; st = sc.st
        last = sc.cal.session_date(datetime.datetime.now(IST))
        root = BoxLayout(orientation="vertical"); b1, b2, b3, b4, b5 = bar(), bar(), bar(), bar(), bar()
        self.d1 = tinput(last.isoformat(), "From YYYY-MM-DD"); self.d2 = tinput(last.isoformat(), "To YYYY-MM-DD")
        for w in (Label(text="Date", size_hint_x=.3), self.d1, Label(text="to", size_hint_x=.2), self.d2): b1.add_widget(w)
        for n, k in (("Last session", 1), ("3 sessions", 3), ("5 sessions", 5)): b2.add_widget(Button(text=n, on_release=lambda b, k=k: self.quick(k)))
        self.t1 = tinput(st["h_tfrom"], "HH:MM"); self.t2 = tinput(st["h_tto"], "HH:MM")
        self.mode = Spinner(text=st["h_mode"], values=["Peak", "Date-wise", "Time-wise"]); self.slot = Spinner(text=st["h_slot"], values=["15m", "30m", "1H"])
        for w in (Label(text="Time", size_hint_x=.35), self.t1, Label(text="to", size_hint_x=.2), self.t2, self.mode, self.slot): b3.add_widget(w)
        self.tf = Spinner(text=st["show_tf"], values=S.TF_NAMES); self.dir = Spinner(text=st["direction"], values=["both", "pos", "neg"])
        self.side = Spinner(text="ALL", values=["ALL", "CE", "PE"]); self.only = ToggleButton(text="Crossing", state="down")
        for w in (self.tf, self.dir, self.side, self.only): b4.add_widget(w)
        b4.add_widget(Button(text="RUN", bold=True, on_release=self.run))
        self.sort = Spinner(text=INV.get(st["h_sort"], "|OI %| abs"), values=list(SORTS))
        self.gt = tinput("" if st["ltp_gt"] is None else str(st["ltp_gt"]), "> %"); self.lt = tinput("" if st["ltp_lt"] is None else str(st["ltp_lt"]), "< %")
        self.ord = order_button(st)
        for w in (self.sort, Label(text="LTP%>", size_hint_x=.5), self.gt, Label(text="<", size_hint_x=.25), self.lt, self.ord): b5.add_widget(w)
        self.msg = Label(size_hint_y=None, height=dp(24), font_size=sp(11), color=(.7, .8, .9, 1)); self.table = Table()
        self.table.on_sort = self.sort_by
        for w in (b1, b2, b3, b4, b5, self.msg, self.table): root.add_widget(w)
        self.add_widget(root)

    def sort_by(self, title):
        key = COL_KEYS.get(title); st = self.sc.st
        if not key: return
        toggle_sort(st, "h_sort", st["h_sort"], key); self.sort.text = INV.get(key, self.sort.text); self.refresh()

    def quick(self, k):
        d = self.sc.cal.session_date(datetime.datetime.now(IST)); e = d
        for _ in range(k - 1): d = self.sc.cal.prev_td(d)
        self.d1.text, self.d2.text = d.isoformat(), e.isoformat()

    def run(self, *a):
        try:
            d1, d2 = datetime.date.fromisoformat(self.d1.text.strip()), datetime.date.fromisoformat(self.d2.text.strip())
            t1, t2 = datetime.time.fromisoformat(self.t1.text.strip()), datetime.time.fromisoformat(self.t2.text.strip())
        except ValueError: return info("Input", "Dates: YYYY-MM-DD (e.g. 2026-11-04)\nTimes: HH:MM (e.g. 09:15)")
        if d1 > d2: d1, d2 = d2, d1
        if t1 > t2: t1, t2 = t2, t1
        if d2 > datetime.datetime.now(IST).date(): return info("Date", "End date is in the future")
        if (d2 - d1).days > 10: return info("Date", "Max range is 10 days")
        st = self.sc.st
        st.d.update(direction=self.dir.text, show_tf=self.tf.text, h_mode=self.mode.text, h_slot=self.slot.text, h_tfrom=self.t1.text.strip(), h_tto=self.t2.text.strip())
        opt = dict(tfrom=t1, tto=t2, mode=self.mode.text, slot={"15m": 900, "30m": 1800, "1H": 3600}[self.slot.text], gt=fnum(self.gt.text), lt=fnum(self.lt.text))
        self.sc.hist_scan(d1, d2, self.tf.text, opt)

    def refresh(self):
        st = self.sc.st; sync_order(self.ord, st); st["h_sort"] = SORTS[self.sort.text]
        h = self.sc.hist; gt, lt = fnum(self.gt.text), fnum(self.lt.text)
        self.msg.text = h.get("msg", "Choose date / time / mode, then RUN (scans your selected stocks, ATM +/- N)")
        rows = [r for r in h.get("rows", []) if (self.side.text == "ALL" or r["type"] == self.side.text)
                and (self.only.state != "down" or r["cross"]) and price_ok(r["ltp_pct"], gt, lt)]
        rows = sort_rows(rows, st["h_sort"], st["order"])[:int(st["max_rows"])]
        self.table.set_lines(hdr(HCOLS, st["h_sort"], st["order"]), [(hist_line(r), GREEN if r["oi_chg"] > 0 else RED) for r in rows], HCOLS)


ALERT_COLS = [("Alert@", 8, "<")] + COLS


class AlertScreen(Screen):
    def __init__(self, sc, **kw):
        super().__init__(**kw); self.sc = sc; self.key = "alert_ts"
        root = BoxLayout(orientation="vertical"); b = bar()
        self.on = ToggleButton(text="Alerts ON", state="down" if sc.st["alerts_on"] else "normal")
        self.on.bind(state=lambda i, s: (sc.st.__setitem__("alerts_on", s == "down"), sc.st.save()))
        self.ord = order_button(sc.st)
        for w in (self.on, Button(text="Clear history", on_release=lambda i: sc.alerts.clear()), self.ord): b.add_widget(w)
        self.table = Table(); self.table.on_sort = self.sort_by; root.add_widget(b); root.add_widget(self.table); self.add_widget(root)

    def sort_by(self, title):
        key = COL_KEYS.get(title)
        if key: self.key = toggle_sort(self.sc.st, "_unused", self.key, key); self.refresh()

    def refresh(self):
        st = self.sc.st; sync_order(self.ord, st)
        items = sort_rows(list(self.sc.alerts.history), self.key, st["order"])
        lines = [(hhmm(r["alert_ts"]) + " " + row_line(r), GREEN if r["oi_chg"] > 0 else RED) for r in items[:200]]
        self.table.set_lines(hdr(ALERT_COLS, self.key, st["order"]), lines, ALERT_COLS)


class StockPicker(Popup):
    def __init__(self, sc, **kw):
        super().__init__(title="Select stocks", size_hint=(.95, .9), **kw); self.sc = sc
        self.syms = sc.im.symbols(); st = sc.st
        self.sel = set(self.syms if st["all_stocks"] else st["stocks"])
        root = BoxLayout(orientation="vertical"); bar = BoxLayout(size_hint_y=None, height=dp(42))
        self.q = TextInput(hint_text="search", multiline=False); self.q.bind(text=lambda i, t: self.fill())
        bar.add_widget(self.q)
        bar.add_widget(Button(text="All", size_hint_x=.3, on_release=lambda b: (self.sel.update(self.syms), self.fill())))
        bar.add_widget(Button(text="None", size_hint_x=.3, on_release=lambda b: (self.sel.clear(), self.fill())))
        bar.add_widget(Button(text="Done", size_hint_x=.3, on_release=self.done))
        self.grid = GridLayout(cols=3, size_hint_y=None, spacing=dp(2)); self.grid.bind(minimum_height=self.grid.setter("height"))
        sv = ScrollView(); sv.add_widget(self.grid); root.add_widget(bar); root.add_widget(sv); self.content = root; self.fill()

    def fill(self):
        self.grid.clear_widgets(); f = self.q.text.strip().upper()
        for s in self.syms:
            if f and f not in s: continue
            b = ToggleButton(text=s, size_hint_y=None, height=dp(38), font_size=sp(12), state="down" if s in self.sel else "normal")
            b.bind(state=lambda i, v, s=s: self.sel.add(s) if v == "down" else self.sel.discard(s)); self.grid.add_widget(b)

    def done(self, *a):
        st = self.sc.st; st["stocks"] = sorted(self.sel); st["all_stocks"] = bool(self.syms) and self.sel == set(self.syms)
        st.save(); self.sc.reconfigure(); self.dismiss()


def L(t):
    l = Label(text=t, size_hint_y=None, height=dp(28), halign="left", bold=True, color=(.6, .85, 1, 1))
    l.bind(size=lambda i, s: setattr(i, "text_size", (s[0], None))); return l

def TI(v, **k): return TextInput(text=str(v), multiline=False, size_hint_y=None, height=dp(38), write_tab=False, **k)
def BTN(t, f): return Button(text=t, size_hint_y=None, height=dp(40), on_release=f)


class SettingsScreen(Screen):
    def __init__(self, sc, **kw):
        super().__init__(**kw); self.sc = sc; st = sc.st
        g = GridLayout(cols=1, size_hint_y=None, spacing=dp(6), padding=dp(8)); g.bind(minimum_height=g.setter("height"))
        g.add_widget(L("Dhan credentials (needs Data API subscription)"))
        self.cid = TI(st["client_id"], hint_text="Client ID"); self.tok = TI(st["access_token"], hint_text="Access token", password=True)
        g.add_widget(self.cid); g.add_widget(self.tok)
        g.add_widget(BTN("Save & Connect", lambda b: self.apply(True))); g.add_widget(BTN("Renew token (24h)", self.renew))
        g.add_widget(L("Stocks")); g.add_widget(BTN("Select stocks...", self.pick))
        g.add_widget(L("Expiry (multi-select)")); eb = BoxLayout(size_hint_y=None, height=dp(40)); self.exp = {}
        for i, n in enumerate(["Current", "Next", "3rd", "4th"]):
            b = ToggleButton(text=n, state="down" if i in st["expiry_slots"] else "normal"); self.exp[i] = b; eb.add_widget(b)
        g.add_widget(eb)
        g.add_widget(L("Strikes: ATM +/- N  (CE | PE)")); nb = BoxLayout(size_hint_y=None, height=dp(38))
        self.nce = TI(st["n_ce"], input_filter="int"); self.npe = TI(st["n_pe"], input_filter="int"); nb.add_widget(self.nce); nb.add_widget(self.npe); g.add_widget(nb)
        pb = BoxLayout(size_hint_y=None, height=dp(38))
        for n in (0, 1, 2, 3, 5, 10): pb.add_widget(Button(text=str(n), on_release=lambda b, n=n: (setattr(self.nce, "text", str(n)), setattr(self.npe, "text", str(n)))))
        g.add_widget(pb)
        g.add_widget(L("Timeframes: enable | min OI gain %")); self.chk, self.th = {}, {}
        for tf in S.TF_NAMES:
            r = BoxLayout(size_hint_y=None, height=dp(38)); c = CheckBox(active=tf in st["timeframes"], size_hint_x=.2)
            t = TI(st["thresholds"].get(tf, 10), input_filter="float"); self.chk[tf], self.th[tf] = c, t
            r.add_widget(c); r.add_widget(Label(text=tf, size_hint_x=.3)); r.add_widget(t); g.add_widget(r)
        tb = BoxLayout(size_hint_y=None, height=dp(38))
        tb.add_widget(Button(text="All TF", on_release=lambda b: [setattr(c, "active", True) for c in self.chk.values()]))
        for v in (5, 10, 15, 20): tb.add_widget(Button(text="%d%%" % v, on_release=lambda b, v=v: [setattr(t, "text", str(v)) for t in self.th.values()]))
        g.add_widget(tb)
        g.add_widget(L("Min absolute OI change")); self.mabs = TI(st["min_abs_oi"], input_filter="int"); g.add_widget(self.mabs)
        g.add_widget(BTN("Reset filters", lambda b: (st.reset_filters(), info("Filters", "Reset (reopen tab to see)"))))
        g.add_widget(L("Alerts: enabled | sound | notification")); ab = BoxLayout(size_hint_y=None, height=dp(38))
        self.al = {k: CheckBox(active=st[k]) for k in ("alerts_on", "sound_on", "notify_on")}
        for c in self.al.values(): ab.add_widget(c)
        g.add_widget(ab)
        g.add_widget(L("Retention days | DB snapshot sec | holidays (YYYY-MM-DD,...)")); self.ret = TI(st["retention_days"], input_filter="int")
        self.dbi = TI(st["db_interval"], input_filter="int"); self.hol = TI(",".join(st["holidays"])); [g.add_widget(w) for w in (self.ret, self.dbi, self.hol)]
        g.add_widget(L("Historical scan (loads past OI from Dhan so all timeframes work immediately)"))
        self.bf = CheckBox(active=st["auto_backfill"], size_hint_y=None, height=dp(34)); g.add_widget(self.bf)
        g.add_widget(BTN("Backfill history now", lambda b: (self.apply(False), self.sc.backfill_now(), info("History", "Backfill started - progress shows in the top status line"))))
        g.add_widget(BTN("View app log", self.show_log))
        g.add_widget(L("Presets")); self.pn = TI("", hint_text="preset name"); g.add_widget(self.pn)
        g.add_widget(BTN("Save preset", self.save_preset)); self.ps = Spinner(text="Load preset", values=list(st["presets"]), size_hint_y=None, height=dp(40))
        self.ps.bind(text=self.load_preset); g.add_widget(self.ps); g.add_widget(BTN("Apply settings", lambda b: self.apply(False)))
        sv = ScrollView(); sv.add_widget(g); self.add_widget(sv)

    def show_log(self, *a):
        try:
            with open(os.path.join(os.path.dirname(self.sc.db.con.execute("PRAGMA database_list").fetchall()[0][2]), "scanner.log")) as f:
                t = "".join(f.readlines()[-40:])
        except Exception as e: t = "no log: %s" % e
        sv = ScrollView(); lb = Label(text=t, size_hint_y=None, font_size=sp(10), text_size=(dp(300), None), halign="left")
        lb.bind(texture_size=lambda i, s: setattr(i, "height", s[1])); sv.add_widget(lb)
        Popup(title="scanner.log (last 40 lines)", content=sv, size_hint=(.95, .85)).open()

    def pick(self, *a):
        if not self.sc.im.by: return info("Stocks", "Instrument master still loading - wait and retry.")
        StockPicker(self.sc).open()

    def apply(self, reauth):
        st = self.sc.st
        try:
            st["client_id"], st["access_token"] = self.cid.text.strip(), self.tok.text.strip()
            st["expiry_slots"] = [i for i, b in self.exp.items() if b.state == "down"] or [0]
            st["n_ce"], st["n_pe"] = int(self.nce.text or 0), int(self.npe.text or 0)
            st["timeframes"] = [t for t, c in self.chk.items() if c.active]
            st["thresholds"] = {t: float(w.text or 0) for t, w in self.th.items()}
            st["min_abs_oi"] = int(self.mabs.text or 0)
            for k, c in self.al.items(): st[k] = c.active
            st["auto_backfill"] = self.bf.active
            st["retention_days"], st["db_interval"] = max(2, int(self.ret.text or 5)), max(15, int(self.dbi.text or 60))
            st["holidays"] = [h.strip() for h in self.hol.text.split(",") if h.strip()]
            st.save(); self.sc.reconfigure(reauth); info("Saved", "Settings applied")
        except Exception as e: info("Error", str(e))

    def renew(self, *a):
        def run():
            try:
                self.sc.st["client_id"], self.sc.st["access_token"] = self.cid.text.strip(), self.tok.text.strip()
                t = self.sc.client.renew(); self.sc.st["access_token"] = t; self.sc.st.save()
                Clock.schedule_once(lambda dt: (setattr(self.tok, "text", t), info("Token", "Renewed"), self.sc.reconfigure(True)))
            except Exception as e: Clock.schedule_once(lambda dt, e=e: info("Renew failed", str(e)))
        threading.Thread(target=run, daemon=True).start()

    def save_preset(self, *a):
        if self.pn.text.strip():
            self.apply(False); self.sc.st.save_preset(self.pn.text.strip()); self.ps.values = list(self.sc.st["presets"])

    def load_preset(self, sp_, name):
        if name in self.sc.st["presets"]: self.sc.st.load_preset(name); info("Preset", "Loaded '%s'. Reopen app to refresh fields." % name)


class Dashboard(BoxLayout):
    def __init__(self, sc, **kw):
        super().__init__(orientation="vertical", **kw); self.sc = sc
        self.status = Label(size_hint_y=None, height=dp(26), font_size=sp(10), color=(.7, .8, .9, 1), shorten=True, halign="left")
        self.status.bind(size=lambda i, s: setattr(i, "text_size", (s[0], None)))
        self.sm = ScreenManager()
        for cls, n in ((ScannerScreen, "Scanner"), (MtfScreen, "Multi-TF"), (HistoryScreen, "History"), (AlertScreen, "Alerts"), (SettingsScreen, "Settings")):
            self.sm.add_widget(cls(sc, name=n))
        nav = BoxLayout(size_hint_y=None, height=dp(46))
        for n in ("Scanner", "Multi-TF", "History", "Alerts", "Settings"): nav.add_widget(Button(text=n, on_release=lambda b, n=n: self.go(n)))
        self.add_widget(self.status); self.add_widget(self.sm); self.add_widget(nav)
        Clock.schedule_interval(self.tick, 2)

    def go(self, n): self.sm.current = n; self.tick(0)

    def tick(self, dt):
        self.status.text = self.sc.status_text(); cur = self.sm.current_screen
        if hasattr(cur, "refresh"):
            try: cur.refresh()
            except Exception: self.sc.log.exception("ui refresh")
