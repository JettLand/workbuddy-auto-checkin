---
name: workbuddy-auto-checkin
description: WorkBuddy 每日积分签到（仅 Windows）。当用户提到"签到""积分签到""每日签到""自动签到""daily check-in"，或询问签到为何失效、如何部署后台常驻签到、如何排查鉴权失败时使用本技能，提供现行执行体的部署、配置与排障指引。自 v3.0.0 起实际签到由独立后台常驻程序执行，不再由本技能脚本或 WorkBuddy 自动化任务触发；旧 scripts/ 链路已废弃，仅作诊断溯源。
version: "3.0.0"
license: MIT
author: Jett
agent_created: true
allowed-tools: Bash, Read, automation_update
target_platform: windows
target_agent: workbuddy
---

# WorkBuddy 每日积分签到（workbuddy-auto-checkin）

> **v3.0.0 破坏性变更**：客户端将登录态 `auth.accessToken` 改为 `$wbEncrypted` 加密信封，v2.4.1 及之前的「读明文登录态」链路自 2026-10-30 起持续返回 401，**重新登录也无法修复**。现行签到执行体为代码仓库 `host/` 下的独立后台常驻程序：不依赖 WorkBuddy 客户端保持运行、不依赖客户端内置自动签到、不依赖 WorkBuddy 自动化任务。

## 一、现行执行体

| 组成 | 文件 | 作用 |
|---|---|---|
| 纯界面壳 | `tray_host.py` → 打包为 `wb-checkin-host.exe` | 命令提示符窗口 + 系统托盘图标；右键菜单 Restore 还原窗口 / Minimize to tray 缩小到托盘 / Exit 释放控制台并终止进程；最小化窗口亦自动隐藏 |
| 业务脚本 | `payload.py` | 启动即强制发一轮签到请求，另于每日 00:05 执行一次常驻兜底（唯一时点）；定时轮次先做状态预检幂等；POST 结果与运行信息同步输出到控制台与日志 |
| 凭证模块 | `wbcredential.py` | 双路取令牌 + Windows 数据保护接口缓存派生密钥，实现完全离线自足 |

- 壳为**纯界面框架**，不含任何业务逻辑与业务文本，仅保留必要的界面标识（菜单项名称与托盘图标提示）；启动时以 `runpy` 运行时加载同目录 `payload.py`。**业务功能变更只需替换 `.py`，不需重新打包 exe**；仅改壳才需重打包。
- exe 必须与 `payload.py`、`wbcredential.py` 同目录。运行信息同步写入 exe 同目录下的业务日志与托盘诊断日志（运行态产物，首次运行时生成）。
- 配置默认读技能安装目录 `scripts` 子目录下的 `config.json`，可用环境变量 `WB_CHECKIN_CONFIG` 覆盖。

### 快速开始

1. 确认本机 WorkBuddy 曾正确登录过一次（用于建立登录态与密钥缓存）。
2. 运行 `wb-checkin-host.exe`；控制台出现 `daemon started` → `checkin ... -> 400 ...` → `startup trigger -> ...` → `next run at 次日 00:05:00` 即正常。**每次启动都会真正发出一次签到请求**：当日尚未签到时服务端返回 200；已签到时返回 HTTP 400 且业务码 10001（服务端明确答复「今日已签」），日志记为 `already (server confirmed)`，不视为失败。此后仅在每日 00:05 兜底一轮，不再于其他时点触发。
3. 最小化窗口，或右键选 Minimize to tray，即隐藏到托盘；右键选 Restore 可还原，选 Exit 会关闭命令提示符窗口并终止进程。Windows 11 常把新图标收进「隐藏的图标」溢出面板，可点任务栏 `^` 展开后找到带 `WorkBuddy Checkin` 提示的图标；如需常驻显示，把它拖到任务栏即可。

无需调试端口、无需桌面快捷方式、无需 WorkBuddy 自动化任务。平台侧现存自动化仅 `00:05` 一条且处于暂停态，不参与签到。

## 二、凭证机制

**双路兜底，先 A 后 B；双路失败明确报错，不再静默退回过期备用明文文件。**

- **路 A（主）**：读取登录态文件 `workbuddy-desktop.info`，校验 `expiresAt` 未过期（过期硬阻断）→ 取 `accessToken` 加密信封的 `keyId` → 备妥 32 字节派生密钥 → AES-256-GCM 解密得当前有效令牌，同时取 `account.uid` 与 `auth.domain`。
- **路 B（兜底）**：经 CDP `Runtime.evaluate` 执行配置中的 `token_exprs` / `uid_expr` / `domain_expr` 取令牌；需客户端以调试端口启动，当前环境通常不可用。

**完全离线自足**：派生密钥经 Windows 数据保护接口（`CryptProtectData`）以当前用户上下文加密后缓存于 `%LOCALAPPDATA%\WorkBuddyCheckin\keycache.json`，读取时按 `keyId` 与密钥标识双重校验。首次成功调取密钥后即写缓存，此后**客户端完全关闭也能签到**（截至令牌 `expiresAt`）。缓存仅含加密后的派生密钥，**不含明文令牌、不含明文密钥**。

密钥首次取得方式：只读扫描 WorkBuddy 进程内存中的 44 字节 canonical base64 候选，按 `keyId = SHA256(密钥)[:16]` 校验命中；`密钥 = SHA256(atRestSecretKey 字符串)`。信封为 `sym-v1` 标准字段包装（AES-256-GCM，nonce 12 字节、authTag 16 字节），无需解 `keyblob`。加密体系与 AAD 构造的完整定论见项目日志。

**边界**：数据保护接口绑定当前 Windows 用户，可防其他用户与离线磁盘读取，**不防同一用户下的恶意进程**；令牌到期或客户端轮换 at-rest 密钥后，需客户端运行并登录一次以刷新登录态与缓存——这不是本地方案能绕过的。

## 三、先决条件与配置

| 项 | 要求 |
|---|---|
| 系统 | Windows 10 / 11；源码运行需 Python 3.8+，打包 exe 无需 Python |
| 依赖 | `cryptography`（AES-256-GCM）、`websocket-client`（仅路 B）；PyInstaller 仅打包时需要 |
| 网络 | 可访问 `copilot.tencent.com` |
| 环境变量 | `WB_CHECKIN_CONFIG`（配置文件路径覆盖）、`WB_CHECKIN_KEYCACHE`（密钥缓存路径覆盖） |

签到与状态查询均为 **POST**；状态端点必须用 POST（GET 一律 404）；`checkin-activity-status` 才是真实状态，`checkin-status` 返回全零假状态。定时轮次先查状态，仅当明确读到 `today_checked_in=true` 时幂等跳过；`data.active` 显式为 `false` 时当日放弃。**启动触发点不做状态预检**，直接发签到请求，由服务端判定当日是否已签（HTTP 400 + 业务码 10001）。异常、非 200 或字段缺失一律不判定为取消，宁可多一次幂等请求也不漏签。

## 四、排障

| 现象 | 处置 |
|---|---|
| 控制台无运行信息 | 确认 `payload.py` 与 exe 同目录且未损坏；运行信息由该脚本输出，壳本身不含业务文本 |
| 托盘右键无菜单 | 先确认点的是带 `WorkBuddy Checkin` 提示的图标（Windows 11 新图标默认在溢出面板）；壳须以真实顶层窗口注册图标、置 `NIF_MESSAGE` 回调标志、设 `NOTIFYICON_VERSION_4`，并同时处理自定义回调与直接投递的 `WM_CONTEXTMENU` / `WM_RBUTTONUP`；查托盘诊断日志是否出现消息码、菜单项数量与命令返回值 |
| 选 Minimize to tray 后窗口只是最小化、未隐藏 | 壳须沿 `GetAncestor(GetConsoleWindow(), GA_ROOTOWNER)` 的 owner 链定位可见窗口再执行 `SW_HIDE`。若默认终端是 Windows Terminal，`GetConsoleWindow()` 只返回 0×0 的 `PseudoConsoleWindow` 伪窗口，隐藏它不影响用户看到的 `CASCADIA_HOSTING_WINDOW_CLASS` 宿主窗口；托盘诊断日志应出现 `minimized to tray hwnd=`，且「手动最小化自动隐藏」须检测同一宿主窗口 |
| 选 Exit 后图标消失但窗口仍在 | 退出分支须显式 `FreeConsole()` 释放控制台并 `os._exit(0)` 终止进程；仅删托盘图标与销毁隐藏工具窗口不会关闭由 conhost 持有的命令提示符窗口。托盘诊断日志应出现 `exit requested` → `releasing console, exiting process` |
| 到点未签到或触发时点不符 | 定时点为 `SCHEDULE` 唯一项 00:05；`next_run_at()` 返回绝对时刻，`next run at` 日志须精确到 `T00:05:00`。若曾出现每 6 小时触发或 `00:04:59`，说明用了 `min(秒数, 6h)` 截断或浮点秒数反推时刻，均为旧缺陷 |
| `startup trigger -> already (server confirmed)` | 正常：启动已发出签到请求，服务端确认今日已签。每日积分由服务端按日幂等发放，同日重复启动不会重复计分 |
| `... trigger -> auth_failed` | 令牌过期或密钥已轮换；运行并登录一次 WorkBuddy 客户端刷新登录态与缓存 |
| `... trigger -> error` | 查业务日志的 POST 状态码；端点漂移时按下方历史定论重新校准 |
| 双路取令牌均失败 | 检查登录态文件是否存在且未过期、密钥缓存 `keyId` 是否匹配 |

**切勿在 WorkBuddy 进程树内执行 `taskkill WorkBuddy.exe`** —— 命令工具与自动化运行时均属其子树，会杀掉自身宿主。

## 五、历史链路（v2.4.1 及之前，已废弃）

旧执行体（技能安装目录 `scripts` 子目录下的签到主脚本）采用「明文登录态主路径 → 旧版 DPAPI 加密存储兜底 → 受控 CDP 回退」三段式取令牌，配合 `calibrate.py` 的 asar 主动扫描自愈、`--retry` 任务级重试、退出码分级与两条单时点自动化。该链路因客户端加密改造**已不具备签到能力**，源码仅保留供诊断溯源，**不要按旧版命令执行签到**。旧日志中出现的退出码 `1` 表示鉴权失效或请求失败，其余分级仅属历史行为，详见 CHANGELOG；**v3.0.0 后台程序不使用退出码分级**，结果以控制台与日志输出为准。

仍跨版本有效的定论：

- 端点发现的唯一可靠来源是 `calibrate.py` 对本地 `app.asar` 的主动扫描（初始化 + 404 触发）；被动网络嗅探不可行——签到请求由守护进程发出、不经渲染进程网络栈，CDP 网络域观测不到。
- asar 扫描须用 mmap 配合 `mm.find()`（多字节子串 `in` 判断在 mmap 上恒为假）。
- 端点发现不致误判：`feature_removed` 不自动持久化，需人工在 `config.json` 置 `true`。

配套回归技能 `workbuddy-auto-checkin-verify` v1.2.1 仅覆盖上述历史链路，其前置条件（明文登录态可读）在新客户端已失效，**不适用于 v3.0.0 执行体**。

## 六、合规说明

本方案在本机读取自身登录态，由独立后台程序直接调用签到接口，属个人设备本地自动化：不修改客户端、不绕过登录鉴权、**明文令牌不落盘**（仅加密后的派生密钥落盘）。仅供个人学习与自用，请遵守 WorkBuddy 服务条款与平台规则；若官方明确禁止此类自动化，请立即停止使用。请勿用于批量刷取或侵犯他人权益。
