#!/usr/bin/env python3
"""WCAG 2.2 contrast audit/fix for CyberPanel themes.

Checks every theme's design.css:
  - text vs background pairs at 4.5:1 (WCAG 1.4.3)
  - accent-as-link vs backgrounds at 4.5:1
  - focus ring vs backgrounds at 3:1 (WCAG 1.4.11 / 2.4.13-adjacent)
  - outline suppression (outline: none / 0)

Understands both variable vocabularies:
  - v2 themes: the current design tokens (--bg-primary, --text-primary, …)
  - legacy themes: the pre-2.4 UI variables, audited against how the panel's
    cyberpanel-theme-bridge.css maps them onto the tokens

Vars a theme omits resolve to the value the panel would actually use
(stock light tokens), so "dark bg + inherited dark text" failures surface.

Usage: python3 tools/contrast_audit.py [--fix] [themes-root]
  --fix  minimally adjust failing colors (hue-preserving lightness moves)
         and ensure every theme defines a compliant --focus-ring.
"""
import os, re, sys, colorsys

FIX = '--fix' in sys.argv
COMPLETE = '--complete' in sys.argv
DARK = '--dark' in sys.argv
ROOT = next((a for a in sys.argv[1:] if not a.startswith('-')), '.')

# Stock DARK tokens (the [data-theme=dark] block): what an undefined var
# resolves to when the user has the dark-mode toggle on. Run with --dark to
# audit that mode — a theme passes WCAG only if it passes BOTH modes.
DEFAULTS_DARK = {
    'bg-primary': '#15161b', 'bg-secondary': '#1d1f26', 'bg-sidebar': '#191a20',
    'bg-hover': '#272a33', 'text-primary': '#e4e4e7', 'text-secondary': '#9aa1ad',
    'text-heading': '#f3f4f6', 'accent-color': '#7c7ff3', 'text-on-accent': '#15161b',
    'accent-hover': '#8b8ef5', 'focus-ring': '#a5a3f0',
    'bg-muted': '#1d1f26', 'bg-code': '#23252d',
    'table-head-bg': '#3b3f9e', 'table-head-text': '#f3f4f6',
    'sidebar-text': '#9aa1ad', 'sidebar-text-muted': '#9aa1ad',
    'sidebar-section-bg': '#7c7ff3', 'sidebar-section-text': '#ffffff',
    'sidebar-item-hover-bg': '#272a33', 'sidebar-item-hover-text': '#7c7ff3',
}

# Stock light tokens = what an undefined var falls back to (panel + bridge)
DEFAULTS = {
    'bg-primary': '#f6f7f9', 'bg-secondary': '#ffffff', 'bg-sidebar': '#fbfbfc',
    'bg-hover': '#eef0f4', 'text-primary': '#2f3640', 'text-secondary': '#6b7280',
    'text-heading': '#1e293b', 'accent-color': '#5856d6', 'text-on-accent': '#ffffff',
    'focus-ring': '#5856d6',
    'sidebar-text': '#6b7280', 'sidebar-text-muted': '#6b7280',
    'sidebar-section-bg': '#5856d6', 'sidebar-section-text': '#ffffff',
    'sidebar-item-hover-bg': '#eef0f4', 'sidebar-item-hover-text': '#5856d6',
    'accent-hover': '#4644c0', 'bg-muted': '#f6f7f9', 'bg-code': '#f3f4f6',
    'table-head-bg': '#5b5fcf', 'table-head-text': '#ffffff',
}
if DARK:
    DEFAULTS = DEFAULTS_DARK
# token -> token it falls back to in the panel CSS when undefined
FALLBACK_TOKEN = {
    'sidebar-text': 'text-secondary', 'sidebar-text-muted': 'text-secondary',
    'sidebar-item-hover-bg': 'bg-hover', 'sidebar-item-hover-text': 'accent-color',
    'sidebar-section-bg': 'accent-color',
}

# legacy var -> token it bridges to
BRIDGE = {
    'background-color-second': 'bg-primary', 'background-color-third': 'bg-secondary',
    'sidebar-background': 'bg-sidebar', 'background-color-first': 'bg-sidebar',
    'hover-background-color': 'bg-hover', 'sidebar-hover-background': 'bg-hover',
    'content-text-color': 'text-primary', 'link-color-first': 'text-primary',
    'text-color-first': 'text-heading',
}
# extra self-consistent legacy pairs (checked directly, not via bridge)
LEGACY_PAIRS = [
    ('sidebar-color', 'sidebar-background', 4.5),
    ('sidebar-hover-text-color', 'sidebar-hover-background', 4.5),
    ('sidebar-header-text-color', 'sidebar-header-background', 4.5),
    ('sidebar-submenu-color', 'sidebar-submenu-background', 4.5),
    ('hover-text-color', 'hover-background-color', 4.5),
    ('resources-text-color', 'resources-background', 4.5),
]
TOKEN_PAIRS = [
    ('text-primary', 'bg-primary', 4.5), ('text-primary', 'bg-secondary', 4.5),
    ('text-primary', 'bg-sidebar', 4.5), ('text-primary', 'bg-hover', 4.5),
    ('text-secondary', 'bg-primary', 4.5), ('text-secondary', 'bg-secondary', 4.5),
    ('text-heading', 'bg-primary', 4.5), ('text-heading', 'bg-secondary', 4.5),
    ('text-on-accent', 'accent-color', 4.5),
    ('accent-color', 'bg-primary', 4.5), ('accent-color', 'bg-secondary', 4.5),
    ('focus-ring', 'bg-primary', 3.0), ('focus-ring', 'bg-secondary', 3.0),
    ('focus-ring', 'bg-sidebar', 3.0),
    ('sidebar-text', 'bg-sidebar', 4.5),
    ('sidebar-section-text', 'sidebar-section-bg', 4.5),
    ('sidebar-item-hover-text', 'sidebar-item-hover-bg', 4.5),
    ('text-primary', 'bg-muted', 4.5), ('text-primary', 'bg-code', 4.5),
    ('table-head-text', 'table-head-bg', 4.5),
    ('text-on-accent', 'accent-hover', 4.5),
]
NAMED = {'white': '#ffffff', 'black': '#000000', 'transparent': None}


def parse_color(v, under='#ffffff'):
    if v is None:
        return None
    v = v.strip().lower()
    if v in NAMED:
        v = NAMED[v]
        if v is None:
            return None
    m = re.match(r'#([0-9a-f]{3})$', v)
    if m:
        return tuple(int(c * 2, 16) for c in m.group(1))
    m = re.match(r'#([0-9a-f]{6})', v)
    if m:
        h = m.group(1)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    m = re.match(r'rgba?\(([^)]+)\)', v)
    if m:
        parts = [p.strip() for p in m.group(1).split(',')]
        rgb = tuple(int(float(p)) for p in parts[:3])
        if len(parts) == 4:
            a = float(parts[3])
            ub = parse_color(under) or (255, 255, 255)
            rgb = tuple(round(a * c + (1 - a) * u) for c, u in zip(rgb, ub))
        return rgb
    m = re.search(r'#([0-9a-f]{6}|[0-9a-f]{3})', v)  # first stop of a gradient
    if m:
        return parse_color('#' + m.group(1))
    return None


def lum(rgb):
    def f(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (f(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(a, b):
    la, lb = lum(a), lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def hex_of(rgb):
    return '#%02x%02x%02x' % rgb


def adjust(fg, bgs, need):
    """Hue-preserving lightness walk of fg until it meets `need` vs every bg.
    Tries the away-from-background direction first, then the opposite (e.g.
    white text on a mid-tone accent must flip dark, not get lighter)."""
    h, l0, s = colorsys.rgb_to_hls(*(c / 255 for c in fg))
    avg = sum(lum(b) for b in bgs) / len(bgs)
    for step in ((0.02, -0.02) if avg < 0.5 else (-0.02, 0.02)):
        l = l0
        for _ in range(60):
            rgb = colorsys_rgb(h, l, s)
            if all(ratio(rgb, b) >= need for b in bgs):
                return rgb
            nl = min(1.0, max(0.0, l + step))
            if nl == l:
                break
            l = nl
    return None


def colorsys_rgb(h, l, s):
    return tuple(round(c * 255) for c in colorsys.hls_to_rgb(h, l, s))


def get_vars(css):
    """name -> (value, is_declared). Later declarations win, like the cascade."""
    out = {}
    for m in re.finditer(r'--([a-z0-9-]+)\s*:\s*([^;}]+)[;}]', css, re.I):
        out[m.group(1).lower()] = m.group(2).strip()
    return out


def shade(rgb, delta):
    """shift lightness by delta (darken if positive luminance direction given)"""
    h, l, sv = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
    return colorsys_rgb(h, min(1.0, max(0.0, l + delta)), sv)


def complete_theme(decl):
    """Tokens to pin so the theme renders identically in light and dark mode
    (any token left unset flips with the [data-theme] toggle)."""
    if 'bg-primary' not in decl:
        return {}
    get = lambda t, d=None: decl.get(t, d)
    bgp = parse_color(get('bg-primary'))
    if not bgp:
        return {}
    dark_theme = lum(bgp) < 0.5
    step = 0.06 if dark_theme else -0.06
    out = {}
    def pin(tok, val):
        if tok not in decl and val:
            out[tok] = val if isinstance(val, str) else hex_of(val)
    pin('bg-secondary', get('bg-primary'))
    bgs_v = get('bg-secondary', out.get('bg-secondary', get('bg-primary')))
    pin('bg-sidebar', get('bg-primary'))
    pin('bg-hover', shade(bgp, step))
    pin('bg-muted', get('bg-primary'))
    pin('bg-code', shade(bgp, step * 1.4))
    pin('text-secondary', get('text-primary'))
    pin('text-heading', get('text-primary'))
    acc_v = get('accent-color')
    if acc_v:
        acc = parse_color(acc_v)
        if acc:
            pin('accent-hover', shade(acc, 0.08 if dark_theme else -0.08))
            if 'text-on-accent' not in decl:
                pin('text-on-accent', '#ffffff' if ratio((255, 255, 255), acc) >= ratio((16, 16, 16), acc) else '#101010')
            pin('table-head-bg', acc_v)
            pin('table-head-text', get('text-on-accent', out.get('text-on-accent')))
            pin('focus-ring', acc_v)
        pin('border-color', hex_of(shade(bgp, step * 2)))
    return out


report, total_fail, total_fixed = [], 0, 0
# legacy-* dirs are archived pre-2.4 theme versions kept for history; they are
# superseded by their *-v2 ports and no longer served by the panel's catalog.
themes = sorted(d for d in os.listdir(ROOT)
                if os.path.isdir(os.path.join(ROOT, d)) and not d.startswith(('.', 'tools', 'legacy-')))
for theme in themes:
    path = os.path.join(ROOT, theme, 'design.css')
    if not os.path.exists(path):
        continue
    css = open(path, encoding='utf-8', errors='replace', newline='').read()
    decl = get_vars(css)
    if COMPLETE:
        add = complete_theme(decl)
        if add:
            nl = '\r\n' if '\r\n' in css else '\n'
            block = (nl * 2 + '/* Mode-invariance: pin every token the dark/light toggle would' + nl
                     + '   otherwise flip, so the theme renders identically in both modes. */' + nl
                     + ':root {' + nl)
            block += ''.join('    --%s: %s;%s' % (k, v, nl) for k, v in sorted(add.items()))
            block += '}' + nl
            css += block
            open(path, 'w', encoding='utf-8', newline='').write(css)
            decl = get_vars(css)
    legacy = 'bg-primary' not in decl

    def resolve(token):
        """effective value of a design token for this theme (declared, bridged, or default)"""
        cands = [token] if not legacy else \
            [v for v, t in BRIDGE.items() if t == token] or [token]
        if not legacy:
            if token in decl:
                return decl[token], token
        else:
            for v in cands:
                if v in decl:
                    return decl[v], v
        if token in FALLBACK_TOKEN:
            return resolve(FALLBACK_TOKEN[token])
        return DEFAULTS.get(token), None

    fails, fixes = [], {}   # fixes: declared-var-name -> new hex
    pairs = list(TOKEN_PAIRS)
    checked = set()
    for fg_t, bg_t, need in pairs:
        fg_v, fg_src = resolve(fg_t)
        bg_v, _ = resolve(bg_t)
        fg = parse_color(fg_v, under=bg_v)
        bg = parse_color(bg_v)
        if not fg or not bg:
            continue
        r = ratio(fg, bg)
        if r < need:
            # sidebar-* pairs: fix by declaring the sidebar token itself, never
            # by mutating the token it falls back to (e.g. the theme accent)
            if fg_t.startswith('sidebar-'):
                fg_src = None
            fails.append((fg_t, bg_t, r, need, fg_src))
    if legacy:
        for fg_v, bg_v_name, need in LEGACY_PAIRS:
            if fg_v not in decl or bg_v_name not in decl:
                continue
            fg = parse_color(decl[fg_v], under=decl[bg_v_name])
            bg = parse_color(decl[bg_v_name])
            if not fg or not bg:
                continue
            r = ratio(fg, bg)
            if r < need:
                fails.append((fg_v, bg_v_name, r, need, fg_v))

    outline_kill = re.findall(r'outline\s*:\s*(?:none|0)\b', css)

    if FIX and (fails or legacy or 'focus-ring' not in decl):
        # group failures by the declared var we can change
        by_src = {}
        for fg_t, bg_t, r, need, src in fails:
            by_src.setdefault((src or fg_t, need), set()).add(bg_t)
        newcss = css
        for (src, need), bg_tokens in sorted(by_src.items()):
            bgs = []
            for bt in bg_tokens:
                if legacy and bt in decl:      # legacy self-pair: bg name is a var
                    bgs.append(parse_color(decl[bt]))
                else:
                    bv, _ = resolve(bt)
                    bgs.append(parse_color(bv))
            bgs = [b for b in bgs if b]
            cur_v = decl.get(src) or DEFAULTS.get(src)
            cur = parse_color(cur_v, under=hex_of(bgs[0]) if bgs else '#fff')
            if not cur or not bgs:
                continue
            new = adjust(cur, bgs, need)
            if not new:
                continue
            nh = hex_of(new)
            if src in decl:                    # rewrite the declaration in place
                newcss = re.sub(r'(--%s\s*:\s*)[^;}]+' % re.escape(src),
                                lambda m: m.group(1) + nh, newcss)
                decl[src] = nh
            else:                              # token wasn't declared: declare the fixed value
                fixes[src] = nh
            total_fixed += 1
        # guarantee a compliant focus ring on the theme's own backgrounds
        ring_bgs = [parse_color(resolve(t)[0]) for t in ('bg-primary', 'bg-secondary', 'bg-sidebar')]
        ring_bgs = [b for b in ring_bgs if b]
        ring_v = decl.get('focus-ring') or fixes.get('focus-ring')
        ring = parse_color(ring_v) if ring_v else None
        if not ring or not all(ratio(ring, b) >= 3 for b in ring_bgs):
            base = ring or parse_color(resolve('accent-color')[0]) or (88, 86, 214)
            new_ring = adjust(base, ring_bgs, 3.0)
            if new_ring:
                fixes['focus-ring'] = hex_of(new_ring)
        if fixes:
            block = ('\n\n/* WCAG 2.2 contrast fixes: tokens this theme previously inherited\n'
                     '   with insufficient contrast, plus a focus ring visible on its own\n'
                     '   backgrounds (1.4.3 text 4.5:1, 1.4.11 focus 3:1). */\n:root {\n')
            block += ''.join(f'    --{k}: {v};\n' for k, v in sorted(fixes.items()))
            block += '}\n'
            newcss += block
        if newcss != css:
            open(path, 'w', encoding='utf-8', newline='').write(newcss)
    total_fail += len(fails)
    report.append((theme, 'v2' if not legacy else 'legacy', fails, len(outline_kill), bool(fixes)))

for theme, kind, fails, outlines, patched in report:
    status = 'OK' if not fails and not outlines else f'{len(fails)} contrast fails' + (f', {outlines} outline-kills' if outlines else '')
    print(f'{theme:38} [{kind:6}] {status}')
    for fg, bg, r, need, src in fails:
        print(f'    {fg} on {bg}: {r:.2f} (need {need})' + (f'  [declared as --{src}]' if src and src != fg else '  [inherited default]'))
print(f'\nTotal failing pairs: {total_fail}' + (f' | vars adjusted/declared: {total_fixed}' if FIX else ''))
