#!/usr/bin/env python3
"""Zepp Life -> Garmin Connect 体重同步。

Zepp 侧：
  apptoken 请求头认证 -> band_data 发现数字 uid ->
  GET https://api-mifit.zepp.com/users/{uid}/members/-1/weightRecords
  apptoken 失效时用 .zepp_credentials 自动重新登录换取（zepp_login.py，
  逆向自 user.huami.com/privacy 登录页 JS）。

Garmin 侧写入格式参考 cyberjunky/python-garminconnect 的 add_weigh_in：
  POST https://connect.garmin.com/modern/proxy/weight-service/user-weight
认证复用 garmin-sync-coros 目标账号（GARMIN_ACCOUNT_ID，默认 account_a）的加密 garth token，
与 garmin-coros 定时任务同一套 token 刷新机制。

去重规则（严格）：Garmin 当天已有任何体重记录则跳过不写。

用法：
  sync_weight.py            # 正常同步
  sync_weight.py --dry-run  # 只读：拉 Zepp 数据、查 Garmin，不写入

退出码：0 = 成功或无新数据；1 = 失败（定时任务据此决定是否通知）。
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
GARMIN_PROJECT = os.path.expanduser(os.environ.get("GARMIN_PROJECT", "~/workspace/garmin-sync-coros"))
ACCOUNT_ID = os.environ.get("GARMIN_ACCOUNT_ID", "account_a")

# 复用 garmin-sync-coros 的认证模块（token 加解密、garth 配置）
sys.path.insert(0, os.path.join(GARMIN_PROJECT, "scripts"))

LOCAL_TZ = ZoneInfo(os.environ.get("TZ_NAME", "Asia/Shanghai"))

ZEPP_API_BASE = "https://api-mifit.huami.com"
ZEPP_WEIGHT_API = "https://api-mifit.zepp.com"

APPT_TOKEN_FILE = os.path.join(PROJECT_ROOT, ".apptoken")
STATE_FILE = os.path.join(PROJECT_ROOT, "state.json")
# 全量同步：不限制回填天数。每天只取 Zepp 当天最新的一条记录；
# Garmin 当天已有任何体重记录则跳过不写。


def log(msg):
    print(f"[{datetime.now(LOCAL_TZ).strftime('%H:%M:%S')}] {msg}", flush=True)


def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


# ---------------- Zepp Life ----------------

def zepp_session(apptoken):
    import requests

    s = requests.Session()
    s.headers.update(
        {
            "apptoken": apptoken,
            "appPlatform": "web",
            "appname": "com.xiaomi.hm.health",
            "Content-Type": "application/json",
        }
    )
    s.timeout = 30
    return s


def zepp_validate(s):
    try:
        r = s.get(f"{ZEPP_API_BASE}/v1/sport/run/history.json", params={"limit": 1})
        return r.status_code == 200 and "invalid token" not in r.text
    except Exception:
        return False


def zepp_get_session():
    """返回可用的 (session, uid)。

    优先用已保存的 apptoken；无效或缺失时用 .zepp_credentials
    自动重新登录换取并保存。uid 缓存于 state.json，避免每次
    因 band_data 为空而重复登录。
    """
    sys.path.insert(0, PROJECT_ROOT)
    import zepp_login

    state = load_state()
    apptoken = ""
    if os.path.exists(APPT_TOKEN_FILE):
        apptoken = open(APPT_TOKEN_FILE, encoding="utf-8").read().strip()
    uid = ""
    if apptoken:
        s = zepp_session(apptoken)
        if zepp_validate(s):
            uid = state.get("zepp_uid") or zepp_discover_uid(s)
            if uid:
                if uid != state.get("zepp_uid"):
                    state["zepp_uid"] = uid
                    save_state(state)
                log("Zepp apptoken 有效")
                return s, uid
            log("Zepp apptoken 有效但无法确定 uid，重新登录")
        else:
            log("Zepp apptoken 无效或已过期，重新登录换取")
    else:
        log("无已保存的 apptoken，登录换取")

    apptoken, uid = zepp_login.refresh_and_save(APPT_TOKEN_FILE)
    state["zepp_uid"] = uid
    save_state(state)
    log(f"Zepp 登录成功，已保存新的 apptoken（uid {uid}）")
    return zepp_session(apptoken), uid


def zepp_discover_uid(s):
    """参考 zepp-life-mcp 的 _discover_user_id：从 band_data summary 里找数字 uid。"""
    today = datetime.now(LOCAL_TZ).date()
    start = (today - timedelta(days=30)).isoformat()
    r = s.get(
        f"{ZEPP_API_BASE}/v1/data/band_data.json",
        params={
            "query_type": "summary",
            "device_type": "android_phone",
            "from_date": start,
            "to_date": today.isoformat(),
        },
    )
    if r.status_code != 200:
        return None
    data = r.json().get("data", [])
    if not isinstance(data, list):
        return None
    for item in data:
        if not isinstance(item, dict):
            continue
        uid = str(item.get("uid", ""))
        if uid.isdigit():
            return uid
    return None


def zepp_weight_records(s, uid, limit=200):
    r = s.get(
        f"{ZEPP_WEIGHT_API}/users/{uid}/members/-1/weightRecords",
        params={"limit": limit},
    )
    r.raise_for_status()
    items = r.json().get("items", [])
    records = []
    for item in items:
        ts = item.get("generatedTime")
        summary = item.get("summary") or {}
        weight = summary.get("weight")
        if not ts or not weight:
            continue
        try:
            weight = float(weight)
        except (TypeError, ValueError):
            continue
        if weight <= 0:
            continue
        records.append(
            {
                "id": str(item.get("id", ts)),
                "ts": int(ts),  # epoch 秒（UTC）
                "weight": weight,
            }
        )
    records.sort(key=lambda x: x["ts"])
    return records


# ---------------- Garmin ----------------

def garmin_login():
    """复用 garmin-sync-coros 目标账号的 token；失效则做一次无头密码登录。"""
    from garmin.garth_auth import (
        apply_browser_user_agent,
        configure_domain,
        load_garth,
        remove_garth_user_agent,
    )
    from garmin.garth_token_store import (
        has_encrypted_token,
        read_encrypted_token,
        write_encrypted_token,
    )

    garth = load_garth()

    cfg = json.load(
        open(os.path.join(GARMIN_PROJECT, "config.local.json"), encoding="utf-8")
    )
    account = next(a for a in cfg["accounts"] if a["id"] == ACCOUNT_ID)
    g = account["garmin"]
    token_path = os.path.join(
        GARMIN_PROJECT, "db", "accounts", ACCOUNT_ID, "garth_token.enc"
    )
    token_salt = g.get("token_salt", "")

    configure_domain(garth, g.get("domain", ""))

    restored = False
    if token_salt and has_encrypted_token(token_path):
        try:
            garth.client.loads(read_encrypted_token(token_path, token_salt))
            _ = garth.client.username  # 触发校验 / OAuth2 自动刷新
            remove_garth_user_agent(garth)
            restored = True
            # 回写刷新后的 token
            write_encrypted_token(token_path, token_salt, garth.client.dumps())
        except Exception as e:
            log(f"token 恢复失败（{type(e).__name__}），尝试密码登录")

    if not restored:
        email, password = g.get("email", ""), g.get("password", "")
        if not email or not password:
            die("Garmin token 失效且配置中无账号密码，无法登录")
        apply_browser_user_agent(garth)
        try:
            garth.login(email, password)
        except Exception as e:
            remove_garth_user_agent(garth)
            die(f"Garmin 密码登录失败（可能需要验证码/人工介入）：{type(e).__name__}: {e}")
        remove_garth_user_agent(garth)
        if token_salt:
            write_encrypted_token(token_path, token_salt, garth.client.dumps())
        log("Garmin 密码登录成功，token 已回写")

    # 确认登录的是目标账号（防写错账号）
    profile = garth.client.connectapi("/userprofile-service/socialProfile")
    display = (profile or {}).get("displayName", "")
    log(f"Garmin 账号：{display or '(未知)'}")
    return garth


def _fmt_ts(dt):
    # 与 python-garminconnect._fmt_ts 一致：本地/UTC 时间，去掉时区，毫秒精度
    return dt.replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]


def garmin_has_weight(garth, local_date):
    """该日期 Garmin 是否已有体重记录。有则 True（调用方跳过不写）。

    读取失败时直接报错退出（由定时任务通知人工处理），
    绝不因"读不到"而冒险写入造成重复。
    """
    data = garth.client.connectapi(
        f"/weight-service/weight/dayview/{local_date}",
        params={"includeAll": "true"},
    )
    entries = (data or {}).get("dateWeightList", []) or []
    return len(entries) > 0


def garmin_add_weigh_in(garth, ts_epoch, weight_kg, dry_run=False):
    local_dt = datetime.fromtimestamp(ts_epoch, LOCAL_TZ)
    utc_dt = datetime.fromtimestamp(ts_epoch, timezone.utc)
    payload = {
        "dateTimestamp": _fmt_ts(local_dt),
        "gmtTimestamp": _fmt_ts(utc_dt),
        "unitKey": "kg",
        "sourceType": "MANUAL",
        "value": round(weight_kg, 2),
    }
    if dry_run:
        log(f"[dry-run] 将写入：{payload}")
        return True
    garth.client.connectapi(
        "/weight-service/user-weight", method="POST", json=payload
    )
    log(
        f"已写入 Garmin：{weight_kg:.2f} kg @ "
        f"{local_dt.strftime('%Y-%m-%d %H:%M')}（北京时间）"
    )
    return True


# ---------------- state ----------------

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            return json.load(open(STATE_FILE, encoding="utf-8"))
        except Exception:
            pass
    return {"last_synced_ts": 0, "last_synced_id": ""}


def save_state(state):
    tmp = STATE_FILE + ".tmp"
    json.dump(state, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)


# ---------------- main ----------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只读，不写入 Garmin")
    args = ap.parse_args()

    # 1. Zepp 拉数据（apptoken 自动续期）
    import requests  # noqa: F401  (确保 venv 有 requests)

    s, uid = zepp_get_session()
    records = zepp_weight_records(s, uid)
    log(f"Zepp 最近体重记录 {len(records)} 条（uid {uid}）")
    if not records:
        log("Zepp 侧无体重记录，本次无事可做")
        return

    state = load_state()
    # 每天只保留 Zepp 当天最新的一条记录
    by_day = {}
    for r in records:
        day = datetime.fromtimestamp(r["ts"], LOCAL_TZ).strftime("%Y-%m-%d")
        if day not in by_day or r["ts"] > by_day[day]["ts"]:
            by_day[day] = r
    daily = sorted(by_day.values(), key=lambda x: x["ts"])
    log(f"Zepp 去重后 {len(daily)} 个有数据的日期")

    new_records = [r for r in daily if r["ts"] > state.get("last_synced_ts", 0)]
    if not new_records:
        latest = daily[-1] if daily else None
        if latest:
            log(
                "无新体重记录（最新："
                f"{datetime.fromtimestamp(latest['ts'], LOCAL_TZ).strftime('%m-%d %H:%M')} "
                f"{latest['weight']:.1f} kg，已同步过）"
            )
        else:
            log("Zepp 侧无体重记录，本次无事可做")
        return
    log(f"待处理 {len(new_records)} 个日期")

    # 2. Garmin 登录
    garth = garmin_login()

    # 3. 逐条同步（严格去重：Garmin 当天有数据就跳过）
    synced = 0
    for rec in new_records:
        local_dt = datetime.fromtimestamp(rec["ts"], LOCAL_TZ)
        local_date = local_dt.strftime("%Y-%m-%d")
        try:
            has = garmin_has_weight(garth, local_date)
        except Exception as e:
            die(f"读取 Garmin {local_date} 体重记录失败，不敢写入：{type(e).__name__}: {e}")
        if has:
            log(
                f"跳过（Garmin {local_date} 已有体重数据）："
                f"{local_dt.strftime('%m-%d %H:%M')} {rec['weight']:.1f} kg"
            )
        else:
            garmin_add_weigh_in(garth, rec["ts"], rec["weight"], dry_run=args.dry_run)
            synced += 1
        if not args.dry_run:
            state["last_synced_ts"] = rec["ts"]
            state["last_synced_id"] = rec["id"]
            save_state(state)

    log(f"完成：新增写入 {synced} 条，跳过 {len(new_records) - synced} 条")


if __name__ == "__main__":
    main()
