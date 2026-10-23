#!/usr/bin/env python3
"""Export a post-run review card as a dark-mode PNG.

Shares the nightly brief's image pipeline (same dark theme variables —
the slate-blue palette below — same 600 CSS px width at 3x, same CDP
screenshot tool — the export_shot.js sitting next to this file — same
blank-tail crop, except the bottom inset mirrors the measured top inset
so padding reads uniform). The review fragment's own margin/max-width
are neutralized so padding is uniform: 10px wrapper gutter + the card's
own 14/16px padding, nothing else.

Usage: export_review.py [review_json] [out_png]
Default json: last_review.json next to this script.
Default out:  review-card-<activity date or today>-dark.png next to it.
"""
import subprocess
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHOT_JS = HERE / "export_shot.js"
JSON_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "last_review.json"
OUT_PNG = (Path(sys.argv[2]) if len(sys.argv) > 2
           else HERE / f"review-card-{date.today().isoformat()}-dark.png")
RAW_PNG = HERE / "export" / "review-dark-raw.png"
WRAPPER = HERE / "export" / "review-export-dark.html"

DARK_WRAPPER = """<!DOCTYPE html><html data-theme="dark"><head><meta charset="utf-8"><style>
:root{
  --hatch-widget-text:#e8edf3;
  --hatch-widget-muted:#98a4b3;
  --hatch-widget-border:#303a47;
  --hatch-widget-surface-muted:#232b36;
  --hatch-widget-surface:#1a2029;
  --hatch-widget-bg:#11151b;
  --hatch-widget-accent:#4da3ff;
  --hatch-widget-on-accent:#0d1117;
  --hatch-widget-focus:#4da3ff;
  --hatch-widget-shadow:none;
}
*{box-sizing:border-box;}
body{margin:0;background:#11151b;font-family:"PingFang SC","Noto Sans CJK SC","Source Han Sans SC",sans-serif;}
.wrap{width:600px;padding:10px;}
.prr{margin:0 !important;max-width:none !important;}
</style></head><body><div class="wrap">%s</div></body></html>"""


def main():
    (HERE / "export").mkdir(parents=True, exist_ok=True)
    frag = subprocess.run(
        [sys.executable, str(HERE / "render.py"), str(JSON_PATH)],
        capture_output=True, text=True, check=True).stdout
    WRAPPER.write_text(DARK_WRAPPER % frag)
    subprocess.run(
        ["node", str(SHOT_JS), str(WRAPPER), str(RAW_PNG), "600", "3"],
        check=True, timeout=120)
    from PIL import Image
    im = Image.open(RAW_PNG).convert("RGB")
    w, h = im.size
    px = im.load()
    bg = px[2, 2]
    first = None
    last = 0
    for y in range(h):
        for x in range(0, w, 5):
            r, g, b = px[x, y]
            if abs(r - bg[0]) > 10 or abs(g - bg[1]) > 10 or abs(b - bg[2]) > 10:
                if first is None:
                    first = y
                last = y
                break
    OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    # Bottom inset mirrors the measured top inset, so padding reads uniform.
    im.crop((0, 0, w, min(h, last + (first or 0) + 1))).save(OUT_PNG)
    print(OUT_PNG)


if __name__ == "__main__":
    main()
