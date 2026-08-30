#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
calibrate.py —— workbuddy-auto-checkin 自校准脚本（零第三方依赖）

用途：当 WorkBuddy 客户端升级、签到接口路径或令牌获取位置发生变化、甚至取消签到功能时，
      重新扫描本地安装的 app.asar，自动提取最新的关键参数并写回 config.json，
      使 checkin_native.py 无需改代码即可继续工作（自我学习 / 更新迭代）。

扫描内容：
  1. 签到接口路径（/billing/meter/... 等，含 daily-checkin / checkin-status）
  2. API 基地址（https://.../v2）
  3. 令牌获取方法存在性（getToken / getAccessToken），据此调整 token_exprs 优先级
  4. 客户端版本号
  5. 是否仍存在签到相关代码（仅用于探测日志；不再自动写回 feature_removed，
     由主脚本在「已知接口全 404 + 升级检索无产出」时判定功能移除，避免误伤）

用法：
  python calibrate.py            # 自动定位 asar 并校准
  python calibrate.py <asar>     # 指定 asar 路径
  python calibrate.py --check    # 仅探测，不写 config.json
  python calibrate.py --live     # 【人工诊断】被动抓取；实测对 WorkBuddy 常规抓不到，见函数说明
  python calibrate.py --auto      # asar 主动扫描（初始化 / 失败升级走此路；不再自动 live 补录）

退出码：0=成功；1=找不到 asar / 扫描失败 / 被动抓取未命中。
"""

import glob
import json
import mmap
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wbcommon
import sniff


def find_asar(cfg, explicit=None):
    """定位 app.asar（弹性多层查找，适配不同终端/会话/安装位置）。

    优先级（依次尝试，任一层命中即返回）：
      1) 显式覆盖：函数参数 explicit / 环境变量 WORKBUDDY_ASAR_PATH /
         config.json 的 workbuddy_asar_path
      2) config.asar_candidates（可集中维护的候选路径）
      3) 共享发现（wbcommon.discover_workbuddy_bases）：运行中进程、注册表、
         环境变量安装根、全固定盘符扫描 —— 不再硬编码盘符，跨机器/远程会话可用
    所有探测容错，任一层失败不影响其余层。
    """
    found = []

    def consider(path):
        if not path:
            return
        try:
            p = os.path.normcase(os.path.abspath(os.path.expandvars(path)))
        except Exception:
            return
        if os.path.isfile(p) and p not in found:
            found.append(p)

    # 1) 显式覆盖（最高优先级）
    for src in (explicit, os.environ.get("WORKBUDDY_ASAR_PATH"),
                (cfg or {}).get("workbuddy_asar_path")):
        consider(src)

    # 2) config 候选
    for p in list((cfg or {}).get("asar_candidates") or []):
        consider(p)

    # 3) 共享弹性发现（含盘根、Program Files、进程目录、注册表）
    for base in wbcommon.discover_workbuddy_bases():
        consider(os.path.join(base, "resources", "app.asar"))
        try:
            for p in glob.glob(os.path.join(base, "*WorkBuddy*", "resources", "app.asar")):
                consider(p)
        except Exception:
            pass

    return found[0] if found else None


def _has(data, needle):
    """子串是否出现。data 可以是 bytes，也可以是 mmap 对象。

    坑：mmap 对象对 `b"getToken" in mm` 这类**多字节子串**判断会返回 False
    （Python 3.13 实测），但 `mm.find(b"getToken")` 正常。因此统一用 find()，
    避免因改用 mmap 扫描而把 has_get_token / has_checkin_code 全部误判为 False。
    """
    try:
        return data.find(needle) != -1
    except AttributeError:
        return needle in data


def scan_asar(data):
    """从 app.asar 提取关键参数。data 可为 bytes 或 mmap 对象。返回 findings dict。"""
    f = {
        "checkin_paths": [],
        "status_paths": [],
        "api_base": None,
        "has_get_token": _has(data, b"getToken"),
        "has_get_access_token": _has(data, b"getAccessToken"),
        "has_checkin_code": _has(data, b"daily-checkin") or _has(data, b"checkin-status"),
        "version": None,
    }

    # 1) 接口路径：/billing/meter/... 以及含 checkin 的路径
    paths = set()
    for m in re.finditer(rb"/billing/meter/[A-Za-z0-9/_-]+", data):
        p = m.group(0).decode("ascii", "replace")
        if len(p) < 60:
            paths.add(p)
    for p in sorted(paths):
        # 分类：领取接口 vs 状态/活动查询接口，避免把查询接口误当领取接口
        if "status" in p or "activity" in p:
            f["status_paths"].append(p)
        elif "daily-checkin" in p:
            f["checkin_paths"].append(p)
        elif "checkin" in p:
            # 不确定语义的 checkin 路径保守归入状态类
            f["status_paths"].append(p)
    # 兜底：直接用已知关键字
    if _has(data, b"/billing/meter/daily-checkin") and "/billing/meter/daily-checkin" not in f["checkin_paths"]:
        f["checkin_paths"].append("/billing/meter/daily-checkin")
    if _has(data, b"/billing/meter/checkin-status") and "/billing/meter/checkin-status" not in f["status_paths"]:
        f["status_paths"].append("/billing/meter/checkin-status")

    # 2) api_base：找带主机的 /v2 或 copilot.tencent.com
    for m in re.finditer(rb"https?://[A-Za-z0-9.-]+/v2", data):
        base = m.group(0).decode("ascii", "replace")
        if "copilot.tencent.com" in base or "workbuddy" in base:
            f["api_base"] = base
            break
    if not f["api_base"] and _has(data, b"copilot.tencent.com"):
        f["api_base"] = "https://copilot.tencent.com/v2"

    # 3) 版本号：asar 静态提取不可靠（混杂大量依赖版本号/年份），留待调用方经 CDP 获取
    f["version"] = None

    return f


def apply_to_config(cfg, findings, log):
    """把 findings 写回 config，返回 config。"""
    if findings["checkin_paths"]:
        cfg["checkin_paths"] = findings["checkin_paths"]
    if findings["status_paths"]:
        cfg["checkin_status_paths"] = findings["status_paths"]
    if findings["api_base"]:
        cfg["api_base"] = findings["api_base"]

    # 令牌表达式优先级：优先存在的方法
    exprs = cfg.get("token_exprs") or []
    if findings["has_get_token"] and findings["has_get_access_token"]:
        pass  # 保持默认顺序
    elif findings["has_get_token"]:
        pass  # getToken 存在，保持
    elif findings["has_get_access_token"]:
        # 只有 getAccessToken，把 getToken 表达式移除，避免无效尝试
        exprs = [e for e in exprs if "getAccessToken" in e or "getToken" not in e]
        cfg["token_exprs"] = exprs or cfg["token_exprs"]
    # 若两者都找不到，保留原表达式由主脚本运行时再判空

    if findings["version"]:
        cfg["last_calibrated_client_version"] = findings["version"]
    # 注意：feature_removed 不再在此自动持久化（避免 asar 字节误判把自动化永久自关）。
    # 仅在「已知接口全 404 + 升级检索（asar 主动扫描）无产出」双重确认后
    # 由主脚本退出码 4 提示，必要时由人工在 config 手动置 feature_removed=true。
    return cfg


def main():
    log = wbcommon.Logger("calibrate")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry_run = "--check" in sys.argv

    # 模式分发：--live 人工诊断（被动抓取）；--auto 仅 asar 主动扫描（不再自动 live 补录）
    if "--live" in sys.argv:
        return cmd_live(log)
    if "--auto" in sys.argv:
        return cmd_auto(log, args, dry_run)

    # 默认模式：asar 扫描校准
    return _scan_and_apply(log, args, dry_run)


def cmd_live(log):
    """被动抓取签到接口并写入 state/learnings.json（与 config 冗余兜底同步）。

    v1.7.7 起定位为**人工诊断命令**，不再被自动链路调用。
    实测（2026-08-29）：CDP 抓包链路本身正常（渲染进程发出的含关键字 POST 可在 3 秒内
    捕获），但 WorkBuddy 的真实签到请求由守护进程发出、不经渲染进程网络栈，
    因此常规情况下本命令抓不到签到请求。仅建议在人工排障、怀疑架构已变更时使用。
    """
    ep = sniff.learn_endpoint_via_cdp(wbcommon.DEFAULT_PORT)
    if not ep:
        log.log("被动抓取未观测到签到请求（需客户端在监听窗口内发起签到）。"
                "注意：实测 WorkBuddy 的签到请求不经渲染进程，常规情况下本命令抓不到；"
                "端点请以 asar 主动扫描（`--auto`）为准。", "WARN")
        return 1
    learnings = wbcommon.load_learnings()
    learnings["recorded_endpoint"] = ep
    wbcommon.save_learnings(learnings)
    # 同步到 config.json 作为冗余兜底
    cfg = wbcommon.load_config()
    cfg["checkin_paths"] = [ep["path"]] + [p for p in (cfg.get("checkin_paths") or []) if p != ep["path"]]
    cfg["api_base"] = ep["api_base"]
    cfg["feature_removed"] = False
    wbcommon.save_config(cfg)
    log.log(f"已通过 live 抓取保存接口: {ep['api_base']}{ep['path']}（写入 state/learnings.json 与 config.json）")
    return 0


def cmd_auto(log, args, dry_run):
    """仅做 asar 主动扫描（初始化 / 失败升级均走此路）。

    v1.7.7 起不再自动 live 补录。实测（2026-08-29）：签到请求由守护进程
    （main/daemon-app-server-entry.js）的 Node 网络栈发出，不经过渲染进程，
    CDP 网络域无法观测；自动补录只是无收益的 60 秒空等。
    人工诊断请用 `python calibrate.py --live`。
    """
    rc = _scan_and_apply(log, args, dry_run)
    if rc != 0:
        return rc
    cfg = wbcommon.load_config()
    if cfg.get("checkin_paths"):
        return 0
    log.log("asar 扫描未找到接口路径。被动嗅探对 WorkBuddy 实测不可行（签到请求不经渲染"
            "进程网络栈），已不再自动补录；如需人工诊断可运行 `python calibrate.py --live`。",
            "WARN")
    return 1


def _scan_and_apply(log, args, dry_run):
    """原 main 的 asar 扫描与写回逻辑（供 --auto 复用）。返回 0/1。"""
    cfg = wbcommon.load_config()
    asar = args[0] if args else find_asar(cfg)
    if not asar or not os.path.isfile(asar):
        log.log("未找到 app.asar（WorkBuddy 可能未安装或路径变化）。请用 `python calibrate.py <asar路径>` 指定。", "ERROR")
        return 1
    log.log(f"扫描 app.asar: {asar}")
    # 用 mmap 按需分页扫描，而非把整个 asar 读进内存：实测 283MB 的 asar
    # 全量读取峰值内存约 270MB，mmap 可降至 KB 级且更快（0.34s -> 0.18s）。
    # mmap 不可用时回退全量读取，保证兼容性。
    findings = None
    try:
        with open(asar, "rb") as fh:
            with mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as data:
                findings = scan_asar(data)
    except Exception as e:
        log.log(f"mmap 扫描失败（{e}），回退全量读取。", "WARN")
        try:
            with open(asar, "rb") as fh:
                findings = scan_asar(fh.read())
        except Exception as e2:
            log.log(f"读取 asar 失败: {e2}", "ERROR")
            return 1
    try:
        cv = wbcommon.client_version(wbcommon.DEFAULT_PORT)
        if cv and cv != "unknown":
            findings["version"] = cv
    except Exception:
        pass
    log.log(f"客户端版本: {findings['version'] or '未知'}")
    log.log(f"API 基地址: {findings['api_base'] or '未识别'}")
    log.log(f"签到接口路径: {findings['checkin_paths'] or '未识别'}")
    log.log(f"状态接口路径: {findings['status_paths'] or '未识别'}")
    log.log(f"getToken 存在: {findings['has_get_token']}；getAccessToken 存在: {findings['has_get_access_token']}")
    log.log(f"仍存在签到相关代码: {findings['has_checkin_code']}")
    if dry_run:
        log.log("--check 模式：仅探测，不写 config.json。")
        return 0
    cfg = apply_to_config(cfg, findings, log)
    if wbcommon.save_config(cfg):
        log.log(f"已更新 config.json -> {wbcommon.CONFIG_PATH}")
    else:
        log.log("写入 config.json 失败。", "ERROR")
        return 1
    # 主动检索结果同时写入运行配置 learnings.recorded_endpoint（生成的配置，优先于 config 兜底），
    # 使初始化主动检索结果被缓存、后续运行不再重复扫描（跳过守卫生效）。
    if not dry_run and findings["checkin_paths"]:
        _base = findings["api_base"] or cfg.get("api_base")
        _p = findings["checkin_paths"][0]
        if _base and _p:
            try:
                _lk = wbcommon.load_learnings()
                _lk["recorded_endpoint"] = {
                    "api_base": _base,
                    "path": _p,
                    "method": "POST",
                    "header_names": sorted((cfg.get("auth_headers") or {}).keys()),
                    "source": "asar_scan",
                }
                wbcommon.save_learnings(_lk)
                log.log(f"已写入运行配置 recorded_endpoint: {_base}{_p}")
            except Exception as _e:
                log.log(f"写入 recorded_endpoint 失败: {_e}", "WARN")
    if not findings["has_checkin_code"]:
        log.log("⚠ 扫描未检测到签到相关代码（仅提示，不自动置 feature_removed）；如确已取消，请手动设 config.feature_removed=true。", "WARN")
    else:
        log.log("校准完成。主脚本 checkin_native.py 将按新配置运行。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        wbcommon.Logger("calibrate").log(f"异常: {e}", "ERROR")
        sys.exit(1)
