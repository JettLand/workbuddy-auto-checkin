import ctypes
import os
import runpy
import sys

# 冻结态取 exe 所在目录，源码态取本文件所在目录；全程运行时动态推导，
# 不写入任何固定路径，5 个文件整体搬迁或改名后仍能定位同目录外置文件。
BASE = os.path.dirname(os.path.abspath(
    sys.executable if getattr(sys, "frozen", False) else __file__))

REQUIRED = ("tray_host.py", "payload.py", "wbcredential.py", "config.json")
missing = [name for name in REQUIRED
           if not os.path.isfile(os.path.join(BASE, name))]
if missing:
    msg = ("启动失败：同目录缺少 " + "、".join(missing) + "\n\n"
           "请将 wb-checkin-host.exe 与 tray_host.py、payload.py、"
           "wbcredential.py、config.json 放在同一目录；该目录可任意改名或"
           "搬迁。\n\n当前程序目录：" + BASE)
    # noconsole 无控制台可写，诊断经系统弹窗呈现（用户关闭后进程退出）。
    ctypes.windll.user32.MessageBoxW(None, msg, "WorkBuddy 自动签到", 0x30)
    sys.exit(2)

runpy.run_path(os.path.join(BASE, "tray_host.py"), run_name="__main__")
