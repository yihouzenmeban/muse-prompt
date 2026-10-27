#!/usr/bin/env python3
"""Pull your Garmin activities and health data via API (read-only).

This is the data source for the nightly training brief (see
../daily-training-brief.md). It prints JSON on stdout: activity
summaries (optionally with lap splits, structured-workout detail and
time-series streams) plus daily health — sleep (with stage timeline and
overnight HR series), overnight HRV with Garmin's official baseline
band, stress, Body Battery, daily summaries and weight.

Data paths (verified empirically against the official Personal API
Swagger spec):
- Activities, HRV, stress, sleep, daily summaries, activity details,
  HR zones, fitness age and weight come from the Garmin Personal API
  gateway (personal.connectapi.garmin.com) using your account's API
  key. Sleep uses the spec'd sleep-service path (the legacy Connect
  path wellness-service/wellness/dailySleepData is NOT served by the
  gateway); resting HR comes from wellness dailyHeartRate, overnight
  HRV/status from hrv-service, and the overnight Body Battery change
  plus the at-wake Body Battery from usersummary/daily
  (bodyBatteryDuringSleep / bodyBatteryAtWakeTime).
- Two things the Personal API does not expose — per-lap splits and the
  sleep stage timeline — come from the garth backend of the
  garmin2coros project (https://github.com/yihouzenmeban/garmin2coros),
  which this script imports. Clone that repo first.

Configuration (environment variables):
- GARMIN_SYNC_PROJECT: path to your garmin2coros clone
  (default ~/workspace/garmin-sync-coros). Your Garmin credentials and
  Personal API key live in that project's config.local.json (see its
  config.example.json); this script never prints tokens or passwords.
- GARMIN_ACCOUNT: account id inside config.local.json (default
  "account_a" — rename to whatever id you configured).
- PULL_TZ: your timezone (default "Asia/Shanghai").

Usage:
    python pull.py --days 7 --limit 50 --detail 10 --health
    python pull.py --profile   # HR zones + fitness age only
"""
import argparse
import datetime
import json
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

SYNC_PROJECT = os.environ.get(
    "GARMIN_SYNC_PROJECT", str(Path.home() / "workspace/garmin-sync-coros"))
sys.path.insert(0, f"{SYNC_PROJECT}/scripts")

from garmin.cn.garth_backend import GarthBackend  # noqa: E402
from garmin.garmin_client import GarminClient  # noqa: E402

TZ = ZoneInfo(os.environ.get("PULL_TZ", "Asia/Shanghai"))
ACCOUNT_ID = os.environ.get("GARMIN_ACCOUNT", "account_a")
PERSONAL_BASE = "https://personal.connectapi.garmin.com"


def _account_config(account_id):
    cfg = json.load(open(f"{SYNC_PROJECT}/config.local.json"))
    acct = next(a for a in cfg["accounts"] if a["id"] == account_id)
    return acct["garmin"]


class PersonalApi:
    """Minimal Personal API client: API key -> 24h Bearer token -> GETs."""

    def __init__(self, api_key):
        self._api_key = api_key
        self._token = None

    def _fetch_token(self):
        resp = requests.post(
            f"{PERSONAL_BASE}/personalapitoken-service/personal-api/personal-api-key/token",
            headers={"Authorization": f"ApiKey {self._api_key}"},
            timeout=30,
        )
        resp.raise_for_status()
        self._token = resp.text.strip()
        return self._token

    def get_json(self, path, params=None):
        token = self._token or self._fetch_token()
        for attempt in range(2):
            resp = requests.get(
                f"{PERSONAL_BASE}/{path}",
                headers={"Authorization": f"Bearer {token}", "Accept": "*/*"},
                params=params,
                timeout=30,
            )
            if resp.status_code == 401 and attempt == 0:
                token = self._fetch_token()
                continue
            resp.raise_for_status()
            return resp.json()

    def list_activities(self, start=0, limit=50):
        # The personal gateway rejects large pages (limit=50 -> HTTP 500,
        # limit<=30 is fine), so page internally in chunks of 20.
        out = []
        s = start
        while len(out) < limit:
            want = min(20, limit - len(out))
            page = self.get_json(
                "activitylist-service/activities/search/activities",
                params={"start": s, "limit": want},
            )
            if not page:
                break
            out.extend(page)
            if len(page) < want:
                break
            s += len(page)
        return out


def build_personal(account_id=ACCOUNT_ID):
    g = _account_config(account_id)
    api_key = g.get("api_key")
    if not api_key:
        raise RuntimeError(f"{account_id} has no Personal API key configured")
    return PersonalApi(api_key)


def build_client(account_id=ACCOUNT_ID):
    g = _account_config(account_id)
    backend = GarthBackend(
        g["email"],
        g["password"],
        g.get("domain", "COM"),
        token_salt=g.get("token_salt"),
        token_path=f"{SYNC_PROJECT}/db/accounts/{account_id}/garth_token.enc",
    )
    return GarminClient(backend=backend, newest_num=0)


def _connectapi(client, path):
    """Arbitrary Connect API GET via the garth backend (read-only use)."""
    return client.backend.connectapi(path)


def summarize_activity(a):
    avg_speed = a.get("averageSpeed")  # m/s
    pace = round(1000 / avg_speed / 60, 2) if avg_speed else None  # min/km
    return {
        "activity_id": a.get("activityId"),
        "name": a.get("activityName"),
        "type": (a.get("activityType") or {}).get("typeKey"),
        "start_local": a.get("startTimeLocal"),
        "distance_km": round(a["distance"] / 1000, 2) if a.get("distance") else None,
        "duration_s": a.get("duration"),
        "moving_duration_s": a.get("movingDuration"),
        "elevation_gain_m": round(a["elevationGain"]) if a.get("elevationGain") else 0,
        "avg_hr": round(a["averageHR"]) if a.get("averageHR") else None,
        "max_hr": round(a["maxHR"]) if a.get("maxHR") else None,
        "avg_pace_min_km": pace,
        "avg_speed_kmh": round(a["averageSpeed"] * 3.6, 1) if a.get("averageSpeed") else None,
        "max_speed_kmh": round(a["maxSpeed"] * 3.6, 1) if a.get("maxSpeed") else None,
        "vo2max": a.get("vO2MaxValue"),
        "aerobic_training_effect": a.get("aerobicTrainingEffect"),
        "calories": round(a["calories"]) if a.get("calories") else None,
        "hr_zones_s": {
            f"z{i}": a.get(f"hrTimeInZone_{i}") for i in range(1, 6)
        },
        "location": a.get("locationName"),
    }


def get_laps(client, activity_id):
    data = _connectapi(client, f"activity-service/activity/{activity_id}/splits")
    laps = []
    for lap in data.get("lapDTOs", []):
        dist = lap.get("distance") or 0
        dur = lap.get("duration")  # seconds, scalar
        pace = round(dur / dist * 1000 / 60, 2) if dist and dur else None  # min/km
        laps.append({
            "distance_m": round(dist),
            "duration_s": round(dur) if dur else None,
            "pace_min_km": pace,
            "avg_hr": round(lap["averageHR"]) if lap.get("averageHR") else None,
            "elevation_gain_m": round(lap.get("elevationGain") or 0),
            "cadence_avg_spm": (round(lap["averageRunCadence"])
                                if lap.get("averageRunCadence") else None),
            "stride_length_m": (round(lap["strideLength"] / 100, 2)
                                if lap.get("strideLength") else None),
            "vertical_oscillation_cm": (round(lap["verticalOscillation"], 1)
                                        if lap.get("verticalOscillation") else None),
            "vertical_ratio_pct": (round(lap["verticalRatio"], 1)
                                   if lap.get("verticalRatio") else None),
            "ground_contact_time_ms": (round(lap["groundContactTime"])
                                       if lap.get("groundContactTime") else None),
        })
    return laps


def _pick(obj, *keys):
    """Safely drill into dicts; return scalar as-is if a non-dict is hit."""
    cur = obj
    for k in keys:
        if isinstance(cur, dict):
            cur = cur.get(k)
        else:
            return cur
    return cur


def _hhmm(epoch_ms):
    """Garmin '*TimestampLocal' values are wall-clock-shifted epochs;
    reading them as UTC yields the local HH:MM."""
    if not epoch_ms:
        return None
    dt = datetime.datetime.fromtimestamp(
        epoch_ms / 1000, tz=datetime.timezone.utc)
    return dt.strftime("%H:%M")


def get_sleep_day(personal, date_str):
    """Sleep via the Personal API: sleep-service for the night itself,
    dailyHeartRate for resting HR. Overnight HRV/status and the Body
    Battery change are filled in by the caller (hrv-service and
    usersummary/daily respectively)."""
    try:
        dto = personal.get_json(
            "sleep-service/sleep/dailySleep", params={"date": date_str}
        )
    except Exception:
        return None
    if not isinstance(dto, dict) or dto.get("sleepTimeSeconds") is None:
        return None
    entry = {
        "date": date_str,
        "sleep_seconds": dto.get("sleepTimeSeconds"),
        "sleep_score": _pick(dto, "sleepScores", "overall", "value"),
        "deep_sleep_seconds": dto.get("deepSleepSeconds"),
        "rem_sleep_seconds": dto.get("remSleepSeconds"),
        "awake_seconds": dto.get("awakeSleepSeconds"),
        "resting_hr": None,
        "avg_overnight_hrv_ms": None,
        "hrv_status": None,
        "body_battery_change": None,
        "avg_sleep_stress": dto.get("avgSleepStress"),
        "avg_respiration": dto.get("averageRespirationValue"),
        "avg_spo2": dto.get("averageSpO2Value"),
        "user_profile_pk": dto.get("userProfilePK"),
        "sleep_start_local": _hhmm(dto.get("sleepStartTimestampLocal")),
        "sleep_end_local": _hhmm(dto.get("sleepEndTimestampLocal")),
        "levels": None,
        "hr_readings": None,
    }
    try:
        hr = personal.get_json(
            "wellness-service/wellness/dailyHeartRate", params={"date": date_str}
        )
        entry["resting_hr"] = hr.get("restingHeartRate")
    except Exception:
        pass
    return entry


_LEVEL_STAGES = {0.0: "deep", 1.0: "light", 2.0: "rem", 3.0: "awake"}


def get_sleep_extras(client, user_profile_pk, date_str):
    """One night's stage timeline + heart-rate series, via the Connect
    (garth) dailySleepData endpoint — the Personal API's dailySleep
    returns totals only. Verified 2026-10-22: per-stage second sums
    match the Personal totals exactly (activityLevel 0=deep, 1=light,
    2=REM, 3=awake); sleepHeartRate is a 2-min series across the night."""
    if not user_profile_pk:
        return None, None
    try:
        data = _connectapi(
            client,
            f"wellness-service/wellness/dailySleepData/{user_profile_pk}"
            f"?date={date_str}&nonSleepBufferMinutes=60")
    except Exception:
        return None, None
    levels = []
    for it in (data or {}).get("sleepLevels") or []:
        stage = _LEVEL_STAGES.get(it.get("activityLevel"))
        if stage is None:
            continue
        try:
            s = datetime.datetime.fromisoformat(it["startGMT"])
            e = datetime.datetime.fromisoformat(it["endGMT"])
        except Exception:
            continue
        levels.append({"stage": stage,
                       "seconds": int((e - s).total_seconds())})
    hr = []
    for it in (data or {}).get("sleepHeartRate") or []:
        ts, v = it.get("startGMT"), it.get("value")
        if ts is None or v is None:
            continue
        t = datetime.datetime.fromtimestamp(ts / 1000, tz=TZ).strftime("%H:%M")
        hr.append({"t": t, "v": v})
    return levels or None, hr or None


def get_hrv_day(personal, date_str):
    try:
        data = personal.get_json(f"hrv-service/hrv/{date_str}")
    except Exception:
        return None
    summary = data.get("hrvSummary") or {}
    return {
        "date": date_str,
        "avg_hrv_ms": summary.get("lastNightAvg"),
        "weekly_avg": summary.get("weeklyAvg"),
        "max_hrv_ms": summary.get("lastNight5MinHigh"),
        "status": summary.get("status"),
        # Overnight 5-min readings [{t: local HH:MM, v: ms}] + Garmin's own
        # baseline band from hrvSummary.baseline (verified present 2026-10-22)
        "readings": [{"t": (r.get("readingTimeLocal") or "")[11:16],
                      "v": r.get("hrvValue")}
                     for r in (data.get("hrvReadings") or [])],
        "baseline": {"low_upper": _pick(summary, "baseline", "lowUpper"),
                     "balanced_low": _pick(summary, "baseline", "balancedLow"),
                     "balanced_high": _pick(summary, "baseline", "balancedUpper")},
    }


def get_stress_day(personal, date_str):
    """Daytime stress summary (0-100 overall level + durations in seconds)."""
    try:
        data = personal.get_json(
            f"usersummary-service/stats/stress/daily/{date_str}/{date_str}"
        )
    except Exception:
        return None
    entry = (data or [None])[0] or {}
    values = entry.get("values") or {}
    return {
        "date": date_str,
        "overall_stress_level": values.get("overallStressLevel"),
        "rest_stress_seconds": values.get("restStressDuration"),
        "low_stress_seconds": values.get("lowStressDuration"),
        "medium_stress_seconds": values.get("mediumStressDuration"),
        "high_stress_seconds": values.get("highStressDuration"),
    }


def get_daily_summary(personal, date_str):
    """usersummary/daily: one call carrying Body Battery (at-wake level and
    overnight change), steps, intensity minutes, calories, 7d-avg resting
    HR, average SpO2 and waking respiration for the day."""
    try:
        d = personal.get_json(
            "usersummary-service/usersummary/daily",
            params={"calendarDate": date_str},
        )
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    return {
        "date": date_str,
        "steps": d.get("totalSteps"),
        "distance_m": d.get("totalDistanceMeters"),
        "floors_ascended": (round(d["floorsAscended"], 1)
                            if d.get("floorsAscended") is not None else None),
        "active_kcal": d.get("activeKilocalories"),
        "bmr_kcal": d.get("bmrKilocalories"),
        "total_kcal": d.get("totalKilocalories"),
        "moderate_intensity_min": d.get("moderateIntensityMinutes"),
        "vigorous_intensity_min": d.get("vigorousIntensityMinutes"),
        "resting_hr": d.get("restingHeartRate"),
        "resting_hr_7d_avg": d.get("lastSevenDaysAvgRestingHeartRate"),
        "avg_stress_level": d.get("averageStressLevel"),
        "stress_qualifier": d.get("stressQualifier"),
        "body_battery_at_wake": d.get("bodyBatteryAtWakeTime"),
        "body_battery_change": d.get("bodyBatteryDuringSleep"),
        "body_battery_high": d.get("bodyBatteryHighestValue"),
        "body_battery_low": d.get("bodyBatteryLowestValue"),
        "avg_spo2": d.get("averageSpo2"),
        "avg_waking_respiration": d.get("avgWakingRespirationValue"),
    }


def _speed_to_pace(speed):
    """m/s -> min/km (None-safe)."""
    return round(1000 / speed / 60, 2) if speed else None


def get_activity_stream(personal, activity_id, points=None, elapsed_s=None):
    """Time-series stream via the Personal details endpoint (chart data).

    Returns downsampled hr / pace / elevation series for rendering a
    mini timeline chart. Pace is derived from speed and lightly smoothed
    (5-point moving average, None-aware). Failure-tolerant: None.

    Sampling is duration-adaptive (2026-10-27 fix for the old fixed
    maxChartSize=160, which made longer activities sparser and could not
    resolve 20 s strides): target one point per second, i.e. the watch's
    native 1 Hz rate. The request is ceil(elapsed)+1, NOT exactly the
    duration: the server returns full native data only when requested >=
    native count, and requesting exactly the duration decimates
    (verified 2026-10-27: 2852 -> 1437 rows, 2853 -> 2853). The +1 covers
    the inclusive endpoints (records = span+1 for a clean 1 Hz run) and
    elapsed (not timer duration) covers pauses/gaps. Callers that pass
    points explicitly keep the old behavior.
    """
    if points is None:
        if elapsed_s:
            import math
            points = math.ceil(elapsed_s) + 1
        else:
            points = 160
    try:
        det = personal.get_json(
            f"activity-service/activity/{activity_id}/details",
            params={"maxChartSize": points})
    except Exception:
        return None
    if not isinstance(det, dict):
        return None
    idx = {dsc.get("key"): dsc.get("metricsIndex")
           for dsc in det.get("metricDescriptors") or []}
    rows = det.get("activityDetailMetrics") or []
    if not rows:
        return None

    def series(key):
        i = idx.get(key)
        if i is None:
            return []
        out = []
        for r in rows:
            m = r.get("metrics") or []
            out.append(m[i] if len(m) > i else None)
        return out

    hr_raw = series("directHeartRate")
    spd = series("directSpeed")
    elev = series("directElevation")
    pace = [round(1000 / v / 60, 2) if v and v > 0.5 else None for v in spd]
    kmh = [round(v * 3.6, 1) if v is not None else None for v in spd]
    smooth = []
    for j in range(len(pace)):
        win = [p for p in pace[max(0, j - 2):j + 3] if p]
        smooth.append(round(sum(win) / len(win), 2) if win else None)
    smooth_kmh = []
    for j in range(len(kmh)):
        win = [x for x in kmh[max(0, j - 2):j + 3] if x is not None]
        smooth_kmh.append(round(sum(win) / len(win), 1) if len(win) >= 2 else kmh[j])
    return {
        "hr": [round(v) if v else None for v in hr_raw],
        "pace_min_km": smooth,
        "speed_kmh": smooth_kmh,
        "elevation_m": [round(v) if v is not None else None for v in elev],
    }


def get_activity_detail(personal, activity_id):
    """activity-service detail + attached structured workout (Personal API).

    Carries what the list summary lacks: training load, anaerobic effect,
    workout compliance/RPE/feel as scored by the watch, grade-adjusted
    pace, recovery HR, and interval-structure split summaries."""
    try:
        det = personal.get_json(f"activity-service/activity/{activity_id}")
    except Exception:
        return None
    if not isinstance(det, dict):
        return None
    s = det.get("summaryDTO") or {}
    splits = []
    for sp in det.get("splitSummaries") or []:
        dist = sp.get("distance") or 0
        dur = sp.get("duration")
        splits.append({
            "type": sp.get("splitType"),
            "distance_m": round(dist) if dist else None,
            "duration_s": round(dur) if dur else None,
            "pace_min_km": (round(dur / dist * 1000 / 60, 2)
                            if dist and dur else None),
            "avg_hr": sp.get("averageHR"),
            "max_hr": sp.get("maxHR"),
        })
    detail = {
        "training_load": (round(s["activityTrainingLoad"], 1)
                          if s.get("activityTrainingLoad") is not None else None),
        "aerobic_training_effect": s.get("trainingEffect"),
        "anaerobic_training_effect": s.get("anaerobicTrainingEffect"),
        "training_effect_label": s.get("trainingEffectLabel"),
        "compliance_score": s.get("directWorkoutComplianceScore"),
        "rpe": s.get("directWorkoutRpe"),
        "feel": s.get("directWorkoutFeel"),
        "gap_pace_min_km": _speed_to_pace(s.get("avgGradeAdjustedSpeed")),
        "recovery_hr": s.get("recoveryHeartRate"),
        "body_battery_impact": s.get("differenceBodyBattery"),
        "avg_temperature_c": (round(s["averageTemperature"], 1)
                              if s.get("averageTemperature") is not None else None),
        "avg_power_w": s.get("averagePower"),
        "normalized_power_w": s.get("normalizedPower"),
        "split_summaries": splits,
    }
    if s.get("averageRunCadence"):
        detail["running_dynamics"] = {
            "cadence_avg_spm": round(s["averageRunCadence"]),
            "cadence_max_spm": (round(s["maxRunCadence"])
                                if s.get("maxRunCadence") else None),
            "stride_length_m": (round(s["strideLength"] / 100, 2)
                                if s.get("strideLength") else None),
            "vertical_oscillation_cm": (round(s["verticalOscillation"], 1)
                                        if s.get("verticalOscillation") else None),
            "vertical_ratio_pct": (round(s["verticalRatio"], 1)
                                   if s.get("verticalRatio") else None),
            "ground_contact_time_ms": (round(s["groundContactTime"])
                                       if s.get("groundContactTime") else None),
            "steps": s.get("steps"),
        }
    stream = get_activity_stream(personal, activity_id,
                                 elapsed_s=(s.get("elapsedDuration")
                                            or s.get("duration")))
    if stream:
        detail["stream"] = stream
    try:
        workouts = personal.get_json(
            f"activity-service/activity/{activity_id}/workouts")
    except Exception:
        workouts = None
    if isinstance(workouts, list) and workouts:
        w = workouts[0] or {}
        steps = []
        for st in w.get("steps") or []:
            lo = _speed_to_pace(st.get("targetValueHigh"))
            hi = _speed_to_pace(st.get("targetValueLow"))
            steps.append({
                "intensity": st.get("intensity"),
                "duration_type": st.get("durationType"),
                "duration_value": st.get("durationValue"),
                "target_pace_min_km": ([lo, hi] if lo or hi else None),
                "notes": st.get("notes"),
            })
        detail["workout"] = {"name": w.get("workoutName"), "steps": steps}
    return detail


def get_weight_window(personal, start_date, end_date):
    """weight/range: latest daily weights in the window (API unit: grams)."""
    try:
        data = personal.get_json(
            f"weight-service/weight/range/{start_date}/{end_date}")
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    days = []
    for item in data.get("dailyWeightSummaries") or []:
        latest = item.get("latestWeight") or {}
        grams = latest.get("weight")
        if grams:
            days.append({
                "date": item.get("summaryDate") or latest.get("calendarDate"),
                "weight_kg": round(grams / 1000, 2),
            })
    days.sort(key=lambda x: x["date"] or "")
    avg = (data.get("totalAverage") or {}).get("weight")
    return {
        "latest_date": days[-1]["date"] if days else None,
        "latest_weight_kg": days[-1]["weight_kg"] if days else None,
        "avg_weight_kg": round(avg / 1000, 2) if avg else None,
        "days": days,
    }


def get_profile(personal):
    """Static-ish athlete profile for workout prescription: running HR
    zones + lactate threshold (biometric-service) and fitness age."""
    out = {"ok": True}
    try:
        zones = personal.get_json("biometric-service/heartRateZones/v2")
        if isinstance(zones, list) and zones:
            z = next((x for x in zones if x.get("sport") == "RUNNING"),
                     zones[0])
            out["hr_zones_running"] = {
                "method": z.get("trainingMethod"),
                "resting_hr_used": z.get("restingHeartRateUsed"),
                "max_hr": z.get("maxHeartRateUsed"),
                "lactate_threshold_hr": z.get("lactateThresholdHeartRateUsed"),
                "zone_floors": {f"z{i}": z.get(f"zone{i}Floor")
                                for i in range(1, 6)},
            }
    except Exception:
        out["hr_zones_running"] = None
    try:
        today = datetime.datetime.now(TZ).date().isoformat()
        fa = personal.get_json(f"fitnessage-service/fitnessage/v2/{today}")
        if isinstance(fa, dict):
            comp = fa.get("components") or {}
            out["fitness_age"] = {
                "chronological_age": fa.get("chronologicalAge"),
                "fitness_age": (round(fa["fitnessAge"], 1)
                                if fa.get("fitnessAge") else None),
                "rhr_component": (comp.get("rhr") or {}).get("value"),
                "bmi": (comp.get("bmi") or {}).get("value"),
                "vigorous_minutes_avg": (comp.get("vigorousMinutesAvg")
                                         or {}).get("value"),
            }
    except Exception:
        out["fitness_age"] = None
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--account", default=ACCOUNT_ID)
    parser.add_argument("--health", action="store_true", help="include sleep/HRV")
    parser.add_argument("--laps", type=int, default=0,
                        help="include lap splits for the latest N activities")
    parser.add_argument("--detail", type=int, default=0,
                        help="include Personal-API activity detail (training "
                             "load, compliance, split summaries, workout "
                             "steps) for the latest N activities")
    parser.add_argument("--profile", action="store_true",
                        help="print HR zones + fitness age and exit")
    parser.add_argument("--limit", type=int, default=50,
                        help="max activities to scan")
    args = parser.parse_args()

    personal = build_personal(args.account)
    try:
        personal.list_activities(start=0, limit=1)
    except Exception as e:
        print(json.dumps({"ok": False, "error": f"auth failed: {type(e).__name__}"}))
        return 2

    if args.profile:
        print(json.dumps(get_profile(personal), ensure_ascii=False))
        return 0

    # Garth is needed for lap splits and for the sleep stage timeline
    # (dailySleepData) — the two things the Personal API does not expose.
    # Build it lazily; if its login fails, laps/levels stay None and
    # everything else is unaffected.
    garth = None
    if args.laps or args.health:
        try:
            garth = build_client(args.account)
            garth.ensure_login()
        except Exception:
            garth = None

    cutoff = (datetime.datetime.now(TZ) - datetime.timedelta(days=args.days)).date()
    activities = []
    for a in personal.list_activities(start=0, limit=args.limit):
        start_local = (a.get("startTimeLocal") or "")[:10]
        try:
            adate = datetime.date.fromisoformat(start_local)
        except ValueError:
            continue
        if adate < cutoff:
            break
        activities.append(a)

    result = {
        "ok": True,
        "account": args.account,
        "since": cutoff.isoformat(),
        "activity_count": len(activities),
        "activities": [summarize_activity(a) for a in activities],
    }

    if args.laps:
        for a in result["activities"][: args.laps]:
            try:
                a["laps"] = get_laps(garth, a["activity_id"]) if garth else None
            except Exception:
                a["laps"] = None

    if args.detail:
        for a in result["activities"][: args.detail]:
            a["detail"] = get_activity_detail(personal, a["activity_id"])

    if args.health:
        health = []
        for i in range(args.days):
            d = (datetime.datetime.now(TZ) - datetime.timedelta(days=i)).date().isoformat()
            hrv = get_hrv_day(personal, d)
            sleep = get_sleep_day(personal, d)
            daily = get_daily_summary(personal, d)
            if sleep is not None and hrv is not None:
                sleep["avg_overnight_hrv_ms"] = hrv["avg_hrv_ms"]
                sleep["hrv_status"] = hrv["status"]
            if sleep is not None and daily is not None:
                sleep["body_battery_change"] = daily["body_battery_change"]
            if i == 0 and sleep is not None and garth is not None:
                # Stage timeline + overnight HR only for the most recent
                # night (brief chart)
                sleep["levels"], sleep["hr_readings"] = get_sleep_extras(
                    garth, sleep.get("user_profile_pk"), d)
            health.append({
                "sleep": sleep,
                "hrv": hrv,
                "stress": get_stress_day(personal, d),
                "daily": daily,
            })
        result["health"] = health
        result["weight"] = get_weight_window(
            personal, cutoff.isoformat(),
            datetime.datetime.now(TZ).date().isoformat())

    totals = {}
    for a in result["activities"]:
        t = (a.get("type") or "unknown")
        b = totals.setdefault(t, {"count": 0, "distance_km": 0.0, "elevation_gain_m": 0})
        b["count"] += 1
        b["distance_km"] = round(b["distance_km"] + (a["distance_km"] or 0), 1)
        b["elevation_gain_m"] += a["elevation_gain_m"] or 0
    result["totals_by_type"] = totals

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
