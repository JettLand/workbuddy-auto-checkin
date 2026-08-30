#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sniff.py —— 运行时被动抓取签到接口（零第三方依赖）

通过 CDP 的 Network 域监听运行中 WorkBuddy 客户端实际发出的 HTTP 请求，
提取签到接口的：端点路径(api_base + path)、请求方法、请求头结构。

安全约束（务必遵守）：
  - 只记录「端点 + 请求头名」，绝不记录 Authorization / X-User-Id 等敏感值，
    也不记录响应体。令牌仍在签到时由客户端现场签发（零令牌属性不变）。
  - 仅被动监听：不导航、不点击、不打扰用户当前页面；抓不到就返回 None，由调用方决定跳过。

定位（v1.7.7 起）：**人工诊断工具，已退出自动链路**
  - 端点发现的唯一可靠手段是 calibrate.py 的 asar 主动扫描；本模块不再被
    checkin_native.py / calibrate.py --auto 自动调用。

实测结论（2026-08-29，WorkBuddy 5.3.14）——机制可用，但对本应用实际抓不到：
  1. 抓包链路本身正常：让渲染进程发出含关键字的 POST，3.1 秒内被捕获，
     _is_checkin_url 过滤逻辑正确（能排除 checkin-status 等状态查询）。
  2. 但真实签到请求不经渲染进程：netstat 与 CDP SystemInfo.getProcessInfo 交叉验证，
     到 copilot.tencent.com:443 的连接中，渲染进程为 0 条，而
     main/daemon-app-server-entry.js 守护进程持有 4 条；静态代码一致——
     httpService.post("/billing/meter/daily-checkin") 位于 main/initialize.js，
     渲染侧仅 getDaemonClientFeature("authClaimDailyCheckin")() 转交守护进程。
     CDP 网络域只覆盖渲染进程，故永远观测不到该请求。
  3. 静默 45 秒实测：渲染进程网络栈仅 2 个无关请求，零签到流量。
  因此本模块仅保留供人工排障（如怀疑架构变更）时手动运行，不作为兜底依赖。
"""

import datetime
import json
import os
import select
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wbcommon


# 命中关键词（URL path 含其一即疑似签到领取接口）
CHECKIN_KEYWORDS = ("daily-checkin", "dailycheckin", "checkin", "sign-in", "signin", "sign/in")
# 排除关键词（含其一视为查询/状态类，非领取）
EXCLUDE_KEYWORDS = ("status", "activity", "query", "list")


def _is_checkin_url(url):
    if not url or not url.startswith("http"):
        return False
    low = url.lower()
    if any(k in low for k in EXCLUDE_KEYWORDS):
        return False
    return any(k in low for k in CHECKIN_KEYWORDS)


def split_endpoint(url):
    """从完整 URL 拆出 (api_base, path)。如 https://x/v2/billing/meter/daily-checkin
    拆为 ('https://x/v2', '/billing/meter/daily-checkin')。供调用方复用。"""
    p = urllib.parse.urlparse(url)
    origin = f"{p.scheme}://{p.netloc}"
    if "/v2" in p.path:
        idx = p.path.index("/v2") + len("/v2")
        api_base = origin + "/v2"
        path = p.path[idx:] or "/"
    else:
        api_base = origin
        path = p.path or "/"
    return api_base.rstrip("/"), path


def capture_checkin_request(port=None, window=None):
    """被动监听所有 page 目标，捕获首个疑似签到 POST 请求，返回端点 dict 或 None。"""
    port = port or wbcommon.DEFAULT_PORT
    if window is None:
        cfg = wbcommon.load_config()
        try:
            window = int(cfg.get("passive_capture_seconds", 60))
        except Exception:
            window = 60
    window = max(5, min(window, 600))

    try:
        targets = wbcommon.cdp_targets(port)
    except Exception:
        return None

    conns = []
    for t in targets:
        if t.get("type") != "page" or not t.get("webSocketDebuggerUrl"):
            continue
        try:
            ws = wbcommon.WebSocket(t["webSocketDebuggerUrl"], timeout=2)
            ws.send_text(json.dumps({"id": 1, "method": "Network.enable", "params": {}}))
            conns.append(ws)
        except Exception:
            continue
    if not conns:
        return None

    deadline = time.time() + window
    try:
        while time.time() < deadline:
            socks = [c._sock for c in conns if getattr(c, "_sock", None)]
            if not socks:
                break
            r, _, _ = select.select(socks, [], [], 1.0)
            for ws in conns:
                if getattr(ws, "_sock", None) not in r:
                    continue
                try:
                    raw = ws.recv_text()
                except Exception:
                    continue
                try:
                    obj = json.loads(raw)
                except Exception:
                    continue
                if obj.get("method") != "Network.requestWillBeSent":
                    continue
                params = obj.get("params", {})
                req = params.get("request", {})
                method = (req.get("method") or "").upper()
                url = req.get("url") or ""
                if method == "POST" and _is_checkin_url(url):
                    api_base, path = split_endpoint(url)
                    header_names = sorted(req.get("headers", {}).keys())
                    return {
                        "api_base": api_base,
                        "path": path,
                        "method": "POST",
                        "header_names": header_names,
                    }
    finally:
        for ws in conns:
            try:
                ws.close()
            except Exception:
                pass
    return None


def learn_endpoint_via_cdp(port=None, window=None):
    """被动抓取签到接口并附加时间戳/来源标记；抓不到返回 None。"""
    ep = capture_checkin_request(port, window)
    if not ep:
        return None
    ep["captured_at"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    ep["captured_from"] = "live_cdp"
    return ep


if __name__ == "__main__":
    log = wbcommon.Logger("sniff")
    ep = learn_endpoint_via_cdp()
    if ep:
        log.log(f"捕获到签到接口: {ep['api_base']}{ep['path']} 头: {ep['header_names']}")
    else:
        log.log("被动抓取未观测到签到请求（客户端未在此窗口内发起签到）。", "WARN")
