import ctypes
import json
import os
import runpy
import sys

# 冻结态取 exe 所在目录，源码态取本文件所在目录；全程运行时动态推导，
# 不写入任何固定路径，多文件整体搬迁或改名后仍能定位同目录外置文件。
BASE = os.path.dirname(os.path.abspath(
    sys.executable if getattr(sys, "frozen", False) else __file__))
CONFIG = os.path.join(BASE, "config.json")

# bootstrap 唯一硬编码锚点：须先定位清单文件才能读到入口与必需清单。
DEFAULT_ENTRY = "tray_host.py"
DEFAULT_REQUIRED = ("payload.py", "wbcredential.py")


def _fatal(msg):
    # noconsole 无控制台可写，诊断经系统弹窗呈现（用户关闭后进程退出）。
    ctypes.windll.user32.MessageBoxW(None, msg, "WorkBuddy 自动签到", 0x30)
    sys.exit(2)


def _safe_name(name):
    """仅接受同目录纯文件名，拒绝子路径与上级跳转。"""
    return (isinstance(name, str) and bool(name)
            and name == os.path.basename(name)
            and "/" not in name and "\\" not in name and ".." not in name)


if not os.path.isfile(CONFIG):
    _fatal("启动失败：同目录缺少 config.json\n\n"
           "请将程序本体与 config.json 放在同一目录；该目录可任意改名或搬迁。\n\n"
           "当前程序目录：" + BASE)
try:
    with open(CONFIG, "r", encoding="utf-8-sig") as f:
        cfg = json.load(f)
except Exception as e:
    _fatal("启动失败：config.json 无法读取或格式错误（%s: %s）\n\n"
           "当前程序目录：%s" % (type(e).__name__, e, BASE))

if not isinstance(cfg, dict):
    _fatal("启动失败：config.json 顶层须为 JSON 对象\n\n当前程序目录：" + BASE)

entry = cfg.get("entry_script", DEFAULT_ENTRY)
required = cfg.get("required_files", list(DEFAULT_REQUIRED))
if not _safe_name(entry):
    _fatal("启动失败：config.json 的 entry_script 不是合法的同类目录文件名：%r"
           % (entry,))
if not isinstance(required, (list, tuple)) or not all(
        _safe_name(n) for n in required):
    _fatal("启动失败：config.json 的 required_files 含非法文件名（须为同目录纯文件名）")

checks = list(dict.fromkeys([entry] + list(required)))
missing = [name for name in checks
           if not os.path.isfile(os.path.join(BASE, name))]
if missing:
    _fatal("启动失败：同目录缺少 " + "、".join(missing) + "\n\n"
           "请将程序本体与 config.json 所列文件放在同一目录；"
           "该目录可任意改名或搬迁。\n\n当前程序目录：" + BASE)

runpy.run_path(os.path.join(BASE, entry), run_name="__main__")
