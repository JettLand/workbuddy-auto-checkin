#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
launch_and_checkin.py —— WorkBuddy「启动即签到」启动器

用于实现触发方式一：**每次启动 WorkBuddy 时，检测是否已签到，未签到则签到**。

调试参数（--remote-debugging-port / --remote-allow-origins）由本脚本内 FLAGS 常量统一保管，
经 pythonw 无窗口调用；因此 .lnk 指向本脚本而非直接写死参数，避免参数被误改、并保证单一来源。

行为：
  - 若 CDP 调试端口已就绪（WorkBuddy 已在运行且带调试参数），跳过启动，直接等待就绪后签到；
  - 若 WorkBuddy 未运行，直接以调试参数冷启动（经 .lnk / ShellExecute，父进程为 explorer）；
    轮询 CDP 端口就绪后执行一次签到；
  - 若 WorkBuddy 已在运行但未带调试参数：本启动器**不再**自动重启（该能力已于 v1.5.0
    从代码移除，原历史文档 `docs/relaunch_reference.md` 亦已删除）；仅记录提示，请用户
    通过桌面「WorkBuddy 自动签到」.lnk 冷启动以带调试参数运行。
  - 无论是否已签到，签到脚本均幂等（今日已签到自动跳过），不会重复领取。

注意：启动器经 pythonw 以**无窗口**方式运行（不弹命令行窗口）。WorkBuddy 以 DETACHED_PROCESS
方式启动，作为独立进程存活，结束本启动器不会误杀 WorkBuddy。仅当签到遇到需要用户处理的异常
（如鉴权失效、功能疑似取消）时，才弹出 Windows 消息框提示；正常运行与「已签到」均保持静默。
"""

import os
import sys
import time
import ctypes
import subprocess
import urllib.request
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wbcommon

PORT = wbcommon.DEFAULT_PORT
FLAGS = "--remote-debugging-port={0} --remote-allow-origins=http://127.0.0.1:{0}".format(PORT)
# DETACHED_PROCESS 仅用于 wait/check 等子进程，不再用于启动 WorkBuddy 本身
DETACHED = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


def launch_workbuddy_via_shell(exe, log, context=""):
    """通过 ShellExecute 启动 WorkBuddy（带调试参数）。

    context 用于区分启动来源，便于在日志里标记：
      - "【手动启动】"：由主流程在 WB 未运行时直接冷启动（对应桌面「WorkBuddy 自动签到」.lnk）；
      - 空字符串：其它 / 未知来源。
    """
    prefix = ("{0} ".format(context)) if context else ""
    try:
        import win32api
        # ShellExecute(0, "open", exe, 参数, 工作目录, 显示方式)
        # 由 shell 派发，新进程父进程为 explorer，调试参数被正常接受
        h = win32api.ShellExecute(0, "open", exe, FLAGS, os.path.dirname(exe), 1)
        log.log("{0}已通过 ShellExecute 以调试参数启动 WorkBuddy（hInst={1}）。".format(prefix, h))
        return True
    except Exception as e:
        log.log("{0}ShellExecute 启动失败: {1}".format(prefix, e), "ERROR")
        # 兜底：win32api 不可用时退回 subprocess（可能失败，会由后续 CDP 检测发现）
        try:
            subprocess.Popen([exe] + FLAGS.split(), cwd=os.path.dirname(exe),
                             creationflags=DETACHED, close_fds=True)
            log.log("{0}已通过 subprocess 兜底启动 WorkBuddy（注意：参数可能被拒）。".format(prefix), "WARN")
            return True
        except Exception as e2:
            log.log("{0}兜底启动也失败: {1}".format(prefix, e2), "ERROR")
            return False


def notify(title, message):
    """弹出 Windows 消息框（仅用于需要用户关注的结果；无控制台环境亦可工作）。"""
    try:
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x40)
    except Exception:
        pass


def cdp_ready():
    try:
        urllib.request.urlopen("http://127.0.0.1:{0}/json/version".format(PORT), timeout=2)
        return True
    except Exception:
        return False


def is_workbuddy_running():
    """粗略判断是否已有 WorkBuddy 进程在运行（避免重复启动造成双开）。

    注意：用 capture_output（字节）并手动以 errors="replace" 解码，避免中文 Windows
    （cp936/GBK）下 text=True 触发 subprocess 读取线程的 UnicodeDecodeError（会被
    except 吞掉并误判为未运行，进而重复拉起被单实例机制吸收的伪实例）。
    """
    try:
        r = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq WorkBuddy.exe"],
            capture_output=True, timeout=10,
        )
        out = r.stdout or b""
        out = out.decode("utf-8", "replace") if isinstance(out, bytes) else out
        return "WorkBuddy.exe" in out
    except Exception:
        return False



def find_exe():
    try:
        import setup
        return setup.find_exe()
    except Exception:
        return None


def main():
    log = wbcommon.Logger("launch")
    log.log("=== WorkBuddy 启动即签到 ===")

    exe = find_exe()
    launched = False
    running_without_debug = False
    if not exe:
        log.log("未定位到 WorkBuddy.exe，跳过启动（若已手动运行，将直接尝试签到）。", "WARN")
    else:
        if cdp_ready():
            log.log("【手动启动】CDP 端口已就绪（WorkBuddy 已在运行且带调试参数），跳过启动步骤。")
        elif is_workbuddy_running():
            # 自动重启（kill + 带参重启）已停用（v1.5.0 起从代码移除）。
            # WB 已在运行但未带调试参数时，无法启用 CDP；仅记录提示，请用户通过桌面
            # 「WorkBuddy 自动签到」.lnk 冷启动以带调试参数运行，从而启用每日签到。
            running_without_debug = True
            log.log("【手动启动】检测到 WorkBuddy 已在运行但未带调试参数；自动重启已停用，"
                    "请完全关闭后通过桌面「WorkBuddy 自动签到」快捷方式冷启动以启用签到。", "WARN")
        else:
            log.log("【手动启动】以调试参数启动 WorkBuddy: {0}".format(exe))
            launched = launch_workbuddy_via_shell(exe, log, "【手动启动】")

    # 仅在「刚冷启动」时轮询等待 CDP 就绪；其余情况不空等
    ready = cdp_ready()
    if (launched or running_without_debug) and not ready:
        for _ in range(45):
            if cdp_ready():
                ready = True
                break
            time.sleep(1)
    if not ready:
        log.log("CDP 未就绪；直接尝试签到（若客户端未运行将优雅跳过）。", "WARN")

    # 执行幂等签到（sys.executable 在 pythonw 下为 pythonw.exe，同样无控制台窗口）
    native = os.path.join(os.path.dirname(os.path.abspath(__file__)), "checkin_native.py")
    try:
        r = subprocess.run([sys.executable, native], timeout=120)
        rc = r.returncode
        log.log("签到脚本退出码: {0}".format(rc))
        # 仅对需要用户关注的异常弹窗提示；成功 / 已签 / 预期跳过保持静默
        if rc == 1:
            notify("WorkBuddy 每日签到",
                   "今日签到失败：会话鉴权失效（401）。请重新登录 WorkBuddy 客户端后重试。")
        elif rc == 2 and running_without_debug:
            notify("WorkBuddy 每日签到",
                   "WorkBuddy 已在运行但未带调试参数，无法执行签到。请完全关闭 WorkBuddy 后，"
                   "通过桌面「WorkBuddy 自动签到」快捷方式冷启动。")
        elif rc == 2 and launched and not ready:
            notify("WorkBuddy 每日签到",
                   "已启动 WorkBuddy，但调试端口未能就绪，签到未执行。请确认通过「WorkBuddy 自动签到」"
                   "快捷方式启动，或检查 WorkBuddy 调试端口后重试。")
        elif rc == 4:
            notify("WorkBuddy 每日签到",
                   "签到接口疑似已失效或功能被取消，已自动跳过。若为误判，可运行 calibrate.py 重新校准。")
        elif rc == 3:
            notify("WorkBuddy 每日签到",
                   "签到过程中发生异常，请查看技能 logs/checkin.log 排查。")
        return rc
    except Exception as e:
        log.log("执行签到脚本失败: {0}".format(e), "ERROR")
        notify("WorkBuddy 每日签到", "启动签到脚本失败，请查看日志排查：{0}".format(e))
        return 3


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        wbcommon.Logger("launch").log("异常: {0}".format(e), "ERROR")
        sys.exit(1)
