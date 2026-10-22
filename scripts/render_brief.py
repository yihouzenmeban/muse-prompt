#!/usr/bin/env python3
"""Render the nightly training brief card as an HTML fragment.

Usage: render_brief.py [brief.json]  -> prints the HTML fragment to stdout.

Input JSON is semantic (raw values); all chart geometry is computed here.
The layout: masthead + countdown, verdict, schedule rows, a 4-cell stats
strip, then two charts side by side — a Garmin-style 7-night HRV scatter
against the official baseline band, and a Garmin-style sleep hypnogram
(stage blocks with the night's HRV and heart-rate series overlaid on the
same time axis). Colors: ink/greys + one orange accent (#fc5200); sleep
stage colors sampled from the Garmin Connect app.
Schema (example values are fictional):
{
  "date_label": "5月13日 · 周三 · 深度减量期",
  "countdown": {"n": 12, "unit": "天", "label": "距目标 100K"},
  "verdict_html": "<b>恢复良好。</b>...",
  "plan": [{"date": "5/13", "sub": "周三 · 今天", "title": "恢复跑 <b>9.60</b> km",
            "detail": "...", "race": false}],
  "stats": [{"v": "7h01", "unit": "m", "l": "昨晚睡眠 · 85 分"} x4],
  "hrv": {"label": "夜间 HRV · 昨晚", "value": "79", "unit": "ms",
          "values": [72, 75, 71, 78, 74, 76, 79],
          "statuses": ["BALANCED", ...], "band": [64, 92],
          "low_upper": 58, "dates": ["5/7", ..., "5/13"]},
  "sleep_chart": {"label": "睡眠 · 昨晚", "value": "85", "unit": "分",
           "start": "23:12", "end": "06:13",
           "segments": [{"stage": "light", "seconds": 600}, ...],
           "hrv_readings": [{"t": "23:14", "v": 78}, ...], "hrv_avg": 79,
           "hr_readings": [{"t": "23:12", "v": 52}, ...], "hr_avg": 54,
           "legend": [{"stage": "deep", "label": "深睡 1h09"}, ...]},
  "weather": "天气：..."
}
"""
import json
import sys

CSS = """
.tb{--acc:#fc5200;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;color:var(--hatch-widget-text);box-sizing:border-box;padding:16px 18px 14px;font-variant-numeric:tabular-nums;}
html[data-theme="dark"] .tb{--acc:#ff7a45;}
.tb *{box-sizing:border-box;}
.tb-mast{display:flex;justify-content:space-between;align-items:flex-end;gap:12px;}
.tb-wm{font-size:17px;font-weight:800;line-height:1.3;}
.tb-wm span{display:block;font-size:12px;font-weight:400;color:var(--hatch-widget-muted);margin-top:2px;}
.tb-cd{text-align:right;flex:none;}
.tb-cd .n{font-size:34px;font-weight:800;line-height:1;color:var(--acc);}
.tb-cd .n small{font-size:14px;font-weight:700;}
.tb-cd .t{font-size:11px;color:var(--hatch-widget-muted);margin-top:3px;}
.tb-rule{border:none;border-top:1px solid var(--hatch-widget-border);margin:7px 0;}
.tb-rule.flush-t{margin-top:0;}
.tb-rule.flush-b{margin-bottom:0;}
.tb-verdict{font-size:15px;line-height:1.65;margin-top:12px;text-align:justify;}
.tb-verdict b{font-weight:700;}
.tb-strip{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;}
.cell .v{font-size:17px;font-weight:700;line-height:1.25;}
.cell .v small{font-size:11px;font-weight:500;color:var(--hatch-widget-muted);}
.cell .l{font-size:11px;color:var(--hatch-widget-muted);margin-top:2px;line-height:1.45;}
.tb-times{display:flex;justify-content:space-between;font-size:10px;color:var(--hatch-widget-muted);margin-top:4px;}
.sleep-legend{display:flex;gap:10px;flex-wrap:wrap;margin-top:0;font-size:10.5px;color:var(--hatch-widget-muted);}
.sleep-legend span{display:inline-flex;align-items:center;gap:5px;}
.sleep-legend b{width:8px;height:8px;border-radius:2px;display:inline-block;}
.sleep-legend i.lg-line{width:14px;height:2px;border-radius:1px;background:var(--hatch-widget-text);display:inline-block;}
.sleep-legend i.lg-hr{width:14px;height:2px;border-radius:1px;background:#e53935;display:inline-block;}
.tb-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:15px;}
.tb-grid>div{display:flex;flex-direction:column;}
.cell-fill{flex:1;}
.cell-desc{margin-top:7px;}
.hrv-sub{font-size:10.5px;color:var(--hatch-widget-muted);margin-top:5px;}
.tb-ch{display:flex;align-items:baseline;gap:8px;}
.tb-ch .lb{font-size:12px;font-weight:600;color:var(--hatch-widget-muted);white-space:nowrap;}
.tb-ch .val{font-size:13px;font-weight:700;white-space:nowrap;}
.tb-ch .val small{font-size:11px;font-weight:500;color:var(--hatch-widget-muted);}
.tb-days{display:flex;gap:4px;margin-top:4px;}
.tb-days em{flex:1;text-align:center;font-style:normal;font-size:10px;color:var(--hatch-widget-muted);}
.tb-days em.today{color:var(--acc);font-weight:700;}
svg .bar{fill:#d9dce0;}
html[data-theme="dark"] svg .bar{fill:#454b54;}
svg .bar-spike{fill:var(--hatch-widget-text);}
svg .bar-today{fill:var(--acc);}
svg text{font-family:inherit;}
.plan{margin-top:0;}
.rw{display:grid;grid-template-columns:66px 1fr;column-gap:14px;padding:9px 0;border-top:1px solid var(--hatch-widget-border);align-items:center;}
.rw:first-child{border-top:none;}
.rw .d1{font-size:13px;font-weight:700;line-height:20px;}
.rw .d2{font-size:11.5px;color:var(--hatch-widget-muted);line-height:17px;}
.rw .race{color:var(--acc);}
.rw .t1{font-size:13.5px;font-weight:600;line-height:20px;}
.rw .t1 b{font-weight:800;}
.rw .t2{font-size:12.5px;color:var(--hatch-widget-muted);line-height:17px;}
.tb-foot{font-size:12.5px;color:var(--hatch-widget-muted);line-height:1.6;padding-top:11px;text-align:justify;}
"""


def f1(x):
    """Format with at most 1 decimal, dropping a trailing .0"""
    s = f"{round(float(x), 1):.1f}"
    return s[:-2] if s.endswith(".0") else s


def xs_for(n):
    if n <= 1:
        return [85.0]
    return [8 + i * (154 / (n - 1)) for i in range(n)]


def hrv_svg(h):
    """Garmin-style 7-night HRV scatter (modelled on the Connect app):
    dots only, no connecting line; the official baseline band
    (h["band"] = [balanced_low, balanced_high]) behind them; y gridlines
    every 30 with left labels. Each dot is one night's HRV (single-night
    value; plotting the 7-day average instead was tried and reverted —
    the single-night value is what the app shows and reads better).
    Marker shape = that day's Garmin status (BALANCED circle, UNBALANCED
    square, LOW/POOR triangle); marker COLOR = position vs the official
    baseline: in band green #428947, below band orange #d27034, below
    low_upper red #b94038. Y domain: data range padded a little and
    snapped to 10s, gridlines every 30."""
    vals = h["values"]
    statuses = h.get("statuses") or []
    blo, bhi = h["band"]
    lu = h.get("low_upper") or 0
    lo = int((min(min(vals), blo) - 5) // 10 * 10)
    hi = int(-((-(max(max(vals), bhi) + 5)) // 10) * 10)
    if hi - lo < 60:
        hi = lo + 60

    def pos_color(v):
        if lu and v < lu:
            return "#b94038"
        if v < blo:
            return "#d27034"
        return "#428947"
    X0, X1, YT, YB = 22.0, 164.0, 4.0, 78.0

    def Y(v):
        return YB - (v - lo) / (hi - lo) * (YB - YT)

    def X(i):
        return X0 + i * (X1 - X0) / max(1, len(vals) - 1)

    out = ['<svg viewBox="0 0 170 84" style="width:100%;height:auto;display:block;margin-top:6px;" role="img" aria-label="近7晚HRV散点图（佳明基准带）">']
    t = int(lo // 30 * 30) + 30
    while t < hi:
        y = Y(t)
        out.append(f'<line x1="20" y1="{f1(y)}" x2="170" y2="{f1(y)}" stroke="var(--hatch-widget-border)" stroke-width="0.7"></line>')
        out.append(f'<text x="16" y="{f1(y + 2.5)}" text-anchor="end" font-size="8" fill="var(--hatch-widget-muted)">{t}</text>')
        t += 30
    out.append(f'<rect x="20" y="{f1(Y(bhi))}" width="150" height="{f1(Y(blo) - Y(bhi))}" fill="var(--hatch-widget-surface-muted)"></rect>')
    for i, v in enumerate(vals):
        st = statuses[i] if i < len(statuses) else None
        x, y = X(i), Y(v)
        col = pos_color(v)
        if st == "UNBALANCED":
            out.append(f'<rect x="{f1(x - 3.2)}" y="{f1(y - 3.2)}" width="6.4" height="6.4" fill="{col}"></rect>')
        elif st in ("LOW", "POOR"):
            out.append(f'<polygon points="{f1(x)},{f1(y - 3.8)} {f1(x - 3.6)},{f1(y + 2.8)} {f1(x + 3.6)},{f1(y + 2.8)}" fill="{col}"></polygon>')
        else:
            out.append(f'<circle cx="{f1(x)}" cy="{f1(y)}" r="3.4" fill="{col}"></circle>')
    out.append("</svg>")
    return "".join(out)


STAGE_COLORS = {"deep": "#3971c1", "light": "#69a3ed",
                "rem": "#bc40b3", "awake": "#d67ec8"}
STAGE_HEIGHTS = {"deep": 19, "light": 40, "rem": 60, "awake": 76}
HR_COLOR = "#e53935"


def _minutes(hhmm):
    try:
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return None


def _overlay_pts(readings, start_min, total_min, pad, x0=0.0, width=170.0):
    """Map [{t: HH:MM, v}] readings onto the night's shared time axis;
    y scaled to the series' own min/max ± pad, into the 8–76 band.
    Returns (points_str, lo, hi) — the scale goes back so the caller can
    draw axis labels for it."""
    vals = [r["v"] for r in readings]
    lo, hi = min(vals) - pad, max(vals) + pad
    pts = []
    for r in readings:
        tm = _minutes(r.get("t") or "")
        if tm is None:
            continue
        off = tm - start_min
        if off < 0:
            off += 1440
        x = x0 + off / total_min * width
        if x0 <= x <= x0 + width:
            y = 76 - (r["v"] - lo) / (hi - lo) * 68
            pts.append(f"{f1(x)},{f1(y)}")
    return (" ".join(pts) if len(pts) > 1 else ""), lo, hi


def sleep_svg(sc):
    """Garmin-style hypnogram: contiguous stage blocks across the night,
    block height = stage depth (awake tallest, deep shortest). The night's
    heart-rate (accent) and HRV (ink) series overlay the same time axis."""
    segs = sc["segments"]
    total = sum(s["seconds"] for s in segs) or 1
    PX0, PX1 = 18.0, 152.0  # plot area, leaving room for the two y-axes
    PW = PX1 - PX0
    out = ['<svg viewBox="0 0 170 84" style="width:100%;height:auto;display:block;margin-top:6px;" role="img" aria-label="昨晚睡眠阶段图（含整晚心率与 HRV 曲线）">']
    acc = 0.0
    for s in segs:
        w = s["seconds"] / total * PW
        h = STAGE_HEIGHTS[s["stage"]]
        out.append(f'<rect x="{f1(PX0 + acc)}" y="{f1(84 - h)}" width="{f1(w)}" height="{h}" fill="{STAGE_COLORS[s["stage"]]}"></rect>')
        acc += w
    start_min = _minutes(sc.get("start") or "")
    if start_min is not None:
        total_min = total / 60.0
        hr_lo = hr_hi = hrv_lo = hrv_hi = None
        hr = [r for r in (sc.get("hr_readings") or []) if r.get("v") is not None]
        if hr:
            # Raw 2-min HR samples spike ±10 bpm between neighbours; draw a
            # centered 5-point (10-min) moving average, like Garmin's app.
            vs = [r["v"] for r in hr]
            smoothed = [{"t": r["t"],
                         "v": sum(vs[max(0, i - 2):i + 3]) / len(vs[max(0, i - 2):i + 3])}
                        for i, r in enumerate(hr)]
            pts, hr_lo, hr_hi = _overlay_pts(smoothed, start_min, total_min, 3, PX0, PW)
            if pts:
                out.append(f'<polyline points="{pts}" fill="none" stroke="{HR_COLOR}" stroke-width="0.8" stroke-linejoin="round" stroke-linecap="round" opacity="0.6"></polyline>')
        readings = [r for r in (sc.get("hrv_readings") or []) if r.get("v") is not None]
        if readings:
            pts, hrv_lo, hrv_hi = _overlay_pts(readings, start_min, total_min, 8, PX0, PW)
            if pts:
                out.append(f'<polyline points="{pts}" fill="none" stroke="var(--hatch-widget-text)" stroke-width="0.9" stroke-linejoin="round" stroke-linecap="round" opacity="0.65"></polyline>')
        # dual axes: HRV scale left, HR scale right (top/mid/bottom of each
        # series' own scale, matching the 8/42/76 y anchors of the mapping)
        if hrv_lo is not None:
            for yy, vv in ((8, hrv_hi), (42, (hrv_lo + hrv_hi) / 2), (76, hrv_lo)):
                out.append(f'<text x="{f1(PX0 - 3)}" y="{f1(yy + 2.5)}" text-anchor="end" font-size="7.5" fill="var(--hatch-widget-muted)">{round(vv)}</text>')
        if hr_lo is not None:
            for yy, vv in ((8, hr_hi), (42, (hr_lo + hr_hi) / 2), (76, hr_lo)):
                out.append(f'<text x="{f1(PX1 + 3)}" y="{f1(yy + 2.5)}" font-size="7.5" fill="var(--hatch-widget-muted)">{round(vv)}</text>')
    out.append("</svg>")
    return "".join(out)


def sleep_legend(sc):
    items = "".join(
        f'<span><b style="background:{STAGE_COLORS[it["stage"]]};"></b>{it["label"]}</span>'
        for it in sc.get("legend") or [])
    if sc.get("hrv_avg") is not None:
        items += f'<span><i class="lg-line"></i>HRV · 均值 {sc["hrv_avg"]}</span>'
    if sc.get("hr_avg") is not None:
        items += f'<span><i class="lg-hr"></i>心率 · 均值 {sc["hr_avg"]}</span>'
    return f'<div class="sleep-legend">{items}</div>' if items else ""


def days_row(labels, today_index):
    cells = []
    for i, t in enumerate(labels):
        cls = ' class="today"' if i == today_index else ""
        cells.append(f"<em{cls}>{t}</em>")
    return f'<div class="tb-days">{"".join(cells)}</div>'


def render(d):
    p = ['<div class="tb">', f"<style>{CSS}</style>"]
    cd = d["countdown"]
    p.append(f'<div class="tb-mast"><div class="tb-wm">训练播报<span>{d["date_label"]}</span></div>'
             f'<div class="tb-cd"><div class="n">{cd["n"]}<small> {cd["unit"]}</small></div><div class="t">{cd["label"]}</div></div></div>')
    p.append(f'<div class="tb-verdict">{d["verdict_html"]}</div>')
    # plan (schedule) above the data blocks
    p.append('<hr class="tb-rule flush-b" style="margin-top:16px"><div class="plan">')
    for r in d["plan"]:
        race = ' class="race"' if r.get("race") else ""
        d1cls = 'd1 race' if r.get("race") else 'd1'
        d2cls = 'd2 race' if r.get("race") else 'd2'
        p.append(f'<div class="rw"><div><div class="{d1cls}">{r["date"]}</div><div class="{d2cls}">{r["sub"]}</div></div>'
                 f'<div><div class="t1">{r["title"]}</div><div class="t2">{r["detail"]}</div></div></div>')
    p.append("</div>")
    # stats + sleep structure
    p.append('<hr class="tb-rule flush-t"><div style="margin-top:20px;"><div class="tb-strip">')
    for s in d["stats"]:
        unit = f'<small>{s["unit"]}</small>' if s.get("unit") else ""
        p.append(f'<div class="cell"><div class="v">{s["v"]}{unit}</div><div class="l">{s["l"]}</div></div>')
    p.append("</div>")
    p.append("</div>")
    # charts side by side, equal height: HRV trend + last night's sleep stages
    h, sc = d["hrv"], d["sleep_chart"]
    p.append('<hr class="tb-rule"><div class="tb-grid">')
    p.append(f'<div>{sleep_svg(sc)}'
             f'<div class="tb-times"><span>{sc["start"]}</span><span>{sc["end"]}</span></div>'
             f'<div class="cell-fill"></div><div class="cell-desc">{sleep_legend(sc)}</div></div>')
    p.append(f'<div>{hrv_svg(h)}'
             f'<div class="tb-times"><span>{h["dates"][0]}</span><span>{h["dates"][-1]}</span></div>'
             f'<div class="cell-fill"></div><div class="cell-desc"><div class="tb-ch"><span class="lb">{h["label"]}</span><span class="val">{h["value"]} <small>{h["unit"]}</small></span></div>'
             f'<div class="hrv-sub">近 7 晚 {min(h["values"])}–{max(h["values"])} · 基准带 {h["band"][0]}–{h["band"][1]}</div></div></div>')
    p.append("</div>")
    if d.get("weather"):
        p.append(f'<hr class="tb-rule"><div class="tb-foot">{d["weather"]}</div>')
    p.append("</div>")
    return "".join(p)


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "~/workspace/brief-latest.json"
    import os
    with open(os.path.expanduser(path), encoding="utf-8") as fh:
        data = json.load(fh)
    print(render(data))
