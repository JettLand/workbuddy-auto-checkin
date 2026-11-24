import ctypes
import ctypes.wintypes as w
import datetime
import os
import runpy
import sys
import threading
import time

U = ctypes.WinDLL("user32", use_last_error=True)
S = ctypes.WinDLL("shell32", use_last_error=True)
K = ctypes.WinDLL("kernel32", use_last_error=True)
A = ctypes.WinDLL("advapi32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", w.UINT), ("style", w.UINT), ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
        ("hInstance", w.HINSTANCE), ("hIcon", w.HICON), ("hCursor", w.HANDLE),
        ("hbrBackground", w.HANDLE), ("lpszMenuName", w.LPCWSTR),
        ("lpszClassName", w.LPCWSTR), ("hIconSm", w.HICON),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", w.DWORD), ("hWnd", w.HWND), ("uID", w.UINT),
        ("uFlags", w.UINT), ("uCallbackMessage", w.UINT), ("hIcon", w.HICON),
        ("szTip", w.WCHAR * 128), ("dwState", w.DWORD), ("dwStateMask", w.DWORD),
        ("szInfo", w.WCHAR * 256), ("uVersion", w.UINT),
        ("szInfoTitle", w.WCHAR * 64), ("dwInfoFlags", w.DWORD),
        ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", w.HICON),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", w.HWND), ("message", w.UINT), ("wParam", w.WPARAM),
        ("lParam", w.LPARAM), ("time", w.DWORD), ("pt", w.POINT),
    ]


WM_DESTROY = 2
WM_RBUTTONUP = 0x205
WM_LBUTTONDBLCLK = 0x203
WM_CONTEXTMENU = 0x7B
WM_NULL = 0
NIM_ADD = 0
NIM_DELETE = 2
NIM_MODIFY = 1
NIM_SETVERSION = 4
NIF_MESSAGE = 1
NIF_ICON = 2
NIF_TIP = 4
NIF_INFO = 0x10
NIF_SHOWTIP = 0x80
NIIF_WARNING = 2
MB_ICONWARNING = 0x30
MB_SYSTEMMODAL = 0x1000
MB_TOPMOST = 0x40000
MB_SETFOREGROUND = 0x10000
NOTIFYICON_VERSION_4 = 4
PM_REMOVE = 1
WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
WS_EX_TOOLWINDOW = 0x80
SW_HIDE = 0
SW_RESTORE = 9
GA_ROOTOWNER = 3
MF_STRING = 0
MF_CHECKED = 8
MF_SEPARATOR = 0x800
TPM_RETURNCMD = 0x100
TPM_RIGHTBUTTON = 2
IDI_APPLICATION = 32512
CB_MSG = 0x8001
APP_MENU = 0x8002

_state = {"console": None, "nid": None, "stop": threading.Event(),
          "last_menu": 0.0}


def _base():
    return os.path.dirname(os.path.abspath(
        sys.executable if getattr(sys, "frozen", False) else __file__))


def _host_log(msg):
    try:
        path = os.path.join(_base(), "logs", "host.log")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(datetime.datetime.now().isoformat(timespec="seconds")
                    + " " + msg + "\n")
    except Exception:
        pass


def _visible_window():
    """定位用户真正看到的窗口。

    Windows Terminal 承载时 GetConsoleWindow() 返回的是 0x0 的
    PseudoConsoleWindow 伪窗口，隐藏它不会隐藏可见窗口；真实窗口是
    owner 链顶端的 CASCADIA_HOSTING_WINDOW_CLASS 宿主窗口。
    传统 conhost 下 GetConsoleWindow() 自身即为可见顶层窗口。
    """
    c = _state["console"]
    if not c:
        return None
    return U.GetAncestor(c, GA_ROOTOWNER) or c


def _restore():
    c = _visible_window()
    if c:
        U.ShowWindow(c, SW_RESTORE)
        U.SetForegroundWindow(c)


def _minimize():
    c = _visible_window()
    if c:
        U.ShowWindow(c, SW_HIDE)
        _host_log("minimized to tray hwnd=%s" % c)


def _notify(title, text):
    """缺卡告警双通道：托盘气泡（约 10 秒自消）+ 置顶模态弹窗（不点不消失）。

    NIM_MODIFY + NIF_INFO 只更新气球字段，不动图标注册；弹窗阻塞
    payload 线程直到点击——00:05 后本无其他任务，无实际影响。
    """
    nid = _state["nid"]
    if nid:
        nid.uFlags = NIF_INFO
        nid.dwInfoFlags = NIIF_WARNING
        nid.szInfoTitle = title[:63]
        nid.szInfo = text[:255]
        S.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))
    _host_log("balloon title=%s text=%s" % (title[:20], text[:40]))
    try:
        U.MessageBoxW(None, text[:1024], title[:63],
                      MB_ICONWARNING | MB_SYSTEMMODAL | MB_TOPMOST
                      | MB_SETFOREGROUND)
        _host_log("alert box dismissed")
    except Exception as e:
        _host_log("alert box failed: %r" % (e,))


def _balloon(title, text):
    """轻量气泡提示（设置类操作反馈，不弹模态窗）。"""
    nid = _state["nid"]
    if nid:
        nid.uFlags = NIF_INFO
        nid.dwInfoFlags = 0
        nid.szInfoTitle = title[:63]
        nid.szInfo = text[:255]
        S.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "WorkBuddyCheckin"
HKEY_CURRENT_USER = 0x80000001
KEY_QUERY_VALUE = 1
KEY_SET_VALUE = 2
REG_SZ = 1
ERROR_FILE_NOT_FOUND = 2


def _autostart_cmd():
    """自启动命令动态推导：冻结态为 exe 本体（boot 逻辑已冻结在内）；
    源码态为 python 调 boot.py（含缺失文件诊断）。含空格路径加引号。"""
    if getattr(sys, "frozen", False):
        return '"%s"' % sys.executable
    return '"%s" "%s"' % (sys.executable, os.path.join(_base(), "boot.py"))


def _autostart_enabled():
    h = ctypes.c_void_p()
    if A.RegOpenKeyExW(HKEY_CURRENT_USER, RUN_KEY, 0, KEY_QUERY_VALUE,
                       ctypes.byref(h)) != 0:
        return False
    try:
        return A.RegQueryValueExW(h, RUN_VALUE, None, None, None, None) == 0
    finally:
        A.RegCloseKey(h)


def _autostart_set(on):
    h = ctypes.c_void_p()
    rc = A.RegOpenKeyExW(HKEY_CURRENT_USER, RUN_KEY, 0, KEY_SET_VALUE,
                         ctypes.byref(h))
    if rc != 0:
        raise OSError("RegOpenKeyExW rc=%d" % rc)
    try:
        if on:
            data = _autostart_cmd().encode("utf-16-le") + b"\x00\x00"
            rc = A.RegSetValueExW(h, RUN_VALUE, 0, REG_SZ, data, len(data))
        else:
            rc = A.RegDeleteValueW(h, RUN_VALUE)
            if rc == ERROR_FILE_NOT_FOUND:
                return
        if rc != 0:
            raise OSError("rc=%d" % rc)
    finally:
        A.RegCloseKey(h)


def _autostart_toggle():
    on = not _autostart_enabled()
    try:
        _autostart_set(on)
        _host_log("autostart -> %s" % ("on" if on else "off"))
        _balloon("开机自启动", "已开启，下次开机自动运行" if on else "已关闭")
    except OSError as e:
        _host_log("autostart failed: %s" % e)
        _balloon("开机自启动", "设置失败（注册表写入被拒绝）")


def _payload():
    p = os.path.join(_base(), "payload.py")
    if os.path.isfile(p):
        runpy.run_path(p, run_name="__main__",
                       init_globals={"_tray_notify": _notify})


def _watch():
    while not _state["stop"].wait(0.4):
        c = _visible_window()
        if c and U.IsIconic(c):
            U.ShowWindow(c, SW_HIDE)


def _menu(hwnd):
    m = U.CreatePopupMenu()
    U.AppendMenuW(m, MF_STRING | (MF_CHECKED if _autostart_enabled() else 0),
                  4, "开机自启动")
    U.AppendMenuW(m, MF_SEPARATOR, 0, None)
    U.AppendMenuW(m, MF_STRING, 1, "还原窗口")
    U.AppendMenuW(m, MF_STRING, 2, "缩小到托盘")
    U.AppendMenuW(m, MF_STRING, 3, "退出程序")
    items = U.GetMenuItemCount(m)
    pt = w.POINT()
    U.GetCursorPos(ctypes.byref(pt))
    fg = U.SetForegroundWindow(hwnd)
    cmd = U.TrackPopupMenu(m, TPM_RETURNCMD | TPM_RIGHTBUTTON,
                           pt.x, pt.y, 0, hwnd, None)
    U.PostMessageW(hwnd, WM_NULL, 0, 0)
    U.DestroyMenu(m)
    _host_log("menu items=%s cmd=%s fg=%s err=%s"
              % (items, cmd, fg, ctypes.get_last_error()))
    if cmd == 1:
        _restore()
    elif cmd == 2:
        _minimize()
    elif cmd == 4:
        _autostart_toggle()
    elif cmd == 3:
        _host_log("exit requested")
        _state["stop"].set()
        S.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(_state["nid"]))
        _host_log("releasing console, exiting process")
        K.FreeConsole()
        os._exit(0)


@WNDPROC
def _proc(hwnd, msg, wp, lp):
    if msg == CB_MSG:
        code = lp & 0xFFFF
        if code in (WM_RBUTTONUP, WM_CONTEXTMENU, WM_LBUTTONDBLCLK):
            _host_log("tray cb=0x%X" % code)
        if code in (WM_RBUTTONUP, WM_CONTEXTMENU):
            U.PostMessageW(hwnd, APP_MENU, 0, 0)
        elif code == WM_LBUTTONDBLCLK:
            _restore()
        return 0
    if msg in (WM_RBUTTONUP, WM_CONTEXTMENU):
        _host_log("tray direct=0x%X" % msg)
        U.PostMessageW(hwnd, APP_MENU, 0, 0)
        return 0
    if msg == WM_LBUTTONDBLCLK:
        _restore()
        return 0
    if msg == WM_DESTROY:
        U.PostQuitMessage(0)
        return 0
    return U.DefWindowProcW(hwnd, msg, wp, lp)


def main():
    U.DefWindowProcW.restype = LRESULT
    U.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
    U.RegisterClassExW.restype = w.UINT
    U.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
    U.CreateWindowExW.restype = w.HWND
    U.CreateWindowExW.argtypes = [
        w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        w.HWND, w.HMENU, w.HINSTANCE, ctypes.c_void_p,
    ]
    U.GetMessageW.argtypes = [ctypes.POINTER(MSG), w.HWND, w.UINT, w.UINT]
    U.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
    U.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
    U.LoadIconW.restype = w.HICON
    U.LoadIconW.argtypes = [w.HINSTANCE, ctypes.c_void_p]
    U.CreatePopupMenu.restype = w.HMENU
    U.AppendMenuW.argtypes = [w.HMENU, w.UINT, ctypes.c_size_t, w.LPCWSTR]
    U.GetMenuItemCount.restype = ctypes.c_int
    U.GetMenuItemCount.argtypes = [w.HMENU]
    U.TrackPopupMenu.restype = w.UINT
    U.TrackPopupMenu.argtypes = [
        w.HMENU, w.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        w.HWND, ctypes.c_void_p,
    ]
    U.GetCursorPos.argtypes = [ctypes.POINTER(w.POINT)]
    U.SetForegroundWindow.argtypes = [w.HWND]
    U.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
    U.DestroyMenu.argtypes = [w.HMENU]
    U.DestroyWindow.argtypes = [w.HWND]
    U.ShowWindow.argtypes = [w.HWND, ctypes.c_int]
    U.IsIconic.restype = w.BOOL
    U.IsIconic.argtypes = [w.HWND]
    U.PostQuitMessage.argtypes = [ctypes.c_int]
    U.PeekMessageW.restype = w.BOOL
    U.PeekMessageW.argtypes = [ctypes.POINTER(MSG), w.HWND, w.UINT,
                               w.UINT, w.UINT]
    U.GetParent.restype = w.HWND
    U.GetParent.argtypes = [w.HWND]
    U.GetAncestor.restype = w.HWND
    U.GetAncestor.argtypes = [w.HWND, w.UINT]
    S.Shell_NotifyIconW.restype = w.BOOL
    S.Shell_NotifyIconW.argtypes = [w.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
    K.GetConsoleWindow.restype = w.HWND
    K.GetModuleHandleW.restype = w.HINSTANCE
    K.GetModuleHandleW.argtypes = [w.LPCWSTR]
    A.RegOpenKeyExW.restype = ctypes.c_long
    A.RegOpenKeyExW.argtypes = [ctypes.c_void_p, w.LPCWSTR, w.DWORD,
                                w.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    A.RegCloseKey.restype = ctypes.c_long
    A.RegCloseKey.argtypes = [ctypes.c_void_p]
    A.RegQueryValueExW.restype = ctypes.c_long
    A.RegQueryValueExW.argtypes = [ctypes.c_void_p, w.LPCWSTR, ctypes.c_void_p,
                                   ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.c_void_p]
    A.RegSetValueExW.restype = ctypes.c_long
    A.RegSetValueExW.argtypes = [ctypes.c_void_p, w.LPCWSTR, w.DWORD, w.DWORD,
                                 ctypes.c_void_p, w.DWORD]
    A.RegDeleteValueW.restype = ctypes.c_long
    A.RegDeleteValueW.argtypes = [ctypes.c_void_p, w.LPCWSTR]

    _state["console"] = K.GetConsoleWindow()
    inst = K.GetModuleHandleW(None)
    wc = WNDCLASSEXW()
    wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
    wc.lpfnWndProc = _proc
    wc.hInstance = inst
    wc.lpszClassName = "WBHost"
    U.RegisterClassExW(ctypes.byref(wc))
    hwnd = U.CreateWindowExW(WS_EX_TOOLWINDOW, "WBHost", "",
                             WS_POPUP | WS_VISIBLE, 0, 0, 0, 0,
                             None, None, inst, None)
    nid = NOTIFYICONDATAW()
    nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
    nid.hWnd = hwnd
    nid.uID = 1
    nid.uFlags = NIF_ICON | NIF_MESSAGE | NIF_TIP | NIF_SHOWTIP
    nid.uCallbackMessage = CB_MSG
    nid.hIcon = U.LoadIconW(None, IDI_APPLICATION)
    nid.szTip = "WorkBuddy 自动签到"
    _state["nid"] = nid
    added = S.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
    nid.uVersion = NOTIFYICON_VERSION_4
    versioned = S.Shell_NotifyIconW(NIM_SETVERSION, ctypes.byref(nid))
    _host_log("host ready console=%s hwnd=%s parent=%s tray_add=%s v4=%s err=%s"
              % (_state["console"], hwnd, U.GetParent(hwnd),
                 added, versioned, ctypes.get_last_error()))
    threading.Thread(target=_watch, daemon=True).start()
    threading.Thread(target=_payload, daemon=True).start()
    m = MSG()
    while U.GetMessageW(ctypes.byref(m), None, 0, 0) > 0:
        if m.message == APP_MENU:
            if time.monotonic() - _state["last_menu"] >= 0.8:
                _menu(hwnd)
                _state["last_menu"] = time.monotonic()
                drain = MSG()
                while U.PeekMessageW(ctypes.byref(drain), None,
                                     APP_MENU, APP_MENU, PM_REMOVE):
                    pass
            continue
        U.TranslateMessage(ctypes.byref(m))
        U.DispatchMessageW(ctypes.byref(m))


if __name__ == "__main__":
    main()
