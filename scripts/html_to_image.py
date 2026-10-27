#!/usr/bin/env python3
"""Convert a specified message / HTML fragment into a PNG image.

This is the single, generic image path in muse-prompt. It is NOT used
by the nightly training brief or the post-run review any more -- those
two are delivered as HTML cards (widget token pasted into the delivery
message). Use this script only when the user explicitly asks to turn a
specified piece of content into an image, or as a manual fallback.

Pipeline: input -> generic theme wrapper (only when the input is a
fragment, not a full document) -> Chromium screenshot over CDP
(export_shot.js sitting next to this file; headless --screenshot can
hang in some VMs, CDP is reliable) -> crop the blank tail -> PNG.

Usage:
    html_to_image.py <input> <output.png>
        [--width 600] [--scale 3] [--theme dark|light]
        [--title "card title"]

<input> may be:
  - an HTML fragment file (no <html>/<body> wrapper): it is wrapped
    in a generic theme shell;
  - a full HTML document file: it is used as-is;
  - plain text (no '<' tag at all): it is escaped and wrapped in a
    simple card, one paragraph per line, with --title as its heading
    when given.

Defaults match the old brief/review exports so existing callers get
the same look: 600 CSS px wide, 3x device scale, dark theme.
Chinese fonts: "PingFang SC" first, then Noto Sans CJK SC / Source
Han Sans SC -- install a CJK font on Linux, otherwise Chinese text
will be missing or fall back badly.
"""

import argparse
import html as html_lib
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHOT_JS = HERE / "export_shot.js"

THEMES = {
    "dark": {
        "bg": "#11151b",
        "surface": "#1a2029",
        "text": "#e8edf3",
        "muted": "#98a4b3",
        "border": "#303a47",
        "accent": "#4da3ff",
    },
    "light": {
        "bg": "#ffffff",
        "surface": "#f5f5f4",
        "text": "#1a1a1a",
        "muted": "#666666",
        "border": "#dddddd",
        "accent": "#2563eb",
    },
}


def build_wrapper(content: str, theme: dict, width: int, title: str | None) -> str:
    heading = f'<div style="font-size:16px;font-weight:700;margin-bottom:8px;">{html_lib.escape(title)}</div>' if title else ""
    return f"""<!DOCTYPE html><html data-theme="dark"><head><meta charset="utf-8"><style>
:root{{
  --hatch-widget-text:{theme["text"]};
  --hatch-widget-muted:{theme["muted"]};
  --hatch-widget-border:{theme["border"]};
  --hatch-widget-surface:{theme["surface"]};
  --hatch-widget-bg:{theme["bg"]};
  --hatch-widget-accent:{theme["accent"]};
}}
*{{box-sizing:border-box;}}
body{{margin:0;background:{theme["bg"]};font-family:"PingFang SC","Noto Sans CJK SC","Source Han Sans SC",sans-serif;}}
.wrap{{width:{width}px;padding:10px;color:{theme["text"]};font-size:14px;line-height:1.7;}}
</style></head><body><div class="wrap">{heading}{content}</div></body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", help="HTML fragment, full HTML document, or plain text file")
    ap.add_argument("output", help="output PNG path")
    ap.add_argument("--width", type=int, default=600, help="CSS width in px (default 600)")
    ap.add_argument("--scale", type=float, default=3, help="device scale factor (default 3)")
    ap.add_argument("--theme", choices=["dark", "light"], default="dark")
    ap.add_argument("--title", default=None, help="heading for plain-text input")
    args = ap.parse_args()

    raw = Path(args.input).read_text(encoding="utf-8")
    stripped = raw.strip()
    if "<html" in stripped.lower() or "<body" in stripped.lower():
        document = raw
    elif "<" in stripped:
        # HTML fragment: wrap in the generic theme shell.
        document = build_wrapper(stripped, THEMES[args.theme], args.width, args.title)
    else:
        # Plain text message: escape, one paragraph per line.
        paras = "".join(f"<p style='margin:0 0 8px;'>{html_lib.escape(line)}</p>" for line in stripped.splitlines() if line.strip())
        document = build_wrapper(paras, THEMES[args.theme], args.width, args.title)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        wrapper = tmp / "wrapper.html"
        raw_png = tmp / "raw.png"
        wrapper.write_text(document, encoding="utf-8")
        subprocess.run(
            ["node", str(SHOT_JS), str(wrapper), str(raw_png), str(args.width), str(args.scale)],
            check=True, timeout=120,
        )
        from PIL import Image

        im = Image.open(raw_png).convert("RGB")
        w, h = im.size
        px = im.load()
        bg = px[2, 2]
        last = 0
        for y in range(h - 1, -1, -1):
            row_has_content = any(px[x, y] != bg for x in range(0, w, 4))
            if row_has_content:
                last = y
                break
        pad = int(10 * args.scale)
        im = im.crop((0, 0, w, min(h, last + pad + 1)))
        im.save(out)
    print(f"saved {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
