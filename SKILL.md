---
name: workbuddy-auto-checkin
description: WorkBuddy 每日积分签到技能（仅 Windows）。当用户或自动化任务提到"签到""积分签到""每日签到""自动签到""daily check-in"，或希望 WorkBuddy 登录后自动完成签到、不想每天手动点领积分时，应优先使用本技能；WorkBuddy 升级后签到接口失效需要重新校准时也适用。支持一键初始化（CDP 模式下生成带调试参数的桌面启动器）、原生零令牌签到（取令牌三段式：明文登录态主路径 → 旧版 DPAPI 加密存储兜底 → 受控 CDP 回退，无需手动配置）、运行日志与结果反馈、可选企业微信推送通知。脚本幂等，今日已签到自动跳过。仅处理签到/领取积分操作，不涉及查询积分余额或积分规则说明。
version: "2.4.0"
license: MIT
author: Jett
agent_created: true
allowed-tools: Bash, Read, automation_update
---

# WorkBuddy 每日积分签到（workbuddy-auto-checkin）

在**已登录的本机 WorkBuddy 客户端**上自动完成每日积分签到：运行时优先读本机明文登录态取令牌（无需调试端口，零手动配置），失败时受控回退 CDP、幂等（今日已签自动跳过）、可一键初始化。

## 新用户快速开始（5 分钟）

本技能**零配置即可用**：只要你本机已安装并登录 WorkBuddy 客户端（v5.3.8+），不需要改任何配置、不需要桌面快捷方式、不需要开启调试端口。

1. **确认前置**：本机已安装 WorkBuddy 并已登录（登录后客户端会写入明文登录态文件 `workbuddy-desktop.info`）。
2. **环境自检（推荐）**：运行 `python scripts/setup.py --doctor`，查看就绪度报告（✅ 可零配置运行 / ❌ 缺什么一目了然）。
3. **设置每日自动化**：由本技能**两条单时点自动化**负责——`00:05` 与 `12:05` 各一条（拆成两条，避免依赖平台对单条多 `BYHOUR` 的支持，确保每点必然触发），无需手动。首次部署让本 Agent 用 `automation_update` 创建这两条即可。
4. **完毕**：签到幂等，今日已签自动跳过；客户端升级导致接口失效时 `calibrate.py --auto` 自愈。

> 不需要 `.lnk`、不需要调试端口、不需要手动配置——这就是 v2.x 相对旧版的最大简化。需要 CDP 回退或「启动即签到」时再跑 `python scripts/setup.py --cdp`。

## 快速开始

**1. 首次部署（一次性）**

```sh
python scripts/setup.py
```

定位 WorkBuddy。**仅 CDP 模式**生成桌面启动器「WorkBuddy 自动签到.lnk」（带调试参数）；明文模式（默认 `cdp_fallback_allowed=false`）不生成——主路径读明文登录态无需调试端口 / .lnk。需生成时运行 `python scripts/setup.py --cdp`，或将 `config.cdp_fallback_allowed` 置 `true` 后重跑 `setup.py`。

> CDP 模式下 `setup.py` 会**弹性定位** `WorkBuddy.exe`，不再依赖固定盘符：依次尝试 ①显式覆盖（命令行参数 / 环境变量 `WORKBUDDY_EXE_PATH` / `config.workbuddy_exe_path`）→ ②正在运行的进程 → ③注册表卸载项 → ④环境变量驱动的安装根（`%ProgramFiles%` 等，不硬编码盘符）→ ⑤全盘固定驱动器扫描 → ⑥PATH。首次用 `python scripts/setup.py <WorkBuddy.exe路径>` 显式指定后，路径会固化到 `config.json`，其他终端 / 后续调用免重复指定。

**2. 日常签到**

（CDP 模式）用桌面「**WorkBuddy 自动签到.lnk**」启动 WorkBuddy —— 它已升级为「启动即签到」：每次启动会先拉起客户端、待 CDP 就绪后自动检测并签到（今日已签则跳过）。（明文模式，默认）直接运行下面的命令即可签到，无需 .lnk：

```sh
python scripts/checkin_native.py
```

> ⚠️ **关键习惯（仅 CDP 模式）**：若启用了 CDP 回退 /「启动即签到」，后续启动 WorkBuddy **只能**用桌面「WorkBuddy 自动签到」.lnk（带调试参数）。若用普通方式（开始菜单 / 开机自启 / 原桌面快捷方式）打开，客户端不带调试端口，CDP 回退将**静默失败**。明文模式（默认）直接运行 `checkin_native.py` 即可，无需 .lnk。

**3. 每日兜底（可选）**：在 WorkBuddy「自动化」面板建**两条单时点任务**——`00:05` 与 `12:05` 各一条（不要合并为单条多 `BYHOUR` 任务，以免平台不支持时漏触发），prompt 写"运行 `scripts/checkin_native.py` 做原生零令牌签到，按退出码分级处理"。客户端常驻时即可兜底补签。

## 验证签到结果

- `logs/checkin.log` 末尾出现 `签到成功` 或 `今日已签到`；
- `state/last_result.json` 的 `status` 为 `success` / `already_checked` / `skipped`（三者均表示今日已签），`exit_code` 为 `0`；失败/异常时 `status` 为 `auth_failed` / `error` / `no_token` / `activity_inactive` / `gave_up_today` / `feature_removed` / `endpoint_not_found`，对应下方退出码表。

| 退出码 | 含义 | 处理 |
|---|---|---|
| `0` | 成功 / 已签 / 幂等跳过 | 无需处理 |
| `1` | 鉴权失效（401/403），或请求失败（网络异常 / 5xx 已重试仍失败） | 401 重新登录 WorkBuddy；其余查 `logs/checkin.log` |
| `2` | （已弃用，v2.0.0）CDP 不再是签到前置条件（主路径改读明文登录态），该退出码不再产生 | 无需处理 |
| `3` | 其它异常（取不到令牌等） | 查 `logs/checkin.log` |
| `4` | 接口失效 / 功能疑似取消（升级检索后仍无可用接口） | 检查网络与客户端；必要时人工运行 `python scripts/calibrate.py` 复查 |
| `5` | （已弃用）初始化已改为主动检索 + config 已知接口兜底，不再因缺记录退出 | 无需处理 |

## 先决条件

- **系统**：Windows 10 / 11（CDP 回退依赖调试端口与桌面 .lnk，均为 Windows 能力；明文模式仅需能读取本地登录态文件）。
- **Python**：3.8+（核心逻辑仅标准库；`setup.py` 缺 `pywin32` 时自动 `pip install` 一次）。
- **WorkBuddy**：已安装且处于**登录态**（未登录无法签到）。
- **网络**：可访问 `copilot.tencent.com` 签到接口。

## 取令牌：明文优先，DPAPI 旧版兜底，CDP 受控回退（v2.0.0）

`checkin_native.py` 取令牌分三段，**主路径不再依赖 CDP / 调试端口 / .lnk 冷启动**：

1. **明文登录态文件（主路径）** —— WorkBuddy v5.3.8+ 会把登录态写成明文 JSON，纯标准库直接读取：
   - Windows：`%LOCALAPPDATA%\CodeBuddyExtension\Data\Public\auth\workbuddy-desktop.info`（`%APPDATA%` 为回退）
   - macOS：`~/Library/Application Support/CodeBuddyExtension/Data/Public/auth/workbuddy-desktop.info`
   - Linux：`~/.config/CodeBuddyExtension/Data/Public/auth/workbuddy-desktop.info`
   - 取 `auth.accessToken` / `account.uid` / `auth.domain`。**客户端未运行也能读**（只要近期运行并刷新过）。
   - **候选路径枚举**：平台根 × 产品目录（`CodeBuddyExtension` / `CodeBuddy` / `WorkBuddy` / `Tencent-Cloud.coding-copilot`）× 子路径（`Data/Public/auth`、`Data/User/auth`、`Data/auth`、`User/auth`）× 文件名全组合，覆盖改名 / 渠道 / 版本布局差异。
   - **显式覆盖（最高优先级）**：`config.json` 的 `token_file_paths`（完整文件路径列表）或环境变量 `WORKBUDDY_LOGIN_STATE_PATH`（多路径用 `;` 分隔），用于便携版 / 自定义安装 / 未来换落点。
2. **旧版 DPAPI 兜底（仅 Windows，自动）** —— 当明文文件缺失、但 WorkBuddy 旧版（v5.3.8 之前）的加密存储尚在时自动触发：用 Windows DPAPI 解密 `Local State` 中的主密钥，再 AES-GCM 解密 `state.vscdb`（`User\globalStorage\state.vscdb`）中的令牌。需 `cryptography` 库（首次使用惰性安装一次）。受 `config.token_dpapi_enabled`（默认 `true`）开关控制；非 Windows 或旧存储不存在时静默跳过，**不阻断主路径**。
3. **CDP 回退（受控，须取得同意）** —— 仅当明文与 DPAPI 均失败时触发：
   - **交互模式**（有人在）：打印强提示并询问「是否执行 CDP 回退？[y/N]」，**默认 N**（回车即拒绝）。
   - **无人值守**：查 `config.cdp_fallback_allowed`（默认 `false`）。未预先授权则**不回退**，只写入
     `state/pending_cdp_consent_<日期>` 待决标记，**待你上线后再决策**（按日期，次日自动失效，绝不永久关闭）。
   - CDP 回退仍需 `.lnk` 调试端口启动（参数 `--remote-debugging-port=9222 --remote-allow-origins=http://127.0.0.1:9222`，二者缺一不可，仅监听本地回环）；可用 `WORKBUDDY_CDP_PORT` 指定非默认端口。
   - 无人值守判定：`WORKBUDDY_CHECKIN_UNATTENDED=1` 显式标记优先，其次取 `stdin.isatty()`。
     **自动化任务务必显式设该变量**，不可依赖 isatty 判断。

> 令牌**仅在内存中使用**：不落盘、不写入日志、不回显终端；日志只记录长度。
> 改造后 `.lnk` 从「必需」降为「可选增强」——仅在需要 CDP 回退时才有意义。

## 无人值守重试（双时点自动化）

以 `--retry`（或 `WORKBUDDY_CHECKIN_RETRY=1`）启用：可重试失败时，延后 **60~600 秒随机值**后重跑整个任务，尝试上限 **10 次**，总耗时上限 **3600 秒**（次数与总时长双重约束，任一到达即停）。每次重试都**先跑服务端状态预检**，幂等保证不会重复领取。

| 失败类型 | 是否重试 |
|---|---|
| 网络异常 / 超时、服务端 5xx | ✅ 重试 |
| 取令牌失败（文件写入中 / 暂缺） | ✅ 重试（客户端稍后可能写入）|
| CDP 不可用（且明文也未读到） | ✅ 重试 |
| 401 / 403 鉴权失效 | ✅ 重试（每次重试会重读明文登录态，客户端刷新后可恢复）|
| 接口失效 / 端点全 404 且升级检索无产出（退出码 4） | ✅ 重试（端点可能恢复，或升级检索可重新发现）|
| **签到活动已取消或未开启**（状态预检 `data.active=false`） | ❌ **当日放弃，并明确告知用户** |
| config 人工标记 `feature_removed=true` | ❌ 当日放弃（人工已判定功能取消）|

**「当日放弃」的唯一依据是活动确实取消，而不是"试不出来"。**

- 判定信号：状态预检响应中 `data.active` **显式为 `false`**（如本期活动到期未续、下一期未开启）。
  字段缺失、解析失败、非 200 一律**不判定为取消**——不臆断、不误放弃。
- 命中后写 `state/gave_up_<日期>`，并在日志与 `state/last_result.json`
  （`status=activity_inactive`）中**明确告知活动取消这一事实**；
  同日再跑直接跳过，**跨日自动失效**，次日 00:05 正常尝试。

**尝试达上限（10 次）或总耗时达上限（3600 秒）时，不代为放弃** —— 只写
`state/pending_user_decision_<日期>` 提示（含失败原因、尝试次数、最后退出码），留待你判断：
活动是否真的取消了？是否要改配置？是否需要手动补签？该标记跨日自动失效。
沿用既有原则——**不自动持久化 `feature_removed`**，避免误判把自动化永久自关。

## 环境变量

| 变量 | 作用 |
|---|---|
| `WORKBUDDY_CHECKIN_UNATTENDED=1` | 标记无人值守（跳过询问，改查配置授权）；自动化任务**必设** |
| `WORKBUDDY_CHECKIN_RETRY=1` | 启用任务级重试（等价 `--retry`）|
| `WORKBUDDY_CHECKIN_CDP_FALLBACK=1` | 临时授权 CDP 回退（不落盘，优先级高于配置）|
| `WORKBUDDY_CDP_PORT` | CDP 调试端口，默认 9222（仅 CDP 回退分支用到）|
| `WORKBUDDY_EXE_PATH` | 显式指定 `WorkBuddy.exe` 路径（CDP 模式定位用，优先级高于自动发现；可固化进 `config.workbuddy_exe_path`）|
| `WORKBUDDY_ASAR_PATH` | 显式指定 `app.asar` 路径（端点扫描定位用，优先级高于自动发现；可固化进 `config.workbuddy_asar_path`）|
| `WORKBUDDY_CHECKIN_URL` | 覆盖完整签到接口（最高优先级，调试用）|
| `WORKBUDDY_CHECKIN_STATE_DIR` | 重定向 state 目录（默认技能目录下 `state/`），便于隔离测试 |
| `WORKBUDDY_LOGIN_STATE_PATH` | 显式指定明文登录态文件（多路径用 `;` 分隔），作为候选路径的**最高优先级覆盖**，用于便携版 / 自定义安装 / 未来换落点 |

**服务端状态预检**：签到前先 POST `checkin-activity-status` 查询今日状态，仅当**明确读到 `today_checked_in=true`** 时才跳过签到；任何异常、非 200 或字段缺失一律回退正常签到——宁可多一次幂等请求，也绝不漏签。两个易错点：该端点**必须用 POST**（用 GET 一律返回 404）；`checkin-activity-status` 才是真实状态，而 `checkin-status` 返回的是全零的假状态。

## 触发方式

- **启动即签到**：桌面「WorkBuddy 自动签到.lnk」经 `pythonw.exe` 无窗口运行 `launch_and_checkin.py`，以调试参数拉起 WorkBuddy，待 CDP 就绪后运行一次 `checkin_native.py`（已签则跳过）；仅异常（401 / CDP 未就绪 / 接口失效）弹窗提示。
- **常驻双时点兜底**：自动化任务只跑 `checkin_native.py`（每日 00:05 与 12:05 各跑一次），CDP 不可用时退出码 3（no_token）直接结束，**从不杀 WB**。两路均幂等，重复触发不会重复领券。

## 推送通知（可选，默认禁用）

签到结果可推送至企业微信群机器人（markdown 消息），便于无人值守时感知结果。

- **启用**：在 `config.json` 填入 `notify.webhook_url`（企业微信机器人 Webhook 地址，形如 `https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx`），并按需调整 `notify.on`（`success` / `already` / `error` 三类事件的发送开关，默认成功与异常推送、已签不推）。
- **行为**：仅当 `webhook_url` 非空时才实际推送；未配置时所有调用静默跳过，**不影响退出码与主流程**。推送失败（网络/限频）亦被吞掉，绝不阻断签到。
- **限制**：企业微信 markdown 仅支持标题/加粗/引用/列表，不支持表格与代码块；单机器人限频 20 条/分。
- **安全**：Webhook 地址即群写入权限，**切勿提交到公开仓库**。

## 应对更新与功能取消（初始化主动检索 + 失败升级兜底）

WorkBuddy 升级后接口或令牌位置可能变化，甚至取消签到。本技能采用「初始化主动检索为主、失败升级兜底为辅」的自愈模型：

1. **初始化主动检索（首选）**：`checkin_native.py` 在 `recorded_endpoint` 缺失时（首次运行或已清空），自动运行 `calibrate.py --auto` **主动扫描本地 `app.asar`** 提取真实接口并写入 `state/learnings.json`（生成的运行配置）；已记录则跳过，干净安装仅首次扫描。此为无人值守下最可靠的自发现手段。asar 定位已弹性化：不再硬编码盘符，自动从运行中进程、注册表卸载项、环境变量安装根、全固定盘符扫描发现 `app.asar`，跨机器/远程会话可用；也可用 `WORKBUDDY_ASAR_PATH` 或 `config.workbuddy_asar_path` 显式指定。
2. **config 降级兜底**：主动检索无产出（如 asar 未含明文路径）时不退出，降级回退 `config.json` 已知接口（`api_base` + `checkin_paths`）签到。
3. **失败升级检索（仅 404 时触发）**：即便经 recorded/config 已知接口，若所有候选仍返回 404，`checkin_native.py` 才升级做 **asar 主动扫描**二次确认，检索到新接口后重试一次；仍无产出则退出码 4 提示。
4. **被动抓取（v1.7.7 起退出自动链路，仅人工诊断）**：`sniff.py` 不再被自动调用。实测表明 WorkBuddy 的签到请求由守护进程发出、不经过渲染进程网络栈，CDP 网络域无法观测（证据见下方「已知限制」），自动嗅探只是无收益的空等。`build_urls()` 优先级：环境变量 `WORKBUDDY_CHECKIN_URL`（最高优先，调试覆盖）→ `learnings.recorded_endpoint` → `config.checkin_paths` → `learnings.last_known_good`。

`feature_removed` **不再自动持久化**：asar 字节误判不会把自动化永久自关。仅在「已知接口全 404 + 升级检索无产出」时退出码 4 提示，必要时由人工在 `config.json` 手动置 `feature_removed=true`。

手动补录 / 调试：

```sh
python scripts/calibrate.py --auto   # 主动扫描 app.asar，提取并写入真实接口（初始化首选，亦用于手动补录）
python scripts/calibrate.py --check  # 仅探测，不写配置
python scripts/sniff.py              # 【人工诊断】被动抓取；常规抓不到，见下方限制
python scripts/calibrate.py --live   # 同上（若抓到则写入 learnings.json 与 config.json）
python scripts/setup.py --teach      # 一键被动捕获并写入 learnings.json（同为诊断用途）
```

> 接口发现的唯一可靠路径是 asar 主动扫描：初始化即触发，纯定时任务无需用户在场即可完成自愈。被动抓取（`sniff.py` / `--live` / `--teach`）自 v1.7.7 起仅作人工诊断保留，**不要**把它当作兜底依赖。若 `calibrate.py` 在 `app.asar` 找不到签到代码，仅提示、不自动置 `feature_removed`，由人工判断后手动设置。

## 排障

- **切勿在 WorkBuddy 进程树内执行 `taskkill WorkBuddy.exe`**（Bash 工具 / 自动化运行时均属其子树）——会杀掉脚本自身宿主，导致重启/结果无法完成。
- **明文登录态不可读时的兜底**：若明文登录态文件缺失/未刷新、且未授权 CDP 回退（退出码 3，no_token），最稳妥的做法是**先让 WorkBuddy 运行并刷新一次登录态**（明文会被重写），再重跑；或显式授权 CDP 回退（设 `WORKBUDDY_CHECKIN_CDP_FALLBACK=1` 或 `config.cdp_fallback_allowed=true`）后用 `.lnk` 冷启动。本技能不提供需手工抓取令牌的替代脚本。

## 已知限制（端点发现手段）

端点接口的发现**唯一稳健来源是本地 `app.asar` 主动扫描**。以下手段经实测对本应用均不可行，后续版本复查时勿重复投入：

- **被动嗅探（`sniff.py`，CDP 网络域）不可行**——机制正常，但架构上抓不到：
  - 机制层没问题：让渲染进程发出含关键字的 POST，3.1 秒内即可被捕获，`_is_checkin_url` 过滤正确。
  - 但真实签到请求**不经渲染进程**。netstat 与 CDP `SystemInfo.getProcessInfo` 交叉验证：到 `copilot.tencent.com:443` 的连接，渲染进程 **0 条**，而 `main/daemon-app-server-entry.js --stdio` 守护进程 **4 条**；静态代码一致——`httpService.post("/billing/meter/daily-checkin")` 位于守护进程初始化模块（main 进程的 initialize 脚本），渲染侧只做 `getDaemonClientFeature("authClaimDailyCheckin")()` 转交。CDP 网络域仅覆盖渲染进程，故永远观测不到。
  - 触发层无解：渲染进程 `window` 上无任何签出入口，无法主动让客户端发请求。
  - 时机层无价值：静默 45 秒实测渲染进程仅 2 个无关请求，零签到流量，无人值守（00:05）必然空手。
  - 处置：v1.7.7 已将其移出自动链路，仅保留 `python scripts/sniff.py` 供人工排障。

- **CDP 读运行时全局不可行**：签到端点写死在渲染进程的模块作用域/打包闭包内，不挂在 `window` 上。经 `Runtime.evaluate` 枚举 `window` 全局、深扫 `__GENIE_DEFAULT_APP_PROVIDERS__` / `__genieAccountService`、扫描 `localStorage` 均未命中端点字符串（`copilot.tencent.com` / `billing/meter` / `daily-checkin`）；`performance.getEntriesByType('resource')` 因 `app.asar` 走 `file://` 加载返回空。能经 `window` 读到的只有账户/鉴权对象（现有 `token_exprs` 即取此）——**令牌可现场取、端点不可全局读**。
- **Web 前端包直读不可行**：`copilot.tencent.com/` 仅是 API 网关（根重定向到 codebuddy.cn 营销站）；`www.workbuddy.cn` 公开主包仅含定价/营销 UI 与 CDN 资源 URL，不含任何签到端点字符串。公开可抓的网页包是"官网/落地页 SPA"，签到逻辑只在桌面 `app.asar` 内。

> 因此新增/变更端点发现能力时，应优先加固 `calibrate.py` 的 asar 扫描（如应对未来路径混淆：加宽正则、或扫描失败时回退 `config` 已知接口），而非转向运行时读全局或网页包抓取。L3（MITM 代理 / 进程内存扫描 / 调用 App 内部函数）更重更脆，不建议纳入。

## 合规说明

本技能通过 CDP 调用**本机**运行中的 WorkBuddy，属个人设备的本地自动化：不修改客户端、不绕过登录鉴权、令牌不落盘。仅供**个人学习与自用**，请遵守 WorkBuddy 服务条款与平台规则；若官方明确禁止此类自动化，请立即停止使用。请勿用于批量刷取或侵犯他人权益。
