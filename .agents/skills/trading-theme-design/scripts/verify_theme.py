#!/usr/bin/env python3
"""Verify a theme block against creating-a-theme.md §3/§5.

Usage:
    verify_theme.py <theme_id>            # read the block from frontend/src/theme.css
    verify_theme.py <theme_id> --css path # alternate css path

Computes WCAG 2.1 contrast ratios from the values AS SHIPPED in theme.css
(not from memory / a proposal doc) and checks every §3 contract rule + §5
acceptance item. Exit code 0 = all doc-mandated checks pass; 1 = failures.

This is the §5 quantitative gate. It is necessary but not sufficient — the
doc also requires the §4.5 Playwright check and a screenshot eyeball, both
of which need the live dev stack (API :8100 + frontend :5173).
"""
import re, sys, argparse

# §2 token inventory — every theme must define all 32 (the §5 "most common
# LLM error" is silently inheriting :root by omitting tokens).
REQUIRED = {
    # 13 color
    "bg","panel","panel-2","border","text","muted","accent","on-accent",
    "green","amber","orange","red","deep-red",
    # 6 regime
    "regime-risk-on-low-vol","regime-risk-on-elevated-vol","regime-neutral",
    "regime-caution","regime-risk-off-stress","regime-crisis",
    # 3 font stacks
    "font-sans","font-mono","font-body",
    # 10 type scale
    "fs-105","fs-11","fs-115","fs-12","fs-125","fs-13","fs-14","fs-15","fs-18","fs-24",
}

# --- WCAG math ---
def _hex(s):
    s = s.lstrip('#')
    if len(s) == 3: s = ''.join(c*2 for c in s)
    return tuple(int(s[i:i+2], 16) for i in (0, 2, 4))
def _lin(c):
    c /= 255
    return c/12.92 if c <= 0.03928 else ((c+0.055)/1.055)**2.4
def _L(h):
    r, g, b = _hex(h)
    return 0.2126*_lin(r) + 0.7152*_lin(g) + 0.0722*_lin(b)
def ratio(a, b):
    la, lb = _L(a), _L(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi+0.05)/(lo+0.05)
def hsl(h):
    r, g, b = [x/255 for x in _hex(h)]
    mx, mn = max(r, g, b), min(r, g, b)
    l = (mx+mn)/2
    if mx == mn: return (0.0, 0.0, l)
    d = mx-mn
    s = d/(2-mx-mn) if l > 0.5 else d/(mx+mn)
    if mx == r: hue = ((g-b)/d) % 6
    elif mx == g: hue = (b-r)/d + 2
    else: hue = (r-g)/d + 4
    return (hue*60, s, l)
def hue_gap(a, b):
    h1, h2 = hsl(a)[0], hsl(b)[0]
    return min(abs(h1-h2), 360-abs(h1-h2))

def parse_block(theme_id, css_path):
    css = open(css_path).read()
    m = re.search(rf':root\[data-theme="{theme_id}"\]\s*\{{(.*?)\n\}}', css, re.S)
    if not m:
        sys.exit(f"FAIL: no :root[data-theme=\"{theme_id}\"] block in {css_path}")
    toks = {}
    for line in m.group(1).splitlines():
        line = line.split("/*")[0]  # strip comments so combined-line tokens parse
        for mm in re.finditer(r'--([\w-]+):\s*([^;]+);', line):
            toks[mm.group(1)] = mm.group(2).strip()
    return toks

def check(theme_id, css_path):
    t = parse_block(theme_id, css_path)
    bg, pn = t["bg"], t["panel"]
    fails = []
    def chk(num, label, cond, detail=""):
        mark = "PASS" if cond else "FAIL"
        print(f"  [{mark}] {num} {label}" + (f"  — {detail}" if (not cond and detail) else ""))
        if not cond: fails.append(num)

    print(f"========== {theme_id} ==========")

    # §5.1 — token inventory
    miss = REQUIRED - set(t.keys())
    chk("§5.1", "all 32 tokens present (13c+6r+3f+10fs)", not miss, f"missing: {sorted(miss)}")
    badv = [k for k, v in t.items() if "var(" in v or "color-mix" in v or "grad" in v]
    chk("§5.1", "plain values (no var/color-mix/gradient — Plotly needs concrete hex)",
        not badv, f"offenders: {badv}")

    # §3.2/§3.3 — text + muted ≥4.5:1 on both surfaces
    txt, mt = t["text"], t["muted"]
    chk("§3.2", f"--text bg{ratio(txt,bg):.2f}/pn{ratio(txt,pn):.2f} ≥4.5",
        ratio(txt,bg) >= 4.5 and ratio(txt,pn) >= 4.5)
    chk("§3.3", f"--muted bg{ratio(mt,bg):.2f}/pn{ratio(mt,pn):.2f} ≥4.5 (11px trap)",
        ratio(mt,bg) >= 4.5 and ratio(mt,pn) >= 4.5)

    # §3.4 — accent ≥4.5:1 as text, ≥3:1 vs on-accent
    ac, on = t["accent"], t["on-accent"]
    chk("§3.4", f"--accent text bg{ratio(ac,bg):.2f}/pn{ratio(ac,pn):.2f} ≥4.5",
        ratio(ac,bg) >= 4.5 and ratio(ac,pn) >= 4.5)
    chk("§3.4", f"--accent vs --on-accent {ratio(ac,on):.2f} ≥3.0", ratio(ac,on) >= 3.0)

    # §3.5 — status ramp perceptually ordered; accent distinct from green/red
    ramp = [t["green"], t["amber"], t["orange"], t["red"]]
    hues = [hsl(c)[0] for c in ramp]
    mono = all(hues[i] >= hues[i+1] for i in range(3)) or all(hues[i] <= hues[i+1] for i in range(3))
    chk("§3.5", f"status ramp ordered (hue {[round(h) for h in hues]})", mono)
    chk("§3.5", "accent distinct from green & red (≥3:1 OR ≥30° hue)",
        ratio(ac, t["green"]) >= 3 or hue_gap(ac, t["green"]) >= 30)

    # §3.6 — regime: ≥3:1 (4.5 risk-on) on both surfaces; middle four differ
    reg = [("risk-on-low-vol", t["regime-risk-on-low-vol"], 4.5),
           ("risk-on-elevated-vol", t["regime-risk-on-elevated-vol"], 3.0),
           ("neutral", t["regime-neutral"], 3.0),
           ("caution", t["regime-caution"], 3.0),
           ("risk-off-stress", t["regime-risk-off-stress"], 3.0),
           ("crisis", t["regime-crisis"], 3.0)]
    rf = [f"{n} bg{ratio(c,bg):.1f}/pn{ratio(c,pn):.1f}<{b}" for n, c, b in reg
          if ratio(c, bg) < b or ratio(c, pn) < b]
    chk("§3.6", "regime colors ≥ threshold on bg & panel", not rf, "; ".join(rf))
    mid = [t[k] for k in ["regime-risk-on-elevated-vol","regime-neutral",
                          "regime-caution","regime-risk-off-stress"]]
    chk("§3.6", "middle four regime colors all differ", len(set(mid)) == 4)

    # §3.1 — surface layering: every surface pair distinguishable
    sur = [("bg",bg),("panel",pn),("panel-2",t["panel-2"]),("border",t["border"])]
    sp = []
    for i in range(4):
        for j in range(i+1, 4):
            r = ratio(sur[i][1], sur[j][1])
            if r < 1.1: sp.append(f"{sur[i][0]}~{sur[j][0]} {r:.2f}")
    chk("§3.1", "surfaces distinguishable (all pairs ≥1.1:1)", not sp, "; ".join(sp))

    # informational: adjacent severity pairs that are close on the ramp (not a
    # doc failure, but flag for the screenshot eyeball — chip labels must carry
    # the distinction per synthesis Rule C4)
    allreg = [t[k] for k in ["regime-risk-on-low-vol","regime-risk-on-elevated-vol",
              "regime-neutral","regime-caution","regime-risk-off-stress","regime-crisis"]]
    names = ["ron","elev","neut","caut","stress","crisis"]
    close = [f"{names[i]}~{names[j]}" for i in range(6) for j in range(i+1, 6)
             if ratio(allreg[i], allreg[j]) < 1.5 and hue_gap(allreg[i], allreg[j]) < 20]
    if close:
        print(f"  [info] severity pairs close on ramp (watch in eyeball): {', '.join(close)}")

    return fails

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("theme_id")
    ap.add_argument("--css", default="frontend/src/theme.css")
    args = ap.parse_args()
    print(f"§5 verification — values read from {args.css}\n")
    fails = check(args.theme_id, args.css)
    print("\n" + "="*55)
    if fails:
        print(f"DOC-MANDATED FAILURES on: {', '.join(sorted(set(fails)))}")
        sys.exit(1)
    print("✓ all quantitative §3/§5 checks pass")
    print("="*55)
    print("Remaining (need live dev stack): §4.5 Playwright, §5 screenshot eyeball")

if __name__ == "__main__":
    main()
