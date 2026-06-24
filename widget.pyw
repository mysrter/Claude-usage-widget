import os
import sys
import json
import time
import socket
import threading
import tkinter as tk
import tkinter.font as tkfont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from usage_core import (UsageScanner, fmt_tok, fmt_cost, fmt_duration)

REFRESH_MS = 20_000
LOCK_PORT = 49317
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "widget_config.json")
LIMITS_PATH = os.path.join(SCRIPT_DIR, "limits.json")
SELFTEST = "--selftest" in sys.argv

BG, CARD, CARD2 = "#211e1c", "#2b2723", "#34302b"
ACCENT, ACCENT_D = "#d97757", "#8f4f3a"
BLUE, TRACK = "#4f80d6", "#46413b"
AMBER, RED = "#d9a05b", "#d95c4f"
FG, MUTED, FAINT, LINE = "#ece7e1", "#9c948b", "#6f675f", "#3a352f"
TR_DAYS = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]
TR_DAYS_FULL = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]

DEFAULT_LIMITS = {
    "window_hours": 5,
    "weekly_reset_weekday": 6,
    "weekly_reset_hour": 18,
    "plan_label": "",
    "session_cap_tokens": None,
    "weekly_cap_tokens": None,
    "session_cap_usd": None,
    "weekly_cap_usd": None,
}

def single_instance_lock():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", LOCK_PORT))
        s.listen(1)
        return s
    except OSError:
        return None

def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return dict(default)

def _save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

def bar_color(ratio):
    if ratio >= 0.9:
        return RED
    if ratio >= 0.75:
        return AMBER
    return BLUE

class Widget:
    def __init__(self, root):
        self.root = root
        self.scanner = UsageScanner()
        self._scanning = False
        self._last = None
        self.detail_open = False
        self._session_reset_at = None
        self._session_active = False

        self.limits = _load_json(LIMITS_PATH, DEFAULT_LIMITS)
        for k, v in DEFAULT_LIMITS.items():
            self.limits.setdefault(k, v)
        if not os.path.exists(LIMITS_PATH):
            _save_json(LIMITS_PATH, self.limits)
        self.win_hours = int(self.limits.get("window_hours") or 5)

        root.overrideredirect(True)
        root.attributes("-topmost", True)
        try:
            root.attributes("-alpha", 0.97)
        except Exception:
            pass
        root.configure(bg=BG)

        self.f_title  = tkfont.Font(family="Segoe UI Semibold", size=11)
        self.f_htitle = tkfont.Font(family="Segoe UI", size=11)
        self.f_pct    = tkfont.Font(family="Segoe UI Semibold", size=11)
        self.f_hero  = tkfont.Font(family="Segoe UI", size=21, weight="bold")
        self.f_cost  = tkfont.Font(family="Segoe UI", size=12)
        self.f_sub   = tkfont.Font(family="Segoe UI", size=9)
        self.f_lbl   = tkfont.Font(family="Segoe UI Semibold", size=8)
        self.f_val   = tkfont.Font(family="Segoe UI Semibold", size=12)
        self.f_mono  = tkfont.Font(family="Consolas", size=9)
        self.f_btn   = tkfont.Font(family="Segoe UI", size=11)

        outer = tk.Frame(root, bg=BG)
        outer.pack(fill="both", expand=True)
        self.card = tk.Frame(outer, bg=CARD)
        self.card.pack(fill="both", expand=True, padx=1, pady=1)

        self._build_header()
        plan = self.limits.get("plan_label") or ""
        if plan:
            tk.Label(self.card, text="Plan kullanım limiti · " + plan, bg=CARD,
                     fg=FAINT, font=self.f_sub, anchor="w").pack(fill="x", padx=12, pady=(0, 6))
        self.hero_s = self._build_hero("Geçerli oturum")
        self.hero_w = self._build_hero("Haftalık · tüm modeller")
        self._build_detail()
        self._build_footer()

        cfg = _load_json(CONFIG_PATH, {})
        root.update_idletasks()
        if cfg.get("geo"):
            root.geometry(cfg["geo"])
        else:
            sw = root.winfo_screenwidth()
            root.geometry(f"+{sw - 300 - 24}+48")

        self.refresh()
        self._clock()
        if SELFTEST:
            root.after(3200, root.destroy)
        else:
            self._schedule()

    def _build_header(self):
        h = tk.Frame(self.card, bg=CARD)
        h.pack(fill="x", padx=12, pady=(10, 4))
        dot = tk.Label(h, text="◆", bg=CARD, fg=ACCENT, font=self.f_title)
        dot.pack(side="left")
        title = tk.Label(h, text="  Claude Usage", bg=CARD, fg=FG, font=self.f_title)
        title.pack(side="left")
        for name, cmd in (("✕", self._quit), ("⟳", self.refresh), ("⚙", self._open_calibrate)):
            b = tk.Label(h, text=name, bg=CARD, fg=FAINT, font=self.f_btn, cursor="hand2")
            b.pack(side="right", padx=(8, 0))
            b.bind("<Button-1>", lambda e, c=cmd: c())
            b.bind("<Enter>", lambda e, w=b: w.config(fg=ACCENT))
            b.bind("<Leave>", lambda e, w=b: w.config(fg=FAINT))
        for w in (h, dot, title):
            w.bind("<Button-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
            w.bind("<ButtonRelease-1>", self._drag_end)

    def _build_hero(self, title):
        box = tk.Frame(self.card, bg=CARD2)
        box.pack(fill="x", padx=12, pady=(0, 8))
        top = tk.Frame(box, bg=CARD2)
        top.pack(fill="x", padx=12, pady=(10, 0))
        lbl = tk.Label(top, text=title, bg=CARD2, fg=FG, font=self.f_htitle)
        lbl.pack(side="left")
        pct = tk.Label(top, text="", bg=CARD2, fg=MUTED, font=self.f_pct)
        pct.pack(side="right")
        bar = tk.Canvas(box, height=10, bg=CARD2, highlightthickness=0)
        bar.pack(fill="x", padx=12, pady=(7, 0))
        sub = tk.Label(box, text="", bg=CARD2, fg=MUTED, font=self.f_sub, anchor="w")
        sub.pack(fill="x", padx=12, pady=(5, 11))
        return {"box": box, "lbl": lbl, "pct": pct, "bar": bar, "sub": sub}

    def _rrect(self, c, x0, y0, x1, y1, color):
        h = y1 - y0
        r = h / 2.0
        if x1 - x0 <= h:
            c.create_oval(x0, y0, x0 + h, y1, fill=color, width=0)
            return
        c.create_oval(x0, y0, x0 + 2 * r, y1, fill=color, width=0)
        c.create_oval(x1 - 2 * r, y0, x1, y1, fill=color, width=0)
        c.create_rectangle(x0 + r, y0, x1 - r, y1, fill=color, width=0)

    def _draw_bar(self, bar, ratio, color):
        bar.delete("all")
        bar.update_idletasks()
        W = bar.winfo_width() or 274
        H = 10
        self._rrect(bar, 0, 0, W, H, TRACK)
        fw = max(0.0, min(ratio, 1.0)) * W
        if fw >= 1:
            self._rrect(bar, 0, 0, max(fw, H), H, color)

    def _stat_box(self, parent, title):
        b = tk.Frame(parent, bg=CARD2)
        tk.Label(b, text=title, bg=CARD2, fg=MUTED, font=self.f_lbl).pack(pady=(7, 0))
        val = tk.Label(b, text="—", bg=CARD2, fg=FG, font=self.f_val)
        val.pack()
        cost = tk.Label(b, text="", bg=CARD2, fg=ACCENT, font=self.f_lbl)
        cost.pack(pady=(0, 7))
        return b, val, cost

    def _build_detail(self):
        self.detail_btn = tk.Label(self.card, text="▸ Detaylar", bg=CARD, fg=MUTED,
                                   font=self.f_sub, cursor="hand2", anchor="w")
        self.detail_btn.pack(fill="x", padx=12, pady=(0, 0))
        self.detail_btn.bind("<Button-1>", lambda e: self._toggle_detail())
        self.detail_box = tk.Frame(self.card, bg=CARD)

        stats = tk.Frame(self.detail_box, bg=CARD)
        stats.pack(fill="x", pady=(6, 2))
        b1, self.v_today, self.c_today = self._stat_box(stats, "BUGÜN")
        b2, self.v_month, self.c_month = self._stat_box(stats, "30 GÜN")
        b3, self.v_total, self.c_total = self._stat_box(stats, "TOPLAM")
        for i, b in enumerate((b1, b2, b3)):
            b.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 5, 0))
            stats.columnconfigure(i, weight=1)

        tk.Label(self.detail_box, text="SON 7 GÜN", bg=CARD, fg=MUTED,
                 font=self.f_lbl, anchor="w").pack(fill="x", pady=(8, 0))
        self.canvas = tk.Canvas(self.detail_box, height=82, bg=CARD, highlightthickness=0)
        self.canvas.pack(fill="x")

        tk.Label(self.detail_box, text="MODELE GÖRE", bg=CARD, fg=MUTED,
                 font=self.f_lbl, anchor="w").pack(fill="x", pady=(6, 0))
        self.models_box = tk.Frame(self.detail_box, bg=CARD)
        self.models_box.pack(fill="x", pady=(2, 0))

        tk.Label(self.detail_box, text="PROJELER", bg=CARD, fg=MUTED,
                 font=self.f_lbl, anchor="w").pack(fill="x", pady=(6, 0))
        self.proj_box = tk.Frame(self.detail_box, bg=CARD)
        self.proj_box.pack(fill="x", pady=(2, 0))

    def _build_footer(self):
        tk.Frame(self.card, bg=LINE, height=1).pack(fill="x", padx=12, pady=(8, 0))
        self.footer = tk.Label(self.card, text="", bg=CARD, fg=FAINT,
                               font=self.f_lbl, anchor="w")
        self.footer.pack(fill="x", padx=12, pady=(4, 8))

    def _drag_start(self, e):
        self._dx, self._dy = e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y()

    def _drag_move(self, e):
        self.root.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    def _drag_end(self, e):
        cfg = _load_json(CONFIG_PATH, {})
        cfg["geo"] = f"+{self.root.winfo_x()}+{self.root.winfo_y()}"
        _save_json(CONFIG_PATH, cfg)

    def _toggle_detail(self):
        self.detail_open = not self.detail_open
        if self.detail_open:
            self.detail_btn.config(text="▾ Detaylar")
            self.detail_box.pack(fill="x", padx=12, after=self.detail_btn)
            if self._last:
                self._fill_detail(self._last)
        else:
            self.detail_btn.config(text="▸ Detaylar")
            self.detail_box.pack_forget()
        self._fit()

    def refresh(self):
        if self._scanning:
            return
        self._scanning = True
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        try:
            s = self.scanner.scan(
                window_hours=self.win_hours,
                weekly_weekday=int(self.limits.get("weekly_reset_weekday", 6)),
                weekly_hour=int(self.limits.get("weekly_reset_hour", 18)))
        except Exception as ex:
            s = {"error": str(ex)}
        self.root.after(0, lambda: self._on_scan(s))

    def _on_scan(self, s):
        self._scanning = False
        if "error" in s:
            self.footer.config(text="hata: " + s["error"][:42])
            return
        self._last = s
        self.apply(s)
        if SELFTEST:
            se = s["session"]
            print("SELFTEST OK | 5sa:", fmt_tok(se["tok"]), fmt_cost(se["cost"]),
                  "reset", fmt_duration(se["reset_in"]),
                  "| 7g:", fmt_tok(s["week"]["tok"]),
                  "| pencere", self.root.winfo_width(), "x", self.root.winfo_height())
            if "--testcal" in sys.argv:
                self._open_calibrate()
                print("SELFTEST: kalibrasyon penceresi acildi (hata yok)")

    def _schedule(self):
        self.root.after(REFRESH_MS, self._tick)

    def _tick(self):
        self.refresh()
        self._schedule()

    def _clock(self):
        self._update_session_sub()
        if not SELFTEST:
            self.root.after(1000, self._clock)

    def _update_session_sub(self):
        if self._session_active and self._session_reset_at:
            rem = self._session_reset_at - time.time()
            txt = ("sıfırlanmasına " + fmt_duration(rem)) if rem > 0 \
                else "pencere doldu · ilk istekte yenilenir"
        else:
            txt = "pencere boş · ilk istekte başlar"
        self.hero_s["sub"].config(text=txt, fg=MUTED)

    def _set_bar(self, hero, b, cap_tok, cap_usd):
        cap, used = None, b["tok"]
        if cap_tok:
            cap, used = cap_tok, b["tok"]
        elif cap_usd:
            cap, used = cap_usd, b["cost"]
        if cap and cap > 0:
            ratio = max(0.0, min(used / cap, 1.0))
            hero["pct"].config(text=f"%{int(round(ratio * 100))} kullanıldı", fg=FG)
            self._draw_bar(hero["bar"], ratio, bar_color(ratio))
        else:
            hero["pct"].config(text=fmt_cost(b["cost"]), fg=MUTED)
            self._draw_bar(hero["bar"], 0, BLUE)

    def _weekly_sub(self, wk):
        ra = wk.get("reset_at")
        ri = wk.get("reset_in") or 0
        if ri >= 36 * 3600:
            d, h = ri // 86400, (ri % 86400) // 3600
            rem = f"{d} gün {h} sa"
        else:
            rem = fmt_duration(ri)
        if ra is not None:
            return f"{TR_DAYS_FULL[ra.weekday()]} {ra.strftime('%H:%M')} sıfırlanır · {rem}"
        return f"{wk['calls']} çağrı · son 7 gün"

    def apply(self, s):
        se = s["session"]
        self._session_active = bool(se.get("active"))
        self._session_reset_at = (se["start"] + self.win_hours * 3600) if se.get("start") else None
        self._set_bar(self.hero_s, se, self.limits.get("session_cap_tokens"),
                      self.limits.get("session_cap_usd"))
        self._update_session_sub()

        self._set_bar(self.hero_w, s["week"], self.limits.get("weekly_cap_tokens"),
                      self.limits.get("weekly_cap_usd"))
        self.hero_w["sub"].config(text=self._weekly_sub(s["week"]), fg=MUTED)

        if self.detail_open:
            self._fill_detail(s)
        self.footer.config(text=f"güncellendi {s['updated']}  ·  her 20 sn")
        self._fit()

    def _fill_detail(self, s):
        for vlbl, clbl, key in ((self.v_today, self.c_today, "today"),
                                (self.v_month, self.c_month, "month"),
                                (self.v_total, self.c_total, "all")):
            b = s[key]
            vlbl.config(text=fmt_tok(b["tok"]))
            clbl.config(text=fmt_cost(b["cost"]))
        self._draw_chart(s["series"])
        self._fill_list(self.models_box, s["by_model"], 4, FG)
        self._fill_list(self.proj_box, s["by_project"], 5, MUTED)

    def _fill_list(self, box, items, n, name_fg):
        for w in box.winfo_children():
            w.destroy()
        rows = [it for it in items if it[1] > 0][:n]
        if not rows:
            tk.Label(box, text="veri yok", bg=CARD, fg=FAINT, font=self.f_sub,
                     anchor="w").pack(fill="x")
            return
        for name, tok, cost in rows:
            r = tk.Frame(box, bg=CARD)
            r.pack(fill="x", pady=1)
            tk.Label(r, text=name, bg=CARD, fg=name_fg, font=self.f_sub,
                     anchor="w").pack(side="left")
            tk.Label(r, text=fmt_cost(cost), bg=CARD, fg=ACCENT, font=self.f_mono,
                     anchor="e").pack(side="right")
            tk.Label(r, text=fmt_tok(tok), bg=CARD, fg=FAINT, font=self.f_mono,
                     anchor="e").pack(side="right", padx=(0, 10))

    def _draw_chart(self, series):
        c = self.canvas
        c.delete("all")
        c.update_idletasks()
        W = c.winfo_width() or 276
        area = 58
        gap = 9
        n = len(series)
        bw = (W - gap * (n - 1)) / n
        maxt = max([t for _, t, _ in series] + [1])
        for i, (d, t, cost) in enumerate(series):
            x0 = i * (bw + gap)
            h = (t / maxt) * area if maxt else 0
            if t > 0:
                h = max(h, 3)
            today = (i == n - 1)
            c.create_rectangle(x0, area - h, x0 + bw, area,
                               fill=(ACCENT if today else ACCENT_D), width=0)
            c.create_text(x0 + bw / 2, area + 13, text=TR_DAYS[d.weekday()],
                          fill=(FG if today else FAINT), font=self.f_lbl)

    def _fit(self):
        self.root.update_idletasks()
        self.root.geometry(f"300x{self.root.winfo_reqheight()}")

    def _open_calibrate(self):
        if not self._last:
            return
        sc = self._last["session"]["cost"]
        wc = self._last["week"]["cost"]

        def cur(cost, cap):
            return str(int(round(cost / cap * 100))) if cap else ""

        top = tk.Toplevel(self.root)
        top.title("Kalibrasyon")
        top.configure(bg=CARD)
        top.attributes("-topmost", True)
        top.resizable(False, False)
        top.geometry(f"+{self.root.winfo_x() + 16}+{self.root.winfo_y() + 64}")

        tk.Label(top, text="Claude Desktop ▸ Settings ▸ Usage'daki\nyüzdeleri yaz, çubuklar ona oturur:",
                 bg=CARD, fg=FG, font=self.f_sub, justify="left").pack(padx=14, pady=(12, 8), anchor="w")
        frm = tk.Frame(top, bg=CARD)
        frm.pack(padx=14, fill="x")

        def row(r, label, cap_key):
            tk.Label(frm, text=label, bg=CARD, fg=MUTED, font=self.f_sub,
                     width=11, anchor="w").grid(row=r, column=0, pady=3)
            e = tk.Entry(frm, width=7, bg=CARD2, fg=FG, insertbackground=FG,
                         relief="flat", justify="center", font=self.f_sub)
            e.grid(row=r, column=1)
            tk.Label(frm, text="%", bg=CARD, fg=MUTED, font=self.f_sub).grid(row=r, column=2, padx=(4, 0))
            e.insert(0, cur(sc if "session" in cap_key else wc, self.limits.get(cap_key)))
            return e

        e_s = row(0, "Geçerli oturum", "session_cap_usd")
        e_w = row(1, "Haftalık", "weekly_cap_usd")
        msg = tk.Label(top, text="", bg=CARD, fg=MUTED, font=self.f_lbl, anchor="w")
        msg.pack(padx=14, pady=(6, 0), anchor="w", fill="x")

        def save():
            try:
                sp = float(e_s.get().strip() or 0)
                wp = float(e_w.get().strip() or 0)
            except ValueError:
                msg.config(text="geçersiz sayı", fg=RED)
                return
            if sp > 0 and sc > 0:
                self.limits["session_cap_usd"] = round(sc / (sp / 100.0), 2)
                self.limits["session_cap_tokens"] = None
            if wp > 0 and wc > 0:
                self.limits["weekly_cap_usd"] = round(wc / (wp / 100.0), 2)
                self.limits["weekly_cap_tokens"] = None
            _save_json(LIMITS_PATH, self.limits)
            self.apply(self._last)
            top.destroy()

        btns = tk.Frame(top, bg=CARD)
        btns.pack(padx=14, pady=12, fill="x")
        tk.Button(btns, text="Kaydet", command=save, bg=ACCENT, fg=CARD,
                  relief="flat", font=self.f_sub, cursor="hand2", padx=10).pack(side="right")
        tk.Button(btns, text="İptal", command=top.destroy, bg=CARD2, fg=FG,
                  relief="flat", font=self.f_sub, cursor="hand2", padx=10).pack(side="right", padx=(0, 8))
        e_s.focus_set()
        top.bind("<Return>", lambda e: save())

    def _quit(self):
        cfg = _load_json(CONFIG_PATH, {})
        cfg["geo"] = f"+{self.root.winfo_x()}+{self.root.winfo_y()}"
        _save_json(CONFIG_PATH, cfg)
        self.root.destroy()

def main():
    lock = single_instance_lock()
    if lock is None and not SELFTEST:
        return
    root = tk.Tk()
    if SELFTEST:
        import traceback
        root.report_callback_exception = lambda exc, val, tb: traceback.print_exception(exc, val, tb)
    root.title("Claude Usage")
    root.geometry("300x1")
    Widget(root)
    root.update_idletasks()
    root.geometry(f"300x{root.winfo_reqheight()}")
    root.mainloop()
    if lock is not None:
        try:
            lock.close()
        except Exception:
            pass

if __name__ == "__main__":
    main()
