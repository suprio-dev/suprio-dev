#!/usr/bin/env python3
"""
Generates three animated SVGs for a GitHub profile README:
  stats-streak.svg    total contributions + current / longest streak
  stats-overview.svg  profile numbers + top languages
  stats-heatmap.svg   animated contribution heatmap (last 365 days)
  stats-runner.svg    contribution graph + a bot running along it (replaces activity graph & snake)

Pure standard library. Run daily from a GitHub Action (see update-stats.yml).

Env:
  GH_USER   GitHub username (default: suprio-dev)
  GH_TOKEN  token (GITHUB_TOKEN works). Without it the script falls back to
            scraping the public contribution calendar, and REST calls are
            rate-limited.
  OUT_DIR   where to write the SVGs (default: current directory)
Flags:
  --sample  use sample repo/language numbers (only for previewing the design)
"""
import os, sys, re, json, html, datetime as dt, urllib.request

USER = os.environ.get("GH_USER", "suprio-dev")
TOKEN = os.environ.get("GH_TOKEN", "")
OUT = os.environ.get("OUT_DIR", ".")
SAMPLE = "--sample" in sys.argv
NOW = dt.datetime.now(dt.timezone.utc)
TODAY = NOW.date()
UPDATED = NOW.strftime("%Y-%m-%d") + " UTC"
MONO = "JetBrains Mono, Consolas, Menlo, monospace"
BG, EDGE = "#080D1A", "#22D3EE"


def esc(s):
    return html.escape(str(s), quote=False)


# ----------------------------------------------------------------- network
def http(url, data=None, headers=None, timeout=30):
    h = {"User-Agent": "profile-stats-bot"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def rest(path):
    h = {"Accept": "application/vnd.github+json"}
    if TOKEN:
        h["Authorization"] = f"Bearer {TOKEN}"
    return json.loads(http("https://api.github.com" + path, headers=h))


def gql(query, variables):
    body = json.dumps({"query": query, "variables": variables}).encode()
    res = json.loads(http("https://api.github.com/graphql", data=body,
                          headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}))
    if res.get("errors"):
        raise RuntimeError(res["errors"])
    return res["data"]


# --------------------------------------------------------- contribution days
def days_graphql(a, b):
    q = ("query($l:String!,$f:DateTime!,$t:DateTime!){user(login:$l){contributionsCollection(from:$f,to:$t)"
         "{contributionCalendar{weeks{contributionDays{date contributionCount}}}}}}")
    d = gql(q, {"l": USER, "f": f"{a}T00:00:00Z", "t": f"{b}T23:59:59Z"})
    out = {}
    for w in d["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]:
        for day in w["contributionDays"]:
            out[dt.date.fromisoformat(day["date"])] = day["contributionCount"]
    return out


def days_scrape(a, b):
    h = http(f"https://github.com/users/{USER}/contributions?from={a}&to={b}", headers={"User-Agent": "Mozilla/5.0"})
    cells = re.findall(r'<td[^>]*?data-date="([\d-]+)"[^>]*?id="([^"]+)"', h)
    tips = dict(re.findall(r'<tool-tip[^>]*?for="([^"]+)"[^>]*>([^<]*)</tool-tip>', h))
    out = {}
    for date, cid in cells:
        m = re.match(r"(\d+) contribution", tips.get(cid, ""))
        out[dt.date.fromisoformat(date)] = int(m.group(1)) if m else 0
    return out


def get_days(a, b):
    if TOKEN:
        try:
            return days_graphql(a, b)
        except Exception as e:  # fall back to the public calendar
            print("graphql failed, scraping instead:", str(e)[:120])
    out = days_scrape(a, b)
    return {d: c for d, c in out.items() if a <= d <= b}


# ------------------------------------------------------------------ streaks
def streaks(days):
    run, start = 0, None
    best = (0, None, None)
    for d in sorted(days):
        if days[d] > 0:
            if run == 0:
                start = d
            run += 1
            if run > best[0]:
                best = (run, start, d)
        else:
            run = 0
    d = TODAY if days.get(TODAY, 0) > 0 else TODAY - dt.timedelta(days=1)
    cur, end = 0, d
    while days.get(d, 0) > 0:
        cur += 1
        d -= dt.timedelta(days=1)
    cur_start = d + dt.timedelta(days=1) if cur else None
    return (cur, cur_start, end if cur else None), best


def fmt_d(d):
    return f"{d.strftime('%b')} {d.day}"


def rng(s, e):
    if not s:
        return "—"
    if s == e:
        return f"{fmt_d(s)}, {s.year}"
    if s.year == e.year:
        return f"{fmt_d(s)} - {fmt_d(e)}"
    return f"{fmt_d(s)}, {s.year} - {fmt_d(e)}, {e.year}"


# ------------------------------------------------------------------- helpers
def rev(delay, body, rise=10):
    """Fade + rise in once, after `delay` seconds (visible by default for non-animated viewers)."""
    T = round(delay + 0.7, 2)
    a = round(delay / T, 4)
    return (f'<g><animate attributeName="opacity" values="0;0;1" keyTimes="0;{a};1" dur="{T}s" fill="freeze"/>'
            f'<animateTransform attributeName="transform" type="translate" values="0 {rise};0 {rise};0 0" '
            f'keyTimes="0;{a};1" dur="{T}s" fill="freeze"/>{body}</g>')


def card(x, y, w, h):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{BG}" stroke="{EDGE}" stroke-opacity="0.3" stroke-width="1.5"/>'


def svg(w, h, title, body):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" '
            f'aria-label="{esc(title)}"><title>{esc(title)}</title>\n{body}\n</svg>\n')


def updated_label(x, y):
    return (f'<text x="{x}" y="{y}" text-anchor="end" font-family="{MONO}" font-size="9.5" fill="#475569">'
            f'updated {UPDATED}</text>')


# --------------------------------------------------------------- streak card
def streak_svg(total, since, cur, longest):
    parts = [card(2, 2, 796, 196)]
    for x in (268, 532):
        parts.append(f'<line x1="{x}" y1="34" x2="{x}" y2="160" stroke="#1E293B" stroke-width="1.5"/>')

    def col(cx, num, label, sub, delay, big=True):
        return rev(delay, (
            f'<text x="{cx}" y="100" text-anchor="middle" font-family="{MONO}" font-size="38" font-weight="800" fill="#E2E8F0">{esc(num)}</text>'
            f'<text x="{cx}" y="156" text-anchor="middle" font-family="{MONO}" font-size="13" font-weight="700" fill="#22D3EE">{esc(label)}</text>'
            f'<text x="{cx}" y="176" text-anchor="middle" font-family="{MONO}" font-size="11" fill="#64748B">{esc(sub)}</text>'))

    parts.append(col(135, f"{total:,}", "Total Contributions", f"{fmt_d(since)}, {since.year} - Present", 0.2))
    parts.append(col(665, f"{longest[0]:,}", "Longest Streak", rng(longest[1], longest[2]), 0.6))

    # centre: ring + flame
    n, s, e = cur
    frac = min(1.0, n / longest[0]) if longest[0] else 0
    live = n > 0
    ring_col = "#22D3EE" if live else "#334155"
    T = 1.9
    a = round(0.4 / T, 4)
    ring = ""
    if frac > 0:
        off = round(1 - frac, 4)
        ring = (f'<circle cx="400" cy="86" r="44" fill="none" stroke="{ring_col}" stroke-opacity="0.18" stroke-width="13" transform="rotate(-90 400 86)" '
                f'pathLength="1" stroke-dasharray="1" stroke-dashoffset="{off}"><animate attributeName="stroke-dashoffset" values="1;1;{off}" keyTimes="0;{a};1" dur="{T}s" fill="freeze"/>'
                f'<animate attributeName="stroke-opacity" values="0.1;0.3;0.1" dur="2.4s" begin="{T}s" repeatCount="indefinite"/></circle>'
                f'<circle cx="400" cy="86" r="44" fill="none" stroke="{ring_col}" stroke-width="7" transform="rotate(-90 400 86)" '
                f'pathLength="1" stroke-dasharray="1" stroke-dashoffset="{off}"><animate attributeName="stroke-dashoffset" values="1;1;{off}" keyTimes="0;{a};1" dur="{T}s" fill="freeze"/></circle>')
    flame_col = ("#FB923C", "#FBBF24") if live else ("#475569", "#64748B")
    flame = (f'<circle cx="400" cy="42" r="12" fill="{BG}"/>'
             f'<g transform="translate(400,42)"><g><animateTransform attributeName="transform" type="scale" values="1;1.14;1" dur="1.4s" repeatCount="indefinite"/>'
             f'<path d="M0 -11 C7 -4 9 2 5 8 C3 11 -3 11 -5 8 C-9 2 -3 -2 0 -11Z" fill="{flame_col[0]}"/>'
             f'<path d="M0 -3 C3 1 4 4 2 7 C1 8 -1 8 -2 7 C-4 4 -2 1 0 -3Z" fill="{flame_col[1]}"/></g></g>')
    parts.append(
        f'<circle cx="400" cy="86" r="44" fill="none" stroke="#1E293B" stroke-width="7"/>{ring}{flame}'
        + rev(0.4, f'<text x="400" y="98" text-anchor="middle" font-family="{MONO}" font-size="32" font-weight="800" fill="#E2E8F0">{n}</text>', rise=6)
        + rev(0.4, f'<text x="400" y="156" text-anchor="middle" font-family="{MONO}" font-size="13" font-weight="700" fill="#FB923C">Current Streak</text>'
                   f'<text x="400" y="176" text-anchor="middle" font-family="{MONO}" font-size="11" fill="#64748B">{esc(rng(s, e))}</text>'))
    parts.append(updated_label(784, 192))
    return svg(800, 200, "GitHub contribution streak", "\n".join(parts))


# ------------------------------------------------------------ overview card
LANGC = {"JavaScript": "#F1E05A", "HTML": "#E34C26", "CSS": "#8B5CF6", "Python": "#3776AB", "Java": "#F89820",
         "C": "#94A3B8", "C++": "#F34B7D", "TypeScript": "#3178C6", "Shell": "#89E051", "SCSS": "#C6538C",
         "Jupyter Notebook": "#DA5B0B", "EJS": "#A91E50", "Dockerfile": "#38BDF8"}
PAL = ["#22D3EE", "#A78BFA", "#34D399", "#FBBF24", "#F472B6", "#FB923C"]


def overview_svg(rows, langs):
    p = [card(2, 2, 388, 272), card(410, 2, 388, 272)]
    p.append(f'<text x="26" y="36" font-family="{MONO}" font-size="12" font-weight="700" letter-spacing="2" fill="#22D3EE">GITHUB OVERVIEW</text>'
             f'<line x1="26" y1="48" x2="366" y2="48" stroke="#1E293B"/>')
    for i, (label, val) in enumerate(rows[:7]):
        y = 78 + i * 28
        c = PAL[i % len(PAL)]
        p.append(rev(0.15 + i * 0.12, (
            f'<rect x="26" y="{y-11}" width="8" height="8" rx="2.5" fill="{c}"/>'
            f'<text x="44" y="{y-3}" font-family="{MONO}" font-size="13" fill="#94A3B8">{esc(label)}</text>'
            f'<text x="366" y="{y-3}" text-anchor="end" font-family="{MONO}" font-size="15" font-weight="800" fill="#E2E8F0">{esc(val)}</text>'), rise=6))
    p.append(f'<text x="434" y="36" font-family="{MONO}" font-size="12" font-weight="700" letter-spacing="2" fill="#A78BFA">TOP LANGUAGES</text>'
             f'<line x1="434" y1="48" x2="774" y2="48" stroke="#1E293B"/>')
    if not langs:
        p.append(f'<text x="434" y="110" font-family="{MONO}" font-size="12" fill="#64748B">Language data appears after the</text>'
                 f'<text x="434" y="130" font-family="{MONO}" font-size="12" fill="#64748B">first automatic daily update.</text>')
    else:
        total = sum(b for _, b in langs) or 1
        mx = max(b for _, b in langs)
        for i, (name, b) in enumerate(langs[:5]):
            y = 80 + i * 38
            c = LANGC.get(name, PAL[i % len(PAL)])
            W = max(6, round(338 * b / mx))
            d = 0.3 + i * 0.15
            T = round(d + 1.0, 2)
            a = round(d / T, 4)
            p.append(rev(d, (
                f'<circle cx="440" cy="{y-4}" r="5" fill="{c}"/>'
                f'<text x="454" y="{y}" font-family="{MONO}" font-size="13" font-weight="700" fill="#E2E8F0">{esc(name)}</text>'
                f'<text x="774" y="{y}" text-anchor="end" font-family="{MONO}" font-size="12" fill="#94A3B8">{b*100/total:.1f}%</text>'
                f'<rect x="434" y="{y+8}" width="338" height="7" rx="3.5" fill="#1E293B"/>'
                f'<rect x="434" y="{y+8}" width="{W}" height="7" rx="3.5" fill="{c}"><animate attributeName="width" values="0;0;{W}" keyTimes="0;{a};1" dur="{T}s" fill="freeze"/></rect>'), rise=6))
    p.append(updated_label(782, 264))
    return svg(800, 276, "GitHub overview and top languages", "\n".join(p))


# ----------------------------------------------------------------- heatmap
LV = ["#111A2E", "#155E75", "#0891B2", "#22D3EE", "#A5F3FC"]


def heatmap_svg(days, year_total):
    start = TODAY - dt.timedelta(days=364)
    start -= dt.timedelta(days=(start.weekday() + 1) % 7)  # back to Sunday
    mx = max([c for c in days.values()] + [1])

    def level(c):
        if c <= 0:
            return 0
        r = c / mx
        return 1 if r <= .25 else 2 if r <= .5 else 3 if r <= .75 else 4

    x0, y0, pitch, cs = 34, 62, 14, 11
    ncol = ((TODAY - start).days // 7) + 1
    cols, months = [], []
    for ci in range(ncol):
        cells = []
        for r in range(7):
            d = start + dt.timedelta(days=ci * 7 + r)
            if d > TODAY:
                break
            c = days.get(d, 0)
            cells.append(f'<rect x="{x0+ci*pitch}" y="{y0+r*pitch}" width="{cs}" height="{cs}" rx="2.5" fill="{LV[level(c)]}"><title>{c} contributions on {d.isoformat()}</title></rect>')
            if d.day == 1 and (not months or ci - months[-1][0] >= 3):
                months.append((ci, d.strftime("%b")))
        dly = round(ci * 0.03, 2)
        T = round(dly + 0.5, 2)
        a = round(dly / T, 4)
        cols.append(f'<g><animate attributeName="opacity" values="0;0;1" keyTimes="0;{a};1" dur="{T}s" fill="freeze"/>'
                    f'<animateTransform attributeName="transform" type="translate" values="0 8;0 8;0 0" keyTimes="0;{a};1" dur="{T}s" fill="freeze"/>{"".join(cells)}</g>')
    if not months or months[0][0] >= 3:
        months.insert(0, (0, (start + dt.timedelta(days=3)).strftime("%b")))
    p = [card(2, 2, 796, 200),
         '<defs><linearGradient id="sw" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#67E8F9" stop-opacity="0"/>'
         '<stop offset="0.5" stop-color="#67E8F9" stop-opacity="0.35"/><stop offset="1" stop-color="#67E8F9" stop-opacity="0"/></linearGradient>'
         f'<clipPath id="grid"><rect x="{x0-2}" y="{y0-2}" width="{ncol*pitch+2}" height="{7*pitch+2}"/></clipPath></defs>',
         f'<text x="26" y="32" font-family="{MONO}" font-size="12" font-weight="700" letter-spacing="2" fill="#22D3EE">CONTRIBUTION ACTIVITY</text>',
         f'<text x="774" y="32" text-anchor="end" font-family="{MONO}" font-size="12" fill="#94A3B8">{year_total:,} contributions in the last year</text>']
    for ci, name in months:
        p.append(f'<text x="{x0+ci*pitch}" y="54" font-family="{MONO}" font-size="10" fill="#64748B">{name}</text>')
    for r, name in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        p.append(f'<text x="28" y="{y0+r*pitch+9}" text-anchor="end" font-family="{MONO}" font-size="9" fill="#64748B">{name}</text>')
    p.extend(cols)
    # sweeping light + today marker
    p.append(f'<g clip-path="url(#grid)"><rect x="{x0-90}" y="{y0-4}" width="90" height="{7*pitch+6}" fill="url(#sw)">'
             f'<animate attributeName="x" values="{x0-90};{x0+ncol*pitch};{x0+ncol*pitch}" keyTimes="0;0.55;1" dur="7s" begin="2.5s" repeatCount="indefinite"/></rect></g>')
    tci, tr = (TODAY - start).days // 7, (TODAY - start).days % 7
    p.append(f'<rect x="{x0+tci*pitch-2}" y="{y0+tr*pitch-2}" width="{cs+4}" height="{cs+4}" rx="4" fill="none" stroke="#FBBF24" stroke-width="1.6" opacity="0">'
             f'<animate attributeName="opacity" values="0;0;1;0.2;1" keyTimes="0;0.01;0.1;0.6;1" dur="2s" begin="{round(ncol*0.03+0.5,2)}s" repeatCount="indefinite"/></rect>')
    # legend + footer
    p.append(f'<text x="26" y="190" font-family="{MONO}" font-size="9.5" fill="#475569">updated {UPDATED}</text>')
    lx = 774 - (5 * 14 + 70)
    p.append(f'<text x="{lx}" y="190" font-family="{MONO}" font-size="10" fill="#64748B">Less</text>')
    for i, c in enumerate(LV):
        p.append(f'<rect x="{lx+30+i*14}" y="181" width="{cs}" height="{cs}" rx="2.5" fill="{c}"/>')
    p.append(f'<text x="{lx+30+5*14+4}" y="190" font-family="{MONO}" font-size="10" fill="#64748B">More</text>')
    return svg(800, 204, "Animated GitHub contribution heatmap", "\n".join(p))



# ------------------------------------------------- runner (graph + snake merged)
BOT = """<g transform="scale(0.42)" color="#22D3EE">
<ellipse cx="0" cy="-4" rx="9" ry="12" fill="#FBBF24" opacity="0.9"><animate attributeName="ry" values="12;19;12" dur="0.25s" repeatCount="indefinite"/></ellipse>
<rect x="-14" y="-24" width="28" height="8" rx="4" fill="#475569"/>
<rect x="-18" y="-60" width="36" height="38" rx="10" fill="currentColor"/>
<circle cx="0" cy="-42" r="5" fill="#0B1220"/><circle cx="0" cy="-42" r="2.5" fill="#67E8F9"><animate attributeName="opacity" values="1;0.3;1" dur="1.2s" repeatCount="indefinite"/></circle>
<rect x="-24" y="-100" width="48" height="38" rx="14" fill="currentColor"/><rect x="-18" y="-94" width="36" height="26" rx="10" fill="#0B1220"/>
<ellipse cx="-4" cy="-82" rx="3.5" ry="4" fill="#67E8F9"><animate attributeName="ry" values="4;4;0.6;4" keyTimes="0;0.9;0.95;1" dur="3s" repeatCount="indefinite"/></ellipse>
<ellipse cx="10" cy="-82" rx="3.5" ry="4" fill="#67E8F9"><animate attributeName="ry" values="4;4;0.6;4" keyTimes="0;0.9;0.95;1" dur="3s" repeatCount="indefinite"/></ellipse>
<path d="M-1 -74 Q5 -70 11 -74" stroke="#67E8F9" stroke-width="1.8" fill="none" stroke-linecap="round"/>
<line x1="0" y1="-100" x2="0" y2="-110" stroke="currentColor" stroke-width="3" stroke-linecap="round"/>
<circle cx="0" cy="-113" r="4" fill="#FBBF24"><animate attributeName="opacity" values="1;0.2;1" dur="0.9s" repeatCount="indefinite"/></circle></g>"""


def runner_svg(days, cur):
    N = 90
    dates = [TODAY - dt.timedelta(days=N - 1 - i) for i in range(N)]
    vals = [days.get(d, 0) for d in dates]
    x0, x1, yb, yt = 48, 770, 206, 80
    W = x1 - x0
    ymax = max(max(vals), 4)
    X = [x0 + i * W / (N - 1) for i in range(N)]
    Y = [yb - v / ymax * (yb - yt) for v in vals]
    T, A, B = 14.0, 0.8, 9.8

    d = f"M{X[0]:.1f} {Y[0]:.1f}"
    seglen = []
    for i in range(N - 1):
        p0 = (X[max(i - 1, 0)], Y[max(i - 1, 0)]); p1 = (X[i], Y[i]); p2 = (X[i + 1], Y[i + 1]); p3 = (X[min(i + 2, N - 1)], Y[min(i + 2, N - 1)])
        c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6]
        c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6]
        lo, hi = min(p1[1], p2[1]), max(p1[1], p2[1])
        c1[1] = min(max(c1[1], lo), hi); c2[1] = min(max(c2[1], lo), hi)
        d += f" C{c1[0]:.1f} {c1[1]:.1f} {c2[0]:.1f} {c2[1]:.1f} {p2[0]:.1f} {p2[1]:.1f}"
        L, prev = 0.0, p1
        for k in range(1, 13):
            t = k / 12
            bx = (1-t)**3*p1[0] + 3*(1-t)**2*t*c1[0] + 3*(1-t)*t*t*c2[0] + t**3*p2[0]
            by = (1-t)**3*p1[1] + 3*(1-t)**2*t*c1[1] + 3*(1-t)*t*t*c2[1] + t**3*p2[1]
            L += ((bx - prev[0]) ** 2 + (by - prev[1]) ** 2) ** 0.5
            prev = (bx, by)
        seglen.append(L)
    tot = sum(seglen) or 1
    frac, acc = [0.0], 0.0
    for L in seglen:
        acc += L; frac.append(acc / tot)
    ktimes = [0.0] + [round((A + (X[i] - x0) / W * (B - A)) / T, 4) for i in range(N)] + [1.0]
    kpts = [0.0] + [round(f, 4) for f in frac] + [1.0]
    node_t = lambda i: (A + (X[i] - x0) / W * (B - A)) / T

    # peaks the bot "collects"
    order = sorted([i for i in range(N) if vals[i] > 0], key=lambda i: -vals[i])
    peaks = []
    for i in order:
        if all(abs(i - j) >= 8 for j in peaks):
            peaks.append(i)
        if len(peaks) == 4:
            break

    q = [card(2, 2, 796, 258),
         '<defs><linearGradient id="ag" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#22D3EE" stop-opacity="0.38"/>'
         '<stop offset="1" stop-color="#22D3EE" stop-opacity="0"/></linearGradient>'
         f'<clipPath id="reveal"><rect x="0" y="0" width="{x1+10}" height="260"><animate attributeName="width" values="{x0};{x0};{x1+10};{x1+10}" '
         f'keyTimes="0;{round(A/T,4)};{round(B/T,4)};1" dur="{T}s" repeatCount="indefinite"/></rect></clipPath></defs>']
    inner = []
    inner.append(f'<text x="26" y="32" font-family="{MONO}" font-size="12" font-weight="700" letter-spacing="2" fill="#22D3EE">CONTRIBUTION RUNNER</text>')
    inner.append(f'<text x="774" y="32" text-anchor="end" font-family="{MONO}" font-size="12" fill="#94A3B8">last {N} days · {sum(vals):,} contributions</text>')
    inner.append(f'<text x="774" y="50" text-anchor="end" font-family="{MONO}" font-size="10.5" fill="#64748B">best day {max(vals)} · active {sum(1 for v in vals if v > 0)}/{N} days</text>')
    for yy in (yb, (yb + yt) / 2, yt):
        inner.append(f'<line x1="{x0}" y1="{yy}" x2="{x1}" y2="{yy}" stroke="#1E293B" stroke-width="1" stroke-dasharray="{"0" if yy == yb else "3 5"}"/>')
    inner.append(f'<text x="{x0-8}" y="{yb+4}" text-anchor="end" font-family="{MONO}" font-size="10" fill="#475569">0</text>'
                 f'<text x="{x0-8}" y="{yt+4}" text-anchor="end" font-family="{MONO}" font-size="10" fill="#475569">{ymax}</text>')
    last_lbl = -99
    for i, dd in enumerate(dates):
        if dd.day == 1 and i - last_lbl >= 6:
            inner.append(f'<text x="{X[i]:.1f}" y="226" text-anchor="middle" font-family="{MONO}" font-size="10" fill="#64748B">{dd.strftime("%b")}</text>')
            last_lbl = i
    inner.append(f'<text x="{x1}" y="226" text-anchor="end" font-family="{MONO}" font-size="10" font-weight="700" fill="#FBBF24">today</text>')

    clipped = []
    n_cur, s_cur, e_cur = cur
    if n_cur > 0:
        i_s = max(0, (s_cur - dates[0]).days)
        i_e = min(N - 1, (e_cur - dates[0]).days)
        bx0, bx1 = X[i_s], X[i_e]
        clipped.append(f'<rect x="{bx0:.1f}" y="{yt-18}" width="{bx1-bx0:.1f}" height="{yb-yt+18}" fill="#FB923C" fill-opacity="0.09"/>')
        if bx1 - bx0 > 80:
            clipped.append(f'<text x="{(bx0+bx1)/2:.1f}" y="{yt-6}" text-anchor="middle" font-family="{MONO}" font-size="10.5" font-weight="700" fill="#FB923C">{n_cur}-day streak</text>')
    clipped.append(f'<path d="{d} L{x1} {yb} L{x0} {yb} Z" fill="url(#ag)"/>')
    clipped.append(f'<path d="{d}" fill="none" stroke="#22D3EE" stroke-opacity="0.25" stroke-width="8" stroke-linejoin="round"/>')
    clipped.append(f'<path d="{d}" fill="none" stroke="#22D3EE" stroke-width="2.6" stroke-linejoin="round" stroke-linecap="round"/>')
    inner.append(f'<g clip-path="url(#reveal)">{"".join(clipped)}</g>')

    for i in peaks:
        t = round(node_t(i), 4)
        k = f"0;{t};{round(t+0.012,4)};{round(t+0.03,4)};1"
        inner.append(
            f'<circle cx="{X[i]:.1f}" cy="{Y[i]:.1f}" r="4.5" fill="#FBBF24" stroke="{BG}" stroke-width="2"><animate attributeName="r" values="0;0;8;4.5;4.5" keyTimes="{k}" dur="{T}s" repeatCount="indefinite"/></circle>'
            f'<circle cx="{X[i]:.1f}" cy="{Y[i]:.1f}" r="4.5" fill="none" stroke="#FBBF24" stroke-width="1.8" opacity="0"><animate attributeName="r" values="4.5;4.5;20;20" keyTimes="0;{t};{round(t+0.05,4)};1" dur="{T}s" repeatCount="indefinite"/>'
            f'<animate attributeName="opacity" values="0;0.9;0;0" keyTimes="0;{t};{round(t+0.05,4)};1" dur="{T}s" repeatCount="indefinite"/></circle>'
            f'<text x="{X[i]:.1f}" y="{Y[i]-12:.1f}" text-anchor="middle" font-family="{MONO}" font-size="11" font-weight="800" fill="#FBBF24" opacity="1">'
            f'<animate attributeName="opacity" values="0;0;1;1" keyTimes="0;{t};{round(t+0.03,4)};1" dur="{T}s" repeatCount="indefinite"/>{vals[i]}</text>')
    # today marker
    te = round(B / T, 4)
    inner.append(f'<circle cx="{X[-1]:.1f}" cy="{Y[-1]:.1f}" r="4" fill="#FFFFFF" stroke="#22D3EE" stroke-width="2" opacity="1"><animate attributeName="opacity" values="0;0;1;1" keyTimes="0;{te};{round(te+0.02,4)};1" dur="{T}s" repeatCount="indefinite"/></circle>')
    # the bot
    inner.append(f'<g><animateMotion dur="{T}s" repeatCount="indefinite" calcMode="linear" keyPoints="{";".join(map(str,kpts))}" '
                 f'keyTimes="{";".join(map(str,ktimes))}" path="{d}"/><g transform="translate(0,-9)">{BOT}</g></g>')
    inner.append(f'<text x="26" y="250" font-family="{MONO}" font-size="9.5" fill="#475569">updated {UPDATED}</text>')
    q.append(f'<g><animate attributeName="opacity" values="0;1;1;0" keyTimes="0;0.02;0.93;1" dur="{T}s" repeatCount="indefinite"/>{"".join(inner)}</g>')
    return svg(800, 262, "Contribution graph with a bot running along the last 90 days", "\n".join(q))


# --------------------------------------------------------------------- main
def main():
    created = dt.date(TODAY.year - 1, 1, 1)
    user = {}
    try:
        user = rest(f"/users/{USER}")
        created = dt.date.fromisoformat(user["created_at"][:10])
    except Exception as e:
        print("user lookup failed:", str(e)[:100])

    # contribution days: every calendar year since the account was created
    days = {}
    for y in range(created.year, TODAY.year + 1):
        a, b = max(dt.date(y, 1, 1), created), min(dt.date(y, 12, 31), TODAY)
        try:
            days.update(get_days(a, b))
        except Exception as e:
            print(f"calendar {y} failed:", str(e)[:100])
    if not days:
        sys.exit("no contribution data could be fetched")

    total = sum(days.values())
    if not user:
        created = min((d for d, c in days.items() if c > 0), default=created)
    cur, best = streaks(days)
    year_total = sum(c for d, c in days.items() if d > TODAY - dt.timedelta(days=365))

    # overview numbers
    rows = [("Contributions (last year)", f"{year_total:,}")]
    if TOKEN:
        try:
            f = (TODAY - dt.timedelta(days=364)).isoformat()
            q = ("query($l:String!,$f:DateTime!,$t:DateTime!){user(login:$l){contributionsCollection(from:$f,to:$t)"
                 "{totalCommitContributions totalPullRequestContributions totalIssueContributions}}}")
            c = gql(q, {"l": USER, "f": f"{f}T00:00:00Z", "t": f"{TODAY.isoformat()}T23:59:59Z"})["user"]["contributionsCollection"]
            rows += [("Commits (last year)", f"{c['totalCommitContributions']:,}"),
                     ("Pull requests", f"{c['totalPullRequestContributions']:,}"),
                     ("Issues opened", f"{c['totalIssueContributions']:,}")]
        except Exception as e:
            print("summary query failed:", str(e)[:100])

    langs = []
    try:
        if SAMPLE:
            raise RuntimeError("sample mode")
        repos = [r for r in rest(f"/users/{USER}/repos?per_page=100&type=owner") if not r.get("fork")]
        stars = sum(r.get("stargazers_count", 0) for r in repos)
        agg = {}
        for r in repos:
            try:
                for k, v in rest(f"/repos/{USER}/{r['name']}/languages").items():
                    agg[k] = agg.get(k, 0) + v
            except Exception:
                pass
        langs = sorted(agg.items(), key=lambda kv: -kv[1])
        rows += [("Public repos", f"{user.get('public_repos', len(repos)):,}"), ("Stars earned", f"{stars:,}"),
                 ("Followers", f"{user.get('followers', 0):,}")]
    except Exception as e:
        if SAMPLE:
            langs = [("JavaScript", 52000), ("HTML", 41000), ("CSS", 30000), ("C", 9000), ("Python", 6000)]
            rows += [("Public repos", "12"), ("Stars earned", "3"), ("Followers", "21")]
        else:
            print("repo/language lookup failed:", str(e)[:100])

    os.makedirs(OUT, exist_ok=True)
    for name, content in (("stats-streak.svg", streak_svg(total, created, cur, best)),
                          ("stats-overview.svg", overview_svg(rows, langs)),
                          ("stats-heatmap.svg", heatmap_svg(days, year_total)),
                          ("stats-runner.svg", runner_svg(days, cur))):
        with open(os.path.join(OUT, name), "w", encoding="utf-8") as fh:
            fh.write(content)
    print(f"ok: total={total} current={cur[0]} longest={best[0]} langs={len(langs)} rows={len(rows)}")


if __name__ == "__main__":
    main()
