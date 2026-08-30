#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WorkBuddy 原生零令牌签到（方案 A 最终落地，全自动 + 自适应）

原理：
  通过 CDP 连接运行中的 WorkBuddy 客户端，从渲染进程现场取得实时会话令牌，
  再直接 POST 官方签到接口完成签到。全程无需用户配置令牌、令牌不落盘，
  随客户端登录态自动续期。

自适应能力（应对 WorkBuddy 更新 / 取消签到）：
  - 令牌获取表达式、接口路径、鉴权头均外置到 config.json（多候选）。
  - 初始化主动检索（首选自愈路径）：recorded_endpoint 缺失时即运行 calibrate.py --auto
    主动扫描本地 app.asar，把真实接口写入 state/learnings.json（生成的运行配置）；已记录则跳过，
    干净安装仅首次扫描。扫描失败不退出，降级回退 config.checkin_paths 兜底（plan A：绝不误判功能移除）。
  - 失败升级兜底：即便经 recorded/config 已知接口，若所有候选均 404，仍升级做 asar 主动扫描，
    检索到新接口重试，仍未产出则退出码 4 提示（不自伤 feature_removed）。
  - config.checkin_paths 定位为「降级兜底」，仅在 asar 主动检索无产出时使用，不优先；
    feature_removed 不再自动持久化，仅在「已知接口全 404 + 升级检索无产出」时由退出码 4 提示。
  - 被动抓取（sniff）自 v1.7.7 起**退出自动链路**，降级为人工诊断命令：实测签到请求由守护进程
    发出、不经渲染进程网络栈，CDP 无法观测（详见 sniff.py 模块说明与 SKILL.md 已知限制）。
    sniff 模块仍被 import，仅复用其 split_endpoint()。

运行日志：logs/checkin.log（追加）
结果反馈：state/last_result.json（结构化，供自动化/用户查询）

退出码：
  0  成功 / 今日已签到 / 幂等跳过
  1  被后端拒绝（401 鉴权失效、其它非 2xx）
  2  CDP 不可用（客户端未运行或未带调试参数）→ 可回退令牌脚本
  3  其它异常（取不到令牌等）
  4  接口路径失效 / 签到功能疑似取消（升级检索后仍无可用接口，建议人工复查）
  5  （已弃用）初始化已改为主动检索 + config 已知接口兜底，不再因缺记录而退出。

环境变量（可选覆盖）：
  WORKBUDDY_CDP_PORT   调试端口，默认 9222
  WORKBUDDY_CHECKIN_URL 覆盖完整签到接口（最高优先级）
"""

import datetime
import json
import os
import random
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wbcommon
import tokenfile
import sniff
import notify

# 暂时性失败（网络异常 code=0 / 服务端 5xx）的接口级重试策略。
# 00:05 无人值守场景下，一次网络抖动不该让当天签到失败。
RETRY_ATTEMPTS = 2   # 同一接口最多尝试次数（首次 + 1 次退避重试）
RETRY_DELAY = 3      # 退避间隔（秒）

# v2.0.0 任务级重试（无人值守专用，--retry 或 WORKBUDDY_CHECKIN_RETRY=1 启用）：
# 可重试失败时，自动延后一个 60~600 秒的随机值后**重跑整个任务**（每次都先跑状态预检，
# 幂等保证不会重复领取）。终止性失败（活动取消，退出码 4）不重试——当日放弃、次日再试。
TASK_RETRY_MAX = 10           # 尝试上限（首次 + 9 次重试）
TASK_RETRY_MIN_SEC = 60       # 延后下限（秒）
TASK_RETRY_MAX_SEC = 600      # 延后上限（秒）
TASK_RETRY_TOTAL_SEC = 3600   # 总耗时上限（秒），与次数上限构成双重约束


def build_identity_js(cfg):
    """生成一段 async IIFE，返回 JSON 字符串 {token, uid, domain}。

    在单一 CDP 会话内一次性取回令牌/uid/domain（A1：避免原先 3 次独立
    WebSocket 握手）。令牌表达式仍由 config 多候选驱动，逐个尝试取首个非空字符串。
    """
    token_parts = []
    for e in (cfg.get("token_exprs") or []):
        token_parts.append(
            "try{const __t=(" + e + ");if(typeof __t==='string'&&__t)return __t;}catch(_e){}"
        )
    token_js = "(async function(){" + "".join(token_parts) + "return null;})()"
    uid_expr = cfg.get("uid_expr") or "null"
    domain_expr = cfg.get("domain_expr") or "null"
    return (
        "(async function(){"
        "try{"
        "const __tok=await(" + token_js + ");"
        "const __uid=String((" + uid_expr + ")||'');"
        "const __dom=String((" + domain_expr + ")||'');"
        "return JSON.stringify({token: typeof __tok==='string'?__tok:null, uid: __uid, domain: __dom});"
        "}catch(e){return JSON.stringify({token:null,uid:'',domain:''});}"
        "})()"
    )


def fetch_identity(cfg, log):
    """一次性经 CDP 取回 token / uid / domain（单会话，零令牌、不落盘）。"""
    js = build_identity_js(cfg)
    raw = wbcommon.cdp_evaluate(wbcommon.DEFAULT_PORT, js, await_promise=True)
    token, uid, domain = "", "", ""
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                token = data.get("token") or ""
                uid = data.get("uid") or ""
                domain = data.get("domain") or ""
        except Exception:
            pass
    # 脱敏：uid / domain 完全由运行时经 CDP 动态获取，无硬编码回退
    uid = (uid or "").strip()
    domain = (domain or "").strip() or cfg.get("default_domain") or "www.workbuddy.cn"
    return token, uid, domain


def build_urls(cfg, learnings=None):
    """生成候选签到 URL 列表，优先级：环境变量 > learnings.recorded_endpoint
    > config.checkin_paths > learnings.last_known_good。"""
    env_url = os.environ.get("WORKBUDDY_CHECKIN_URL")
    if env_url:
        return [env_url]
    urls = []

    def add(api_base, path):
        if not api_base or not path:
            return
        u = api_base.rstrip("/") + (path if path.startswith("/") else "/" + path)
        if u not in urls:
            urls.append(u)

    rec = (learnings or {}).get("recorded_endpoint")
    if rec:
        add(rec.get("api_base"), rec.get("path"))
    for p in cfg.get("checkin_paths") or []:
        add(cfg.get("api_base"), p)
    lkg = (learnings or {}).get("last_known_good")
    if lkg:
        add(lkg.get("api_base"), lkg.get("path"))
    return urls or [(cfg.get("api_base") or "").rstrip("/") + "/billing/meter/daily-checkin"]


def do_post(url, token, uid, domain, headers_extra, log):
    body = json.dumps({}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("X-User-Id", uid)
    req.add_header("X-Domain", domain or "www.workbuddy.cn")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers_extra or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.getcode(), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, "ERR:" + str(e)


def interpret(code, text, log):
    """根据 HTTP 状态与响应文本判定结果。返回 (status, exit_code, message)。

    status 取值：
      success / already_checked  确定成功
      auth_failed                鉴权失效（换路径无意义）
      endpoint_not_found         404，应尝试其它候选路径
      retryable                  暂时性失败（网络异常 code=0 或服务端 5xx），可重试
      failed                     其它确定性失败
    """
    text_l = (text or "").lower()
    if 200 <= code < 300:
        return "success", 0, "签到成功"
    if code == 401 or code == 403:
        return "auth_failed", 1, "鉴权失效（401/403），请重新登录客户端后重试"
    if code == 404:
        return "endpoint_not_found", 4, "接口路径不存在（404），疑似 WorkBuddy 更新或取消签到，需重新校准"
    if "already" in text_l or "已签到" in text or "claimed" in text_l:
        return "already_checked", 0, "今日已签到"
    # code==0 表示网络层异常（超时 / DNS / 连接失败），与 5xx 同属暂时性故障，
    # 值得重试；此前它被当作确定性失败立即返回，00:05 场景一次抖动即误报失败。
    if code == 0 or 500 <= code < 600:
        return "retryable", 1, f"暂时性失败（HTTP {code}），可重试"
    return "failed", 1, f"签到未成功（HTTP {code}）"


def try_checkin(urls, token, uid, domain, cfg, log, learnings, version):
    """按候选 URL 顺序尝试签到（B1：统一两处重复重试逻辑）。

    每个候选最多尝试 RETRY_ATTEMPTS 次：遇到「暂时性失败」（网络异常 / 5xx）
    退避 RETRY_DELAY 秒后重试同一 URL；401 等确定性失败不重试；
    404 视为路径失效，继续下一个候选。

    命中确定结果（成功/已签/其它非 404 失败）即写结果并返回 (True, 退出码)；
    仅当所有候选均为 404 时返回 (False, None)，交由调用方做升级检索或判失败。
    """
    status = exit_code = message = code = None
    for url in urls:
        for attempt in range(RETRY_ATTEMPTS):
            code, text = do_post(url, token, uid, domain, cfg.get("auth_headers"), log)
            log.log(f"POST {url} -> HTTP {code}")
            try:
                j = json.loads(text)
                log.log(f"响应: {json.dumps(j, ensure_ascii=False)[:300]}")
            except Exception:
                log.log(f"响应(非JSON): {text[:200]}")
            status, exit_code, message = interpret(code, text, log)
            if status in ("success", "already_checked"):
                wbcommon.mark_checked_today()
                api_base, path = sniff.split_endpoint(url)
                learnings["last_known_good"] = {
                    "api_base": api_base,
                    "path": path,
                    "method": "POST",
                    "header_names": sorted((cfg.get("auth_headers") or {}).keys()),
                    "last_success_ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
                }
                wbcommon.save_learnings(learnings)
                log.log(message)
                wbcommon.write_result(
                    status, message, exit_code=exit_code,
                    extra={"client_version": version, "http_status": code, "url": url},
                )
                return True, exit_code
            if status != "retryable":
                break   # 404 / 401 / 其它确定性失败：无需重试本 URL
            if attempt < RETRY_ATTEMPTS - 1:
                log.log(f"{message}，{RETRY_DELAY}s 后重试…", "WARN")
                time.sleep(RETRY_DELAY)
        # 该候选已试尽
        if status == "endpoint_not_found":
            continue   # 404：继续尝试下一个候选路径
        # 非 404 的失败不继续尝试其它路径（如 401 是令牌问题，换路径无意义）
        log.log(message, "WARN")
        wbcommon.write_result(
            status, message, exit_code=exit_code,
            extra={"client_version": version, "http_status": code, "url": url},
        )
        return True, exit_code
    return False, None


def _build_status_url(cfg, learnings):
    """构造签到状态查询 URL（best-effort 预检用）；无配置则返回 None。

    实测（2026-08-29）：两个状态端点行为并不相同——`checkin-activity-status`
    返回真实状态（today_checked_in / streak_days / daily_credit），而
    `checkin-status` 返回全零的未签状态。故显式优先 activity 端点，
    不再依赖 config 里的排序（此前靠字母序恰好选中正确者，属运气）。
    """
    rec = (learnings or {}).get("recorded_endpoint")
    api_base = (rec or {}).get("api_base") or cfg.get("api_base")
    paths = cfg.get("checkin_status_paths") or []
    if not api_base or not paths:
        return None
    p = None
    for cand in paths:
        if "activity" in cand:
            p = cand
            break
    if p is None:
        p = paths[0]
    return api_base.rstrip("/") + (p if p.startswith("/") else "/" + p)


def _probe_checked_status_ex(status_url, token, uid, domain, headers_extra, log):
    """预检：查询服务端今日是否已签到，并识别签到活动是否已取消/未开启。

    该端点必须用 **POST**（asar 中官方实现为
    `httpService.post("/billing/meter/checkin-status", {})`）；此前用 GET 请求
    一律返回 404，这是本功能自 v1.6.0 引入后从未生效的根因。

    返回 {"checked": bool, "inactive": bool}：
      - checked：仅当**明确**读到已签到标志才为 True；任何异常、非 200、字段缺失
        一律 False，由调用方回退正常 POST 签到——宁可多一次幂等请求，绝不漏签。
      - inactive：**仅在服务端明确返回 data.active=false** 时置位（本期活动到期未续 /
        未开启）。字段缺失、解析失败、非 200 一律 False——不臆断活动取消，绝不误放弃。
    """
    out = {"checked": False, "inactive": False}
    try:
        code, text = do_post(status_url, token, uid, domain, headers_extra, log)
    except Exception as e:
        log.log(f"状态预检异常: {e}（回退正常签到）。", "WARN")
        return out
    if code != 200:
        log.log(f"状态预检返回 HTTP {code}，回退正常签到。")
        return out
    log.log(f"状态预检响应: {' '.join((text or '').split())[:200]}")
    out["checked"] = _looks_already_checked(text)
    try:
        d = ((json.loads(text) or {}).get("data") or {})
        if "active" in d and d.get("active") is False:
            out["inactive"] = True     # 仅显式 false 才判定，缺失不算
    except Exception:
        pass
    return out


def _looks_already_checked(text):
    """判断状态响应是否表示今日已签到；仅在明确命中时才返回 True。

    实测响应形如：
      {"code":0,"data":{"today_checked_in":true,"streak_days":16,"daily_credit":100,...}}
    注意字段是 snake_case 的 `today_checked_in`——旧实现的字段列表里没有它，
    是预检永不命中的第二个原因。
    """
    if not text:
        return False
    try:
        j = json.loads(text)
    except Exception:
        # 非 JSON 响应：保守退回关键字匹配，仅在出现明确字样时判定
        low = (text or "").lower()
        return "已签到" in text or "already checked" in low
    if not isinstance(j, dict):
        return False
    data = j.get("data") if isinstance(j.get("data"), dict) else j
    for key in ("today_checked_in", "todayCheckedIn", "checked", "signed",
                "todayChecked", "isChecked", "alreadyChecked", "signedIn", "todaySigned"):
        v = data.get(key)
        if v is True or v == 1 or v == "true" or v == "1":
            return True
    return False


def _ask_cdp_consent(reason):
    """交互模式下的 CDP 回退**强提示 + 询问**，默认拒绝（回车即 N）。"""
    bar = "=" * 58
    print(bar)
    print(" [warn] 明文登录态读取失败，是否回退到 CDP 方案？")
    print("-" * 58)
    print(f"  失败原因：{reason}")
    print()
    print("  CDP 回退需要同时满足：")
    print("    1. WorkBuddy 以调试端口启动（仅桌面「WorkBuddy 自动签到」快捷方式冷启动）")
    print("    2. 客户端处于登录状态")
    print("  若客户端是用普通方式打开的，本次回退必然失败（退出码 2）。")
    print(bar)
    try:
        ans = input("  是否执行 CDP 回退？[y/N] ").strip().lower()
    except Exception:
        ans = ""
    return ans in ("y", "yes")


def acquire_identity(cfg, log):
    """v2.0.0 取令牌主流程：明文登录态文件优先 → DPAPI 旧版兜底 → 回退闸门(CDP)。

    返回 (token, uid, domain)；失败返回 (None, "", "")，并已写好结构化结果。

    回退闸门（安全默认）：
      - 交互模式（有人在）：强提示 + 询问，默认 N。
      - 无人值守：查 config.cdp_fallback_allowed（或环境变量临时授权）；
        未预先授权则**不回退**，只留待决提示，待用户上线后决策。
    """
    # ① 明文登录态文件（主路径，无需 CDP / 调试端口 / .lnk）
    token, uid, domain = tokenfile.read_identity(
        names=cfg.get("token_file_names"),
        extra_paths=cfg.get("token_file_paths"), log=log)
    if token:
        return token, uid, domain

    reason = "未在本机找到有效的明文登录态文件（客户端未登录，或 v5.3.8+ 文件路径已变）"
    log.log(f"明文登录态读取失败：{reason}", "ERROR")

    # ② DPAPI 兜底（旧版加密存储）：明文缺失时尝试解密 v5.3.8 之前的 state.vscdb
    if cfg.get("token_dpapi_enabled", True) and tokenfile.dpapi_available(log=log):
        dtoken, duid, ddomain = tokenfile.read_identity_dpapi(log=log)
        if dtoken:
            log.log("DPAPI 兜底成功取得令牌，跳过 CDP 回退闸门。", "WARN")
            return dtoken, duid, ddomain
        log.log("DPAPI 兜底未取得令牌，继续走 CDP 回退闸门。", "WARN")

    # ③ 回退闸门（CDP）
    if not wbcommon.is_unattended():
        granted = _ask_cdp_consent(reason)
        log.log("用户已同意执行 CDP 回退。" if granted else "用户未同意 CDP 回退（默认 N），本次不回退。")
    else:
        env_ok = (os.environ.get("WORKBUDDY_CHECKIN_CDP_FALLBACK") or "").strip().lower() in (
            "1", "true", "yes")
        granted = bool(cfg.get("cdp_fallback_allowed")) or env_ok
        if granted:
            log.log("无人值守且已预先授权 cdp_fallback_allowed=true，执行 CDP 回退。", "WARN")
        else:
            log.log("无人值守且未预先授权 CDP 回退：本次不回退，仅留下待决提示，"
                    "待用户上线后决策（如需无人值守也能回退，"
                    "请在 config.json 置 cdp_fallback_allowed=true）。", "WARN")
            wbcommon.write_pending_cdp_consent(reason)

    if not granted:
        wbcommon.write_result("no_token", reason + "；未执行 CDP 回退", exit_code=3)
        return None, "", ""

    # ③ CDP 回退（保留既有链路）
    try:
        token, uid, domain = fetch_identity(cfg, log)
    except Exception as e:
        log.log(f"CDP 回退获取令牌失败: {e}", "ERROR")
        wbcommon.write_result("error", f"CDP 回退获取令牌失败: {e}", exit_code=3)
        return None, "", ""
    if not token:
        log.log("CDP 回退未取得有效令牌（客户端未登录或令牌接口变化）。", "ERROR")
        wbcommon.write_result("no_token", "CDP 回退未取得有效会话令牌", exit_code=3)
        return None, "", ""
    return token, uid, domain


def main():
    log = wbcommon.Logger()
    cfg = wbcommon.load_config()
    learnings = wbcommon.load_learnings()

    # 0) 功能已确认移除（人工判定）：快速短路，并标记当日放弃
    if cfg.get("feature_removed"):
        log.log("config 已标记签到功能移除（feature_removed=true），跳过执行。", "WARN")
        wbcommon.mark_gave_up_today("config 已人工标记 feature_removed=true（判定功能取消）")
        wbcommon.write_result("feature_removed", "签到功能已取消/移除", exit_code=4)
        return 4

    # 0.1) 当日已因终止性失败放弃（活动取消/接口失效）：立即跳过，不重复消耗重试额度。
    #      标记为按日期存储，跨日自动失效，次日 00:05 正常重试（绝不永久关闭）。
    if wbcommon.gave_up_today():
        log.log("今日已因终止性失败（签到活动取消或接口失效）放弃，跳过执行，明日再试。", "WARN")
        wbcommon.write_result("gave_up_today", "今日已放弃：签到活动取消或接口失效，明日再试",
                              exit_code=4)
        return 4

    # 1) 幂等短路
    if wbcommon.early_skip_if_checked(log):
        return 0

    # 2) CDP 可用性（v2.0.0：不再是签到的前置条件）
    #    主路径改为读取 v5.3.8+ 明文登录态，不依赖调试端口；CDP 仅用于
    #    ①取客户端版本号 ②明文读取失败且获授权后的回退分支。故不可用时仅告警。
    version = ""
    try:
        vinfo = wbcommon.cdp_version(wbcommon.DEFAULT_PORT)
        version = wbcommon.extract_client_version((vinfo or {}).get("User-Agent", ""))
        log.log(f"检测到 WorkBuddy 客户端（版本 {version or '未知'}），CDP 可用。")
    except Exception:
        log.log(f"CDP 调试端口 {wbcommon.DEFAULT_PORT} 不可用（客户端未运行或未带调试参数）；"
                f"主路径不依赖 CDP，继续尝试明文登录态。", "WARN")

    # 2.1) 初始化主动检索（首选自愈路径，替代「先试 config」）：
    #      recorded_endpoint 缺失时主动扫描本地 app.asar 提取真实接口并写入 learnings.json
    #      （生成的运行配置）；已记录则跳过（干净安装仅首次扫描，避免每次无谓 I/O）。
    #      扫描失败不退出，降级回退 config.checkin_paths 兜底（plan A：绝不误判功能移除）。
    if not learnings.get("recorded_endpoint"):
        log.log("未记录签到接口（recorded_endpoint 缺失），初始化主动检索 app.asar…")
        try:
            cal = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calibrate.py")
            r = subprocess.run([sys.executable, cal, "--auto"], timeout=180,
                               capture_output=True, text=True)
            if r.returncode == 0:
                log.log("主动检索（asar 扫描）完成。")
            else:
                log.log(f"主动检索返回非零（{r.returncode}），将回退 config 已知接口兜底。", "WARN")
        except Exception as e:
            log.log(f"主动检索异常: {e}，将回退 config 已知接口兜底。", "WARN")
        # 重新加载（calibrate 可能已写回 learnings.recorded_endpoint / config）
        cfg = wbcommon.load_config()
        learnings = wbcommon.load_learnings()
        ep = learnings.get("recorded_endpoint")
        if ep:
            log.log(f"已主动检索到签到接口: {ep['api_base']}{ep['path']}")
        elif cfg.get("api_base") and (cfg.get("checkin_paths") or cfg.get("checkin_status_paths")):
            log.log("主动检索未产出接口（asar 可能未含明文路径），将使用 config 已知接口兜底签到。", "WARN")
        else:
            log.log("主动检索未产出、且 config 也无已知接口，本次可能需依赖后续升级检索。", "WARN")
    else:
        log.log(f"使用已记录签到接口: {learnings['recorded_endpoint']['api_base']}{learnings['recorded_endpoint']['path']}")

    # 3) 取令牌与身份（v2.0.0：明文登录态文件优先 → 回退闸门 → CDP）
    token, uid, domain = acquire_identity(cfg, log)
    if not token:
        # acquire_identity 内部已写好结构化结果（no_token / 无人值守待决标记）
        return 3
    log.log(f"已取得会话令牌（len={len(token)}），uid={(uid or '')[:8]}...")

    # B2 服务端状态预检（best-effort）：若服务端明确显示今日已签，跳过 POST，避免无谓请求
    #    预检必须用 POST（官方实现如此，GET 一律 404），且仅在明确读到
    #    today_checked_in=true 时才短路；其余情况一律回退正常 POST，避免漏签。
    status_url = _build_status_url(cfg, learnings)
    if status_url:
        try:
            pre = _probe_checked_status_ex(status_url, token, uid, domain,
                                           cfg.get("auth_headers"), log)
        except Exception:
            pre = {"checked": False, "inactive": False}
        if pre.get("inactive"):
            # 活动取消（如本期到期未续）：终止性，当日放弃，并**明确告知用户**
            msg = ("签到活动已取消或未开启（服务端返回 active=false，可能是本期活动到期未续）；"
                   "当日不再尝试，明日自动重试；若处于活动间隔期，请等待下一期开启")
            log.log(f"[重要] {msg}", "ERROR")
            wbcommon.mark_gave_up_today("签到活动已取消/未开启（服务端 active=false）")
            wbcommon.write_result("activity_inactive", msg, exit_code=4,
                                  extra={"client_version": version, "url": status_url})
            return 4
        if pre.get("checked"):
            wbcommon.mark_checked_today()
            log.log("服务端状态显示今日已签到（状态预检），跳过 POST。")
            wbcommon.write_result(
                "already_checked", "服务端状态显示今日已签到（状态预检）", exit_code=0,
                extra={"client_version": version, "url": status_url},
            )
            return 0
        # 其余情况（预检失败/字段缺失）不阻断，继续正常 POST

    # 4) 多候选接口签到（优先 learnings.recorded_endpoint → config → last_known_good）
    urls = build_urls(cfg, learnings)
    ok, rc = try_checkin(urls, token, uid, domain, cfg, log, learnings, version)
    if ok:
        return rc

    # 失败升级：所有候选接口均 404 → 升级检索真实接口（asar 主动扫描，calibrate.py --auto）
    # 检索到新接口（config / learnings 更新）后重试一次；若仍无产出则退出码 4 提示
    # （不在 config 自动置 feature_removed，避免 asar 误判把自动化永久自关）。
    log.log("所有候选签到接口均返回 404，升级检索真实接口（asar 主动扫描）…", "WARN")
    urls_before = build_urls(cfg, learnings)
    try:
        cal = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calibrate.py")
        r = subprocess.run([sys.executable, cal, "--auto"], timeout=180,
                           capture_output=True, text=True)
        if r.returncode == 0:
            log.log("升级检索完成，配置已重新加载。")
        else:
            log.log(f"升级检索返回非零（{r.returncode}），继续用检索结果重试。", "WARN")
    except Exception as e:
        log.log(f"升级检索异常: {e}，继续重试。", "WARN")
    # 重新加载（calibrate 可能已更新 config / learnings）
    cfg = wbcommon.load_config()
    learnings = wbcommon.load_learnings()
    urls_after = build_urls(cfg, learnings)
    if urls_after != urls_before:
        ok, rc = try_checkin(urls_after, token, uid, domain, cfg, log, learnings, version)
        if ok:
            return rc
    # v1.7.7 起：此处不再做 live 被动嗅探（原为 60 秒固定空等）。
    # 实测结论（2026-08-29）：签到请求由守护进程（main/daemon-app-server-entry.js）的
    # Node 网络栈发出，不经过渲染进程，CDP 网络域无法观测；且静默期零签到流量，
    # 无人值守时必然空手。被动抓取已降级为人工诊断命令（`python scripts/sniff.py`），
    # 不再进入自动链路，避免无收益的等待。
    # 双重确认仍未找到可用接口：已知接口全 404 + 升级检索无新产出 → 提示功能或已取消
    log.log("升级检索后仍未找到可用接口，签到功能可能已移除或路径已变，建议人工复查。", "ERROR")
    wbcommon.write_result(
        "endpoint_not_found",
        "所有候选接口均 404，且升级检索未产出新接口，签到功能或已取消",
        exit_code=4,
        extra={"client_version": version, "urls_tried": build_urls(cfg, learnings)},
    )
    return 4


def run_with_retry():
    """无人值守任务级重试：可重试失败时，延后 60~600 秒随机值后重跑整个任务。

    放弃的**唯一依据**是「签到活动已取消」——由 main() 依据服务端 active=false
    或 config 人工标记 feature_removed 判定，并写入 gave_up 当日标记。
    其余任何情况（含接口失效、尝试达上限、总耗时达上限）都**不替用户做放弃决定**，
    只写 pending_user_decision 提示留待用户判断。
    """
    log = wbcommon.Logger()
    deadline = time.time() + TASK_RETRY_TOTAL_SEC
    rc = 0
    for attempt in range(1, TASK_RETRY_MAX + 1):
        rc = main()
        if rc == 0:
            wbcommon.clear_pending_user_decision()
            return 0
        if wbcommon.gave_up_today():
            log.log("已确认签到活动取消（或人工标记功能移除）：当日放弃，明日自动重试。", "ERROR")
            return rc
        if attempt >= TASK_RETRY_MAX:
            reason = f"已尝试 {TASK_RETRY_MAX} 次仍未成功（最后退出码 {rc}），原因需人工确认"
            wbcommon.write_pending_user_decision(reason, attempts=attempt, last_exit_code=rc)
            log.log(f"[待用户决策] {reason}；已留下提示，不代为放弃。", "ERROR")
            return rc
        remain = deadline - time.time()
        if remain <= 0:
            reason = (f"已达总耗时上限 {TASK_RETRY_TOTAL_SEC} 秒仍未成功"
                      f"（最后退出码 {rc}），需人工确认")
            wbcommon.write_pending_user_decision(reason, attempts=attempt, last_exit_code=rc)
            log.log(f"[待用户决策] {reason}；已留下提示，不代为放弃。", "ERROR")
            return rc
        delay = min(random.uniform(TASK_RETRY_MIN_SEC, TASK_RETRY_MAX_SEC), remain)
        log.log(f"第 {attempt}/{TASK_RETRY_MAX} 次尝试失败（退出码 {rc}），"
                f"{delay:.0f} 秒后重试…", "WARN")
        time.sleep(delay)
    return rc


if __name__ == "__main__":
    retry = ("--retry" in sys.argv) or (
        (os.environ.get("WORKBUDDY_CHECKIN_RETRY") or "").strip().lower()
        in ("1", "true", "yes"))
    rc = 0
    try:
        rc = run_with_retry() if retry else main()
    except Exception as e:
        log = wbcommon.Logger()
        log.log(f"异常: {e}", "ERROR")
        wbcommon.write_result("error", str(e), exit_code=3)
        rc = 3
    # 接口预留：配置了推送 webhook 时按结果类别推送签到通知；
    # 未配置 webhook 或事件被 on 掩码关闭时静默跳过，不影响退出码。
    try:
        _cfg = wbcommon.load_config()
        _res = wbcommon.read_last_result()
        if _res:
            notify.send_notify(notify._event_for(_res.get("status")), _res, _cfg,
                               wbcommon.Logger())
    except Exception:
        pass
    sys.exit(rc)
