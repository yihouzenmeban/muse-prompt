#!/usr/bin/env python3
"""Render a post-run review card (HTML fragment) from a review JSON.

Usage: render_review.py <review.json>  ->  HTML fragment on stdout.

Companion to post-run-review.md in this repo: the review JSON field spec
lives there. Layout: compact and visual first. One timeline chart
(pace line + HR line + elevation wash, from detail.stream) carries the
shape of the run; the numbers collapse into two inline lines; the HR
zone bar stays; segment rows appear only for structured workouts and
races (show_structure). Text is kept to the lead, two short paragraphs
and one takeaway. Colour lives in the chart and the zone bar only.
Every field is optional except title.
"""
import json
import sys

ZONE_COLORS = {
    "below": "#8fa3bf", "z1": "#4da3ff", "z2": "#34c77b",
    "z3": "#f2c037", "z4": "#f08c3c", "z5": "#e5534b",
}
HR_COLOR = "#d64541"

CSS = """
<style>
.prr{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;color:var(--hatch-widget-text);max-width:560px;box-sizing:border-box;font-size:14px;line-height:1.6;padding:14px 16px}
.prr *{box-sizing:border-box}
.prr-title{font-size:17px;font-weight:700;line-height:1.35}
.prr-sub{font-size:12px;color:var(--hatch-widget-muted);margin-top:2px}
.prr-lead{margin-top:8px;text-align:justify}
.prr-chart{margin-top:12px}
.prr-nums{font-size:13px;margin-top:10px;font-variant-numeric:tabular-nums}
.prr-nums .k{color:var(--hatch-widget-muted)}
.prr-nums b{font-weight:650}
.prr-zbar{display:flex;height:8px;border-radius:4px;overflow:hidden;margin-top:12px}
.prr-zleg{display:flex;flex-wrap:wrap;gap:3px 12px;font-size:11px;color:var(--hatch-widget-muted);margin-top:4px}
.prr-zleg i{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:4px}
.prr-seg{margin-top:10px;font-size:12.5px;font-variant-numeric:tabular-nums}
.prr-seg .r{display:flex;gap:10px;padding:3px 0;border-bottom:1px solid var(--hatch-widget-border)}
.prr-seg .r:last-child{border-bottom:none}
.prr-seg .lab{color:var(--hatch-widget-muted);flex:none;min-width:96px}
.prr-body{margin-top:10px}
.prr-body p{margin:6px 0;text-align:justify}
.prr-morn{font-size:12px;color:var(--hatch-widget-muted);margin-top:10px}
.prr-take{border-top:1px solid var(--hatch-widget-border);margin-top:12px;padding-top:9px;text-align:justify}
</style>
"""


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def fmt_pace(v):
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    m = int(v)
    s = int(round((v - m) * 60))
    if s == 60:
        m, s = m + 1, 0
    return f"{m}:{s:02d}"


def _nice_scale(lo, hi, step, pad_ratio=0.2, min_pad=None):
    """Expand the data range and snap to round steps so the axis reads
    honestly instead of stretching min-max to full height."""
    rng = (hi - lo) or step
    pad = max(rng * pad_ratio, min_pad if min_pad is not None else step / 2)
    nlo = int((lo - pad) // step * step)
    nhi = int(-(-(hi + pad) // step) * step)
    if nhi - nlo < step * 2:
        nhi = nlo + step * 2
    mid = (nlo + nhi) / 2
    return nlo, nhi, [nlo, mid, nhi]


def _path_for(series, x0, x1, y0, y1, lo, hi, invert=False):
    """Polyline path within the plot box for an explicit value scale."""
    rng = (hi - lo) or 1
    n = len(series)
    pts = []
    for i, v in enumerate(series):
        if v is None:
            continue
        x = x0 + i * (x1 - x0) / (n - 1) if n > 1 else x0
        t = (v - lo) / rng
        t = max(0.0, min(1.0, t))
        if invert:
            t = 1 - t
        y = y0 + (1 - t) * (y1 - y0)
        pts.append((round(x, 1), round(y, 1)))
    if len(pts) < 2:
        return "", []
    return "M" + " L".join(f"{x},{y}" for x, y in pts), pts


def chart_svg(chart, distance_km=None, target_pace=None):
    hr = chart.get("hr") or []
    pace = chart.get("pace") or chart.get("pace_min_km") or []
    speed = chart.get("speed_kmh") or []
    elev = chart.get("elev") or chart.get("elevation_m") or []
    hr_vals = [v for v in hr if v is not None]
    pace_vals = [v for v in pace if v is not None]
    speed_vals = [v for v in speed if v is not None]
    if len(hr_vals) < 2 and len(pace_vals) < 2 and len(speed_vals) < 2:
        return ""
    W, H = 520, 126
    L, R, T, B = 30, 40, 8, 16  # plot box insets; axis labels live outside
    x0, x1, y0, y1 = L, W - R, T, H - B
    parts = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" style="display:block">']

    # Scales: HR snapped to 10 bpm steps, pace to 15 s steps, speed to
    # 5 km/h steps, all padded, so a steady effort reads steady instead
    # of filling the frame.
    hr_scale = pace_scale = speed_scale = None
    if hr_vals:
        hr_scale = _nice_scale(min(hr_vals), max(hr_vals), 10, 0.2, 5)
    if pace_vals:
        ps = [v * 60 for v in pace_vals]
        if target_pace:
            ps += [target_pace["lo"] * 60, target_pace["hi"] * 60]
        lo, hi, ticks = _nice_scale(min(ps), max(ps), 15, 0.3, 8)
        pace_scale = (lo / 60, hi / 60, [t / 60 for t in ticks])
    elif speed_vals:
        speed_scale = _nice_scale(min(speed_vals), max(speed_vals), 5, 0.25, 2)

    # Gridlines + HR tick labels (left, red).
    if hr_scale:
        nlo, nhi, ticks = hr_scale
        for tv in ticks:
            t = (tv - nlo) / (nhi - nlo)
            y = y0 + (1 - t) * (y1 - y0)
            parts.append(f'<line x1="{x0}" y1="{y:.0f}" x2="{x1}" y2="{y:.0f}" stroke="var(--hatch-widget-border)" stroke-width="1" opacity="0.7"/>')
            parts.append(f'<text x="{x0 - 4}" y="{y + 3:.0f}" font-size="9.5" text-anchor="end" fill="{HR_COLOR}">{tv:g}</text>')
    # Pace tick labels (right, muted); pace axis is inverted (faster up).
    if pace_scale:
        plo, phi, pticks = pace_scale
        for tv in pticks:
            t = (tv - plo) / (phi - plo)
            y = y0 + t * (y1 - y0)  # slow at bottom after inversion math
            parts.append(f'<text x="{x1 + 4}" y="{y + 3:.0f}" font-size="9.5" fill="var(--hatch-widget-muted)">{fmt_pace(tv)}</text>')
    # Speed tick labels (right, muted, km/h) for cycling charts.
    if speed_scale:
        slo, shi, sticks = speed_scale
        for tv in sticks:
            t = (tv - slo) / (shi - slo)
            y = y0 + (1 - t) * (y1 - y0)
            parts.append(f'<text x="{x1 + 4}" y="{y + 3:.0f}" font-size="9.5" fill="var(--hatch-widget-muted)">{tv:g}</text>')

    # Planned-pace band from the workout target (drawn under the lines).
    if pace_scale and target_pace:
        plo, phi, _ = pace_scale

        def pace_y(tv):
            return y0 + (tv - plo) / (phi - plo) * (y1 - y0)

        y_top = pace_y(target_pace["lo"])
        y_bot = pace_y(target_pace["hi"])
        label = f'目标 {fmt_pace(target_pace["lo"])}–{fmt_pace(target_pace["hi"])}'
        if y_bot - y_top >= 2:
            parts.append(f'<rect x="{x0}" y="{y_top:.0f}" width="{x1 - x0}" height="{y_bot - y_top:.0f}" fill="var(--hatch-widget-accent)" fill-opacity="0.10"/>')
            ly = y_top + (y_bot - y_top) / 2 + 3
            if y_bot - y_top < 11:
                ly = y_top - 3
            parts.append(f'<text x="{x0 + 4}" y="{ly:.0f}" font-size="9.5" fill="var(--hatch-widget-muted)">{esc(label)}</text>')
        else:
            parts.append(f'<line x1="{x0}" y1="{y_top:.0f}" x2="{x1}" y2="{y_top:.0f}" stroke="var(--hatch-widget-accent)" stroke-width="1.2" stroke-dasharray="5 4"/>')
            parts.append(f'<text x="{x0 + 4}" y="{y_top - 3:.0f}" font-size="9.5" fill="var(--hatch-widget-muted)">{esc(label)}</text>')

    epath, epts = _path_for(elev, x0, x1, y0, y1,
                            min([v for v in elev if v is not None], default=0),
                            max([v for v in elev if v is not None], default=1))
    if epath:
        area = epath + f" L{epts[-1][0]},{y1} L{epts[0][0]},{y1} Z"
        parts.append(f'<path d="{area}" fill="var(--hatch-widget-text)" fill-opacity="0.07" stroke="none"/>')
    if pace_scale:
        ppath, _ = _path_for(pace, x0, x1, y0, y1, pace_scale[0], pace_scale[1], invert=True)
        if ppath:
            parts.append(f'<path d="{ppath}" fill="none" stroke="var(--hatch-widget-text)" stroke-width="1.6" stroke-linejoin="round"/>')
    if speed_scale:
        spath, _ = _path_for(speed, x0, x1, y0, y1, speed_scale[0], speed_scale[1])
        if spath:
            parts.append(f'<path d="{spath}" fill="none" stroke="var(--hatch-widget-text)" stroke-width="1.6" stroke-linejoin="round"/>')
    if hr_scale:
        hpath, _ = _path_for(hr, x0, x1, y0, y1, hr_scale[0], hr_scale[1])
        if hpath:
            parts.append(f'<path d="{hpath}" fill="none" stroke="{HR_COLOR}" stroke-width="1.6" stroke-linejoin="round"/>')
    # X endpoints: 0 and total distance.
    parts.append(f'<text x="{x0}" y="{H - 4}" font-size="9.5" fill="var(--hatch-widget-muted)">0</text>')
    if distance_km:
        parts.append(f'<text x="{x1}" y="{H - 4}" font-size="9.5" text-anchor="end" fill="var(--hatch-widget-muted)">{distance_km} km</text>')
    parts.append('</svg>')
    return '<div class="prr-chart">' + "".join(parts) + '</div>'


def nums_line(pairs):
    segs = []
    for k, v in pairs:
        if v is None or v == "":
            continue
        segs.append(f'<span style="white-space:nowrap"><span class="k">{esc(k)}</span> <b>{esc(v)}</b></span>')
    if not segs:
        return ""
    return '<div class="prr-nums">' + ' · '.join(segs) + '</div>'


def render(d):
    h = ['<div class="prr">', CSS]
    h.append(f'<div class="prr-title">{esc(d.get("title", "跑步点评"))}</div>')
    sub = " · ".join(x for x in [d.get("subtitle") or "",
                                 f'{d["distance_km"]} km' if d.get("distance_km") else "",
                                 d.get("duration") or ""] if x)
    if sub:
        h.append(f'<div class="prr-sub">{esc(sub)}</div>')
    if d.get("lead"):
        h.append(f'<div class="prr-lead">{esc(d["lead"])}</div>')

    if d.get("chart"):
        svg = chart_svg(d["chart"], d.get("distance_km"), d.get("target_pace"))
        if svg:
            h.append(svg)

    stats = d.get("stats") or []
    if stats:
        pairs = []
        for t in stats[:4]:
            val = str(t.get("value", ""))
            if t.get("unit"):
                val += t["unit"]
            if t.get("note"):
                val += f'（{t["note"]}）'
            pairs.append((t.get("label", ""), val))
        line = nums_line(pairs)
        if line:
            h.append(line)

    dyn = d.get("dynamics") or {}
    if dyn:
        pairs = []
        if dyn.get("cadence") is not None:
            pairs.append(("步频", dyn["cadence"]))
        if dyn.get("stride_m") is not None:
            pairs.append(("步幅", f'{dyn["stride_m"]} m'))
        if dyn.get("vertical_cm") is not None:
            pairs.append(("振幅", f'{dyn["vertical_cm"]} cm'))
        if dyn.get("vertical_ratio") is not None:
            pairs.append(("垂直比", f'{dyn["vertical_ratio"]}%'))
        if dyn.get("gct_ms") is not None:
            pairs.append(("触地", f'{dyn["gct_ms"]} ms'))
        line = nums_line(pairs)
        if line:
            h.append(line)

    extra = d.get("extra_line") or []
    if extra:
        line = nums_line([(e.get("k", ""), e.get("v")) for e in extra])
        if line:
            h.append(line)

    zones = d.get("zones") or []
    total = sum(z.get("seconds", 0) for z in zones)
    if total:
        h.append('<div class="prr-zbar">')
        for z in zones:
            if not z.get("seconds"):
                continue
            pct = z["seconds"] / total * 100
            h.append(f'<div style="width:{pct:.1f}%;background:{ZONE_COLORS.get(z.get("key", ""), "#999")}"></div>')
        h.append('</div><div class="prr-zleg">')
        for z in zones:
            if not z.get("seconds"):
                continue
            pct = round(z["seconds"] / total * 100)
            h.append(f'<span><i style="background:{ZONE_COLORS.get(z.get("key", ""), "#999")}"></i>{esc(z.get("label", ""))} {pct}%</span>')
        h.append('</div>')

    structure = d.get("structure") or []
    if structure and d.get("show_structure"):
        h.append('<div class="prr-seg">')
        for s in structure:
            bits = []
            if s.get("duration"):
                bits.append(esc(s["duration"]))
            if s.get("pace"):
                bits.append(f'{esc(s["pace"])}/km')
            if s.get("target"):
                bits.append(f'目标 {esc(s["target"])}')
            if s.get("avg_hr"):
                bits.append(f'心率 {esc(s["avg_hr"])}')
            if s.get("cadence"):
                bits.append(f'步频 {esc(s["cadence"])}')
            h.append(f'<div class="r"><div class="lab">{esc(s.get("label", ""))}</div>'
                     f'<div>{" · ".join(bits)}</div></div>')
        h.append('</div>')

    comments = d.get("comments") or []
    if comments:
        h.append('<div class="prr-body">')
        for c in comments:
            text = c.get("t") if isinstance(c, dict) else str(c)
            if text:
                h.append(f'<p>{esc(text)}</p>')
        h.append('</div>')

    morning = d.get("morning") or {}
    if morning:
        items = []
        if morning.get("sleep_score") is not None:
            items.append(f'睡眠 {morning["sleep_score"]} 分')
        if morning.get("hrv") is not None:
            st = f'（{esc(morning["hrv_status"])}）' if morning.get("hrv_status") else ""
            items.append(f'HRV {morning["hrv"]} ms{st}')
        if morning.get("bb_wake") is not None:
            items.append(f'体电 {morning["bb_wake"]}')
        if morning.get("rhr") is not None:
            items.append(f'静息心率 {morning["rhr"]}')
        if items:
            h.append('<div class="prr-morn">今早 ' + ' · '.join(items) + '</div>')

    if d.get("takeaway"):
        h.append(f'<div class="prr-take">{esc(d["takeaway"])}</div>')
    h.append('</div>')
    return "".join(h)


if __name__ == "__main__":
    with open(sys.argv[1]) as f:
        print(render(json.load(f)))
