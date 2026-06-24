import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from usage_core import UsageScanner, fmt_cost

LIM = os.path.join(os.path.dirname(os.path.abspath(__file__)), "limits.json")
DEF = {"window_hours": 5, "weekly_reset_weekday": 6, "weekly_reset_hour": 18,
       "plan_label": "", "session_cap_tokens": None, "weekly_cap_tokens": None,
       "session_cap_usd": None, "weekly_cap_usd": None}

def main():
    try:
        lim = json.load(open(LIM, encoding="utf-8"))
    except Exception:
        lim = {}
    for k, v in DEF.items():
        lim.setdefault(k, v)

    wh = int(lim.get("window_hours") or 5)
    s = UsageScanner().scan(window_hours=wh,
                            weekly_weekday=int(lim.get("weekly_reset_weekday", 6)),
                            weekly_hour=int(lim.get("weekly_reset_hour", 18)))
    sc = s["session"]["cost"]
    wc = s["week"]["cost"]
    print(f"Su anki yerel tuketim:  oturum {fmt_cost(sc)}   haftalik {fmt_cost(wc)}")

    args = sys.argv[1:]
    try:
        if len(args) >= 2:
            sp, wp = float(args[0]), float(args[1])
        else:
            sp = float(input("Claude Desktop > OTURUM yuzdesi (orn 10): ").strip() or "0")
            wp = float(input("Claude Desktop > HAFTALIK (tum modeller) yuzdesi (orn 8): ").strip() or "0")
    except ValueError:
        print("Gecersiz sayi.")
        return

    if sp > 0 and sc > 0:
        lim["session_cap_usd"] = round(sc / (sp / 100.0), 2)
    if wp > 0 and wc > 0:
        lim["weekly_cap_usd"] = round(wc / (wp / 100.0), 2)
    lim["session_cap_tokens"] = None
    lim["weekly_cap_tokens"] = None

    json.dump(lim, open(LIM, "w", encoding="utf-8"), indent=2)
    print(f"Kaydedildi -> session_cap_usd={lim['session_cap_usd']}  "
          f"weekly_cap_usd={lim['weekly_cap_usd']}")
    print("Widget'i kapat-ac (veya yeni Claude Code oturumu) -> yuzdeler guncellenir.")

if __name__ == "__main__":
    main()
