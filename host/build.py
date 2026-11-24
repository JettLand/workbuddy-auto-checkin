# -*- coding: utf-8 -*-
"""一键重打包脚本（图标与 dist 同步零记忆依赖）。

流程：
  1. 从 tray_host.py 内嵌常量 TICON_B64 解码出完整 ICO 字节，
     落临时目录生成 icon.ico（不依赖 Pillow、不新增图片文件）；
  2. 以固化参数调 PyInstaller 重打包 exe（--icon 指向临时 ico）；
  3. 打包完成后即删临时 ico 与构建中间产物（build/、spec）；
  4. 自动同步 dist 外置文件并逐个 sha256 校验（5 文件契约）。

用法（须用带 PyInstaller 的解释器执行）：
    <python-with-pyinstaller> host/build.py

注意：改外置 .py / config.json 不需要重打包（热替换即可）；
仅 boot.py 自身或 Python 依赖集合变化时才运行本脚本。
"""
import base64
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(BASE, "dist")
NAME = "wb-checkin-host"
EXTERNAL = ["tray_host.py", "payload.py", "wbcredential.py", "config.json"]
HIDDEN = ["cryptography", "ctypes", "ctypes.wintypes", "shutil", "time",
          "urllib.request", "urllib.error", "json", "base64", "hashlib",
          "re", "subprocess", "threading", "datetime", "runpy"]


def icon_to_temp():
    src = open(os.path.join(BASE, "tray_host.py"), encoding="utf-8").read()
    m = re.search(r'TICON_B64\s*=\s*\(\s*"([^"]+)"', src)
    if not m:
        raise RuntimeError("tray_host.py 缺少 TICON_B64（图标字节源）")
    d = tempfile.mkdtemp(prefix="wb_icon_")
    ico = os.path.join(d, "icon.ico")
    open(ico, "wb").write(base64.b64decode(m.group(1)))
    return ico


def main():
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        sys.exit("当前解释器无 PyInstaller，请用打包环境执行本脚本")
    exe = os.path.join(DIST, NAME + ".exe")
    if os.path.isfile(exe):
        try:
            open(exe, "r+b").close()
        except PermissionError:
            sys.exit("目标 exe 正在运行（被锁定），请先经托盘菜单「退出程序」"
                     "关闭 %s 后重试" % exe)
    ico = icon_to_temp()
    try:
        cmd = [sys.executable, "-m", "PyInstaller", "--onefile", "--console",
               "--name", NAME, "--noconfirm", "--icon=" + ico]
        cmd += ["--hidden-import=" + h for h in HIDDEN]
        cmd += ["--collect-all=cryptography",
                "--distpath", DIST, "--workpath", os.path.join(BASE, "build"),
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
    print("exe rebuilt with embedded icon")

    ok = True
    for f in EXTERNAL:
        s, d = os.path.join(BASE, f), os.path.join(DIST, f)
        shutil.copyfile(s, d)
        same = (hashlib.sha256(open(s, "rb").read()).hexdigest()
                == hashlib.sha256(open(d, "rb").read()).hexdigest())
        ok = ok and same
        print("%-16s %s" % (f, "sha256 OK" if same else "MISMATCH"))
    if not ok:
        sys.exit("dist 同步校验失败")
    print("dist synced & verified (5-file contract)")


if __name__ == "__main__":
    main()
