# 2-Nov-2026: per-strategy BRAKE (max BTC held) changeable from the control page, mid-cycle, no edit/restart.
# control.json[<key>]["brake_btc"] (None = the strategy's default: 0.28, v10 0.40). Read every step by the paper ladders
# (bot.py v9, variants.py v10/v11/v12/v13) and by the live runner (ladderlive.py, takes effect at its next restart).
# Raising it mid-cycle makes the ladder buy the missed levels one by one at the market; lowering it just stops new buys.
# All-or-nothing: every file is checked first, then all are written. Idempotent; backups *.bak_brake.
import os, sys, shutil
H = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/deltabot")
NEW = {}


def rd(n):
    return open(os.path.join(H, n), encoding="utf-8").read()


def rep(name, s, a, b, cnt=1):
    if s.count(a) != cnt:
        raise SystemExit("ANCHOR PROBLEM in %s (%d hits): %r - nothing written" % (name, s.count(a), a[:70]))
    return s.replace(a, b)


# ---- control.py
s = rd("control.py")
if "def brake_for" not in s:
    s += '''

# ---- per-strategy brake (max BTC held), 2-Nov-2026. None = default.
DEFAULT_BRAKE = {"lv10": 0.40}


def brake_for(name):
    """Effective brake in BTC for a strategy key (custom value from control.json, else the default)."""
    try:
        b = load().get(name, {}).get("brake_btc")
        if b:
            return float(b)
    except Exception:
        pass
    return DEFAULT_BRAKE.get(name, 0.28)


def set_brake(name, btc):
    """btc None / 0 = back to default. Allowed 0.01 .. 1.0 BTC."""
    if name not in NAMES:
        raise ValueError("bad strategy")
    d = load()
    if btc:
        btc = float(btc)
        if not (0.01 <= btc <= 1.0):
            raise ValueError("brake out of range")
        d[name]["brake_btc"] = round(btc, 3)
    else:
        d[name].pop("brake_btc", None)
    d[name]["brake_changed"] = time.strftime("%Y-%m-%d %H:%M:%S")
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    tmp = PATH + ".tmp"
    json.dump(d, open(tmp, "w"))
    os.replace(tmp, PATH)
'''
NEW["control.py"] = s

# ---- bot.py (v9 paper ladder)
s = rd("bot.py")
if "brake_for(" not in s:
    s = rep("bot.py", s, '        ctl = control.get("ladder")\n',
            '        ctl = control.get("ladder")\n'
            '        try:  # per-strategy brake from the control page (2-Nov-2026)\n'
            '            self.ladder.brake = max(1, int(round(control.brake_for("ladder") / BTC_PER_CONTRACT * self.ladder.scale)))\n'
            '        except Exception as _e:\n'
            '            log.error("brake read: %s", _e)\n')
NEW["bot.py"] = s

# ---- variants.py (v10 / v11 / v12 / v13 paper ladders)
s = rd("variants.py")
if "brake_for(" not in s:
    s = rep("variants.py", s, '            ctl = control.get(self.key)\n',
            '            ctl = control.get(self.key)\n'
            '            try:  # per-strategy brake from the control page (2-Nov-2026)\n'
            '                self.ladder.brake = max(1, int(round(control.brake_for(self.key) / BTC_PER_CONTRACT * self.ladder.scale)))\n'
            '            except Exception as _e:\n'
            '                bot.log.error("[%s] brake read: %s", self.key, _e)\n')
NEW["variants.py"] = s

# ---- ladderlive.py (live runner: same brake, applied each live step; hold limit follows it)
try:
    s = rd("ladderlive.py")
    if "brake_for(" not in s:
        s = rep("ladderlive.py", s, '            self.cfg = load_cfg()[self.live_key]\n',
                '            self.cfg = load_cfg()[self.live_key]\n'
                '            try:  # per-strategy brake from the control page (2-Nov-2026)\n'
                '                import control as _ctl\n'
                '                self.ladder.brake = max(1, int(round(_ctl.brake_for(self.live_key) / C * self.ladder.scale)))\n'
                '            except Exception as _e:\n'
                '                log.error("%s brake read: %s", self.live_key, _e)\n')
    NEW["ladderlive.py"] = s
except FileNotFoundError:
    print("ladderlive.py not found, skipped")

# ---- ui.py: brake shown on the card + "Set brake" form + /brake route
s = rd("ui.py")
if "/brake" not in s:
    s = rep("ui.py", s, '                      note="%d resting orders%s" % (len(st.get("orders", {})), extra),\n',
            '                      note="%d resting orders%s | brake %.2f BTC%s" % (len(st.get("orders", {})), extra, control.brake_for(sid_), " (set from page)" if ctl[sid_].get("brake_btc") else ""),\n')
    s = rep("ui.py", s, "        h.append('<details><summary>Open positions (live P&amp;L)</summary>",
            "        if isl(sid):\n"
            "            _bk = control.brake_for(sid)\n"
            "            h.append('<form method=\"post\" style=\"display:inline-block;margin:4px 0\" onsubmit=\"this.action=\\'/brake?s=%s&b=\\'+encodeURIComponent(this.b.value);return confirm(\\'Set the maximum BTC this ladder may hold to \\'+this.b.value+\\' BTC? Lower = no new buys above it; higher = it buys the missed levels at the market. Make sure the money is in the account first.\\')\">'\n"
            "                     '<span class=\"lab\">Brake (max BTC held)</span> <input name=\"b\" type=\"number\" step=\"0.01\" min=\"0.01\" max=\"1\" value=\"%.2f\" style=\"width:70px\"> '\n"
            "                     '<button class=\"bk\">Set brake</button> <span class=\"m\">0 = default</span></form>' % (sid, _bk))\n"
            "        h.append('<details><summary>Open positions (live P&amp;L)</summary>")
    s = rep("ui.py", s, '            elif p == "/deploy":\n',
            '            elif p == "/brake":\n'
            '                _b = float(q.get("b", "0") or 0)\n'
            '                control.set_brake(q["s"], _b if _b > 0 else None)\n'
            '            elif p == "/deploy":\n')
NEW["ui.py"] = s

# ---- write all (only now)
for n, s in NEW.items():
    p = os.path.join(H, n)
    if open(p, encoding="utf-8").read() == s:
        print(n, "already patched")
        continue
    if not os.path.exists(p + ".bak_brake"):
        shutil.copy2(p, p + ".bak_brake")
    open(p, "w", encoding="utf-8").write(s)
    print(n, "patched")
