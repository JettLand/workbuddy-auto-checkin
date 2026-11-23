import datetime
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import wbcredential

LOG = os.path.join(BASE, "logs", "daemon.log")
SCHEDULE = [(0, 5)]


def log(msg):
    line = datetime.datetime.now().isoformat(timespec="seconds") + " " + msg
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


def device_token(cfg):
    """本地加载客户端图灵 SDK 产出设备令牌；不可用返回 None（退化为无令牌直发）。

    客户端 11-20 升级后签到活动日历按设备令牌事后校验，无令牌的签到
    会"当场受理但不入日历"。addon 路径与 channelId 走配置，源码不落盘路径。
    """
    addon = (os.environ.get("WB_CHECKIN_TURING_ADDON")
             or cfg.get("turing_addon_dir") or "").strip()
    if not addon or shutil.which("node") is None or not os.path.isdir(addon):
        return None
    script = (
        "const b=require(%r);"
        "b.configure(%d,%r,%r);"
        "b.fetchDeviceToken({usingCachedMessage:true,"
        "includesOutdatedMessage:true,includesDeviceInfo:true,timeoutMs:15000})"
        ".then(t=>console.log(t),"
        "e=>{console.error(e&&(e.codeName||e.message));process.exit(1)})"
    ) % (addon, int(cfg.get("turing_channel_id") or 109144),
         cfg.get("turing_product_name") or "WorkBuddy",
         cfg.get("turing_product_version") or "5.11.3")
    try:
        r = subprocess.run(["node", "-e", script], capture_output=True,
                           text=True, timeout=30)
        token = r.stdout.strip().splitlines()[-1] if r.returncode == 0 else ""
        return token if token.startswith("v3:") else None
    except Exception:
        return None


def checkin_headers(cfg, token):
    h = dict(cfg.get("auth_headers") or {})
    if token:
        h["X-Device-Token"] = token
    return h


def post(url, token, uid, domain, headers):
    req = urllib.request.Request(url, data=b"{}", method="POST")
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("X-User-Id", uid)
    req.add_header("X-Domain", domain)
    req.add_header("Content-Type", "application/json")
    for name, value in (headers or {}).items():
        if name.lower() not in ("content-type", "x-domain"):
            req.add_header(name, value)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.getcode(), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, "ERR:" + str(e)


def run_once(force=False):
    with open(wbcredential.CONFIG_FILE, "r", encoding="utf-8-sig") as f:
        cfg = json.load(f)
    token, uid, domain = wbcredential.get_identity()
    base = (cfg.get("api_base") or "").rstrip("/")
    headers = checkin_headers(cfg, device_token(cfg))
    if headers.get("X-Device-Token"):
        log("device token ready len=%d" % len(headers["X-Device-Token"]))
    else:
        log("device token unavailable; posting without it")
    if not force:
        for path in cfg.get("checkin_status_paths") or []:
            code, text = post(base + path, token, uid, domain, cfg.get("auth_headers"))
            if code != 200:
                continue
            try:
                data = (json.loads(text) or {}).get("data") or {}
            except Exception:
                data = {}
            if data.get("active") is False:
                return "inactive"
            if data.get("today_checked_in") is True:
                return "already"
            break
    for path in cfg.get("checkin_paths") or []:
        code, text = post(base + path, token, uid, domain, headers)
        log("checkin %s -> %s %s" % (path, code, text[:160]))
        if code == 200:
            return "ok"
        if code in (401, 403):
            return "auth_failed"
        try:
            payload = json.loads(text) or {}
        except Exception:
            payload = {}
        if code == 400 and (payload.get("code") == 10001
                            or "已签到" in (payload.get("msg") or "")):
            return "already (server confirmed)"
    return "error"


def verify_checkin(cfg):
    """复核签到活动日历：今日是否真实入账。

    客户端升级后服务端按设备令牌"当场受理、事后判定"，直发返回 200
    不代表入日历（21/22 缺卡成因）。缺卡间隔重试一次再判定，宁可迟报
    不漏报；checkin-status 为假状态，仅 activity-status 可作真源。
    """
    token, uid, domain = wbcredential.get_identity()
    base = (cfg.get("api_base") or "").rstrip("/")
    today = datetime.date.today().isoformat()
    for attempt in (1, 2):
        for path in cfg.get("checkin_status_paths") or []:
            code, text = post(base + path, token, uid, domain,
                              cfg.get("auth_headers"))
            if code != 200:
                continue
            try:
                data = (json.loads(text) or {}).get("data") or {}
            except Exception:
                data = {}
            if (data.get("today_checked_in") is True
                    or today in (data.get("checkin_dates") or [])):
                return True
        if attempt == 1:
            time.sleep(8)
    return False


def next_run_at():
    """返回下一个定时点的绝对时刻；避免秒数往返换算造成的 1 秒漂移。"""
    now = datetime.datetime.now()
    for hour, minute in SCHEDULE:
        target = now.replace(hour=hour, minute=minute,
                             second=0, microsecond=0)
        if target > now:
            return target
    hour, minute = SCHEDULE[0]
    return (now + datetime.timedelta(days=1)).replace(
        hour=hour, minute=minute, second=0, microsecond=0)


def _run(trigger, force=False):
    try:
        result = run_once(force=force)
        log("%s trigger -> %s" % (trigger, result))
        if result in ("ok", "already (server confirmed)"):
            with open(wbcredential.CONFIG_FILE, "r",
                      encoding="utf-8-sig") as f:
                cfg = json.load(f)
            if verify_checkin(cfg):
                log("verify -> ok (in activity calendar)")
            else:
                log("verify -> MISSING from activity calendar")
                notify = globals().get("_tray_notify")
                if notify:
                    try:
                        notify("WorkBuddy 自动签到",
                               "今日签到可能未生效（活动日历缺卡），"
                               "请打开客户端确认或使用补签卡。")
                        log("alert -> tray balloon sent")
                    except Exception as e:
                        log("alert ERROR %s: %s" % (type(e).__name__, e))
    except Exception as e:
        log("%s trigger ERROR %s: %s" % (trigger, type(e).__name__, e))


def main():
    log("daemon started")
    _run("startup", force=True)
    while True:
        target = next_run_at()
        log("next run at " + target.isoformat(timespec="seconds"))
        while True:
            remaining = (target - datetime.datetime.now()).total_seconds()
            if remaining <= 0:
                break
            time.sleep(min(remaining, 6 * 3600))
        _run("schedule")


if __name__ == "__main__":
    main()
