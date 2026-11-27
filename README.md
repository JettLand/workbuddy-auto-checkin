# workbuddy-auto-checkin

> WorkBuddy 每日积分签到（仅 Windows）。自 v3.0.0 起由**独立后台常驻程序**执行签到，不依赖 WorkBuddy 客户端保持运行、不依赖其内置自动签到、不依赖 WorkBuddy 自动化任务。

- 版本：**v3.5.0**
- 许可：**MIT**
- 作者：Jett
- 平台：Windows 10 / 11

---

## 背景

v2.4.1 及之前读取本机**明文**登录态 `workbuddy-desktop.info` 取令牌。2026 年客户端把 `auth.accessToken` 改为 `$wbEncrypted` 加密信封后，旧脚本跳过主文件、退回已过期的备用明文令牌，自 2026-10-30 起持续返回 401；端点未漂移、功能未下线、重新登录亦无效。v3.0.0 因此重建执行体与凭证链路。

---

## 特性

- **独立常驻（无控制台）**：自建 GUI 主窗口（标题 `WorkBuddy 自动签到`，统一图标）内嵌双标签页日志区（雅黑约 12.75pt 只读显示，`当前信息`＝本次运行输出、`历史信息`＝此前运行日志，每 2 秒刷新）＋系统托盘图标（悬浮显示程序名）。**右上角关闭按钮（X）仅隐藏窗口到托盘，程序继续后台运行**；托盘菜单首项为「开机自启动」勾选项（分隔线区分；勾选时写 HKCU Run 注册表值 `WorkBuddyCheckin`，指向当前程序本体，取消即删除；切换后气泡反馈，无需管理员权限），其后为「还原窗口」/「缩小到托盘」/「退出程序」（退出经托盘菜单执行，彻底终止进程）。
- **双触发点**：每次启动与每日 00:05 各执行一轮，流程完全相同——先状态预检（`checkin-activity-status`）：`today_checked_in=true` 幂等短路记 `already`；`data.active` 显式 `false` 当日放弃；预检不可达或未确认时照常发签到请求兜底（HTTP 400 + 业务码 10001 记为 `already (server confirmed)`，不视为失败）。
- **令牌有效期双检测**：① **服务端有效性**——状态预检复用同一 Bearer 令牌，若所有状态端点均返回 `401/403` 且无任何 `200`，判登录令牌在服务端已失效（记 `token validity -> invalid`、弹窗告知刷新登录态），**短路不发无效签到 POST**、不进重试与复核；网络错误（`code=0`）不参与判定，任一 `200` 即视为有效。② **到期预警**——登录令牌 `expiresAt` 剩余 ≤1 天时弹窗提醒启动客户端刷新登录态（进程内只提醒一次）；已过期（`expiresAt` 早于当前时间）仍由凭证层的硬阻断拦截。二者互补：前者以服务端实测为准，后者提前预警。
- **凭证单通道**：自解 `$wbEncrypted` 加密信封取当前有效令牌（DPAPI 缓存 → 进程内存扫描 → AES-GCM 自解，过期硬阻断）；失败明确报错，不再静默退回过期备用令牌。原 CDP 兜底（需客户端以调试端口启动，正常部署从不成立）已于 v3.2.0 退役。
- **完全离线自足**：派生密钥经 Windows 数据保护接口（`CryptProtectData`）按当前用户加密缓存，首次建立后客户端完全关闭也能签到。
- **设备令牌直发**：签到 POST 尽力附带本地产出的图灵盾设备令牌 `X-Device-Token`——系统 Node 直接加载客户端自带的 N-API 扩展独立产令牌（约 2 秒，不依赖客户端运行）。客户端 2026-11-20 升级后，无令牌的签到会被服务端「当场受理但不入活动日历」（缺卡成因）。令牌不可用时安全退化为无令牌直发。
- **缺卡复核告警**：每次签到后复核活动日历（`checkin-activity-status` 真实状态源）是否真实入账，缺卡间隔重试一次仍缺则弹托盘气泡提醒补签——无论令牌是否生效都不会静默缺卡。
- **签到成功提示**：签到受理成功（HTTP 200 首签/重试成功）时输出明确成功日志（`checkin SUCCESS: credit +N, streak M days`）并弹托盘信息气泡「今日积分 +N，连续签到 M 天」；`already`（当日早已签过）不弹泡以免骚扰，告警类弹窗保持警告样式不变。
- **网络失败当日重试**：签到因网络异常（连接失败/超时，结果归为 `error`）时当日有限重试——间隔＝10 分钟×重试次数（10/20/…/60 分钟，上限 6 次，累计约 3.5 小时）；等待将跨过下一定时点（00:05）时提前让位避免阻塞定时触发；全部失败发系统模态置顶弹窗，点掉弹窗后主循环恢复，若已过 00:05 即自动补签。
- **薄引导器 + 全外置**：exe 只冻结 `boot.py`，界面壳、业务、凭证三份 `.py` 全部由 `runpy` 运行时加载；入口脚本名与必需文件清单由 `config.json` 的 `entry_script` / `required_files` 指定——**改名或增删外置脚本只改配置、零重打包**；仅 boot.py 自身或 Python 依赖集合变化才需重打包。
- **路径动态推导**：按 exe 自身位置定位外置脚本、配置与日志，源码无写死目录；五文件可整体搬迁到任意路径（含空格与非 ASCII 目录）。
- **无控制台闪窗**：GUI 进程调用 `node`（设备令牌）与 `tasklist`（进程扫描）等控制台子系统子进程时统一带 `CREATE_NO_WINDOW`，启动不再闪现命令提示符窗口。
- **运行可见**：业务日志写 `logs/daemon.log` 并由 GUI 主窗口实时滚动展示每轮结果与下次运行时间。

---

## 架构概览

```
后台常驻程序（host/：exe + 3 份外置 .py + config.json，共 5 文件，单一目录交付）
  │
  ├─ wb-checkin-host.exe  ← 仅冻结 boot.py
  │     BASE = dirname(sys.executable if frozen else __file__)
  │     └─ 读 BASE/config.json → runpy.run_path(BASE/entry_script)
  │        （入口与必需清单由配置指定，缺字段回退默认，非法值 fail-closed 弹窗退出 2）
  │
  ├─ 界面壳 tray_host.py（外置，可热替换）
  │     GUI 主窗口（日志实时展示，X 仅隐藏）+ 托盘
  │     （真实顶层窗口 / NIF_MESSAGE / v4 消息）
  │     └─ runpy 运行时加载同目录 payload.py
  │
  ├─ 凭证 wbcredential.get_identity()
  │     ① DPAPI 缓存命中（keyId 校验）── 客户端关闭也能用
  │     ② 未命中 → 只读扫描客户端进程内存调取 atRestSecretKey → 写缓存
  │     └─ AES-256-GCM 自解 $wbEncrypted → token / uid / domain
  │
  └─ 业务 payload.py
        设备令牌：系统 Node 加载客户端图灵 N-API 扩展本地产出（约 2 秒，
                  addon/通道参数走 config.json；不可用则退化无令牌直发）
        启动触发：状态预检 POST → 幂等短路 → 签到 POST（附设备令牌）
        定时触发（每日 00:05，唯一时点）：状态预检 POST → 幂等短路 → 签到 POST
        结果：200 成功 / 400 + 业务码 10001（服务端确认今日已签）
        复核：查活动日历今日是否真实入账；缺卡重试一次后弹托盘气泡告警
        成功：200 时记 checkin SUCCESS 日志行 + 托盘信息气泡（积分/连续天数）
        → logs/daemon.log（GUI 窗口实时展示），以 startup / schedule 标签区分
        等待用绝对目标时刻（next_run_at），仅以 6h 为最长单次睡眠分段
```

令牌**不落盘**；落盘的只有经数据保护接口加密的 32 字节派生密钥。

---

## 快速开始

1. 确认本机 WorkBuddy 曾正确登录过一次（建立登录态与密钥缓存）。
2. 确认 `host/` 下的 exe 与 `tray_host.py`、`payload.py`、`wbcredential.py`、`config.json` 五个文件齐全。运行 `host/wb-checkin-host.exe`。GUI 主窗口日志区出现 `daemon started` → `device token ready len=...`（或 `device token unavailable`）→ `startup trigger -> already`（当日已签时预检短路，不再发签到 POST；未签时走 `checkin ... -> 200` 成功链）→ `next run at 次日 00:05:00` 即正常；**每次启动先查询服务端签到状态，未签才发签到请求**，当日已签即幂等跳过，不视为失败。此后仅在每日 00:05 兜底一轮。
3. 点窗口右上角 X 或右键选「缩小到托盘」仅隐藏窗口，程序继续在托盘后台运行；托盘菜单「还原窗口」随时唤回。右键菜单为「开机自启动」（勾选型，首项）+「还原窗口」/「缩小到托盘」/「退出程序」。鼠标悬浮图标会显示程序名 `WorkBuddy 自动签到`。Windows 11 常把新图标收进「隐藏的图标」溢出面板，点任务栏 `^` 展开后找带该提示的图标；如需常驻显示，把它拖到任务栏。

**五文件交付契约**：exe 必须与 `tray_host.py`、`payload.py`、`wbcredential.py`、`config.json` **同目录**，缺一即退出码 2 并弹中文清单诊断窗（无控制台形态下 print 不可见，诊断经系统弹窗呈现）。程序按 `sys.executable`（冻结态）/ `__file__` 动态推导程序目录，源码不含任何绝对目录；五文件可整体改名或搬迁到任意路径（含空格与非 ASCII 目录），日志随新目录生成，无需重装或重打包。无需调试端口、无需桌面快捷方式、无需自动化任务。

### 从源码运行 / 重新打包

```sh
# 源码运行（需 cryptography）；boot.py 也可直接跑
python host/payload.py

# 仅当修改 boot.py 本身、Python 依赖集合或 exe 图标资源时才需重打包。
# 入口/必需文件清单由 config.json 指定：改名或增删外置脚本只改配置，无需重打包。
# 一键脚本 host/build.py 自动完成全部步骤，零手工记忆依赖：
#   1. 从 config.json 指定的入口脚本内嵌常量 TICON_B64 解码出完整 ICO 字节，落临时目录生成
#      icon.ico（与托盘图标同源；不依赖 Pillow，磁盘不保留图片文件）
#   2. 以固化参数调 PyInstaller 打包（hidden-import 清单、--icon、--collect-all）
#   3. 打包后即删临时 ico 与 build/、spec 中间产物；exe 直接产出到 host/
# 须用带 PyInstaller 的解释器执行；打包前若目标 exe 正在运行会 fail-closed 提示先退出
<python-with-pyinstaller> host/build.py
```

exe 为构筑产物（`host/*.exe` 已被 `.gitignore` 排除），可由上述命令重建；exe 与外置脚本同目录即交付形态，改外置脚本无需重打包。漏配 `--hidden-import` 的典型症状是 exe 秒退、退出码 1、零日志、`ModuleNotFoundError: ctypes.wintypes`——此问题**不能靠改外置 `.py` 修复**，须重打包（`build.py` 已固化完整清单）。

---

## 配置

配置读**程序同目录** `config.json`（源真值＝运行目录同一份 `host/config.json`），可用 `WB_CHECKIN_CONFIG` 覆盖；图灵 SDK 扩展目录可用 `WB_CHECKIN_TURING_ADDON` 覆盖；密钥缓存路径可用 `WB_CHECKIN_KEYCACHE` 覆盖（默认 `%LOCALAPPDATA%\WorkBuddyCheckin\keycache.json`）。**引导器例外**：`entry_script` / `required_files` 由冻结的 `boot.py` 固定读程序同目录 `config.json`（bootstrap 必须先定位清单文件），不受 `WB_CHECKIN_CONFIG` 覆盖。

| 字段 | 说明 |
|---|---|
| `entry_script` | 引导器加载的入口脚本名（同目录纯文件名）；缺省 `tray_host.py`。改名只需改此项＋实际文件，无需重打包 exe |
| `required_files` | 入口之外的必需外置文件清单（同目录纯文件名）；缺省 `["payload.py", "wbcredential.py"]`。入口名自动纳入缺失检查；含路径分隔符或 `..` 一律 fail-closed 弹窗退出 2 |
| `api_base` | 接口根地址 |
| `checkin_paths` | 签到 POST 路径候选 |
| `checkin_status_paths` | 状态预检与复核 POST 路径候选 |
| `auth_headers` | 附加请求头 |
| `turing_addon_dir` | 客户端图灵 SDK N-API 扩展目录（设备令牌产出源；目录或 node 缺失则退化无令牌直发）。**自动维护**：失效/缺失时程序从客户端安装根动态发现并写回，人工编辑仅作覆盖 |
| `turing_channel_id` / `turing_product_name` / `turing_product_version` | 图灵 SDK configure 参数。**自动维护**：动态取自客户端安装根的 `cli/product.json`（`turingSdk.channelId` / `applicationName` / `genieVersion`），客户端升级自动跟随 |

签到与状态查询均为 **POST**；状态端点用 GET 一律 404；`checkin-activity-status` 才是真实状态，`checkin-status` 返回全零假状态。定时轮次与启动触发均先做状态预检：仅当明确读到 `today_checked_in=true` 时幂等跳过；`data.active` 显式为 `false` 时当日放弃；预检不可达或未确认时照常发签到请求兜底（HTTP 400 + 业务码 10001 为正常幂等答复）。

---

## 日志与排障

| 文件 | 内容 |
|---|---|
| `host/logs/daemon.log` | 每轮签到结果、POST 状态码、下次运行时间、异常堆栈摘要 |
| `host/logs/host.log` | 图标注册标志与版本、托盘消息码及来源、菜单命令与返回值、启动/退出记录 |

| 现象 | 处置 |
|---|---|
| exe 启动后秒退、退出码 1、两份日志均无新增 | 引导器模式的依赖收集缺口：PyInstaller 只静态分析 `boot.py`，外置脚本运行时加载的模块未冻结（`ModuleNotFoundError`，典型 `ctypes.wintypes`）。运行 `host/build.py` 重打包（清单已固化），改 `.py` 无效 |
| 搬迁目录后无法启动 / 弹「启动失败」诊断窗 | exe、`config.json` 及配置所列入口与必需文件必须同目录；程序按 exe 自身位置动态推导，源码无写死目录。诊断窗按配置清单动态列出缺失文件与当前程序目录（退出码 2）；配置损坏、入口名含 `../` 等非法值同样弹窗明确报错 |
| 主窗口日志区空白 | 确认 `payload.py` 与 exe 同目录且未损坏；日志文件在 `logs/daemon.log`，首次签到前可能尚未生成 |
| 退出后托盘残留失效图标 | 壳退出分支的 `NIM_DELETE` 必须为官方值 `2`；误写为 `1` 实为 `NIM_MODIFY`，只改图标不删除（`os._exit(0)` 掩盖了该问题） |
| 到点未签到或触发时点不符 | 定时点为 `SCHEDULE` 唯一项 00:05，`next_run_at()` 返回绝对时刻，`next run at` 须精确到 `T00:05:00`；每 6 小时触发或 `00:04:59` 均为旧缺陷 |
| 托盘右键无菜单 | 先确认点的是溢出面板里带 `WorkBuddy 自动签到` 提示的图标；壳须以真实顶层窗口注册图标、置 `NIF_MESSAGE` 回调标志、设 `NOTIFYICON_VERSION_4`，并同时处理自定义回调与直接投递的 `WM_CONTEXTMENU` / `WM_RBUTTONUP`；查 `host.log` 是否出现消息码与菜单命令 |
| 鼠标悬浮图标不显示程序名 | `NOTIFYICON_VERSION_4` 下标准 tooltip 默认被抑制，`uFlags` 须带 `NIF_SHOWTIP`（0x80）才会显示 `szTip`；提示文本为 `WorkBuddy 自动签到` |
| `auth_failed` | 签到 POST 被服务端以 401/403 拒绝（令牌过期或密钥轮换）；运行并登录一次客户端刷新登录态与缓存 |
| `token_invalid` | 状态预检的所有端点均以 401/403 拒绝且无 200，判定登录令牌在服务端已失效；今日签到未发出、不重试不复核。启动并登录一次客户端刷新登录态后重启本程序 |
| 取登录态失败 | 检查登录态文件是否存在且未过期、缓存 `keyId` 是否匹配、客户端是否曾登录并在本机运行过 |
| 弹出「今日签到可能未生效」气泡 | 复核判定缺卡：服务端为「当场受理、事后判定」模式，签到返回 200 不代表入活动日历（客户端 11-20 升级引入设备令牌校验）。打开客户端确认或使用补签卡；`daemon.log` 应有 `verify -> MISSING from activity calendar` |
| 日志出现 `device token unavailable` | 系统无 `node` 命令、`config.json` 的 `turing_addon_dir` 目录不存在或产令牌失败；程序退化为无令牌直发，该签到可能不入活动日历（见上条）。确认 `node` 在 PATH、目录指向客户端安装的 `resources/app.asar.unpacked/native/turing-sdk` |

**切勿在 WorkBuddy 进程树内执行 `taskkill WorkBuddy.exe`** —— 命令工具与自动化运行时均属其子树，会杀掉自身宿主。

---

## 已知边界

- 数据保护接口绑定当前 Windows 用户：可防其他用户与离线磁盘读取，**不防同一用户下的恶意进程**。
- 令牌本身有服务端有效期；到期或客户端轮换 at-rest 密钥后，需客户端运行并登录一次以刷新登录态与缓存。剩余 ≤1 天时程序弹到期预警（进程内一次）；若服务端已提前拒绝（状态查询 401/403）则记 `token_invalid` 并短路当日签到。二者均为**登录令牌**检测——设备令牌服务端为事后判定、无同步校验端点，仍以活动日历入账为准。
- 本地设备令牌的有效性以「签到次日活动日历是否入账」为准（服务端为事后判定模式）；无论令牌是否生效，缺卡复核告警都会第一时间弹泡提示，不会静默缺卡。
- 图灵盾参数（`turing_*` 字段）为缓存式自适应：配置有效直读，失效/缺失时按「配置路径上溯 → 注册表卸载登记 → 常见安装位置」动态发现并自动写回 `config.json`，全部失败则发警告弹窗（此时签到退化为无令牌直发，可能不入活动日历，由缺卡复核告警兜底）。
- v2.x 历史链路（明文登录态 → 旧 DPAPI → CDP 回退、`--retry`、asar 自愈、退出码分级）与配套回归技能已随 v3.2.0 整体移除（git 历史可溯）。
- 端点漂移时从客户端 `app.asar` 扫描核实新端点后更新 `config.json` 的 `checkin_paths`（原 `calibrate.py` 扫描脚本已随 v2.x 移除，git 历史可找回）。

---

## 文件结构

```
workbuddy-auto-checkin/
├── README.md                # 本文件
├── CHANGELOG.md             # 版本变化明细
├── .gitignore               # 排除运行态与构筑物
└── host/                    # 现行执行体（v3.2.0 起纯后台程序，无技能形态）
    ├── boot.py                # 薄引导器（唯一被冻结的入口，路径动态推导；入口/清单读 config）
    ├── config.json            # 入口与必需清单 / 端点 / 请求头 / 图灵 SDK 参数（源真值）
    ├── tray_host.py           # GUI 主窗口壳 + 托盘 + 告警/成功通知（外置，可热替换）
    ├── wbcredential.py        # 凭证单通道 + 密钥缓存（外置）
    ├── payload.py             # 定时签到业务 + 设备令牌 + 缺卡复核（外置）
    ├── build.py               # 一键重打包脚本（图标自动随包，exe 产出本目录）
    └── wb-checkin-host.exe    # gitignored 构筑产物，与外置脚本同目录即交付
        ├── wb-checkin-host.exe # 仅冻结 boot.py
        ├── tray_host.py       # 与源码同步，可热替换
        ├── payload.py         # 与源码同步，可热替换
        ├── wbcredential.py    # 与源码同步，可热替换
        └── config.json        # 与源码同步
```

---

## 合规说明

本方案在本机读取自身登录态，由独立后台程序直接调用签到接口，属个人设备本地自动化：不修改客户端、不绕过登录鉴权、明文令牌不落盘。仅供**个人学习与自用**，请遵守 WorkBuddy 服务条款与平台规则；若官方明确禁止此类自动化，请立即停止使用。请勿用于批量刷取或侵犯他人权益。

> **分发提示**：本项目以私有仓库分发，规避公开分发条款。企业微信 `notify.webhook_url` 即群写入权限，**切勿提交到公开仓库**。`state/`、`logs/`、`host/*.exe`、`build/`、`*.spec`、`__pycache__/` 已被 `.gitignore` 排除。

---

## License

[MIT](LICENSE) — 详见仓库 LICENSE 文件（如缺失，按 MIT 许可理解：可自由使用、修改、分发，作者不对使用后果负责）。
