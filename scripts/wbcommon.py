#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wbcommon.py —— workbuddy-auto-checkin 公共核心模块（零第三方依赖）

提供：
  1. 日志（同时输出到 stdout 与文件，按天滚动）
  2. config.json 的加载 / 保存（把易变的接口路径、令牌表达式外置，供 calibrate 更新）
  3. 标准库实现的极简 WebSocket 客户端（用于 CDP，免去 websocket-client 依赖）
  4. CDP 帮助函数（列目标、求值）
  5. 运行结果反馈（写入 state/last_result.json，供自动化/用户查询）
  6. 客户端版本读取

所有函数仅依赖 Python 标准库，确保任何 Python 3.8+ 环境开箱即用。
"""

import base64
import hashlib
import json
import os
import socket
import struct
import sys
import urllib.parse
import urllib.request
import datetime
import subprocess
import glob
import shutil

# ---------------------------------------------------------------------------
# 路径常量
# ---------------------------------------------------------------------------
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 技能根目录
SCRIPTS_DIR = os.path.join(SKILL_DIR, "scripts")
CONFIG_PATH = os.path.join(SCRIPTS_DIR, "config.json")
STATE_DIR = os.environ.get("WORKBUDDY_CHECKIN_STATE_DIR") or os.path.join(SKILL_DIR, "state")
LOGS_DIR = os.path.join(SKILL_DIR, "logs")
STATE_FILE = os.path.join(STATE_DIR, ".last_checkin")           # 幂等状态：最近成功签到日期
RESULT_FILE = os.path.join(STATE_DIR, "last_result.json")       # 最近一次运行的结构化结果
LEARNINGS_FILE = os.path.join(STATE_DIR, "learnings.json")      # 运行时被动抓取到的接口记录（机器专属，不入包）


# ---------------------------------------------------------------------------
# WorkBuddy 安装位置弹性发现（setup.find_exe / calibrate.find_asar 共用）
# ---------------------------------------------------------------------------
def _ps_cmd(cmd):
    """包装 PowerShell 命令，强制 UTF-8 输出（避免中文系统 GBK 解码截断进程路径）。"""
    return ["powershell", "-NoProfile", "-NonInteractive", "-Command",
            "$OutputEncoding=[System.Text.Encoding]::UTF8; "
            "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; " + cmd]


def _run_ps(cmd, timeout=15):
    """运行 PowerShell 并返回 stdout 文本（UTF-8 容错解码）；失败返回空串。"""
    try:
        r = subprocess.run(_ps_cmd(cmd), capture_output=True, timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = r.stdout or b""
        try:
            return out.decode("utf-8")
        except UnicodeDecodeError:
            return out.decode("utf-8", "replace")
    except Exception:
        return ""


def _fixed_drives():
    """返回所有固定磁盘盘符根目录（如 ['C:\\', 'D:\\']）；探测失败兜底 C:\\。"""
    drives = []
    try:
        out = _run_ps("(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3').DeviceID")
        for line in out.splitlines():
            d = line.strip()
            if d:
                drives.append(d if d.endswith("\\") else d + "\\")
    except Exception:
        pass
    if not drives:
        drives = ["C:\\"]
    return drives


def discover_workbuddy_bases():
    """弹性发现 WorkBuddy 可能安装的基目录（去重，normcase 归一便于跨盘符比较）。

    覆盖：运行中进程目录、注册表卸载项 InstallLocation、环境变量安装根
    （不硬编码盘符）、全固定盘符扫描、%LOCALAPPDATA%/Programs。
    供 setup.find_exe 与 calibrate.find_asar 复用，消除盘符硬编码导致的跨终端定位失败。
    所有探测容错，任一层失败不影响其余层。
    """
    bases = []
    seen = set()

    def add(p):
        if not p:
            return
        p = os.path.normcase(os.path.abspath(p))
        if p not in seen:
            seen.add(p)
            bases.append(p)

    # 1) 运行中进程目录（最可靠，跨任意安装位置）
    try:
        out = _run_ps("Get-Process WorkBuddy -ErrorAction SilentlyContinue | "
                      "Select-Object -ExpandProperty Path")
        for line in out.splitlines():
            line = line.strip()
            if line and line.lower().endswith("workbuddy.exe"):
                add(os.path.dirname(line))
    except Exception:
        pass

    # 2) 注册表卸载项 InstallLocation
    try:
        import winreg
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for sub in (r"Software\Microsoft\Windows\CurrentVersion\Uninstall",
                        r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"):
                try:
                    key = winreg.OpenKey(hive, sub)
                except Exception:
                    continue
                for i in range(winreg.QueryInfoKey(key)[0]):
                    try:
                        subkey = winreg.OpenKey(key, winreg.EnumKey(key, i))
                        name, _ = winreg.QueryValueEx(subkey, "DisplayName")
                        if "WorkBuddy" in name:
                            loc, _ = winreg.QueryValueEx(subkey, "InstallLocation")
                            add(loc)
                    except Exception:
                        continue
    except Exception:
        pass

    # 3) 环境变量安装根（不硬编码盘符）
    for env in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432",
                "LOCALAPPDATA", "APPDATA", "ProgramData"):
        v = os.environ.get(env)
        if v:
            add(v)
            add(os.path.join(v, "Programs"))

    # 4) 全固定盘符扫描（覆盖任意盘符的 Program Files / 盘根 WorkBuddy）
    for drive in _fixed_drives():
        add(os.path.join(drive, "Program Files"))
        add(os.path.join(drive, "Program Files (x86)"))
        add(drive)  # 盘根直接放 WorkBuddy 目录

    return bases

DEFAULT_PORT = int(os.environ.get("WORKBUDDY_CDP_PORT", "9222"))

# ---------------------------------------------------------------------------
# 默认配置（config.json 不存在时使用；calibrate.py 会据此生成/更新）
# ---------------------------------------------------------------------------
DEFAULT_CONFIG = {
    "api_base": "https://copilot.tencent.com/v2",
    "checkin_paths": ["/billing/meter/daily-checkin"],
    "checkin_status_paths": ["/billing/meter/checkin-status"],
    "auth_headers": {
        "X-Domain": "www.workbuddy.cn",
        "Content-Type": "application/json",
    },
    # 令牌获取表达式（按优先级逐个尝试，均须返回 string 令牌）
    "token_exprs": [
        "window.__GENIE_DEFAULT_APP_PROVIDERS__ && window.__GENIE_DEFAULT_APP_PROVIDERS__.auth && typeof window.__GENIE_DEFAULT_APP_PROVIDERS__.auth.getToken === 'function' ? await window.__GENIE_DEFAULT_APP_PROVIDERS__.auth.getToken() : null",
        "window.__GENIE_DEFAULT_APP_PROVIDERS__ && window.__GENIE_DEFAULT_APP_PROVIDERS__.auth && typeof window.__GENIE_DEFAULT_APP_PROVIDERS__.auth.getAccessToken === 'function' ? await window.__GENIE_DEFAULT_APP_PROVIDERS__.auth.getAccessToken() : null",
    ],
    "uid_expr": "window.__genieAccountService && window.__genieAccountService.account && window.__genieAccountService.account.uid || null",
    "domain_expr": "window.__genieAccountService && window.__genieAccountService.account && window.__genieAccountService.account.domain || null",
    "default_uid": "",   # 脱敏：留空，运行时经 uid_expr 从客户端动态获取
    "default_domain": "www.workbuddy.cn",
    "asar_candidates": [],
    "last_calibrated_client_version": None,
    "feature_removed": False,   # 校准后仍找不到签到接口时置 True，主脚本据此快速短路
    "passive_capture_seconds": 60,  # 被动抓取签到接口的监听窗口（秒）
}


# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------
class Logger:
    def __init__(self, name="workbuddy-auto-checkin"):
        self.name = name
        self._log_file = None
        self._ensure_dirs()

    def _ensure_dirs(self):
        for d in (LOGS_DIR, STATE_DIR):
            try:
                os.makedirs(d, exist_ok=True)
            except Exception:
                pass

    def _open_log(self):
        if self._log_file is None:
            try:
                path = os.path.join(LOGS_DIR, "checkin.log")
                # 按大小轮转（C1）：超过 1MB 时备份为 .1 并新建，避免日志无限增长
                try:
                    if os.path.exists(path) and os.path.getsize(path) > 1_000_000:
                        backup = path + ".1"
                        if os.path.exists(backup):
                            os.remove(backup)
                        os.rename(path, backup)
                except Exception:
                    pass
                self._log_file = open(path, "a", encoding="utf-8")
            except Exception:
                self._log_file = None
        return self._log_file

    def log(self, msg, level="INFO"):
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}][{level}][{self.name}] {msg}"
        # 窗口less 运行（pythonw）时 sys.stdout 为 None，需安全降级，仅写文件
        try:
            if sys.stdout is not None:
                print(line, flush=True)
        except Exception:
            pass
        f = self._open_log()
        if f:
            try:
                f.write(line + "\n")
                f.flush()
            except Exception:
                pass

    def close(self):
        if self._log_file:
            try:
                self._log_file.close()
            except Exception:
                pass
            self._log_file = None


# ---------------------------------------------------------------------------
# config.json
# ---------------------------------------------------------------------------
def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # 深拷贝默认
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            user = json.load(f)
        if isinstance(user, dict):
            cfg.update(user)
    except FileNotFoundError:
        pass
    except Exception:
        pass
    return cfg


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 运行时自学习记录（被动抓取到的接口，机器专属，不入上传包）
# ---------------------------------------------------------------------------
def load_learnings():
    """读取 state/learnings.json；不存在或损坏时返回空字典。"""
    try:
        with open(LEARNINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_learnings(data):
    """写入 state/learnings.json。失败静默返回 False。"""
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(LEARNINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 结果反馈
# ---------------------------------------------------------------------------
def write_result(status, message="", exit_code=0, extra=None):
    """把本次运行结果写入 state/last_result.json，便于自动化/用户查询。"""
    result = {
        "timestamp": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": status,
        "message": message,
        "exit_code": exit_code,
    }
    if extra:
        result.update(extra)
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(RESULT_FILE, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return result


def read_last_result():
    try:
        with open(RESULT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 幂等状态
# ---------------------------------------------------------------------------
def today_str():
    return datetime.date.today().strftime("%Y-%m-%d")


def is_checked_today():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return f.read().strip() == today_str()
    except Exception:
        return False


def mark_checked_today():
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            f.write(today_str())
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# v2.0.0：无人值守判定 / 失败分类 / 当日放弃标记 / CDP 回退待决标记
# ---------------------------------------------------------------------------
def is_unattended():
    """是否无人值守（自动化 / 定时任务 / 非交互终端）。

    优先级：环境变量显式标记 > sys.stdin.isatty()。
    无人值守时**绝不弹出询问**——没有用户可应答。
    """
    flag = (os.environ.get("WORKBUDDY_CHECKIN_UNATTENDED") or "").strip().lower()
    if flag in ("1", "true", "yes"):
        return True
    if flag in ("0", "false", "no"):
        return False
    try:
        return not sys.stdin.isatty()
    except Exception:
        return True   # 取不到终端状态时按无人值守处理，避免误阻塞


def _marker_path(kind):
    return os.path.join(STATE_DIR, f"{kind}_{today_str()}")


def mark_gave_up_today(reason=""):
    """标记「当日放弃」：终止性失败后写入；同日再跑立即跳过，跨日自动失效。"""
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(_marker_path("gave_up"), "w", encoding="utf-8") as f:
            json.dump({"date": today_str(), "reason": reason,
                       "ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds")},
                      f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def gave_up_today():
    """今日是否已因终止性失败放弃（跨日自动失效）。"""
    return os.path.isfile(_marker_path("gave_up"))


def write_pending_cdp_consent(reason=""):
    """无人值守且未预先授权时留下「待决」提示，待用户上线后决策。

    与 feature_removed 不同：本标记**按日期**，次日自动失效，绝不永久关闭。
    """
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(_marker_path("pending_cdp_consent"), "w", encoding="utf-8") as f:
            json.dump({"date": today_str(), "reason": reason, "need": "cdp_fallback",
                       "ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds")},
                      f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def read_pending_cdp_consent():
    """读取今日待决的 CDP 回退请求（跨日自动失效）。"""
    p = _marker_path("pending_cdp_consent")
    if not os.path.isfile(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def clear_pending_cdp_consent():
    try:
        os.remove(_marker_path("pending_cdp_consent"))
        return True
    except Exception:
        return False


def write_pending_user_decision(reason="", attempts=0, last_exit_code=None):
    """重试耗尽（或其它需人工判断的持续失败）后留下**待用户决策**提示。

    与 gave_up 的区别（重要）：
      - gave_up          = 已确认「签到活动取消」→ 当日放弃、不再尝试
      - pending_user_decision = 只是**试到上限仍未成功**，原因未明 → **不替用户做放弃决定**，
        留提示交用户判断（活动是否真取消？是否要改配置？是否手动补签？）
    同样按日期存储，跨日自动失效。
    """
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(_marker_path("pending_user_decision"), "w", encoding="utf-8") as f:
            json.dump({"date": today_str(), "reason": reason, "attempts": attempts,
                       "last_exit_code": last_exit_code, "need": "user_decision",
                       "ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds")},
                      f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def read_pending_user_decision():
    p = _marker_path("pending_user_decision")
    if not os.path.isfile(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def clear_pending_user_decision():
    try:
        os.remove(_marker_path("pending_user_decision"))
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 极简 WebSocket 客户端（标准库，用于 CDP）
# ---------------------------------------------------------------------------
class WebSocket:
    def __init__(self, url, timeout=10):
        u = urllib.parse.urlparse(url)
        host = u.hostname or "127.0.0.1"
        port = u.port or 80
        path = u.path or "/"
        if u.query:
            path += "?" + u.query
        self._sock = socket.create_connection((host, port), timeout=timeout)
        self._sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            f"Origin: http://{host}:{port}\r\n"
            "\r\n"
        )
        self._sock.sendall(req.encode("ascii"))
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = self._sock.recv(4096)
            if not chunk:
                break
            resp += chunk
        status_line = resp.split(b"\r\n", 1)[0]
        if b"101" not in status_line:
            raise RuntimeError("WebSocket 握手失败: " + status_line.decode("ascii", "replace"))
        self._buf = b""

    def _read_exact(self, n):
        while len(self._buf) < n:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise RuntimeError("WebSocket 连接被关闭")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _send_frame(self, opcode, payload: bytes):
        mask = os.urandom(4)
        header = bytearray()
        header.append(0x80 | opcode)
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self._sock.sendall(bytes(header) + mask + masked)

    def send_text(self, s):
        self._send_frame(0x1, s.encode("utf-8"))

    def _recv_frame(self):
        """返回 (opcode, payload)，自动处理分片与 ping/pong。"""
        opcode = None
        payload = b""
        while True:
            b0, b1 = self._read_exact(2)
            fin = b0 & 0x80
            op = b0 & 0x0F
            masked = b1 & 0x80
            length = b1 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._read_exact(8))[0]
            mask_key = self._read_exact(4) if masked else None
            data = self._read_exact(length)
            if mask_key:
                data = bytes(b ^ mask_key[i % 4] for i, b in enumerate(data))
            if op == 0x8:        # close
                raise RuntimeError("WebSocket 收到关闭帧")
            if op == 0x9:        # ping -> pong
                self._send_frame(0xA, data)
                continue
            if op == 0xA:        # pong
                continue
            if opcode is None:
                opcode = op
            payload += data
            if fin:
                return opcode, payload

    def recv_text(self):
        while True:
            opcode, payload = self._recv_frame()
            if opcode == 0x1:
                return payload.decode("utf-8", "replace")
            # 0x2 二进制、0x0 分片续帧等：继续

    def close(self):
        try:
            self._sock.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# CDP 帮助函数
# ---------------------------------------------------------------------------
def http_get_json(port, path, timeout=5):
    url = f"http://127.0.0.1:{port}{path}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def cdp_targets(port):
    return http_get_json(port, "/json/list", timeout=5)


def cdp_page_target(port):
    for t in cdp_targets(port):
        if t.get("type") == "page":
            return t
    return None


def cdp_evaluate(port, expression, await_promise=False, timeout=10):
    """连到第一个 page 目标，执行 JS 表达式，返回 result.value 或 None。"""
    page = cdp_page_target(port)
    if not page or not page.get("webSocketDebuggerUrl"):
        return None
    ws = WebSocket(page["webSocketDebuggerUrl"], timeout=timeout)
    mid = 1
    try:
        ws.send_text(json.dumps({"id": mid, "method": "Runtime.enable", "params": {}}))
        mid += 1
        ws.send_text(json.dumps({
            "id": mid,
            "method": "Runtime.evaluate",
            "params": {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": await_promise,
            },
        }))
        import time
        end = time.time() + timeout
        while time.time() < end:
            raw = ws.recv_text()
            try:
                obj = json.loads(raw)
            except Exception:
                continue
            if obj.get("id") == mid:
                return obj.get("result", {}).get("result", {}).get("value")
        return None
    finally:
        ws.close()


def cdp_version(port):
    return http_get_json(port, "/json/version", timeout=5)


def extract_client_version(ua):
    """从 CDP User-Agent 字符串提取 WorkBuddy 版本号（如 5.3.14）；失败返回 None。无网络调用。"""
    import re
    if not ua:
        return None
    m = re.search(r"WorkBuddy/([\d.]+)", ua)
    return m.group(1) if m else None


def client_version(port):
    """从 CDP /json/version 提取 WorkBuddy 版本号（如 5.3.14）。"""
    try:
        v = cdp_version(port)
        return extract_client_version(v.get("User-Agent", ""))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 幂等短路（供主脚本在发起请求前调用）
# ---------------------------------------------------------------------------
def early_skip_if_checked(log):
    if is_checked_today():
        t = today_str()
        log.log(f"今日({t})已签到（本地状态），跳过。")
        write_result("skipped", f"今日({t})已签到，跳过", exit_code=0)
        return True
    return False
