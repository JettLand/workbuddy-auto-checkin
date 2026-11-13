import datetime
import json
import os
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
        code, text = post(base + path, token, uid, domain, cfg.get("auth_headers"))
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
        log("%s trigger -> %s" % (trigger, run_once(force=force)))
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
