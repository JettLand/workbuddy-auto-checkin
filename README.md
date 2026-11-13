# workbuddy-auto-checkin

> WorkBuddy 每日积分签到（仅 Windows）。自 v3.0.0 起由**独立后台常驻程序**执行签到，不依赖 WorkBuddy 客户端保持运行、不依赖其内置自动签到、不依赖 WorkBuddy 自动化任务。

- 版本：**v3.1.0**
- 许可：**MIT**
- 作者：Jett
- 平台：Windows 10 / 11

---

## 背景

v2.4.1 及之前读取本机**明文**登录态 `workbuddy-desktop.info` 取令牌。2026 年客户端把 `auth.accessToken` 改为 `$wbEncrypted` 加密信封后，旧脚本跳过主文件、退回已过期的备用明文令牌，自 2026-10-30 起持续返回 401；端点未漂移、功能未下线、重新登录亦无效。v3.0.0 因此重建执行体与凭证链路。

---

## 特性

- **独立常驻**：命令提示符窗口 + 系统托盘图标（悬浮显示程序名 `WorkBuddy 自动签到`）；最小化自动隐藏，右键菜单为「还原窗口」/「缩小到托盘」/「退出程序」（释放控制台并终止进程，窗口随之关闭）。
- **双触发点**：每次启动立即**强制发出一次签到请求**（不做状态预检），另于每日 00:05 执行一次常驻兜底（唯一时点，先状态预检幂等）。启动轮次由服务端判定当日是否已签：HTTP 400 + 业务码 10001 记为 `already (server confirmed)`，不视为失败。
- **双路凭证**：A 主＝自解 `$wbEncrypted` 加密信封取当前有效令牌（过期硬阻断）；B 兜底＝CDP 取令牌；双路失败明确报错，不再静默退回过期备用令牌。
- **完全离线自足**：派生密钥经 Windows 数据保护接口（`CryptProtectData`）按当前用户加密缓存，首次建立后客户端完全关闭也能签到。
- **薄引导器 + 全外置**：exe 只冻结十余行 `boot.py`，界面壳、业务、凭证三份 `.py` 全部由 `runpy` 运行时加载；**任何代码改动只需替换对应 `.py`，无需重新打包 exe**。
- **路径动态推导**：按 exe 自身位置定位外置脚本与日志，源码无写死目录；四文件可整体搬迁到任意路径（含空格与非 ASCII 目录）。
- **运行可见**：业务日志与控制台同步输出每轮结果与下次运行时间。

---

## 架构概览

```
后台常驻程序（host/dist/：exe + 3 份外置 .py，共 4 文件）
  │
  ├─ wb-checkin-host.exe  ← 仅冻结 boot.py（十余行）
  │     BASE = dirname(sys.executable if frozen else __file__)
  │     └─ runpy.run_path(BASE/tray_host.py)   ← 动态定位，无写死路径
  │
  ├─ 界面壳 tray_host.py（外置，可热替换）
  │     命令提示符窗口 + 托盘（真实顶层窗口 / NIF_MESSAGE / v4 消息）
  │     └─ runpy 运行时加载同目录 payload.py
  │
  ├─ 凭证 wbcredential.get_identity()
  │     ① DPAPI 缓存命中（keyId 校验）── 客户端关闭也能用
  │     ② 未命中 → 只读扫描客户端进程内存调取 atRestSecretKey → 写缓存
  │     └─ AES-256-GCM 自解 $wbEncrypted → token / uid / domain
  │     兜底：CDP Runtime.evaluate（需调试端口）
  │
  └─ 业务 payload.py
        启动触发（force=True）：跳过状态预检，直接签到 POST
        定时触发（每日 00:05，唯一时点）：状态预检 POST → 幂等短路 → 签到 POST
        结果：200 成功 / 400 + 业务码 10001（服务端确认今日已签）
        → 控制台 + logs/daemon.log，以 startup / schedule 标签区分
        等待用绝对目标时刻（next_run_at），仅以 6h 为最长单次睡眠分段
```

令牌**不落盘**；落盘的只有经数据保护接口加密的 32 字节派生密钥。

---

## 快速开始

1. 确认本机 WorkBuddy 曾正确登录过一次（建立登录态与密钥缓存）。
2. 确认 `host/dist/` 下的 exe 与 `tray_host.py`、`payload.py`、`wbcredential.py` 四个文件齐全。运行 `host/dist/wb-checkin-host.exe`。控制台出现 `daemon started` → `checkin ... -> 400 ...` → `startup trigger -> already (server confirmed)` → `next run at 次日 00:05:00` 即正常；**每次启动都会真正发出一次签到请求**，当日已签时由服务端返回 400 + 业务码 10001，不视为失败。此后仅在每日 00:05 兜底一轮。
3. 最小化窗口或右键选「缩小到托盘」即隐藏到托盘；右键菜单为「还原窗口」/「缩小到托盘」/「退出程序」。鼠标悬浮图标会显示程序名 `WorkBuddy 自动签到`。Windows 11 常把新图标收进「隐藏的图标」溢出面板，点任务栏 `^` 展开后找带该提示的图标；如需常驻显示，把它拖到任务栏。

**四文件交付契约**：exe 必须与 `tray_host.py`、`payload.py`、`wbcredential.py` **同目录**，缺一即退出码 2 并打印中文诊断。程序按 `sys.executable`（冻结态）/ `__file__` 动态推导程序目录，源码不含任何绝对目录；四文件可整体改名或搬迁到任意路径（含空格与非 ASCII 目录），日志随新目录生成，无需重装或重打包。无需调试端口、无需桌面快捷方式、无需自动化任务。

### 从源码运行 / 重新打包

```sh
# 源码运行（需 cryptography、websocket-client）；boot.py 也可直接跑
python host/payload.py

# 仅当修改 boot.py 本身或 Python 依赖集合时才需重打包
# --hidden-import 清单必须覆盖三份外置脚本的全部运行时 import：
# PyInstaller 只分析入口 boot.py，外置脚本的 import 不会被自动收集
python -m PyInstaller --onefile --console --name wb-checkin-host --noconfirm \
  --hidden-import=websocket --hidden-import=cryptography \
  --hidden-import=ctypes.wintypes --hidden-import=urllib.request \
  --hidden-import=urllib.error --hidden-import=json --hidden-import=base64 \
  --hidden-import=hashlib --hidden-import=re --hidden-import=subprocess \
  --hidden-import=threading --hidden-import=datetime --hidden-import=runpy \
  --collect-all=cryptography --distpath host/dist --workpath host/build \
  --specpath host host/boot.py
cp host/tray_host.py host/payload.py host/wbcredential.py host/dist/
```

`host/dist/` 为构筑产物，已被 `.gitignore` 排除，可由上述命令重建。漏配 `--hidden-import` 的典型症状是 exe 秒退、退出码 1、零日志、控制台 `ModuleNotFoundError: ctypes.wintypes`——此问题**不能靠改外置 `.py` 修复**，须重打包。

---

## 配置

配置默认读技能安装目录的 `scripts/config.json`，可用 `WB_CHECKIN_CONFIG` 覆盖；密钥缓存路径可用 `WB_CHECKIN_KEYCACHE` 覆盖（默认 `%LOCALAPPDATA%\WorkBuddyCheckin\keycache.json`）。

| 字段 | 说明 |
|---|---|
| `api_base` | 接口根地址 |
| `checkin_paths` | 签到 POST 路径候选 |
| `checkin_status_paths` | 状态预检 POST 路径候选 |
| `auth_headers` | 附加请求头 |
| `token_exprs` / `uid_expr` / `domain_expr` | 仅路 B（CDP）使用的求值表达式 |

签到与状态查询均为 **POST**；状态端点用 GET 一律 404；`checkin-activity-status` 才是真实状态，`checkin-status` 返回全零假状态。定时轮次仅当明确读到 `today_checked_in=true` 时幂等跳过；`data.active` 显式为 `false` 时当日放弃。**启动触发点不做状态预检**，直接发签到请求，由服务端判定当日是否已签（HTTP 400 + 业务码 10001 为正常幂等答复）。

---

## 日志与排障

| 文件 | 内容 |
|---|---|
| `host/dist/logs/daemon.log` | 每轮签到结果、POST 状态码、下次运行时间、异常堆栈摘要 |
| `host/dist/logs/host.log` | 图标注册标志与版本、托盘消息码及来源、菜单命令与返回值、启动/退出记录 |

| 现象 | 处置 |
|---|---|
| exe 启动后秒退、退出码 1、两份日志均无新增 | 引导器模式的依赖收集缺口：PyInstaller 只静态分析 `boot.py`，外置脚本运行时加载的模块未冻结；捕获控制台可见 `ModuleNotFoundError`（典型 `ctypes.wintypes`）。按上方打包命令补齐完整 `--hidden-import` 清单后重打包，改 `.py` 无效 |
| 搬迁目录后无法启动 / 提示缺文件 | 四文件必须同目录；程序按 exe 自身位置动态推导，源码无写死路径。仅复制 exe 会以退出码 2 报错并列出当前程序目录 |
| 控制台空白 | 确认 `payload.py` 与 exe 同目录且未损坏 |
| 选「缩小到托盘」后窗口只是最小化、未隐藏 | 壳须沿 `GetAncestor(GetConsoleWindow(), GA_ROOTOWNER)` 的 owner 链定位可见窗口再 `SW_HIDE`；Windows Terminal 作为默认终端时 `GetConsoleWindow()` 只返回 0×0 的 `PseudoConsoleWindow` 伪窗口，隐藏它不影响 `CASCADIA_HOSTING_WINDOW_CLASS` 宿主窗口。`host.log` 应出现 `minimized to tray hwnd=` |
| 选「退出程序」后图标消失但窗口仍在 | 退出分支须显式 `FreeConsole()` + `os._exit(0)`；仅删图标与销毁隐藏工具窗口不会关闭由 conhost 持有的控制台窗口。`host.log` 应出现 `exit requested` → `releasing console, exiting process` |
| 退出后托盘残留失效图标 | 壳退出分支的 `NIM_DELETE` 必须为官方值 `2`；误写为 `1` 实为 `NIM_MODIFY`，只改图标不删除（`os._exit(0)` 掩盖了该问题） |
| 到点未签到或触发时点不符 | 定时点为 `SCHEDULE` 唯一项 00:05，`next_run_at()` 返回绝对时刻，`next run at` 须精确到 `T00:05:00`；每 6 小时触发或 `00:04:59` 均为旧缺陷 |
| 托盘右键无菜单 | 先确认点的是溢出面板里带 `WorkBuddy 自动签到` 提示的图标；壳须以真实顶层窗口注册图标、置 `NIF_MESSAGE` 回调标志、设 `NOTIFYICON_VERSION_4`，并同时处理自定义回调与直接投递的 `WM_CONTEXTMENU` / `WM_RBUTTONUP`；查 `host.log` 是否出现消息码与菜单命令 |
| 鼠标悬浮图标不显示程序名 | `NOTIFYICON_VERSION_4` 下标准 tooltip 默认被抑制，`uFlags` 须带 `NIF_SHOWTIP`（0x80）才会显示 `szTip`；提示文本为 `WorkBuddy 自动签到` |
| `auth_failed` | 令牌过期或密钥已轮换；运行并登录一次客户端刷新登录态与缓存 |
| 双路取令牌均失败 | 检查登录态文件是否存在且未过期、缓存 `keyId` 是否匹配 |

**切勿在 WorkBuddy 进程树内执行 `taskkill WorkBuddy.exe`** —— 命令工具与自动化运行时均属其子树，会杀掉自身宿主。

---

## 已知边界

- 数据保护接口绑定当前 Windows 用户：可防其他用户与离线磁盘读取，**不防同一用户下的恶意进程**。
- 令牌本身有服务端有效期；到期或客户端轮换 at-rest 密钥后，需客户端运行并登录一次以刷新登录态与缓存。
- 旧 `scripts/` 链路（明文登录态 → DPAPI 旧存储 → CDP 回退、`--retry`、asar 自愈、退出码分级）**已废弃**，源码仅作诊断溯源，不再具备签到能力。配套回归技能 `workbuddy-auto-checkin-verify` v1.2.1 亦仅覆盖该历史链路。
- 端点发现仍以 `calibrate.py` 的 asar 主动扫描为唯一可靠来源；被动网络嗅探不可行（签到请求由守护进程发出，不经渲染进程）。

---

## 文件结构

```
workbuddy-auto-checkin/
├── SKILL.md                 # 技能定义（触发词、现行执行体、排障、合规）
├── README.md                # 本文件
├── CHANGELOG.md             # 版本变化明细
├── .gitignore               # 排除运行态与构筑物
├── scripts/                 # v2.x 历史链路（已废弃，仅诊断溯源）
│   ├── checkin_native.py      # 旧签到主流程
│   ├── tokenfile.py           # 旧明文 / DPAPI 取令牌
│   ├── wbcommon.py            # 旧共享工具
│   ├── calibrate.py           # asar 端点扫描（定论仍有效）
│   ├── setup.py / launch_and_checkin.py / sniff.py / notify.py
│   └── config.json            # 端点与请求头配置（仍被后台程序读取）
└── host/                    # v3.0.0 起现行执行体（不进技能安装目录）
    ├── boot.py                # 薄引导器（唯一被冻结的入口，路径动态推导）
    ├── tray_host.py           # 界面壳（外置，可热替换）
    ├── wbcredential.py        # 双路凭证 + 密钥缓存（外置）
    ├── payload.py             # 定时签到业务（外置）
    └── dist/                  # gitignored 构筑产物，四文件交付契约
        ├── wb-checkin-host.exe # 仅冻结 boot.py
        ├── tray_host.py       # 与源码同步，可热替换
        ├── payload.py         # 与源码同步，可热替换
        └── wbcredential.py    # 与源码同步，可热替换
```

---

## 合规说明

本方案在本机读取自身登录态，由独立后台程序直接调用签到接口，属个人设备本地自动化：不修改客户端、不绕过登录鉴权、明文令牌不落盘。仅供**个人学习与自用**，请遵守 WorkBuddy 服务条款与平台规则；若官方明确禁止此类自动化，请立即停止使用。请勿用于批量刷取或侵犯他人权益。

> **分发提示**：本项目以私有仓库分发，规避公开分发条款。企业微信 `notify.webhook_url` 即群写入权限，**切勿提交到公开仓库**。`state/`、`logs/`、`dist/`、`build/`、`*.spec`、`__pycache__/` 已被 `.gitignore` 排除。

---

## License

[MIT](LICENSE) — 详见仓库 LICENSE 文件（如缺失，按 MIT 许可理解：可自由使用、修改、分发，作者不对使用后果负责）。
