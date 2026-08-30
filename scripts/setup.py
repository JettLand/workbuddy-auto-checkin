#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
setup.py —— workbuddy-auto-checkin 一键初始化脚本（实现「一键加载，全自动运行」）

自动完成（新用户友好）：
  0. 环境自检：检测本机是否安装并登录 WorkBuddy、默认配置是否零配置可用
     （跑 `python setup.py --doctor` 可单独查看这份就绪度报告）
  1. 明文模式（默认）：确认可读明文登录态即视为就绪，**不生成任何桌面快捷方式**，
     因为主路径读明文登录态无需调试端口 / .lnk 冷启动。
  2. CDP 模式（可选）：仅当 cdp_fallback_allowed=true 或显式 --cdp 时，
     才生成桌面「WorkBuddy 自动签到.lnk」（带调试参数，用于 CDP 回退取令牌 / 启动即签到）。
  3. 输出初始化报告与后续操作指引（含「下一步：设置每日自动化」）。

用法：
  python setup.py            # 一键初始化（先自检，明文模式不生成 .lnk）
  python setup.py --doctor  # 仅做环境自检，输出就绪度报告，不写任何文件
  python setup.py --cdp     # 生成桌面 .lnk（CDP 回退 / 启动即签到）
  python setup.py --check   # 仅体检，不写文件
  python setup.py --teach   # 【人工诊断】被动捕获；实测常规抓不到，接口请用 calibrate.py --auto

退出码：0=就绪/完成；1=未完成（给出指引）。
"""

import os
import json
import shutil
import socket
import sys
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wbcommon
import sniff
import tokenfile

PORT = wbcommon.DEFAULT_PORT
FLAGS = f"--remote-debugging-port={PORT} --remote-allow-origins=http://127.0.0.1:{PORT}"
DESKTOP = os.path.join(os.path.expanduser("~"), "Desktop")
LNK_NAME = "WorkBuddy 自动签到.lnk"


def _normalized_existing(path):
    """展开变量/用户目录并归一化；文件不存在则返回 None。"""
    if not path:
        return None
    p = os.path.normpath(os.path.expandvars(os.path.expanduser(str(path).strip())))
    return p if os.path.isfile(p) else None


def _configured_exe_path():
    """显式覆盖来源之一：config.json 的 workbuddy_exe_path。"""
    try:
        cfg = wbcommon.load_config()
        return cfg.get("workbuddy_exe_path") or ""
    except Exception:
        return ""


def _persist_exe_path(path, log=None):
    """把显式指定的 exe 路径写入 config.json，使其他终端/后续调用免重复指定。"""
    try:
        cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        if cfg.get("workbuddy_exe_path") != path:
            cfg["workbuddy_exe_path"] = path
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            if log:
                log.log("已将 exe 路径固化到 config.json: {0}".format(path))
    except Exception as e:
        if log:
            log.log("固化 exe 路径失败（不影响本次运行）: {0}".format(e), "WARN")


def find_exe(explicit=None):
    """定位 WorkBuddy.exe（弹性多层查找，适配不同终端/会话/安装位置）。

    优先级（依次尝试，任一层命中即返回）：
      1) 显式覆盖：函数参数 explicit / 环境变量 WORKBUDDY_EXE_PATH /
         config.json 的 workbuddy_exe_path
      2) 共享发现：wbcommon.discover_workbuddy_bases()（覆盖运行中进程、
         注册表卸载项、环境变量安装根、全固定盘符扫描、%LOCALAPPDATA%/Programs）
      3) PATH 兜底（shutil.which）
    所有探测均为容错式，任一层失败不影响其余层。
    """
    import glob
    found = []

    def consider(path):
        p = _normalized_existing(path)
        if p and p not in found:
            found.append(p)

    # 1) 显式覆盖（最高优先级）
    for src in (explicit, os.environ.get("WORKBUDDY_EXE_PATH"), _configured_exe_path()):
        consider(src)

    # 2) 共享发现：基目录 → 候选 exe（复用 wbcommon.discover_workbuddy_bases，
    #    消除与 find_asar 重复的进程/注册表/全盘扫描逻辑）
    for base in wbcommon.discover_workbuddy_bases():
        try:
            for p in glob.glob(os.path.join(base, "*WorkBuddy*", "WorkBuddy.exe")):
                consider(p)
            consider(os.path.join(base, "WorkBuddy", "WorkBuddy.exe"))
        except Exception:
            pass

    # 3) PATH 兜底
    try:
        consider(shutil.which("WorkBuddy.exe"))
    except Exception:
        pass

    return found[0] if found else None


def port_open(port):
    s = socket.socket()
    s.settimeout(1.5)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except Exception:
        return False
    finally:
        s.close()


def ensure_pywin32(log):
    try:
        import win32com.client  # noqa: F401
        return True
    except ImportError:
        pass
    log.log("未检测到 pywin32，尝试自动安装（仅写快捷方式需要）...")
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", "pywin32"],
            capture_output=True, timeout=180,
        )
        if r.returncode == 0:
            try:
                import win32com.client  # noqa: F401
                return True
            except ImportError:
                pass
    except Exception:
        pass
    return False


def create_shortcut(exe, flags, lnk_path, log, description=None, icon=None):
    import pythoncom
    from win32com.shell import shell
    pythoncom.CoInitialize()
    try:
        shortcut = pythoncom.CoCreateInstance(
            shell.CLSID_ShellLink, None,
            pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink,
        )
        shortcut.SetPath(exe)
        shortcut.SetArguments(flags)
        shortcut.SetWorkingDirectory(os.path.dirname(exe))
        shortcut.SetDescription(description or "WorkBuddy（开启 CDP 调试，供自动签到使用）")
        if icon and os.path.isfile(icon):
            shortcut.SetIconLocation(icon, 0)
        persist = shortcut.QueryInterface(pythoncom.IID_IPersistFile)
        persist.Save(lnk_path, 0)
        return True
    except Exception as e:
        log.log(f"写快捷方式失败: {e}", "WARN")
        return False


def read_shortcut_args(lnk_path):
    """读回 .lnk 的目标与参数段，校验是否已指向所需启动器。"""
    try:
        import pythoncom
        from win32com.shell import shell
        pythoncom.CoInitialize()
        shortcut = pythoncom.CoCreateInstance(
            shell.CLSID_ShellLink, None,
            pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink,
        )
        persist = shortcut.QueryInterface(pythoncom.IID_IPersistFile)
        persist.Load(lnk_path, 0)
        raw_target = shortcut.GetPath(shell.SLGP_UNCPRIORITY if hasattr(shell, "SLGP_UNCPRIORITY") else 0)
        # 部分 pywin32 版本 GetPath 返回 (path, flags) 元组，统一取首个字符串元素
        if isinstance(raw_target, (tuple, list)):
            raw_target = raw_target[0] if raw_target else ""
        target = raw_target or ""
        args = shortcut.GetArguments() or ""
        return target, args
    except Exception:
        return "", ""


def _is_current_launcher(launcher):
    """给定路径是否为**本技能当前 scripts 目录**下的 launch_and_checkin.py。"""
    expected = os.path.join(wbcommon.SCRIPTS_DIR, "launch_and_checkin.py")
    try:
        if not launcher or not os.path.isfile(launcher):
            return False
        return os.path.normcase(os.path.abspath(launcher)) == \
               os.path.normcase(os.path.abspath(expected))
    except OSError:
        return False


def shortcut_ok(lnk_path):
    """快捷方式是否已指向**本技能当前目录**下的启动即签到脚本。

    注意：不能只校验文件名。若仅判断 "launch_and_checkin.py" in target，技能目录
    改名后旧 .lnk 仍含该文件名，会被误判为「已就绪」而跳过重建，导致启动即签到
    静默指向已删除的旧路径（2026-08-30 改名时实测踩到）。故须同时校验所在目录。
    """
    target, args = read_shortcut_args(lnk_path)
    if not target and not args:
        return False
    # 新形态：.lnk 指向启动即签到包装脚本 launch_and_checkin.py
    if "launch_and_checkin.py" in target or "launch_and_checkin.py" in args:
        launcher = target if "launch_and_checkin.py" in target else args.strip().strip('"')
        return _is_current_launcher(launcher)
    # 兼容旧形态：.lnk 直接指向 WorkBuddy.exe 且含调试参数
    if "WorkBuddy.exe" in target and f"remote-debugging-port={PORT}" in args \
            and f"remote-allow-origins=http://127.0.0.1:{PORT}" in args:
        return True
    return False


def launcher_uses_pythonw(lnk_path):
    """启动器是否以 pythonw（无控制台窗口）运行启动即签到脚本。"""
    target, _ = read_shortcut_args(lnk_path)
    return "pythonw.exe" in (target or "").lower()


def cmd_teach():
    """C2：一次性被动捕获签到接口并写入 learnings。

    v1.7.7 起定位为**人工诊断命令**，不再用于首次初始化或补录。
    实测（2026-08-29）：WorkBuddy 的签到请求由守护进程发出、不经渲染进程
    网络栈，CDP 网络域无法观测，常规情况下本命令抓不到请求。
    接口请以 `calibrate.py --auto`（asar 主动扫描）为准。
    """
    log = wbcommon.Logger("setup")
    ep = sniff.learn_endpoint_via_cdp()
    if ep:
        learnings = wbcommon.load_learnings()
        learnings["recorded_endpoint"] = ep
        learnings["capture_failures"] = 0
        learnings.pop("next_capture_after", None)
        wbcommon.save_learnings(learnings)
        log.log(f"已捕获并保存签到接口: {ep['api_base']}{ep['path']}（头: {ep['header_names']}）")
        print("OK: 已记录签到接口，后续运行将优先使用。")
        return 0
    log.log("被动抓取未观测到签到请求。", "WARN")
    print("未捕获到签到请求（这是预期结果）。实测 WorkBuddy 的签到请求不经渲染进程，"
          "被动抓取常规抓不到。请使用 `python scripts/calibrate.py --auto` "
          "通过 asar 主动扫描获取接口。")
    return 1


def self_check(log=None, verbose=True):
    """首次使用环境自检：检测 WB 是否安装、是否已登录（明文登录态可读）、默认配置是否够用。

    返回结构化就绪度 dict：
      {os_ok, installed, logged_in, token_len, config_ok, ready, items}
    items 为 [(名称, 状态, 说明), ...]，状态取值 OK / WARN / FAIL。
    """
    import tokenfile as _tf
    log = log or wbcommon.Logger("setup")
    items = []
    # 1) 操作系统
    if sys.platform == "win32":
        items.append(("操作系统", "OK", "Windows（本技能仅支持 Windows）"))
        os_ok = True
    else:
        items.append(("操作系统", "WARN", f"当前 {sys.platform}，本技能仅验证 Windows；明文登录态路径可能不存在"))
        os_ok = False
    # 2) 安装
    exe = find_exe()
    if exe:
        items.append(("WorkBuddy 安装", "OK", exe))
        installed = True
    else:
        cb = os.path.join(os.environ.get("LOCALAPPDATA", ""), "CodeBuddyExtension")
        if os.path.isdir(cb):
            items.append(("WorkBuddy 安装", "OK", f"检测到目录 {cb}（未定位 exe，但不影响明文签到）"))
            installed = True
        else:
            items.append(("WorkBuddy 安装", "FAIL", "未检测到 WorkBuddy/CodeBuddyExtension，请先安装客户端"))
            installed = False
    # 3) 登录态（明文主路径）
    try:
        token, uid, domain = _tf.read_identity(log=log)
    except Exception:
        token, uid, domain = None, "", ""
    if token:
        items.append(("登录态(明文)", "OK", f"已读取令牌(len={len(token)}, uid={uid or '?'}, domain={domain or '?'})"))
        logged_in, token_len = True, len(token)
    else:
        items.append(("登录态(明文)", "FAIL",
                      "未找到明文登录态文件——请先打开并登录 WorkBuddy 客户端（v5.3.8+），"
                      "登录后它会写入本地明文登录态；随后重跑本脚本即可。"))
        logged_in, token_len = False, 0
    # 4) 默认配置
    try:
        cfg = wbcommon.load_config()
        cdp = bool(cfg.get("cdp_fallback_allowed", False))
        dpapi = bool(cfg.get("token_dpapi_enabled", True))
        items.append(("默认配置", "OK",
                      f"明文主路径默认开；CDP 回退默认={'开' if cdp else '关(安全)'}，"
                      f"DPAPI 兜底={'开' if dpapi else '关'}；notify 默认禁用"))
        config_ok = True
    except Exception as e:
        items.append(("默认配置", "WARN", f"读取 config.json 失败: {e}"))
        config_ok = False

    ready = installed and logged_in and config_ok
    if verbose:
        log.log("=== 环境自检 ===")
        mark = {"OK": "✅", "WARN": "⚠️", "FAIL": "❌"}
        for name, status, detail in items:
            log.log(f"  {mark.get(status, '·')} {name}: {detail}")
        if ready:
            log.log("就绪度：✅ 可零配置直接运行签到（无需 .lnk / 调试端口）。")
        else:
            log.log("就绪度：⚠️ 尚未就绪，请先完成上方 ❌ 项后重跑 `python setup.py`。", "WARN")
    return {"os_ok": os_ok, "installed": installed, "logged_in": logged_in,
            "token_len": token_len, "config_ok": config_ok, "ready": ready, "items": items}


def main():
    log = wbcommon.Logger("setup")
    if "--teach" in sys.argv:
        return cmd_teach()
    if "--doctor" in sys.argv:
        self_check(log=log, verbose=True)
        return 0
    dry_run = "--check" in sys.argv

    log.log("=== workbuddy-auto-checkin 一键初始化 ===")

    # 0) 环境自检（新用户友好：先给整体就绪度）
    rep = self_check(log=log, verbose=True)

    # 明文模式判定
    force_cdp = "--cdp" in sys.argv
    cfg_cdp = False
    try:
        cfg_cdp = bool(wbcommon.load_config().get("cdp_fallback_allowed", False))
    except Exception:
        cfg_cdp = False
    cdp_mode = force_cdp or cfg_cdp

    if not cdp_mode:
        # 明文模式：主路径无需 .lnk / 调试端口 / exe
        if rep["ready"]:
            log.log("=== 初始化完成（明文模式，零配置）===")
            log.log("主路径已就绪：读明文登录态即可签到，无需 .lnk / 调试端口 / 手动配置。")
            log.log("下一步：设置每日自动化（00:05 及 09:05/12:05/15:05/18:05/21:05 多时点兜底），"
                    "由本技能自动化任务负责，无需手动。")
            log.log("如需 CDP 回退或「启动即签到」：置 config.cdp_fallback_allowed=true，"
                    "或运行 `python setup.py --cdp`。")
        else:
            log.log("=== 初始化未完成 ===", "WARN")
            log.log("请先完成上方 ❌ 项（通常为：登录 WorkBuddy 客户端），再重跑 `python setup.py`。", "WARN")
        return 0 if rep["ready"] else 1

    # ===== CDP 模式（需要 exe + pywin32 + .lnk）=====
    if dry_run:
        log.log("--check 模式：仅体检，不写文件。")
        return 0
    # 解析可选的显式 exe 路径参数：python setup.py <WorkBuddy.exe路径>
    explicit_exe = None
    for a in sys.argv[1:]:
        if a.startswith("--"):
            continue
        if os.path.isabs(a) or a.lower().endswith(".exe") or "\\" in a or "/" in a:
            explicit_exe = a
            break
    if explicit_exe and not _normalized_existing(explicit_exe):
        log.log("提供的路径不是有效文件，将忽略并自动查找: {0}".format(explicit_exe), "WARN")
        explicit_exe = None
    exe = find_exe(explicit_exe)
    if not exe:
        log.log("CDP 模式需要 WorkBuddy.exe 路径。可手动指定：`python setup.py <WorkBuddy.exe路径>`；"
                "或设置环境变量 WORKBUDDY_EXE_PATH；或在 config.json 写入 workbuddy_exe_path。", "ERROR")
        return 1
    # 固化显式指定的路径，供其他终端/后续调用免重复指定
    if explicit_exe:
        _persist_exe_path(explicit_exe, log=log)
    log.log(f"WorkBuddy 安装路径: {exe}")

    opened = port_open(PORT)
    log.log(f"CDP 端口 {PORT}: {'已监听' if opened else '未监听（正常，用本脚本生成的快捷方式启动后才监听）'}")

    if not ensure_pywin32(log):
        log.log("无法安装 pywin32，将跳过快捷方式创建；可手动按 SKILL.md 指引加启动参数。", "ERROR")
        return 1

    lnk_path = os.path.join(DESKTOP, LNK_NAME)
    wrapper = os.path.join(os.path.dirname(os.path.abspath(__file__)), "launch_and_checkin.py")
    pythonw_candidate = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    python_exe = pythonw_candidate if os.path.isfile(pythonw_candidate) else sys.executable
    wrapper_args = '"{0}"'.format(wrapper)
    if shortcut_ok(lnk_path) and launcher_uses_pythonw(lnk_path):
        log.log(f"桌面启动器已就绪（pythonw + 启动即签到）: {lnk_path}")
    else:
        log.log("生成/更新桌面启动器（启动即签到包装脚本）...")
        if create_shortcut(
            python_exe, wrapper_args, lnk_path, log,
            description="WorkBuddy 启动并自动签到（CDP 调试 + 启动即签到）",
            icon=exe,
        ):
            if shortcut_ok(lnk_path):
                log.log(f"启动器已创建并校验通过: {lnk_path}")
            else:
                log.log("启动器已写入，但参数校验未通过，请手动核对。", "WARN")
        else:
            log.log("启动器创建失败，请手动按 SKILL.md 指引配置。", "ERROR")
            return 1
    log.log("=== 初始化完成（CDP 模式）===")
    log.log("后续：用桌面「WorkBuddy 自动签到」快捷方式启动 WorkBuddy，即可零令牌自动签到。")
    log.log("若客户端升级导致签到失败，运行 calibrate.py 重新校准；若功能被取消，主脚本会自动识别并跳过。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        wbcommon.Logger("setup").log(f"异常: {e}", "ERROR")
        sys.exit(1)
