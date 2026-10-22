#!/usr/bin/env python3
"""Export the nightly training brief as a dark-mode PNG.

Pipeline: brief-latest.json -> render_brief.py fragment -> dark-theme
wrapper (600 CSS px wide) -> Chromium screenshot over CDP at 3x
(export_shot.js; headless --screenshot mode can hang, CDP is reliable)
-> crop the blank tail -> the output PNG. Default output is
~/workspace/your_files/brief-YYYY-MM-DD-dark.png (in Muse, chat
attachments load from your_files); pass argv[2] to write elsewhere.

Usage: export_brief.py [json_path] [out_png]
"""
import subprocess
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOME = Path.home()
JSON_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "brief-latest.json"
OUT_PNG = (Path(sys.argv[2]) if len(sys.argv) > 2
           else HOME / "workspace/your_files" / f"brief-{date.today().isoformat()}-dark.png")
EXPORT_DIR = HERE / "export"
RAW_PNG = EXPORT_DIR / "brief-dark-raw.png"
WRAPPER = EXPORT_DIR / "brief-export-dark.html"

DARK_WRAPPER = """<!DOCTYPE html><html data-theme="dark"><head><meta charset="utf-8"><style>
:root{
  --hatch-widget-text:#ecece8;
  --hatch-widget-muted:#9c9c96;
  --hatch-widget-border:#373732;
  --hatch-widget-surface-muted:#2a2a27;
  --hatch-widget-surface:#1d1d1b;
  --hatch-widget-bg:#161615;
  --hatch-widget-accent:#FF7A45;
  --hatch-widget-on-accent:#161615;
}
*{box-sizing:border-box;}
body{margin:0;background:#161615;font-family:"Noto Sans CJK SC","Source Han Sans SC",sans-serif;}
.tb{font-family:"PingFang SC","Noto Sans CJK SC","Source Han Sans SC",sans-serif !important;}
.wrap{width:600px;padding:10px;}
</style></head><body><div class="wrap">%s</div></body></html>"""


def main():
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    frag = subprocess.run(
        [sys.executable, str(HERE / "render_brief.py"), str(JSON_PATH)],
        capture_output=True, text=True, check=True).stdout
    WRAPPER.write_text(DARK_WRAPPER % frag)
    subprocess.run(
        ["node", str(HERE / "export_shot.js"), str(WRAPPER), str(RAW_PNG), "600", "3"],
        check=True, timeout=120)
    from PIL import Image
    im = Image.open(RAW_PNG).convert("RGB")
    w, h = im.size
    px = im.load()
    bg = px[2, 2]
    last = 0
    for y in range(h):
        for x in range(0, w, 5):
            r, g, b = px[x, y]
            if abs(r - bg[0]) > 10 or abs(g - bg[1]) > 10 or abs(b - bg[2]) > 10:
                last = y
                break
    OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    im.crop((0, 0, w, min(h, last + 30))).save(OUT_PNG)
    print(OUT_PNG)


if __name__ == "__main__":
    main()
