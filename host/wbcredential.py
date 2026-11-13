import base64
import ctypes
import ctypes.wintypes as w
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.request

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

HOME = os.path.expanduser("~")
LOCAL = os.environ.get("LOCALAPPDATA") or os.path.join(HOME, "AppData", "Local")
AUTH_FILE = os.path.join(LOCAL, "CodeBuddyExtension", "Data", "Public", "auth",
                         "workbuddy-desktop.info")
CDP_PORT_FILE = os.path.join(HOME, ".workbuddy", "app", "session",
                             "DevToolsActivePort")
CONFIG_FILE = os.environ.get("WB_CHECKIN_CONFIG") or os.path.join(
    HOME, ".workbuddy", "skills", "workbuddy-auto-checkin", "scripts", "config.json")
CACHE_FILE = os.environ.get("WB_CHECKIN_KEYCACHE") or os.path.join(
    LOCAL, "WorkBuddyCheckin", "keycache.json")

_k = ctypes.WinDLL("kernel32", use_last_error=True)
_k.OpenProcess.restype = w.HANDLE
_k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
_k.ReadProcessMemory.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                 ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
_k.VirtualQueryEx.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
_k.CloseHandle.argtypes = [w.HANDLE]
_k.LocalFree.argtypes = [ctypes.c_void_p]
_c = ctypes.WinDLL("crypt32", use_last_error=True)


class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", w.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


_PROTECT_ARGS = [ctypes.POINTER(_BLOB), w.LPCWSTR, ctypes.c_void_p,
                 ctypes.c_void_p, ctypes.c_void_p, w.DWORD,
                 ctypes.POINTER(_BLOB)]
_c.CryptProtectData.restype = w.BOOL
_c.CryptProtectData.argtypes = _PROTECT_ARGS
_c.CryptUnprotectData.restype = w.BOOL
_c.CryptUnprotectData.argtypes = _PROTECT_ARGS


class _MBI(ctypes.Structure):
    _fields_ = [("Base", ctypes.c_void_p), ("Alloc", ctypes.c_void_p),
                ("AllocProt", w.DWORD), ("Pad", w.DWORD), ("Size", ctypes.c_size_t),
                ("State", w.DWORD), ("Protect", w.DWORD), ("Type", w.DWORD)]


_B64_32 = re.compile(rb"[A-Za-z0-9+/]{43}=")
_MAX_SCAN = 900 * 1024 * 1024


def _pids():
    out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True).stdout
    found = []
    for line in out.splitlines():
        if "WorkBuddy.exe" in line:
            try:
                found.append(int(line.split('","')[1].replace('"', "")))
            except (IndexError, ValueError):
                pass
    return found


def _read(h, addr, size):
    buf = ctypes.create_string_buffer(size)
    got = ctypes.c_size_t()
    if not _k.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, size, ctypes.byref(got)):
        return b""
    return buf.raw[:got.value]


def _key_from_payload(payload):
    try:
        if len(base64.b64decode(payload, validate=True)) != 32:
            return None
    except Exception:
        return None
    return hashlib.sha256(payload).digest()


def _key_id(key):
    return hashlib.sha256(key).hexdigest()[:16]


def _protect(raw):
    buf = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    src = _BLOB(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    out = _BLOB()
    if not _c.CryptProtectData(ctypes.byref(src), u"WBCheckinKey", None, None,
                               None, 0, ctypes.byref(out)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return bytes(bytearray(out.pbData[:out.cbData]))
    finally:
        _k.LocalFree(out.pbData)


def _unprotect(raw):
    buf = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    src = _BLOB(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    out = _BLOB()
    if not _c.CryptUnprotectData(ctypes.byref(src), None, None, None, None, 0,
                                 ctypes.byref(out)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return bytes(bytearray(out.pbData[:out.cbData]))
    finally:
        _k.LocalFree(out.pbData)


def _load_key(key_id):
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            obj = json.load(f)
        if obj.get("keyId") != key_id:
            return None
        key = _unprotect(base64.b64decode(obj["protected"]))
        if len(key) != 32 or _key_id(key) != key_id:
            return None
        return key
    except Exception:
        return None


def _save_key(key_id, key):
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        blob = base64.b64encode(_protect(key)).decode("ascii")
        tmp = CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"keyId": key_id, "protected": blob}, f)
        os.replace(tmp, CACHE_FILE)
    except Exception:
        pass


def _scan_processes(key_id):
    for pid in _pids():
        h = _k.OpenProcess(0x0410, False, pid)
        if not h:
            continue
        total = 0
        try:
            addr = 0
            mbi = _MBI()
            while addr < 0x7FFFFFFFFFFF and total < _MAX_SCAN:
                if _k.VirtualQueryEx(h, ctypes.c_void_p(addr),
                                     ctypes.cast(ctypes.byref(mbi), ctypes.c_void_p),
                                     ctypes.sizeof(mbi)) == 0:
                    break
                size = mbi.Size or 0x1000
                base = mbi.Base or 0
                prot = mbi.Protect or 0
                if (mbi.State == 0x1000 and prot and not (prot & 0x101)
                        and 0 < size <= 32 * 1024 * 1024):
                    data = _read(h, base, min(size, 32 * 1024 * 1024))
                    total += len(data)
                    for m in _B64_32.finditer(data):
                        key = _key_from_payload(m.group())
                        if key and _key_id(key) == key_id:
                            return key
                nxt = base + size
                if nxt <= addr:
                    break
                addr = nxt
        finally:
            _k.CloseHandle(h)
    return None


def _find_key(key_id):
    key = _load_key(key_id)
    if key is not None:
        return key
    key = _scan_processes(key_id)
    if key is not None:
        _save_key(key_id, key)
    return key


def _aad(key_id):
    def lp(value):
        raw = value.encode() if isinstance(value, str) else value
        return len(raw).to_bytes(4, "big") + raw
    return (b"WB-AAD\0" + b"\x01" + lp("WBEV1") + lp("sym-v1")
            + (1).to_bytes(4, "big") + lp(key_id) + b"\x02\x00\x00")


def _envelope(field):
    if not isinstance(field, dict) or field.get("$wbEncrypted") != 1:
        raise RuntimeError("登录态字段不是 $wbEncrypted 加密信封")
    raw = field["envelope"]
    try:
        return json.loads(raw)
    except Exception:
        return json.loads(base64.b64decode(raw).decode("utf-8"))


def _decrypt(field, key):
    env = _envelope(field)
    if env.get("suite") != 1 or env.get("keyId") != _key_id(key):
        raise RuntimeError("加密套件或密钥标识不匹配")
    body = base64.b64decode(env["ciphertext"]) + base64.b64decode(env["authTag"])
    plain = AESGCM(key).decrypt(base64.b64decode(env["nonce"]), body,
                                _aad(env["keyId"]))
    return plain.decode("utf-8")


def route_a():
    with open(AUTH_FILE, "r", encoding="utf-8-sig") as f:
        obj = json.load(f)
    auth = obj.get("auth") or {}
    expires_at = auth.get("expiresAt") or 0
    if expires_at and expires_at / 1000 <= time.time():
        raise RuntimeError("主登录态已过期，拒绝发放过期令牌")
    key_id = _envelope(auth["accessToken"])["keyId"]
    key = _find_key(key_id)
    if key is None:
        raise RuntimeError("未能取得 at-rest 密钥（需客户端曾登录并运行过一次以建立 DPAPI 缓存）")
    token = _decrypt(auth["accessToken"], key)
    uid = (obj.get("account") or {}).get("uid") or ""
    domain = auth.get("domain") or "www.workbuddy.cn"
    return token, uid, domain


def _cdp_eval(ws_url, expression):
    import websocket
    ws = websocket.create_connection(ws_url, timeout=8, suppress_origin=True)
    try:
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {
            "expression": expression, "awaitPromise": True, "returnByValue": True}}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == 1:
                result = msg.get("result") or {}
                if result.get("exceptionDetails"):
                    raise RuntimeError("CDP 表达式执行异常")
                return (result.get("result") or {}).get("value")
    finally:
        ws.close()


def route_b():
    with open(CDP_PORT_FILE, "r", encoding="utf-8", errors="replace") as f:
        port = int(f.readline().strip())
    with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % port, timeout=4) as r:
        targets = json.load(r)
    page = next((t for t in targets
                 if t.get("type") == "page" and t.get("webSocketDebuggerUrl")), None)
    if not page:
        raise RuntimeError("CDP 无可连接页面（客户端未以调试端口启动）")
    with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
        cfg = json.load(f)
    ws_url = page["webSocketDebuggerUrl"]
    token = None
    for expr in cfg.get("token_exprs") or []:
        token = _cdp_eval(ws_url, expr)
        if token:
            break
    if not token:
        raise RuntimeError("CDP 未返回有效令牌")
    uid = _cdp_eval(ws_url, cfg.get("uid_expr") or "null") or ""
    domain = _cdp_eval(ws_url, cfg.get("domain_expr") or "null") or "www.workbuddy.cn"
    return token, uid, domain


def get_identity():
    errors = []
    for name, fn in (("A", route_a), ("B", route_b)):
        try:
            return fn()
        except Exception as exc:
            errors.append("%s: %s: %s" % (name, type(exc).__name__, exc))
    raise RuntimeError("双路取令牌均失败 | " + " | ".join(errors))
