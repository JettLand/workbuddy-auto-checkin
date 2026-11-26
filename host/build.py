# -*- coding: utf-8 -*-
"""一键重打包脚本（图标与外置文件零记忆依赖）。

流程：
  1. 从 tray_host.py 内嵌常量 TICON_B64 解码出完整 ICO 字节，
     落临时目录生成 icon.ico（不依赖 Pillow、不新增图片文件）；
  2. 以固化参数调 PyInstaller 重打包 exe（--icon 指向临时 ico），
     exe 直接产出到本目录（与外置脚本同目录，单一目录交付）；
  3. 打包完成后即删临时 ico 与构建中间产物（build/、spec）。

用法（须用带 PyInstaller 的解释器执行）：
    <python-with-pyinstaller> host/build.py

注意：改外置 .py / config.json 不需要重打包（exe 运行时从自身
目录加载）；仅 boot.py 自身或 Python 依赖集合变化时才运行本脚本。
"""
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
NAME = "wb-checkin-host"
HIDDEN = ["cryptography", "ctypes", "ctypes.wintypes", "shutil", "time",
          "urllib.request", "urllib.error", "json", "base64", "hashlib",
          "re", "subprocess", "threading", "datetime", "runpy"]


def icon_to_temp():
    # 图标字节源随入口脚本走（入口名由 config.json 指定）。
    try:
        with open(os.path.join(BASE, "config.json"), "r",
                  encoding="utf-8-sig") as f:
            entry = (json.load(f) or {}).get("entry_script") or "tray_host.py"
    except Exception:
        entry = "tray_host.py"
    if not (isinstance(entry, str) and entry == os.path.basename(entry)
            and ".." not in entry):
        raise RuntimeError("config.json 的 entry_script 不是合法的同类目录文件名")
    src = open(os.path.join(BASE, entry), encoding="utf-8").read()
    m = re.search(r'TICON_B64\s*=\s*\(\s*"([^"]+)"', src)
    if not m:
        raise RuntimeError(entry + " 缺少 TICON_B64（图标字节源）")
    d = tempfile.mkdtemp(prefix="wb_icon_")
    ico = os.path.join(d, "icon.ico")
    open(ico, "wb").write(base64.b64decode(m.group(1)))
    return ico


def main():
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        sys.exit("当前解释器无 PyInstaller，请用打包环境执行本脚本")
    exe = os.path.join(BASE, NAME + ".exe")
    if os.path.isfile(exe):
        try:
            open(exe, "r+b").close()
        except PermissionError:
            sys.exit("目标 exe 正在运行（被锁定），请先经托盘菜单「退出程序」"
                     "关闭 %s 后重试" % exe)
    ico = icon_to_temp()
    try:
        cmd = [sys.executable, "-m", "PyInstaller", "--onefile", "--noconsole",
               "--name", NAME, "--noconfirm", "--icon=" + ico]
        cmd += ["--hidden-import=" + h for h in HIDDEN]
        cmd += ["--collect-all=cryptography",
                "--distpath", BASE, "--workpath", os.path.join(BASE, "build"),
                "--specpath", BASE, os.path.join(BASE, "boot.py")]
        r = subprocess.run(cmd)
        if r.returncode:
            sys.exit("PyInstaller 失败 rc=%d" % r.returncode)
    finally:
        os.remove(ico)
        os.rmdir(os.path.dirname(ico))
        # 构建中间产物即用即清
        for p in (os.path.join(BASE, "build"),
                  os.path.join(BASE, NAME + ".spec")):
            if os.path.isdir(p):
                shutil.rmtree(p)
            elif os.path.isfile(p):
                os.remove(p)
    print("exe rebuilt with embedded icon -> %s" % exe)


if __name__ == "__main__":
    main()
