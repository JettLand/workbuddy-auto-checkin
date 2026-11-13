import os
import runpy
import sys

# 冻结态取 exe 所在目录，源码态取本文件所在目录；全程运行时动态推导，
# 不写入任何固定路径，4 个文件整体搬迁或改名后仍能定位同目录外置脚本。
BASE = os.path.dirname(os.path.abspath(
    sys.executable if getattr(sys, "frozen", False) else __file__))
SHELL = os.path.join(BASE, "tray_host.py")

if not os.path.isfile(SHELL):
    sys.stderr.write(
        "启动失败：同目录缺少 tray_host.py\n"
        "请将 wb-checkin-host.exe 与 tray_host.py、payload.py、"
        "wbcredential.py 放在同一目录；该目录可任意改名或搬迁。\n"
        "当前程序目录：" + BASE + "\n")
    sys.exit(2)

runpy.run_path(SHELL, run_name="__main__")
