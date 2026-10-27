#!/usr/bin/env python3
"""QWeather (和风天气) quick lookup: current conditions, daily and
hourly forecasts as compact JSON.

The API key never appears in this script: fetch() comes from a Muse
custom-connector helper (custom.qweather) that reads the key from the
secure vault and calls your dedicated QWeather API host. If you don't
use that connector, replace the fetch import with your own function
that GETs https://<your-api-host>/v7/... with your key as the `key`
query parameter and returns the parsed JSON.

QWeather keys usually don't include the geo/city-lookup API, so known
places are mapped to location IDs / lon,lat in PLACES below. Keep your
own cities OUT of this script: put them in a JSON object
{name: location-id-or-"lon,lat"} at $QWEATHER_PLACES_FILE, or by default
~/workspace/weather/places.local.json — entries there override the
examples below, and that file is yours, never part of the template.

Usage:
    python3 qw.py now 北京
    python3 qw.py daily 北京 7
    python3 qw.py hourly 北京
"""
import json
import os
import sys
from pathlib import Path

_HELPER_DIR = os.environ.get(
    "QWEATHER_HELPER_DIR",
    str(Path.home() / "workspace/custom-connectors/custom.qweather/bin"))
sys.path.insert(0, _HELPER_DIR)
from qweather import fetch  # noqa: E402

# Example places. Values are QWeather location IDs, or "lon,lat" for
# places without an ID.
PLACES = {
    "北京": "101010100", "beijing": "101010100",
    "上海": "101020100", "shanghai": "101020100",
    "广州": "101280101", "guangzhou": "101280101",
}

# User places override (see docstring): silently ignored when absent.
_PLACES_FILE = os.environ.get(
    "QWEATHER_PLACES_FILE",
    str(Path.home() / "workspace/weather/places.local.json"))
try:
    with open(_PLACES_FILE, encoding="utf-8") as _fh:
        PLACES.update(json.load(_fh))
except (OSError, ValueError):
    pass


def _call(path, location, extra=None):
    loc = PLACES.get(location, location)
    params = {"location": loc}
    params.update(extra or {})
    return fetch(path, params)


def cmd_now(place):
    n = _call("/v7/weather/now", place)["now"]
    print(json.dumps({
        "place": place,
        "time": n.get("obsTime"),
        "weather": n.get("text"),
        "temp_c": n.get("temp"),
        "feels_like_c": n.get("feelsLike"),
        "humidity": n.get("humidity"),
        "wind": f"{n.get('windDir')}{n.get('windScale')}级",
        "precip_mm": n.get("precip"),
    }, ensure_ascii=False))


def cmd_daily(place, days="3"):
    days = "7" if days == "7" else "3"
    items = _call(f"/v7/weather/{days}d", place)["daily"]
    out = [{
        "date": d.get("fxDate"),
        "day": d.get("textDay"), "night": d.get("textNight"),
        "temp_max": d.get("tempMax"), "temp_min": d.get("tempMin"),
        "wind_day": f"{d.get('windDirDay')}{d.get('windScaleDay')}级",
        "precip_mm": d.get("precip"),
        "humidity": d.get("humidity"),
    } for d in items]
    print(json.dumps(out, ensure_ascii=False))


def cmd_hourly(place):
    items = _call("/v7/weather/24h", place)["hourly"]
    out = [{
        "time": h.get("fxTime")[11:16],
        "weather": h.get("text"),
        "temp_c": h.get("temp"),
        "precip_mm": h.get("precip"),
        "wind": f"{h.get('windDir')}{h.get('windScale')}级",
    } for h in items]
    print(json.dumps(out, ensure_ascii=False))


def main():
    if len(sys.argv) < 3:
        print("usage: qw.py [now|daily|hourly] <place> [days]", file=sys.stderr)
        return 2
    cmd, place = sys.argv[1], sys.argv[2]
    try:
        if cmd == "now":
            cmd_now(place)
        elif cmd == "daily":
            cmd_daily(place, sys.argv[3] if len(sys.argv) > 3 else "3")
        elif cmd == "hourly":
            cmd_hourly(place)
        else:
            print(f"unknown command {cmd}", file=sys.stderr)
            return 2
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)[:150]}, ensure_ascii=False))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
