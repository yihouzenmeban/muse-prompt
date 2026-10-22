#!/usr/bin/env python3
"""Push a planned workout to the user's intervals.icu calendar via API.

Uses intervals.icu's native workout text format in the event `description`,
posted to POST /api/v1/athlete/0/events/bulk?upsert=true.

Auth: HTTP Basic, username "API_KEY", password = your intervals.icu
API key, read from a 0600 file (default ~/workspace/intervals-icu/.api_key,
override with the INTERVALS_KEY_FILE env var; create and chmod it
yourself, and never print or log the key).

Transport: curl via subprocess, not Python urllib. Reason (verified
2026-10-15 by interleaved A/B tests): through this VM's egress proxy,
Python's http.client intermittently gets zero-byte connection closes and
spurious 302s from the intervals.icu/Cloudflare edge, while curl succeeds
10/10. The Authorization header is passed via `curl --config -` on stdin,
never on the command line, so it doesn't show up in process listings.

Usage:
  push_workout.py --verify-read
      Read-only check: GET /athlete/0 (proves the key works, writes nothing).

  push_workout.py --date 2026-10-16 --name "轻松跑 8km" \
      --description-file workout.txt [--time 06:30] [--distance-m 8000] \
      [--duration-s 2880] [--external-id muse-20261016] [--dry-run]
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import time

KEY_FILE = os.environ.get(
    "INTERVALS_KEY_FILE",
    os.path.expanduser("~/workspace/intervals-icu/.api_key"))
API_BASE = "https://intervals.icu/api/v1"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
CODE_MARKER = "__CURL_CODE__:"


def load_key():
    try:
        st = os.stat(KEY_FILE)
    except FileNotFoundError:
        sys.exit("error: key file not found: " + KEY_FILE)
    if st.st_mode & 0o077:
        print(
            "warning: %s permissions are %s, expected 0600"
            % (KEY_FILE, oct(st.st_mode & 0o777)),
            file=sys.stderr,
        )
    with open(KEY_FILE) as f:
        key = f.read().strip()
    if not key:
        sys.exit(
            "error: API key file is empty — paste your intervals.icu API key "
            "(intervals.icu settings page, bottom) into " + KEY_FILE
        )
    return key


def api_call(path, key, payload=None, method="GET"):
    """Call the intervals.icu API via curl. Returns parsed JSON.

    Retries transient failures (curl exit != 0, HTTP 5xx). Reads are
    idempotent; writes use upsert on a stable external_id, so a retry
    can't duplicate an event. Redirects are never followed (curl default);
    a 3xx/4xx fails loudly.
    """
    creds = base64.b64encode(("API_KEY:" + key).encode()).decode()
    config = "\n".join([
        'header = "Authorization: Basic %s"' % creds,
        'header = "Accept: application/json"',
        'header = "User-Agent: %s"' % UA,
        "connect-timeout = 15",
        "max-time = 60",
        "silent = true",
        "",
    ])
    cmd = ["curl", "--config", "-", "-X", method,
           "-w", "\n" + CODE_MARKER + "%{http_code}",
           API_BASE + path]
    body_file = None
    if payload is not None:
        config += 'header = "Content-Type: application/json"\n'
        body_file = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False)
        json.dump(payload, body_file)
        body_file.close()
        os.chmod(body_file.name, 0o600)
        cmd += ["--data-binary", "@" + body_file.name]
    try:
        last = None
        for attempt in range(3):
            try:
                p = subprocess.run(cmd, input=config, capture_output=True,
                                   text=True, timeout=90)
            except (subprocess.TimeoutExpired, OSError) as e:
                last = "%s: %s" % (type(e).__name__, e)
                time.sleep(2 ** attempt)
                continue
            if p.returncode != 0:
                last = "curl exit %d: %s" % (
                    p.returncode, (p.stderr or "").strip()[:200])
                time.sleep(2 ** attempt)
                continue
            out = p.stdout
            if CODE_MARKER not in out:
                last = "curl returned no status code"
                time.sleep(2 ** attempt)
                continue
            body_text, _, code_s = out.rpartition(CODE_MARKER)
            try:
                code = int(code_s.strip())
            except ValueError:
                last = "unparseable status %r" % code_s.strip()
                time.sleep(2 ** attempt)
                continue
            if 200 <= code < 300:
                try:
                    return json.loads(body_text)
                except ValueError as e:
                    last = "unparseable body: %s" % e
                    time.sleep(2 ** attempt)
                    continue
            if 500 <= code < 600 and attempt < 2:
                last = "HTTP %d: %s" % (code, body_text[:200])
                time.sleep(2 ** attempt)
                continue
            sys.exit("error: HTTP %d from intervals.icu: %s"
                     % (code, body_text[:500]))
        sys.exit("error: intervals.icu unreachable after 3 attempts: %s"
                 % last)
    finally:
        if body_file:
            try:
                os.unlink(body_file.name)
            except OSError:
                pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify-read", action="store_true",
                    help="GET /athlete/0 only (no write)")
    ap.add_argument("--date", help="workout date YYYY-MM-DD")
    ap.add_argument("--time", default="07:30",
                    help="local start time HH:MM (default 07:30 — set it "
                         "to your habitual run start)")
    ap.add_argument("--name", help="workout name")
    ap.add_argument("--type", default="Run", help="activity type, e.g. Run")
    ap.add_argument("--description", help="native intervals.icu workout text")
    ap.add_argument("--description-file", help="file containing the workout text")
    ap.add_argument("--distance-m", type=int, help="planned distance in meters")
    ap.add_argument("--duration-s", type=int, help="planned duration in seconds")
    ap.add_argument("--external-id",
                    help="stable id for upsert (default muse-<date>)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print payload, do not send")
    a = ap.parse_args()
    key = load_key()

    if a.verify_read:
        me = api_call("/athlete/0", key)
        print(json.dumps({"id": me.get("id"), "name": me.get("name")},
                         ensure_ascii=False))
        return

    if not (a.date and a.name):
        sys.exit("error: --date and --name are required (or use --verify-read)")
    desc = a.description or ""
    if a.description_file:
        with open(a.description_file) as f:
            desc = f.read()
    event = {
        "category": "WORKOUT",
        "start_date_local": "%sT%s:00" % (a.date, a.time),
        "name": a.name,
        "description": desc,
        "type": a.type,
        "external_id": a.external_id or ("muse-" + a.date),
    }
    if a.distance_m:
        event["distance"] = a.distance_m
    if a.duration_s:
        event["moving_time"] = a.duration_s

    if a.dry_run:
        print(json.dumps(event, ensure_ascii=False, indent=2))
        print("(dry run — nothing sent)")
        return

    res = api_call("/athlete/0/events/bulk?upsert=true", key, [event],
                   method="POST")
    items = res if isinstance(res, list) else [res]
    for e in items:
        print(json.dumps({
            "id": e.get("id"),
            "name": e.get("name"),
            "start_date_local": e.get("start_date_local"),
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
