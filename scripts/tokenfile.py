#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""读取 WorkBuddy v5.3.8+ 明文登录态（无需 CDP / 调试端口 / .lnk 冷启动）。

背景：
  WorkBuddy v5.3.8+ 桌面端会把登录态写成**明文 JSON 文件**，纯标准库即可读取，
  无需 CDP、无需调试端口、客户端未运行也能读（只要近期运行过并刷新过）。

路径：
  默认枚举：平台根 × 产品目录(CodeBuddyExtension / CodeBuddy / WorkBuddy / …) ×
            子路径(Data/Public/auth、Data/User/auth、Data/auth、User/auth) × 文件名。
  显式覆盖（最高优先级）：环境变量 WORKBUDDY_LOGIN_STATE_PATH 或 config.json 的
            token_file_paths（均为完整文件路径），用于便携版 / 自定义安装 / 未来换落点。
  Windows 旧说明：%LOCALAPPDATA% 优先，%APPDATA% 保留为回退（第三方曾因只探 APPDATA 漏读）。

结构：
  {
    "account": {"uid": ..., "nickname": ..., ...},
    "auth":    {"accessToken": ..., "refreshToken": ..., "expiresAt": <ms>,
                "domain": ..., "tokenType": ...},
    "accounts": [...], "allAccounts": [...]
  }

安全约定（红线）：
  - 令牌**只在内存中传递**，由调用方立即用于官方签到请求。
  - **绝不落盘、绝不写入日志、绝不回显到终端**；日志只记录令牌**长度**。
  - 本模块不发起任何网络请求。

依赖：仅 Python 标准库（json / os / sys / time）。
"""

import base64
import json
import os
import sys
import time

# 产品目录名候选（覆盖不同版本/渠道的命名差异）
_PRODUCT_DIRS = ["CodeBuddyExtension", "CodeBuddy", "WorkBuddy", "Tencent-Cloud.coding-copilot"]
# 登录态相对子路径候选（覆盖 Data/Public、Data/User、Data、User 等布局）
_SUB_DIRS = [
    ("Data", "Public", "auth"),
    ("Data", "User", "auth"),
    ("Data", "auth"),
    ("User", "auth"),
]
DEFAULT_NAMES = ["workbuddy-desktop.info", "Tencent-Cloud.coding-copilot.info"]


def candidates(names=None, extra_paths=None):
    """明文登录态候选路径（按优先级，去重保序）。

    顺序：
      1) 显式覆盖（最高）：环境变量 WORKBUDDY_LOGIN_STATE_PATH
         （多路径用 os.pathsep 分隔）与 extra_paths（来自 config.json 的
         token_file_paths 列表）——用于便携版 / 自定义安装 / 未来版本换落点。
      2) 平台根 + (产品目录 × 子路径 × 文件名) 的全组合枚举。
    """
    names = list(names or DEFAULT_NAMES)
    out = []

    # 1) 显式覆盖
    explicit = []
    env_paths = os.environ.get("WORKBUDDY_LOGIN_STATE_PATH")
    if env_paths:
        explicit.extend(x for x in env_paths.split(os.pathsep) if x.strip())
    if extra_paths:
        explicit.extend(extra_paths)
    for p in explicit:
        p = p.strip()
        if p and p not in out:
            out.append(p)

    # 2) 平台根 + (产品目录 × 子路径 × 文件名)
    home = os.path.expanduser("~")
    roots = []
    if sys.platform == "darwin":
        roots.append(os.path.join(home, "Library", "Application Support"))
    elif sys.platform == "win32":
        # 实测当前桌面端写在 LOCALAPPDATA；APPDATA 保留为回退
        for env in ("LOCALAPPDATA", "APPDATA"):
            v = os.environ.get(env)
            if v:
                roots.append(v)
    else:
        roots.append(os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config"))
    roots.append(home)  # 最后兜底

    for r in roots:
        for prod in _PRODUCT_DIRS:
            for sub in _SUB_DIRS:
                for n in names:
                    p = os.path.join(r, prod, *sub, n)
                    if p not in out:
                        out.append(p)
    return out


def read_identity(names=None, extra_paths=None, log=None):
    """读取明文登录态，返回 (token, uid, domain)；失败返回 (None, "", "")。

    不抛异常：任何解析/缺失问题都退化为「未取到」，交由上层走回退闸门。
    extra_paths：显式覆盖路径（来自 config.json token_file_paths），最高优先级。
    """
    for p in candidates(names, extra_paths=extra_paths):
        if not os.path.isfile(p):
            continue
        try:
            with open(p, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as e:
            if log:
                log.log(f"登录态文件解析失败（跳过该候选）{p}: {e}", "WARN")
            continue

        auth = (data or {}).get("auth") or {}
        acct = (data or {}).get("account") or {}
        token = auth.get("accessToken")
        if not token or not isinstance(token, str) or not token.strip():
            if log:
                log.log(f"登录态文件缺少有效 accessToken（跳过该候选）: {p}", "WARN")
            continue

        uid = str(acct.get("uid") or "")
        domain = str(auth.get("domain") or acct.get("domain") or "")

        # 过期仅提示、不阻断：最终由服务端判定，客户端运行后会自动刷新
        exp = auth.get("expiresAt")
        try:
            if isinstance(exp, (int, float)) and exp > 0 and (exp / 1000.0) < time.time():
                if log:
                    log.log("明文登录态中的 accessToken 已过 expiresAt；"
                            "请打开 WorkBuddy 客户端以刷新登录态。", "WARN")
        except Exception:
            pass

        if log:
            # 安全：只记长度与文件名，绝不记令牌内容
            log.log(f"已由明文登录态取得令牌（len={len(token)}），来源={os.path.basename(p)}")
        return token, uid, domain

    return None, "", ""


# ── DPAPI 兜底：解密旧版 Chromium 系加密登录态（仅 Windows）─────────────────
# 适用场景：WorkBuddy 旧版（v5.3.8 之前）把令牌存在
#   - `Local State`：含 DPAPI 加密的 os_crypt 主密钥
#   - `User\globalStorage\state.vscdb`：SQLite，AES-GCM 加密的令牌
# 当明文登录态文件缺失、但旧存储尚在时，可回退解密，扩大兼容性。
# DPAPI 调用走 ctypes（标准库即可）；AES-GCM 需 cryptography 库，缺失时惰性安装一次。
# 安全红线同明文路径：令牌仅内存传递、绝不落盘/写日志/回显，日志只记长度。

_DPAPI_TOKEN_KEY = r'secret://{"extensionId":"tencent-cloud.coding-copilot","key":"planning-genie.new.accessTokencn"}'


def _dpapi_unprotect(data):
    """Windows DPAPI CryptUnprotectData 解密。data 为字节，返回明文字节。"""
    import ctypes
    import ctypes.wintypes
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    class _BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    blob_in = _BLOB()
    blob_in.cbData = len(data)
    blob_in.pbData = ctypes.create_string_buffer(data, len(data))
    blob_out = _BLOB()
    if not crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, None, None,
                                       None, 0, ctypes.byref(blob_out)):
        raise OSError(f"CryptUnprotectData 失败，错误码 {ctypes.GetLastError()}")
    out = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    kernel32.LocalFree(blob_out.pbData)
    return out


def _ensure_cryptography(log=None):
    """惰性导入 cryptography（AES-GCM）。缺失时尝试一次性 pip 安装；返回构造器或 None。"""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        return AESGCM
    except Exception:
        pass
    try:
        if log:
            log.log("未找到 cryptography 库，尝试一次性安装（DPAPI 兜底所需）...", "WARN")
        import subprocess
        import sys
        subprocess.check_call([sys.executable, "-m", "pip", "install",
                               "--quiet", "cryptography"])
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        if log:
            log.log("cryptography 安装成功，DPAPI 兜底可用。")
        return AESGCM
    except Exception as e:
        if log:
            log.log(f"cryptography 安装/导入失败，DPAPI 兜底不可用：{e}", "WARN")
        return None


def dpapi_available(log=None):
    """快速探测 DPAPI 兜底是否可用（平台 + 旧存储文件存在）。不执行完整读取。"""
    if sys.platform != "win32":
        return False
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return False
    ls = os.path.join(appdata, "WorkBuddy", "Local State")
    db = os.path.join(appdata, "WorkBuddy", "User", "globalStorage", "state.vscdb")
    ok = os.path.isfile(ls) and os.path.isfile(db)
    if log and not ok:
        log.log("DPAPI 兜底不可用：未找到旧版 Local State / state.vscdb。", "WARN")
    return ok


def read_identity_dpapi(log=None):
    """DPAPI 兜底：解密旧版加密登录态，返回 (token, uid, domain)。

    仅 Windows 有效；非 Windows、依赖缺失或任意失败均返回 (None, "", "")。
    不抛异常：失败退化为「未取到」，交由上层走 CDP 回退闸门。
    """
    if sys.platform != "win32":
        return None, "", ""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None, "", ""
    local_state = os.path.join(appdata, "WorkBuddy", "Local State")
    token_db = os.path.join(appdata, "WorkBuddy", "User", "globalStorage",
                            "state.vscdb")
    if not os.path.isfile(local_state) or not os.path.isfile(token_db):
        if log:
            log.log("DPAPI 兜底跳过：未找到旧版 Local State / state.vscdb。", "WARN")
        return None, "", ""

    AESGCM = _ensure_cryptography(log)
    if AESGCM is None:
        return None, "", ""

    try:
        with open(local_state, "r", encoding="utf-8") as fh:
            ls = json.load(fh)
        enc_key = base64.b64decode(ls["os_crypt"]["encrypted_key"])
        aes_key = _dpapi_unprotect(enc_key[5:])  # 跳过 "DPAPI" 5 字节前缀

        import sqlite3
        conn = sqlite3.connect(token_db)
        try:
            cur = conn.cursor()
            cur.execute("SELECT value FROM ItemTable WHERE key=?",
                        (_DPAPI_TOKEN_KEY,))
            row = cur.fetchone()
        finally:
            conn.close()
        if not row:
            if log:
                log.log("DPAPI 兜底跳过：state.vscdb 中未找到令牌键。", "WARN")
            return None, "", ""

        buf = bytes(json.loads(row[0])["data"])
        nonce = buf[3:15]
        ct = buf[15:]
        token_data = json.loads(AESGCM(aes_key).decrypt(nonce, ct, None)
                                .decode("utf-8"))

        auth = token_data.get("auth") or {}
        acct = token_data.get("account") or {}
        token = auth.get("accessToken") or token_data.get("accessToken")
        if not token or not isinstance(token, str) or not token.strip():
            if log:
                log.log("DPAPI 兜底：解密结果缺少有效 accessToken。", "WARN")
            return None, "", ""
        uid = str(acct.get("uid") or "")
        domain = str(auth.get("domain") or acct.get("domain") or "")
        if log:
            log.log(f"已由 DPAPI 旧版存储取得令牌（len={len(token)}）")
        return token, uid, domain
    except Exception as e:
        if log:
            log.log(f"DPAPI 兜底解密失败：{e}", "WARN")
        return None, "", ""
