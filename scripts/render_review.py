#!/usr/bin/env python3
"""Render a post-run review card (HTML fragment) from a review JSON.

Usage: render_review.py <review.json>  ->  HTML fragment on stdout.

Layout: compact and
visual first. One timeline chart (pace line + HR line + elevation wash,
from detail.stream) carries the shape of the run; the numbers collapse
into two inline lines; the HR zone bar stays; segment rows appear only
for structured workouts and races (show_structure). Ordinary sessions
(A-layout): prose is the lead plus one takeaway only — execution goes
to vs_bars (per-segment target band vs actual tick) and the morning
state to recovery (four mini gauges); when either field is present,
comments and the text morning line are not rendered. Races keep
comments + structure. In the dark export, blue (#4da3ff, the Z1 colour)
carries every target/reference mark and red is HR only.
Every field is optional except title.
"""
import json
import math
import sys

ZONE_COLORS = {
    "below": "#8fa3bf", "z1": "#4da3ff", "z2": "#34c77b",
    "z3": "#f2c037", "z4": "#f08c3c", "z5": "#e5534b",
}
HR_COLOR = "#e5534b"

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
.prr-vs{margin-top:12px}
.prr-vs .row{display:flex;align-items:center;gap:10px;margin-top:7px}
.prr-vs .lab{flex:none;width:var(--labw,98px);font-size:12px;color:var(--hatch-widget-muted);white-space:nowrap}
.prr-vs .track{position:relative;flex:1;height:14px;background:var(--hatch-widget-surface-muted);border-radius:4px}
.prr-vs .band{position:absolute;top:0;bottom:0;background:var(--hatch-widget-accent);opacity:.30;border-radius:4px}
.prr-vs .mark{position:absolute;top:-2px;bottom:-2px;width:3px;margin-left:-1px;background:var(--hatch-widget-text);border-radius:2px}
.prr-vs .val{flex:none;width:var(--valw,56px);font-size:12.5px;font-variant-numeric:tabular-nums;line-height:1.3;text-align:right;white-space:nowrap}
.prr-vs .val .d{display:block;font-size:10.5px;color:var(--hatch-widget-muted)}
.prr-vs .cap{font-size:11px;color:var(--hatch-widget-muted);margin-top:6px}
.prr-rec{display:flex;gap:12px;margin-top:12px}
.prr-rec .cell{flex:1;min-width:0}
.prr-rec .lab{font-size:11px;color:var(--hatch-widget-muted)}
.prr-rec .vis{position:relative;height:8px;background:var(--hatch-widget-surface-muted);border-radius:4px;margin-top:6px}
.prr-rec .fill{position:absolute;left:0;top:0;bottom:0;background:var(--hatch-widget-text);border-radius:4px}
.prr-rec .filldim{position:absolute;top:0;bottom:0;background:var(--hatch-widget-text);opacity:.35}
.prr-rec .band{position:absolute;top:0;bottom:0;background:var(--hatch-widget-accent);opacity:.32;border-radius:4px}
.prr-rec .dot{position:absolute;top:50%;width:11px;height:11px;border-radius:50%;background:var(--hatch-widget-text);border:2px solid var(--hatch-widget-bg);transform:translate(-50%,-50%)}
.prr-rec .tick{position:absolute;top:-2px;bottom:-2px;width:2px;margin-left:-1px;background:var(--hatch-widget-muted)}
.prr-rec .val{font-size:12px;margin-top:6px;font-variant-numeric:tabular-nums;white-space:nowrap}
.prr-rec .val b{font-weight:650}
.prr-rec .val .m{color:var(--hatch-widget-muted);font-size:11px}
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
    T, B = 8, 16  # top/bottom insets are fixed; left/right are sized below
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
        # Pace can't go below zero: padding must not invent a negative
        # tick (it used to render as a nonsense "0:-15" label).
        lo = max(0, lo)
        ticks = [t for t in ticks if t >= 0]
        pace_scale = (lo / 60, hi / 60, [t / 60 for t in ticks])
    elif speed_vals:
        speed_scale = _nice_scale(min(speed_vals), max(speed_vals), 5, 0.25, 2)

    # Left/right insets sized to the actual tick labels, so long labels
    # (e.g. a 16:22 pace tick when the watch kept recording after the
    # finish) are never clipped at the card edge.
    def _lbl_w(s):
        return sum(5.5 if ch.isdigit() else 3.0 for ch in s)

    hr_w = max([_lbl_w(f"{tv:g}") for tv in hr_scale[2]] or [0]) if hr_scale else 0
    right_labels = []
    if pace_scale:
        right_labels = [fmt_pace(tv) for tv in pace_scale[2]]
    elif speed_scale:
        right_labels = [f"{tv:g}" for tv in speed_scale[2]]
    r_w = max([_lbl_w(s) for s in right_labels] or [0])
    L = int(hr_w + 6) if hr_scale else 22
    R = int(r_w + 6) if right_labels else 26
    x0, x1, y0, y1 = L, W - R, T, H - B

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


def vs_bars_html(rows):
    """Execution comparison bars: one row per workout segment.

    Shared pace scale (fast at right, snapped to 15s steps like the chart).
    The target band is a tinted span on the track, the actual pace a tick;
    the value column carries the pace plus a plain delta vs the nearest
    band edge (带内 / 快 N 秒 / 慢 N 秒). Rows without a target show the
    tick on a plain track with delta 计划外.
    """
    vals = []
    for r in rows:
        if r.get("actual") is not None:
            vals.append(r["actual"])
        t = r.get("target") or {}
        if t.get("lo") is not None:
            vals.append(t["lo"])
        if t.get("hi") is not None:
            vals.append(t["hi"])
    if not vals:
        return ""
    lo, hi = min(vals), max(vals)
    pad = max(0.25, (hi - lo) * 0.18)
    lo = math.floor((lo - pad) * 4) / 4
    hi = math.ceil((hi + pad) * 4) / 4
    if hi - lo < 1.0:
        mid = (lo + hi) / 2
        lo, hi = mid - 0.5, mid + 0.5

    def X(p):
        return (hi - p) / (hi - lo) * 100

    def delta_of(r):
        actual = r.get("actual")
        t = r.get("target") or {}
        if actual is None:
            return ""
        if t.get("lo") is not None and t.get("hi") is not None:
            if actual < t["lo"]:
                return f'快 {round((t["lo"] - actual) * 60)} 秒'
            if actual > t["hi"]:
                return f'慢 {round((actual - t["hi"]) * 60)} 秒'
            return "带内"
        return "计划外"

    def est_w(s, cjk_px, asc_px):
        return sum(cjk_px if ord(c) > 0x2E7F else asc_px for c in s)

    # Uniform label/value columns sized to the widest row, so every track
    # shares the same left and right edge (ragged tracks look broken).
    labw = max([est_w(str(r.get("label", "")), 12.2, 6.8) for r in rows] + [40]) + 3
    valw = 44
    for r in rows:
        if r.get("actual") is not None:
            valw = max(valw, est_w(fmt_pace(r["actual"]), 12.5, 7.4),
                       est_w(delta_of(r), 10.6, 6.1))
    valw += 3

    out = [f'<div class="prr-vs" style="--labw:{labw:.0f}px;--valw:{valw:.0f}px">']
    for r in rows:
        actual = r.get("actual")
        t = r.get("target") or {}
        band = ""
        if t.get("lo") is not None and t.get("hi") is not None:
            left = X(t["hi"])
            width = X(t["lo"]) - X(t["hi"])
            band = f'<div class="band" style="left:{left:.1f}%;width:{width:.1f}%"></div>'
        mark = ""
        delta = delta_of(r)
        if actual is not None:
            mark = f'<div class="mark" style="left:{X(actual):.1f}%"></div>'
        val = ""
        if actual is not None:
            val = (f'<div class="val"><b>{fmt_pace(actual)}</b>'
                   f'<span class="d">{delta}</span></div>')
        out.append(f'<div class="row"><div class="lab">{esc(r.get("label", ""))}</div>'
                   f'<div class="track">{band}{mark}</div>{val}</div>')
    out.append('<div class="cap">色带 = 课表目标 · 竖线 = 实际配速（右 = 更快）</div></div>')
    return "".join(out)


_HRV_STATUS_CN = {"BALANCED": "平衡", "LOW": "偏低", "UNBALANCED": "不平衡", "POOR": "差"}


def recovery_html(rec):
    """Morning recovery strip: up to four mini gauges in one row.

    sleep: 0-100 fill bar. hrv: dot on the Garmin balanced band.
    bb: wake level bar with this session's drain as a dim segment.
    rhr: dot vs the 7-day average tick. Missing cells are skipped.
    """
    cells = []
    if rec.get("sleep_score") is not None:
        s = rec["sleep_score"]
        cells.append(
            '<div class="cell"><div class="lab">睡眠</div>'
            f'<div class="vis"><div class="fill" style="width:{s:.0f}%"></div></div>'
            f'<div class="val"><b>{s}</b> <span class="m">分</span></div></div>')
    hv = rec.get("hrv") or {}
    if hv.get("value") is not None and hv.get("base_lo") is not None and hv.get("base_hi") is not None:
        v, blo, bhi = hv["value"], hv["base_lo"], hv["base_hi"]
        lo = math.floor(blo * 0.72 / 5) * 5
        hi = math.ceil(bhi * 1.28 / 5) * 5

        def HX(x):
            return (x - lo) / (hi - lo) * 100

        st = _HRV_STATUS_CN.get(str(hv.get("status", "")).upper(), hv.get("status") or "")
        st_html = f' <span class="m">{esc(st)}</span>' if st else ""
        cells.append(
            '<div class="cell"><div class="lab">HRV · 基准带</div>'
            f'<div class="vis"><div class="band" style="left:{HX(blo):.1f}%;width:{HX(bhi) - HX(blo):.1f}%"></div>'
            f'<div class="dot" style="left:{HX(v):.1f}%"></div></div>'
            f'<div class="val"><b>{v}</b> <span class="m">ms</span>{st_html}</div></div>')
    bb = rec.get("bb") or {}
    if bb.get("wake") is not None:
        wake = bb["wake"]
        drain = bb.get("drain")
        dim = ""
        fill_to = wake
        val = f'<b>{wake}</b> <span class="m">晨起</span>'
        if drain is not None:
            after = wake + drain
            fill_to = after
            dim = (f'<div class="filldim" style="left:{after:.0f}%;width:{-drain:.0f}%"></div>')
            val = f'<b>{wake} → {after}</b> <span class="m">本课 {drain}</span>'
        cells.append(
            '<div class="cell"><div class="lab">身体电量</div>'
            f'<div class="vis"><div class="fill" style="width:{fill_to:.0f}%"></div>{dim}</div>'
            f'<div class="val">{val}</div></div>')
    rh = rec.get("rhr") or {}
    if rh.get("value") is not None:
        v = rh["value"]
        avg = rh.get("avg7")
        lo = min(v, avg if avg is not None else v) - 6
        hi = max(v, avg if avg is not None else v) + 6

        def RX(x):
            return (x - lo) / (hi - lo) * 100

        tick = f'<div class="tick" style="left:{RX(avg):.1f}%"></div>' if avg is not None else ""
        avg_html = f' <span class="m">7日 {avg}</span>' if avg is not None else ""
        cells.append(
            '<div class="cell"><div class="lab">静息心率</div>'
            f'<div class="vis">{tick}<div class="dot" style="left:{RX(v):.1f}%"></div></div>'
            f'<div class="val"><b>{v}</b>{avg_html}</div></div>')
    if not cells:
        return ""
    return '<div class="prr-rec">' + "".join(cells) + '</div>'


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
            pairs.append(("垂直振幅", f'{dyn["vertical_cm"]} cm'))
        if dyn.get("vertical_ratio") is not None:
            pairs.append(("垂直比", f'{dyn["vertical_ratio"]}%'))
        if dyn.get("gct_ms") is not None:
            pairs.append(("触地时间", f'{dyn["gct_ms"]} ms'))
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

    vs_bars = d.get("vs_bars") or []
    if vs_bars:
        block = vs_bars_html(vs_bars)
        if block:
            h.append(block)

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

    # A-layout (visual-first): when the comparison bars or the recovery
    # strip carry the story, prose comments and the text morning line are
    # not rendered — the text budget is lead + takeaway only.
    visual_first = bool(vs_bars or d.get("recovery"))
    comments = d.get("comments") or []
    if comments and not visual_first:
        h.append('<div class="prr-body">')
        for c in comments:
            text = c.get("t") if isinstance(c, dict) else str(c)
            if text:
                h.append(f'<p>{esc(text)}</p>')
        h.append('</div>')

    recovery = d.get("recovery") or {}
    if recovery:
        block = recovery_html(recovery)
        if block:
            h.append(block)

    morning = d.get("morning") or {}
    if morning and not recovery:
        items = []
        if morning.get("sleep_score") is not None:
            items.append(f'睡眠 {morning["sleep_score"]} 分')
        if morning.get("hrv") is not None:
            st = f'（{esc(morning["hrv_status"])}）' if morning.get("hrv_status") else ""
            items.append(f'HRV {morning["hrv"]} ms{st}')
        if morning.get("bb_wake") is not None:
            items.append(f'身体电量 {morning["bb_wake"]}')
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
