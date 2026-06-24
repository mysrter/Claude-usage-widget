import os
import glob
import json
import time
from datetime import datetime, timedelta

HOME = os.path.expanduser("~")
PROJECTS_DIR = os.path.join(HOME, ".claude", "projects")

PRICING = {
    "opus":   {"in": 15.0, "out": 75.0, "cw5": 18.75, "cw1": 30.0, "cr": 1.50},
    "sonnet": {"in":  3.0, "out": 15.0, "cw5":  3.75, "cw1":  6.0, "cr": 0.30},
    "haiku":  {"in":  1.0, "out":  5.0, "cw5":  1.25, "cw1":  2.0, "cr": 0.10},
}

def _price(model):
    m = (model or "").lower()
    if "opus" in m:
        return PRICING["opus"]
    if "haiku" in m:
        return PRICING["haiku"]
    if "sonnet" in m:
        return PRICING["sonnet"]
    return PRICING["opus"]

def friendly_model(model):
    if not model:
        return "bilinmeyen"
    m = model.replace("claude-", "")
    parts = m.split("-")
    fam = next((p for p in parts if p.isalpha()), parts[0])
    nums = [p for p in parts if p.isdigit() and len(p) < 5]
    ver = ".".join(nums[:2])
    return (fam.capitalize() + (" " + ver if ver else "")).strip()

def _home_encoded():
    h = os.path.expanduser("~")
    return h.replace(":", "-").replace("\\", "-").replace("/", "-")

def friendly_project(folder):
    home = _home_encoded()
    if folder == home:
        return "(home)"
    if folder.startswith(home + "-"):
        folder = folder[len(home) + 1:]
    toks = [t for t in folder.split("-") if t]
    if not toks:
        return folder
    if len(toks) >= 2:
        return toks[-2] + "/" + toks[-1] if len(toks[-1]) <= 14 else toks[-1]
    return toks[-1]

def _parse_file(path):
    out = []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line or '"usage"' not in line:
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                msg = o.get("message")
                if not isinstance(msg, dict):
                    continue
                usage = msg.get("usage")
                if not isinstance(usage, dict):
                    continue
                ts = o.get("timestamp")
                if not ts:
                    continue
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()
                except Exception:
                    continue

                tin = int(usage.get("input_tokens", 0) or 0)
                tout = int(usage.get("output_tokens", 0) or 0)
                tcr = int(usage.get("cache_read_input_tokens", 0) or 0)
                cw5 = cw1 = 0
                cc = usage.get("cache_creation")
                if isinstance(cc, dict):
                    cw5 = int(cc.get("ephemeral_5m_input_tokens", 0) or 0)
                    cw1 = int(cc.get("ephemeral_1h_input_tokens", 0) or 0)
                else:
                    cw5 = int(usage.get("cache_creation_input_tokens", 0) or 0)
                if not (tin or tout or tcr or cw5 or cw1):
                    continue

                model = msg.get("model") or o.get("model")
                key = (msg.get("id") or "") + "|" + (o.get("requestId") or "")
                if key == "|":
                    key = path + "|" + ts + "|" + str(len(out))

                out.append((key, dt.timestamp(), dt.strftime("%Y-%m-%d"),
                            model, tin, tout, cw5, cw1, tcr))
    except Exception:
        pass
    return out

def _blank():
    return {"in": 0, "out": 0, "cw": 0, "cr": 0, "cost": 0.0, "calls": 0, "tok": 0}

def _add(b, tin, tout, cw, cr, cost):
    b["in"] += tin
    b["out"] += tout
    b["cw"] += cw
    b["cr"] += cr
    b["cost"] += cost
    b["calls"] += 1
    b["tok"] += tin + tout + cw + cr

class UsageScanner:
    def __init__(self):
        self._cache = {}

    def _files(self):
        if not os.path.isdir(PROJECTS_DIR):
            return []
        return glob.glob(os.path.join(PROJECTS_DIR, "**", "*.jsonl"), recursive=True)

    def scan(self, window_hours=5, weekly_weekday=6, weekly_hour=18):
        files = sorted(self._files())
        live = set(files)
        for p in list(self._cache):
            if p not in live:
                del self._cache[p]

        all_entries = []
        for p in files:
            try:
                st = os.stat(p)
            except OSError:
                continue
            cached = self._cache.get(p)
            if cached and cached[0] == st.st_mtime and cached[1] == st.st_size:
                project, entries = cached[2], cached[3]
            else:
                rel = os.path.relpath(p, PROJECTS_DIR)
                project = friendly_project(rel.split(os.sep)[0])
                entries = _parse_file(p)
                self._cache[p] = (st.st_mtime, st.st_size, project, entries)
            for e in entries:
                all_entries.append((project, e))

        return self._aggregate(all_entries, window_hours, weekly_weekday, weekly_hour)

    def _aggregate(self, all_entries, window_hours, weekly_weekday=6, weekly_hour=18):
        seen = set()
        by_day = {}
        by_model = {}
        by_project = {}
        recs = []

        for project, e in all_entries:
            key, ts, day, model, tin, tout, cw5, cw1, tcr = e
            if key in seen:
                continue
            seen.add(key)
            p = _price(model)
            cost = (tin * p["in"] + tout * p["out"] + cw5 * p["cw5"]
                    + cw1 * p["cw1"] + tcr * p["cr"]) / 1_000_000.0
            cw = cw5 + cw1
            recs.append((ts, tin, tout, cw, tcr, cost))
            _add(by_day.setdefault(day, _blank()), tin, tout, cw, tcr, cost)
            _add(by_model.setdefault(friendly_model(model), _blank()), tin, tout, cw, tcr, cost)
            _add(by_project.setdefault(project, _blank()), tin, tout, cw, tcr, cost)

        now = time.time()

        recs.sort(key=lambda r: r[0])
        W = window_hours * 3600
        blocks = []
        for r in recs:
            if not blocks or r[0] >= blocks[-1][0] + W:
                blocks.append([r[0], []])
            blocks[-1][1].append(r)

        session = _blank()
        session["hours"] = window_hours
        session["active"] = False
        session["reset_in"] = None
        session["start"] = None
        if blocks:
            start, items = blocks[-1]
            if now < start + W:
                for ts, tin, tout, cw, tcr, cost in items:
                    _add(session, tin, tout, cw, tcr, cost)
                session["active"] = True
                session["reset_in"] = int(start + W - now)
                session["start"] = start

        now_dt = datetime.now().astimezone()
        days_since = (now_dt.weekday() - weekly_weekday) % 7
        wk_start_dt = (now_dt - timedelta(days=days_since)).replace(
            hour=weekly_hour, minute=0, second=0, microsecond=0)
        if wk_start_dt > now_dt:
            wk_start_dt -= timedelta(days=7)
        wk_start = wk_start_dt.timestamp()
        wk_reset_dt = wk_start_dt + timedelta(days=7)
        week = _blank()
        week["start"] = wk_start
        week["reset_in"] = int(wk_reset_dt.timestamp() - now)
        week["reset_at"] = wk_reset_dt
        for ts, tin, tout, cw, tcr, cost in recs:
            if ts >= wk_start:
                _add(week, tin, tout, cw, tcr, cost)

        today = datetime.now().astimezone().date()

        def cal_window(days):
            agg = _blank()
            for d, b in by_day.items():
                try:
                    dd = datetime.strptime(d, "%Y-%m-%d").date()
                except ValueError:
                    continue
                if 0 <= (today - dd).days < days:
                    for k in agg:
                        agg[k] += b[k]
            return agg

        all_agg = _blank()
        for b in by_day.values():
            for k in all_agg:
                all_agg[k] += b[k]

        series = []
        for i in range(6, -1, -1):
            d = today - timedelta(days=i)
            b = by_day.get(d.strftime("%Y-%m-%d"), _blank())
            series.append((d, b["tok"], b["cost"]))

        model_list = sorted(
            [(m, b["tok"], b["cost"]) for m, b in by_model.items()],
            key=lambda x: x[2], reverse=True)
        project_list = sorted(
            [(pr, b["tok"], b["cost"]) for pr, b in by_project.items()],
            key=lambda x: x[2], reverse=True)

        return {
            "session": session,
            "week": week,
            "today": cal_window(1),
            "month": cal_window(30),
            "all": all_agg,
            "series": series,
            "by_model": model_list,
            "by_project": project_list,
            "updated": datetime.now().astimezone().strftime("%H:%M:%S"),
        }

def fmt_tok(n):
    n = float(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(int(n))

def fmt_cost(c):
    if c >= 1000:
        return f"${c:,.0f}"
    return f"${c:.2f}"

def fmt_duration(sec):
    if sec is None or sec <= 0:
        return "—"
    sec = int(sec)
    h, m = sec // 3600, (sec % 3600) // 60
    if h > 0:
        return f"{h} sa {m} dk"
    return f"{m} dk"

if __name__ == "__main__":
    s = UsageScanner().scan(window_hours=5)
    se = s["session"]
    print("Claude Code kullanimi (yerel):")
    if se["active"]:
        print(f"  5sa pencere : {fmt_tok(se['tok']):>9}  {fmt_cost(se['cost']):>9}  "
              f"| {fmt_duration(se['reset_in'])} sonra sifirlanir  ({se['calls']} cagri)")
    else:
        print("  5sa pencere : bos (ilk istekte yeni pencere baslar)")
    wk = s["week"]
    print(f"  Haftalik   : {fmt_tok(wk['tok']):>9}  {fmt_cost(wk['cost']):>9}  "
          f"| {fmt_duration(wk['reset_in'])} sonra ({wk['calls']} cagri)")
    for name, b in (("Bugun", s["today"]), ("30 gun", s["month"]), ("Toplam", s["all"])):
        print(f"  {name:11}: {fmt_tok(b['tok']):>9}  {fmt_cost(b['cost']):>9}  ({b['calls']} cagri)")
    print("\nModele gore:")
    for m, t, c in s["by_model"]:
        print(f"  {m:14} {fmt_tok(t):>9}  {fmt_cost(c):>9}")
