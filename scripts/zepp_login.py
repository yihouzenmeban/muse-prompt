#!/usr/bin/env python3
"""Zepp/Huami 账号密码登录，换取 token（目标是拿到 apptoken）。

逆向自 user.huami.com/privacy 登录页 JS（main.b5278b36.chunk.js 的 wt 函数）：
  POST https://api-user.huami.com/registrations/{account}/tokens
  Content-Type: application/x-www-form-urlencoded
  头：app_name=com.huami.webapp, Accept-Language=zh
  字段：country_code, password, name, client_id=HuaMi,
        redirect_uri, state=REDIRECTION, token=access, json_response=true

凭证从 .zepp_credentials（0600）读取，绝不打印。
"""

import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
CRED_FILE = os.path.join(PROJECT_ROOT, ".zepp_credentials")
APPT_FILE = os.path.join(PROJECT_ROOT, ".apptoken")

LOGIN_BASE = "https://api-user.huami.com/"


def load_credentials(path=CRED_FILE):
    creds = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            creds[k.strip()] = v.strip()
    username = creds.get("ZEPP_USERNAME", "")
    password = creds.get("ZEPP_PASSWORD", "")
    if not username or not password:
        raise SystemExit("凭证文件缺少 ZEPP_USERNAME / ZEPP_PASSWORD")
    return username, password


def redact(obj):
    """把疑似 token/密码的值打码后返回可打印结构。"""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            lk = k.lower()
            if any(s in lk for s in ("token", "password", "secret", "apptoken", "access")):
                out[k] = f"<redacted len={len(str(v))}>" if v else v
            else:
                out[k] = redact(v)
        return out
    if isinstance(obj, list):
        return [redact(x) for x in obj]
    return obj


def login(username, password):
    import requests

    s = requests.Session()
    s.headers.update(
        {
            "app_name": "com.huami.webapp",
            "Accept-Language": "zh",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        }
    )
    url = LOGIN_BASE + "registrations/" + username + "/tokens"
    data = {
        "country_code": "zh-CN",
        "password": password,
        "name": username,
        "client_id": "HuaMi",
        "redirect_uri": (
            "https://s3-us-west-2.amazonaws.com/hm-registration/successsignin.html"
        ),
        "state": "REDIRECTION",
        "token": "access",
        "json_response": "true",
    }
    r = s.post(url, data=data, timeout=30)
    return r, s


def _login_once(username, password):
    """单次登录尝试，返回 (ok, access_or_error)。"""
    import requests
    from urllib.parse import quote

    s = requests.Session()
    s.headers.update(
        {
            "app_name": "com.huami.webapp",
            "Accept-Language": "zh",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        }
    )
    url = LOGIN_BASE + "registrations/" + quote(username, safe="") + "/tokens"
    data = {
        "country_code": "86",
        "password": password,
        "name": username,
        "client_id": "HuaMi",
        "redirect_uri": (
            "https://s3-us-west-2.amazonaws.com/hm-registration/successsignin.html"
        ),
        "state": "REDIRECTION",
        "token": "access",
        "json_response": "true",
    }
    r = s.post(url, data=data, timeout=30)
    try:
        body = r.json()
    except Exception:
        return False, f"HTTP {r.status_code} 非 JSON"
    if body.get("ok"):
        return True, body.get("access", "")
    return False, f"ok=false error={body.get('error')}"


def _exchange_access(access):
    """用 access 码换 app_token（即 apptoken），返回 (app_token, uid)。"""
    import requests

    r = requests.post(
        "https://account.huami.com/v2/client/login",
        data={
            "country_code": "86",
            "app_name": "com.huami.webapp",
            "third_name": "huami",
            "grant_type": "access_token",
            "code": access,
            "device_id": "02:00:00:00:00:00",
            "device_model": "web",
            "app_version": "4.3.0",
            "dn": "account.huami.com,api-user.huami.com,auth.huami.com,"
            "api-mifit.huami.com,api-open.huami.com",
            "allow_registration": "false",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
        timeout=30,
    )
    body = r.json()
    ti = body.get("token_info", {})
    app_token = ti.get("app_token", "")
    uid = str(ti.get("user_id", ""))
    if not app_token or not uid:
        raise RuntimeError(f"换取 app_token 失败：{redact(body)}")
    return app_token, uid


def get_apptoken():
    """完整登录链，返回 (apptoken, uid)。手机号自动加 +86 前缀。"""
    username, password = load_credentials()
    candidates = [username]
    if username.isdigit() and len(username) == 11 and not username.startswith("+"):
        candidates.insert(0, "+" + "86" + username)
    last_err = ""
    for cand in candidates:
        ok, result = _login_once(cand, password)
        if ok:
            return _exchange_access(result)
        last_err = result
    raise RuntimeError(f"Zepp 登录失败：{last_err}")


def refresh_and_save(path=APPT_FILE):
    """重新登录并保存 apptoken，返回 (apptoken, uid)。"""
    app_token, uid = get_apptoken()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(app_token)
    os.replace(tmp, path)
    os.chmod(path, 0o600)
    return app_token, uid


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="登录并保存 apptoken")
    args = ap.parse_args()
    if args.refresh:
        app_token, uid = refresh_and_save()
        print(f"apptoken 已刷新并保存（uid {uid}，长度 {len(app_token)}）")
    else:
        username, _ = load_credentials()
        print(f"凭证就绪：{username[:3]}***{username[-2:]}（用 --refresh 登录）")


if __name__ == "__main__":
    main()
