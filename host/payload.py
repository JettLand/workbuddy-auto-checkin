import datetime
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import winreg

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import wbcredential

CONFIG_FILE = os.environ.get("WB_CHECKIN_CONFIG") or os.path.join(
    BASE, "config.json")
LOG = os.path.join(BASE, "logs", "daemon.log")
SCHEDULE = [(0, 5)]
RETRY_MAX = 6  # 网络类失败当日重试上限；间隔 10min*次数（累计约 3.5h）
_EXPIRY_WARNED = False  # 登录令牌到期弹窗的进程内去重标记
_EXPIRY_LOG_WARNED = False  # 登录令牌到期日志警告的进程内去重标记


def log(msg):
    line = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " " + msg
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


def _alert(title, msg, tag):
    """统一告警通道：托盘气泡 + 置顶模态窗（通道由 tray_host 注入）。

    所有告警共用此入口，避免各处重复 globals().get / try-except 样板；
    通道缺失或异常一律降级为日志，绝不中断签到流程。tag 仅用于日志归类。
    """
    notify = globals().get("_tray_notify")
    if not notify:
        return
    try:
        notify(title, msg)
        log("alert -> tray balloon sent (%s)" % tag)
    except Exception as e:
        log("alert ERROR %s: %s" % (type(e).__name__, e))


def _registry_roots():
    """从卸载登记表找 WorkBuddy 安装根（覆盖自定义安装位置）。"""
    out = []
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for path in (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                     r"SOFTWARE\WOW6432Node\Microsoft\Windows"
                     r"\CurrentVersion\Uninstall"):
            try:
                key = winreg.OpenKey(hive, path)
            except OSError:
                continue
            try:
                for i in range(winreg.QueryInfoKey(key)[0]):
                    try:
                        sub = winreg.OpenKey(key, winreg.EnumKey(key, i))
                        name = winreg.QueryValueEx(sub, "DisplayName")[0]
                        if "workbuddy" not in str(name).lower():
                            continue
                        try:
                            loc = winreg.QueryValueEx(
                                sub, "InstallLocation")[0]
                            if loc:
                                out.append(os.path.normpath(loc))
                                continue
                        except OSError:
                            pass
                        try:
                            icon = winreg.QueryValueEx(
                                sub, "DisplayIcon")[0]
                            exe = str(icon).split(",")[0].strip().strip('"')
                            if exe.lower().endswith(".exe"):
                                out.append(os.path.dirname(exe))
                        except OSError:
                            pass
                    except OSError:
                        continue
            finally:
                winreg.CloseKey(key)
    return out


def _candidate_roots(cfg):
    """客户端安装根候选（有序去重）：配置路径上溯 → 注册表 → 常见位置（环境变量拼接）。"""
    roots = []
    addon = (os.environ.get("WB_CHECKIN_TURING_ADDON")
             or cfg.get("turing_addon_dir") or "").strip()
    if addon:
        roots.append(os.path.normpath(os.path.join(
            os.path.dirname(os.path.normpath(addon)),
            "..", "..", "..", "..")))
    roots.extend(_registry_roots())
    for env in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            roots.append(os.path.join(base, "WorkBuddy"))
    seen, out = set(), []
    for r in roots:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def _turing_params(cfg):
    """缓存式自适应解析图灵盾参数，返回 (addon, channelId, name, version)。

    配置有效（addon 目录存在且参数齐）→ 直读；失效/缺失 → 按候选根
    动态发现（cli/product.json 单文件取 channelId/applicationName/
    genieVersion，addon 同树推导）并原子写回 config.json；发现全败但
    addon 可用时用配置值/默认值兜底直发；连 addon 都没有则发警告
    弹窗并返回 None。
    """
    addon = (os.environ.get("WB_CHECKIN_TURING_ADDON")
             or cfg.get("turing_addon_dir") or "").strip()
    if (addon and os.path.isdir(addon)
            and cfg.get("turing_channel_id")
            and cfg.get("turing_product_name")
            and cfg.get("turing_product_version")):
        return (addon, int(cfg["turing_channel_id"]),
                str(cfg["turing_product_name"]),
                str(cfg["turing_product_version"]))
    for root in _candidate_roots(cfg):
        pj = os.path.join(root, "resources", "app.asar.unpacked",
                          "cli", "product.json")
        new_addon = os.path.join(root, "resources", "app.asar.unpacked",
                                 "native", "turing-sdk")
        if not (os.path.isfile(pj) and os.path.isdir(new_addon)):
            continue
        try:
            with open(pj, "r", encoding="utf-8") as f:
                prod = json.load(f)
            cid = int(((prod.get("config") or {})
                       .get("turingSdk") or {}).get("channelId") or 0)
            name = prod.get("applicationName")
            ver = prod.get("genieVersion")
        except (OSError, ValueError):
            continue
        if not (cid and name and ver):
            continue
        params = {"turing_addon_dir": new_addon.replace("\\", "/"),
                  "turing_channel_id": cid,
                  "turing_product_name": name,
                  "turing_product_version": ver}
        try:
            merged = dict(cfg)
            merged.update(params)
            tmp = CONFIG_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)
            os.replace(tmp, CONFIG_FILE)
            cfg.update(params)
            log("turing params discovered at %s -> config updated" % root)
        except OSError as e:
            log("turing config write failed: %s" % e)
            cfg.update(params)
        return (new_addon, cid, name, ver)
    if addon and os.path.isdir(addon):
        return (addon, int(cfg.get("turing_channel_id") or 109144),
                str(cfg.get("turing_product_name") or "WorkBuddy"),
                str(cfg.get("turing_product_version") or "5.11.3"))
    log("turing discovery failed entirely")
    _alert("WorkBuddy 自动签到",
           "图灵盾参数自动发现失败，今日签到可能不计入活动日历，"
           "请检查 WorkBuddy 客户端是否已安装。", "turing")
    return None


def device_token(cfg):
    """本地加载客户端图灵 SDK 产出设备令牌；不可用返回 None（退化为无令牌直发）。

    客户端 11-20 升级后签到活动日历按设备令牌事后校验，无令牌的签到
    会"当场受理但不入日历"。参数走缓存式自适应（见 _turing_params）：
    首次运行动态发现并写入 config.json，后续直读，配置失效自动重拉
    更新，全部失败发警告弹窗——源码不含绝对路径，升级免维护。

    参数对齐客户端实态（2026-11-23 内存取证）：客户端实时令牌为单段
    v3 令牌（无设备信息附加段），后台刷新通道 includesOutdatedMessage
    为 false，故 includesDeviceInfo:false + includesOutdatedMessage:false，
    产出与客户端同构同世代（长度随世代 683~699 漂移，属正常时效编码）。
    """
    p = _turing_params(cfg)
    if p is None or shutil.which("node") is None:
        return None
    addon, cid, name, ver = p
    script = (
        "const b=require(%r);"
        "b.configure(%d,%r,%r);"
        "b.fetchDeviceToken({usingCachedMessage:true,"
        "includesOutdatedMessage:false,includesDeviceInfo:false,timeoutMs:15000})"
        ".then(t=>console.log(t),"
        "e=>{console.error(e&&(e.codeName||e.message));process.exit(1)})"
    ) % (addon, cid, name, ver)
    try:
        r = subprocess.run(["node", "-e", script], capture_output=True,
                           text=True, timeout=30,
                           creationflags=subprocess.CREATE_NO_WINDOW)
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


def _announce_success(text):
    """签到受理 200 时输出明确成功日志与托盘信息气泡（轻量，不弹模态窗）。"""
    credit = streak = "?"
    try:
        d = json.loads(text) or {}
        data = d.get("data") or {}
        if d.get("credit") is not None or data.get("credit") is not None:
            credit = d.get("credit") if d.get("credit") is not None \
                else data.get("credit")
        if d.get("streak_days") is not None or data.get("streak_days") \
                is not None:
            streak = d.get("streak_days") if d.get("streak_days") is not None \
                else data.get("streak_days")
    except Exception:
        pass
    log("checkin SUCCESS: credit +%s, streak %s days" % (credit, streak))
    balloon = globals().get("_tray_balloon")
    if balloon:
        try:
            balloon("签到成功", "今日积分 +%s，连续签到 %s 天" % (credit, streak))
        except Exception as e:
            log("success balloon ERROR %s: %s" % (type(e).__name__, e))


def _resp_data(text):
    """从响应体取 data 对象；解析失败或缺失一律视为空对象（收敛预检/复核两处）。"""
    try:
        return (json.loads(text) or {}).get("data") or {}
    except Exception:
        return {}


def _token_expiry_info(cfg):
    """读取登录令牌到期信息，返回 (到期时刻文本, 剩余天数)；无有效期返回 (None, None)。

    有效期取自登录态明文 expiresAt（毫秒时间戳），非服务端检测——服务端
    实际是否认可另由 checkin-activity-status 的 401/403 判定。
    """
    exp = wbcredential.token_expiry(cfg)
    if not exp:
        return None, None
    remain = (exp / 1000 - time.time()) / 86400
    deadline = datetime.datetime.fromtimestamp(
        exp / 1000).strftime("%Y-%m-%d %H:%M:%S")
    return deadline, remain


def _warn_token_expiry(deadline, remain):
    """登录令牌到期双层预警：≤7 天日志警告、≤1 天弹窗告警，各自进程内只提醒一次。

    客户端有 refreshToken 自动续期，临近到期多为客户端长期未运行，提醒
    用户启动一次客户端刷新登录态。已过期（remain<0）由 route_a 硬阻断，
    此处不弹窗——避免与凭证失败报错重复。
    """
    global _EXPIRY_WARNED, _EXPIRY_LOG_WARNED
    if remain is None or remain < 0:
        return
    if remain <= 7 and not _EXPIRY_LOG_WARNED:
        _EXPIRY_LOG_WARNED = True
        log("token expiry warning: expires %s, %.2f days remaining (<=7d)"
            % (deadline, remain))
    if remain <= 1 and not _EXPIRY_WARNED:
        _EXPIRY_WARNED = True
        _alert("WorkBuddy 自动签到",
               "登录令牌将在 1 天内到期（%s，剩余 %.1f 天），签到可能失败。"
               "请启动并登录一次 WorkBuddy 客户端以刷新登录态。"
               % (deadline, remain), "token expiry")


def run_once(cfg, identity):
    """单次签到：cfg 与 identity 由 _run 统一读取一次后注入（#2+#5 收敛）。"""
    token, uid, domain = identity
    deadline, remain = _token_expiry_info(cfg)
    if deadline:
        log("login token expiry: %s (%.2f days remaining)"
            % (deadline, remain))
    else:
        log("login token expiry: unavailable")
    _warn_token_expiry(deadline, remain)
    log("identity source: %s" % wbcredential._LAST_IDENTITY_SOURCE)
    base = (cfg.get("api_base") or "").rstrip("/")
    headers = checkin_headers(cfg, device_token(cfg))
    if headers.get("X-Device-Token"):
        log("device token ready len=%d" % len(headers["X-Device-Token"]))
    else:
        log("device token unavailable; posting without it")
    # 服务端有效期检测：状态端点（复用同一 Bearer）若齐全地以 401/403
    # 拒绝、且无任何 200，判登录令牌在服务端已失效——提前短路，不发无效
    # 签到 POST。网络错误 code=0 不参与判定；任一 200 即视为令牌有效。
    auth_rejected = False
    auth_accepted = False
    for path in cfg.get("checkin_status_paths") or []:
        code, text = post(base + path, token, uid, domain, cfg.get("auth_headers"))
        if code in (401, 403):
            auth_rejected = True
            continue
        if code != 200:
            continue
        auth_accepted = True
        data = _resp_data(text)
        if data.get("active") is False:
            return "inactive"
        if data.get("today_checked_in") is True:
            return "already"
        break
    if auth_rejected and not auth_accepted:
        log("token validity -> invalid (server 401/403 on status endpoints)")
        return "token_invalid"
    for path in cfg.get("checkin_paths") or []:
        code, text = post(base + path, token, uid, domain, headers)
        log("checkin %s -> %s %s" % (path, code, text[:160]))
        if code == 200:
            _announce_success(text)
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


def verify_checkin(cfg, identity):
    """复核签到活动日历：今日是否真实入账。

    客户端升级后服务端按设备令牌"当场受理、事后判定"，直发返回 200
    不代表入日历（21/22 缺卡成因）。缺卡间隔重试一次再判定，宁可迟报
    不漏报；checkin-status 为假状态，仅 activity-status 可作真源。
    identity 由 _run 注入，与签到同一次凭证，避免重复取凭证漂移。
    """
    token, uid, domain = identity
    base = (cfg.get("api_base") or "").rstrip("/")
    today = datetime.date.today().isoformat()
    for attempt in (1, 2):
        for path in cfg.get("checkin_status_paths") or []:
            code, text = post(base + path, token, uid, domain,
                              cfg.get("auth_headers"))
            if code != 200:
                continue
            data = _resp_data(text)
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


def _retry_network(cfg):
    """网络类失败（run_once 归为 error）的当日有限重试。

    间隔 = 10min * 重试次数（10/20/.../60 分钟，累计约 3.5h），与阁主
    2026-11-25 裁定一致。等待将跨过下一定时点时提前让位——定时触发
    会带状态预检重新尝试，等价于重试。全部失败发置顶告警；阁主点掉
    弹窗后主循环恢复，next_run_at() 已过即自动补签。

    每次重试重新取凭证（间隔 10~60 分钟，期间客户端可能刷新登录态），
    与原 run_once 自取凭证语义一致；仅同一轮内的 run_once↔verify 复用
    _run 注入的凭证（#2 收敛范围）。
    """
    for attempt in range(1, RETRY_MAX + 1):
        wait = 10 * 60 * attempt
        nxt = next_run_at()
        if (datetime.datetime.now()
                + datetime.timedelta(seconds=wait)) >= nxt:
            log("retry aborted: next schedule %s within wait window"
                % nxt.strftime("%Y-%m-%d %H:%M:%S"))
            return None
        time.sleep(wait)
        try:
            identity = wbcredential.get_identity()
            result = run_once(cfg, identity)
        except Exception as e:
            log("retry %d ERROR %s: %s" % (attempt, type(e).__name__, e))
            continue
        log("retry %d -> %s" % (attempt, result))
        if result != "error":
            return result
    _alert("WorkBuddy 自动签到",
           "网络异常导致今日签到失败（已重试 %d 次），请检查网络后"
           "重启本程序补签，或打开客户端使用补签卡。" % RETRY_MAX, "network")
    return "error"


def _run(trigger):
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
            cfg = json.load(f)
        identity = wbcredential.get_identity()
        result = run_once(cfg, identity)
        log("%s trigger -> %s" % (trigger, result))
        if result == "token_invalid":
            # 服务端已明确拒签（登录令牌失效），重试与复核都无意义——
            # 直接弹窗告知刷新登录态；模态窗阻塞 payload 线程无碍。
            _alert("WorkBuddy 自动签到",
                   "登录令牌在服务端已失效（签到状态查询返回 401/403），"
                   "今日签到未发出。请启动并登录一次 WorkBuddy 客户端"
                   "刷新登录态后重启本程序。", "token invalid")
            return
        if result == "error":
            result = _retry_network(cfg)
        if result in ("ok", "already (server confirmed)"):
            if verify_checkin(cfg, identity):
                log("verify -> ok (in activity calendar)")
            else:
                log("verify -> MISSING from activity calendar")
                _alert("WorkBuddy 自动签到",
                       "今日签到可能未生效（活动日历缺卡），"
                       "请打开客户端确认或使用补签卡。", "verify missing")
    except Exception as e:
        log("%s trigger ERROR %s: %s" % (trigger, type(e).__name__, e))


def main():
    log("daemon started")
    _run("startup")
    while True:
        target = next_run_at()
        log("next run at " + target.strftime("%Y-%m-%d %H:%M:%S"))
        while True:
            remaining = (target - datetime.datetime.now()).total_seconds()
            if remaining <= 0:
                break
            time.sleep(min(remaining, 6 * 3600))
        _run("schedule")


if __name__ == "__main__":
    main()
