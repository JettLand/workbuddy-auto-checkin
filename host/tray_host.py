import base64
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
G = ctypes.WinDLL("gdi32", use_last_error=True)
C = ctypes.WinDLL("comctl32", use_last_error=True)

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
WS_CHILD = 0x40000000
WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_VSCROLL = 0x200000
ES_MULTILINE = 4
ES_AUTOVSCROLL = 0x40
ES_READONLY = 0x400
WM_CLOSE = 0x10
WM_SIZE = 0x5
WM_SETFONT = 0x30
WM_TIMER = 0x113
EM_SETSEL = 0xB1
EM_SCROLLCARET = 0xB7
IDC_ARROW = 32512
SW_HIDE = 0
SW_SHOW = 5
MF_STRING = 0
MF_CHECKED = 8
MF_SEPARATOR = 0x800
TPM_RETURNCMD = 0x100
TPM_RIGHTBUTTON = 2
IDI_APPLICATION = 32512
LR_DEFAULTCOLOR = 0
SM_CXSMICON = 49
SM_CYSMICON = 50
GUI_W = 760
GUI_H = 480
GUI_TIMER_ID = 1
GUI_TIMER_MS = 2000
GUI_TAIL_BYTES = 4 * 1024 * 1024
GUI_FONT_H = -17  # 约 12.75pt（96dpi）
GUI_FONT_FACE = "Microsoft YaHei UI"
WM_NOTIFY = 0x4E
WS_CLIPSIBLINGS = 0x04000000
TCM_GETCURSEL = 0x130B
TCM_INSERTITEMW = 0x133E
TCM_GETITEMW = 0x133D
TCM_ADJUSTRECT = 0x1328
TCN_SELCHANGE = -551
ICC_TAB_CLASSES = 8
DEFAULT_CHARSET = 1
MB_ICONINFORMATION = 0x40
SPI_GETWORKAREA = 0x0030
SWP_NOSIZE = 0x1
SWP_NOZORDER = 0x4
ERROR_ALREADY_EXISTS = 183
MUTEX_NAME = "WorkBuddyCheckin"


class NMHDR(ctypes.Structure):
    _fields_ = [("hwndFrom", w.HWND), ("idFrom", ctypes.c_size_t),
                ("code", ctypes.c_int)]


class TCITEMW(ctypes.Structure):
    _fields_ = [("mask", w.UINT), ("lpReserved1", w.LPARAM),
                ("lpReserved2", w.LPARAM), ("pszText", w.LPWSTR),
                ("cchTextMax", ctypes.c_int), ("iImage", ctypes.c_int),
                ("lParam", w.LPARAM)]


class INITCOMMONCONTROLSEX(ctypes.Structure):
    _fields_ = [("dwSize", w.DWORD), ("dwICC", w.DWORD)]
# 统一图标（绿色圆底+白色对勾）：base64 多帧 PNG-in-ICO 字节，与 exe 资源图标
# 同源（打包 --icon 消费同一条数据，构建时临时落盘、用后即删）。
TICON_B64 = ("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")
CB_MSG = 0x8001
APP_MENU = 0x8002

_state = {"nid": None, "gui": None, "tab": None, "edit_cur": None,
          "edit_hist": None, "stop": threading.Event(), "last_menu": 0.0,
          "mutex": None}


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


def _read_views():
    """读取运行日志并切分为两个标签页视图（换行统一为 EDIT 所需的 CRLF）。

    「当前信息」＝最后一个 `daemon started` 起至文件尾（本次运行输出）；
    「历史信息」＝其之前的运行日志（只取尾部窗口，上限 GUI_TAIL_BYTES）。
    """
    p = os.path.join(_base(), "logs", "daemon.log")
    try:
        size = os.path.getsize(p)
        with open(p, "rb") as f:
            if size > GUI_TAIL_BYTES:
                f.seek(size - GUI_TAIL_BYTES)
            lines = f.read().decode("utf-8", "replace").splitlines(True)
            if size > GUI_TAIL_BYTES and lines:
                lines = lines[1:]  # 截断处的半行丢弃
    except OSError:
        return "(暂无运行日志)", "(暂无历史日志)"
    start = 0
    for i, ln in enumerate(lines):
        if "daemon started" in ln:
            start = i
    # 日志文件为文本模式写入（行尾已是 CRLF），先归一到 LF 再统一转
    # EDIT 控件所需的 CRLF，避免二次替换产生 \r\r\n
    cur = "".join(lines[start:]).replace("\r\n", "\n").replace("\n", "\r\n")
    hist = "".join(lines[:start]).replace("\r\n", "\n").replace("\n", "\r\n")
    return cur or "(空)", hist or "(暂无历史日志)"


def _tab_sel():
    """当前选中页索引：控件无选中（-1）等异常一律按第 0 页「当前信息」。"""
    return 1 if U.SendMessageW(_state["tab"], TCM_GETCURSEL, 0, 0) == 1 else 0


def _refresh_log():
    cur, hist = _read_views()
    sel = _tab_sel()
    edit, txt = ((_state["edit_cur"], cur) if sel == 0
                 else (_state["edit_hist"], hist))
    if edit:
        U.SetWindowTextW(edit, txt)
        U.SendMessageW(edit, EM_SETSEL, -1, -1)
        U.SendMessageW(edit, EM_SCROLLCARET, 0, 0)


def _show_tab():
    sel = _tab_sel()
    if _state["edit_cur"]:
        U.ShowWindow(_state["edit_cur"], SW_SHOW if sel == 0 else SW_HIDE)
    if _state["edit_hist"]:
        U.ShowWindow(_state["edit_hist"], SW_SHOW if sel == 1 else SW_HIDE)


def _layout():
    gui, tab = _state["gui"], _state["tab"]
    if not gui or not tab:
        return
    rect = w.RECT()
    U.GetClientRect(gui, ctypes.byref(rect))
    U.MoveWindow(tab, 0, 0, rect.right - rect.left,
                 rect.bottom - rect.top, True)
    r = w.RECT(rect.left, rect.top, rect.right, rect.bottom)
    U.SendMessageW(tab, TCM_ADJUSTRECT, 0, ctypes.addressof(r))
    cw, ch = r.right - r.left, r.bottom - r.top
    for e in (_state["edit_cur"], _state["edit_hist"]):
        if e:
            U.MoveWindow(e, r.left, r.top, cw, ch, True)


def _restore():
    g = _state["gui"]
    if g:
        U.ShowWindow(g, SW_SHOW)
        U.SetForegroundWindow(g)


def _hide():
    g = _state["gui"]
    if g:
        U.ShowWindow(g, SW_HIDE)
        _host_log("window hidden")


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


def _tray_hicon(cx, cy):
    """从内嵌 ICO 字节选最接近目标尺寸的帧创建 HICON；失败返回 0。

    ICO 容器＝6 字节 ICONDIR + N×16 字节 ICONDIRENTRY（宽、高、颜色数、
    保留、色平面、位深、帧长、帧偏移；256 记 0）+ 各帧 PNG 数据。
    """
    if not TICON_B64:
        return 0
    raw = base64.b64decode(TICON_B64)
    count = int.from_bytes(raw[4:6], "little")
    best = None
    for i in range(count):
        e = raw[6 + 16 * i:22 + 16 * i]
        ew = e[0] or 256
        eh = e[1] or 256
        score = abs(ew - cx) + abs(eh - cy)
        if best is None or score < best[0]:
            best = (score, int.from_bytes(e[12:16], "little"),
                    int.from_bytes(e[8:12], "little"))
    _, off, size = best
    frame = raw[off:off + size]
    buf = (ctypes.c_char * len(frame)).from_buffer_copy(frame)
    return U.CreateIconFromResourceEx(buf, len(frame), True, 0x00030000,
                                      cx, cy, LR_DEFAULTCOLOR)


def _payload():
    p = os.path.join(_base(), "payload.py")
    if os.path.isfile(p):
        runpy.run_path(p, run_name="__main__",
                       init_globals={"_tray_notify": _notify,
                                     "_tray_balloon": _balloon})


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
        _hide()
    elif cmd == 4:
        _autostart_toggle()
    elif cmd == 3:
        _host_log("exit requested")
        _state["stop"].set()
        S.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(_state["nid"]))
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


@WNDPROC
def _main_proc(hwnd, msg, wp, lp):
    """GUI 主窗口过程：右上角关闭（X）仅隐藏到托盘，不退出程序。"""
    if msg == WM_CLOSE:
        U.ShowWindow(hwnd, SW_HIDE)
        _host_log("gui closed to tray (X)")
        return 0
    if msg == WM_SIZE:
        _layout()
        return 0
    if msg == WM_NOTIFY:
        try:
            nm = ctypes.cast(ctypes.c_void_p(lp),
                             ctypes.POINTER(NMHDR)).contents
        except Exception:
            return 0
        if nm.code == TCN_SELCHANGE and nm.hwndFrom == _state["tab"]:
            _show_tab()
            _refresh_log()
            return 0
        return 0
    if msg == WM_TIMER and wp == GUI_TIMER_ID:
        try:
            _refresh_log()
        except Exception as e:
            _host_log("gui refresh failed: %r" % (e,))
        return 0
    return U.DefWindowProcW(hwnd, msg, wp, lp)


def _center_window(hwnd):
    """窗口居中到工作区（排除任务栏），失败静默保持原位。"""
    r = w.RECT()
    if not U.GetWindowRect(hwnd, ctypes.byref(r)):
        return
    wa = w.RECT()
    if U.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(wa), 0):
        pass
    else:
        wa.left = wa.top = 0
        wa.right = U.GetSystemMetrics(0)   # SM_CXSCREEN
        wa.bottom = U.GetSystemMetrics(1)  # SM_CYSCREEN
    x = wa.left + (wa.right - wa.left - (r.right - r.left)) // 2
    y = wa.top + (wa.bottom - wa.top - (r.bottom - r.top)) // 2
    U.SetWindowPos(hwnd, None, x, y, 0, 0, SWP_NOSIZE | SWP_NOZORDER)


def _create_gui(inst, hicon):
    """创建主窗口（标题栏图标＝统一图标）+ 标签页日志区（只读双 EDIT）。

    窗口承担原控制台的交互角色：「当前信息」页展示本次运行输出，
    「历史信息」页展示此前运行日志；点 X 或托盘菜单「缩小到托盘」
    仅隐藏，程序继续在托盘后台运行。
    """
    C.InitCommonControlsEx(ctypes.byref(
        INITCOMMONCONTROLSEX(ctypes.sizeof(INITCOMMONCONTROLSEX),
                             ICC_TAB_CLASSES)))
    wc = WNDCLASSEXW()
    wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
    wc.lpfnWndProc = _main_proc
    wc.hInstance = inst
    wc.hIcon = hicon
    wc.hIconSm = hicon
    wc.hCursor = U.LoadCursorW(None, IDC_ARROW)
    wc.hbrBackground = ctypes.c_void_p(6)  # (HBRUSH)(COLOR_WINDOW+1)
    wc.lpszClassName = "WBMain"
    U.RegisterClassExW(ctypes.byref(wc))
    gui = U.CreateWindowExW(0, "WBMain", "WorkBuddy 自动签到",
                            WS_OVERLAPPEDWINDOW | WS_VISIBLE,
                            0, 0, GUI_W, GUI_H,
                            None, None, inst, None)
    tab = U.CreateWindowExW(0, "SysTabControl32", None,
                            WS_CHILD | WS_VISIBLE | WS_CLIPSIBLINGS,
                            0, 0, 0, 0, gui, None, inst, None)
    _state["gui"] = gui
    _state["tab"] = tab
    style = (WS_CHILD | WS_VISIBLE | WS_VSCROLL | ES_MULTILINE
             | ES_AUTOVSCROLL | ES_READONLY)
    edit_cur = U.CreateWindowExW(0, "EDIT", None, style,
                                 0, 0, 0, 0, gui, None, inst, None)
    edit_hist = U.CreateWindowExW(0, "EDIT", None,
                                  style & ~WS_VISIBLE,
                                  0, 0, 0, 0, gui, None, inst, None)
    _state["edit_cur"] = edit_cur
    _state["edit_hist"] = edit_hist
    hfont = G.CreateFontW(GUI_FONT_H, 0, 0, 0, 400, 0, 0, 0,
                          DEFAULT_CHARSET, 0, 0, 0, 0, GUI_FONT_FACE)
    # 标签页插入：显式递增索引（曾两次插 index=0 致默认选中第 1 页、
    # 映射错位使可见页永不刷新）；文本用显式 buffer 保活（LPWSTR 字段
    # 直接赋 str 在部分环境读回为空，改 buffer+cast 稳妥）。
    _tab_bufs = []
    for idx, name in enumerate(("当前信息", "历史信息")):
        buf = ctypes.create_unicode_buffer(name)
        _tab_bufs.append(buf)
        item = TCITEMW()
        item.mask = 1  # TCIF_TEXT
        item.pszText = ctypes.cast(buf, w.LPWSTR)
        U.SendMessageW(tab, TCM_INSERTITEMW, idx, ctypes.addressof(item))
    for e in (edit_cur, edit_hist):
        U.SendMessageW(e, WM_SETFONT, hfont, 1)
    _layout()
    _center_window(gui)
    # 插入后读回自证：宿主日志记录控件实际持有的标签文本，供真机
    # 环境排查（注入类环境会清空结构消息的字符串传递）。
    got = []
    for i in range(2):
        rb = ctypes.create_unicode_buffer(64)
        gi = TCITEMW()
        gi.mask = 1
        gi.pszText = ctypes.cast(rb, w.LPWSTR)
        gi.cchTextMax = 64
        U.SendMessageW(tab, TCM_GETITEMW, i, ctypes.addressof(gi))
        got.append(rb.value)
    _host_log("tab labels: %r" % (got,))
    U.SetTimer(gui, GUI_TIMER_ID, GUI_TIMER_MS, None)
    _refresh_log()
    return gui


def _single_instance():
    """防重复拉起：命名互斥量持锁判定；重复实例弹窗提示后由调用方退出。

    默认命名空间为会话局部（同用户同桌面防重即可，无需 Global\\ 前缀）。
    句柄存入 _state 防 GC 提前释放互斥量。
    """
    h = K.CreateMutexW(None, False, MUTEX_NAME)
    _state["mutex"] = h
    if not h or ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        return False
    return True


def main():
    if not _single_instance():
        _host_log("another instance is running, exit")
        U.MessageBoxW(None, "WorkBuddy 自动签到已在运行。\n"
                      "请从系统托盘图标打开窗口。",
                      "WorkBuddy 自动签到",
                      MB_ICONINFORMATION | MB_SYSTEMMODAL
                      | MB_SETFOREGROUND | MB_TOPMOST)
        return
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
    U.CreateIconFromResourceEx.restype = w.HICON
    U.CreateIconFromResourceEx.argtypes = [ctypes.c_void_p, w.UINT, w.BOOL,
                                           w.DWORD, ctypes.c_int, ctypes.c_int,
                                           w.UINT]
    U.GetSystemMetrics.restype = ctypes.c_int
    U.GetSystemMetrics.argtypes = [ctypes.c_int]
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
    U.PostQuitMessage.argtypes = [ctypes.c_int]
    U.PeekMessageW.restype = w.BOOL
    U.PeekMessageW.argtypes = [ctypes.POINTER(MSG), w.HWND, w.UINT,
                               w.UINT, w.UINT]
    U.GetParent.restype = w.HWND
    U.GetParent.argtypes = [w.HWND]
    U.GetAncestor.restype = w.HWND
    U.GetAncestor.argtypes = [w.HWND, w.UINT]
    U.LoadCursorW.restype = w.HANDLE
    U.LoadCursorW.argtypes = [w.HINSTANCE, ctypes.c_void_p]
    U.SetTimer.restype = ctypes.c_size_t
    U.SetTimer.argtypes = [w.HWND, ctypes.c_size_t, w.UINT, ctypes.c_void_p]
    U.MoveWindow.restype = w.BOOL
    U.MoveWindow.argtypes = [w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                             ctypes.c_int, w.BOOL]
    U.SendMessageW.restype = LRESULT
    U.SendMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
    U.SetWindowTextW.restype = w.BOOL
    U.SetWindowTextW.argtypes = [w.HWND, w.LPCWSTR]
    U.GetClientRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
    U.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
    U.SystemParametersInfoW.restype = w.BOOL
    U.SystemParametersInfoW.argtypes = [w.UINT, w.UINT, ctypes.c_void_p, w.UINT]
    U.SetWindowPos.restype = w.BOOL
    U.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int,
                               ctypes.c_int, ctypes.c_int, w.UINT]
    K.CreateMutexW.restype = w.HANDLE
    K.CreateMutexW.argtypes = [ctypes.c_void_p, w.BOOL, w.LPCWSTR]
    G.CreateFontW.restype = ctypes.c_void_p
    G.CreateFontW.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, ctypes.c_int, w.DWORD, w.DWORD,
                              w.DWORD, w.DWORD, w.DWORD, w.DWORD, w.DWORD,
                              w.DWORD, w.LPCWSTR]
    S.Shell_NotifyIconW.restype = w.BOOL
    S.Shell_NotifyIconW.argtypes = [w.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
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
    nid.hIcon = (_tray_hicon(U.GetSystemMetrics(SM_CXSMICON) or 16,
                             U.GetSystemMetrics(SM_CYSMICON) or 16)
                 or U.LoadIconW(None, IDI_APPLICATION))
    nid.szTip = "WorkBuddy 自动签到"
    _state["nid"] = nid
    added = S.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
    nid.uVersion = NOTIFYICON_VERSION_4
    versioned = S.Shell_NotifyIconW(NIM_SETVERSION, ctypes.byref(nid))
    big_icon = (_tray_hicon(32, 32)
                or U.LoadIconW(None, IDI_APPLICATION))
    gui = _create_gui(inst, big_icon)
    _host_log("host ready hwnd=%s tray_add=%s v4=%s gui=%s err=%s"
              % (hwnd, added, versioned, gui, ctypes.get_last_error()))
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
