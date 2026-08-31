# workbuddy-auto-checkin

> WorkBuddy 每日积分签到自动化技能（仅 Windows）。

在**已登录的本机 WorkBuddy 客户端**上自动完成每日积分签到。默认**零配置**：优先读取本机明文登录态文件取令牌，无需调试端口、无需桌面快捷方式、无需手动配置。失败时受控回退 CDP；签到幂等，今日已签自动跳过。

- 版本：**v2.4.1**
- 许可：**MIT**
- 作者：Jett
- 平台：Windows 10 / 11（明文模式仅需能读取本地登录态文件；CDP 回退依赖调试端口与桌面 `.lnk`，为 Windows 能力）

---

## 特性

- **明文优先取令牌**：WorkBuddy v5.3.8+ 把登录态写成明文 JSON，纯标准库直接读取；**客户端未运行也能签**（只要近期运行并刷新过文件）。
- **三段式容错**：`明文登录态` → `旧版 DPAPI 加密存储兜底` → `受控 CDP 回退`，主路径不依赖 CDP / 调试端口 / `.lnk` 冷启动。
- **幂等**：本地标记 + 服务端状态预检双重保障，重复触发不会重复领券。
- **自愈**：客户端升级导致接口失效时，`calibrate.py --auto` 主动扫描本地 `app.asar` 重新发现真实端点。
- **无人值守**：支持 `--retry` 任务级重试、退出码分级处理、待决提示，自动化任务可无人参与运行。
- **可选企业微信推送**：签到结果可推送至企业微信群机器人（默认禁用，需自填 Webhook）。
- **弹性定位**：`WorkBuddy.exe` 与 `app.asar` 的发现不再硬编码盘符，跨机器 / 远程会话 / 自定义安装位置均能定位。

---

## 架构概览

```
签到主流程（checkin_native.py）
  │
  ├─ 取令牌（acquire_identity，三段式）
  │     ① 明文登录态文件  ── 主路径，无需 CDP / .lnk
  │     ② 旧版 DPAPI 兜底  ── 仅 Windows，旧版加密存储尚在时自动触发
  │     ③ CDP 回退（受控）── 仅当 ①② 均失败且已授权
  │
  ├─ 端点发现（自愈）
  │     初始化主动扫描 app.asar → 写入 state/learnings.json
  │     config 已知接口兜底 → 404 才升级二次扫描
  │
  └─ 签到 POST（幂等）
        本地已签标记短路 → 服务端状态预检 → 签到 POST
```

令牌**仅在内存中使用**：不落盘、不写日志、不回显终端；日志只记录长度。

---

## 先决条件

- **系统**：Windows 10 / 11
- **Python**：3.8+（核心逻辑仅标准库；`setup.py` 缺 `pywin32` 时自动 `pip install` 一次）
- **WorkBuddy**：已安装且处于**登录态**（未登录无法签到）
- **网络**：可访问 `copilot.tencent.com` 签到接口

---

## 新用户快速开始（5 分钟）

1. **确认前置**：本机已安装 WorkBuddy 并已登录（登录后客户端会写入明文登录态文件 `workbuddy-desktop.info`）。
2. **环境自检（推荐）**：运行 `python scripts/setup.py --doctor`，查看就绪度报告（✅ 可零配置运行 / ❌ 缺什么一目了然）。
3. **设置每日自动化**：由本技能**两条单时点自动化**负责——`00:05` 与 `12:05` 各一条（拆成两条，避免依赖平台对单条多 `BYHOUR` 的支持，确保每点必然触发），无需手动。首次部署让本 Agent 用 `automation_update` 创建这两条即可。
4. **完毕**：签到幂等，今日已签自动跳过；客户端升级导致接口失效时 `calibrate.py --auto` 自愈。

> 不需要 `.lnk`、不需要调试端口、不需要手动配置——这就是 v2.x 相对旧版的最大简化。需要 CDP 回退或「启动即签到」时再跑 `python scripts/setup.py --cdp`。

---

## 日常使用

**首次部署（一次性）**

```sh
python scripts/setup.py
```

定位 WorkBuddy。**仅 CDP 模式**生成桌面启动器「WorkBuddy 自动签到.lnk」（带调试参数）；明文模式（默认 `cdp_fallback_allowed=false`）不生成——主路径读明文登录态无需调试端口 / `.lnk`。

**日常签到（明文模式，默认）**

```sh
python scripts/checkin_native.py
```

> ⚠️ 若启用了 CDP 回退 /「启动即签到」，后续启动 WorkBuddy **只能用**桌面「WorkBuddy 自动签到」.lnk（带调试参数）。用普通方式（开始菜单 / 开机自启 / 原快捷方式）打开则不带调试端口，CDP 回退会静默失败。明文模式直接运行 `checkin_native.py` 即可，无需 `.lnk`。

---

## 配置

### `config.json` 关键字段

| 字段 | 默认值 | 说明 |
|---|---|---|
| `cdp_fallback_allowed` | `false` | 是否预先授权 CDP 回退（无人值守场景） |
| `token_dpapi_enabled` | `true` | 旧版 DPAPI 兜底开关 |
| `token_file_paths` | `[]` | 明文登录态文件显式覆盖（完整路径列表） |
| `token_file_names` | `["workbuddy-desktop.info", "Tencent-Cloud.coding-copilot.info"]` | 候选文件名 |
| `workbuddy_exe_path` | `""` | `WorkBuddy.exe` 显式路径（CDP 模式，固化用） |
| `workbuddy_asar_path` | `""` | `app.asar` 显式路径（端点扫描，固化用） |
| `asar_candidates` | `[]` | 旧式硬编码 asar 候选（已废弃，改由弹性发现接管） |
| `notify.webhook_url` | `""` | 企业微信机器人 Webhook（空=禁用推送） |
| `notify.on` | `{success, already, error}` | 三类事件推送开关 |

### 环境变量

| 变量 | 作用 |
|---|---|
| `WORKBUDDY_CHECKIN_UNATTENDED=1` | 标记无人值守（跳过询问，改查配置授权）；自动化任务**必设** |
| `WORKBUDDY_CHECKIN_RETRY=1` | 启用任务级重试（等价 `--retry`） |
| `WORKBUDDY_CHECKIN_CDP_FALLBACK=1` | 临时授权 CDP 回退（不落盘，优先级高于配置） |
| `WORKBUDDY_CDP_PORT` | CDP 调试端口，默认 9222（仅 CDP 回退分支用到） |
| `WORKBUDDY_EXE_PATH` | 显式指定 `WorkBuddy.exe` 路径（优先级高于自动发现） |
| `WORKBUDDY_ASAR_PATH` | 显式指定 `app.asar` 路径（优先级高于自动发现） |
| `WORKBUDDY_CHECKIN_URL` | 覆盖完整签到接口（最高优先级，调试用） |
| `WORKBUDDY_CHECKIN_STATE_DIR` | 重定向 state 目录（默认技能目录下 `state/`） |
| `WORKBUDDY_LOGIN_STATE_PATH` | 显式指定明文登录态文件（`;` 分隔），候选路径最高优先级覆盖 |

---

## 退出码

| 退出码 | 含义 | 处理 |
|---|---|---|
| `0` | 成功 / 已签 / 幂等跳过 | 无需处理 |
| `1` | 鉴权失效（401/403），或请求失败（网络 / 5xx 重试仍失败） | 401 重新登录；其余查 `logs/checkin.log` |
| `2` | （已弃用，v2.0.0）不再产生 | — |
| `3` | 其它异常（取不到令牌等） | 查 `logs/checkin.log` |
| `4` | 接口失效 / 功能疑似取消 | 检查网络与客户端；必要时人工 `calibrate.py` 复查 |
| `5` | （已弃用）不再产生 | — |

---

## 无人值守重试

以 `--retry`（或 `WORKBUDDY_CHECKIN_RETRY=1`）启用：可重试失败时，延后 **60~600 秒随机值**后重跑，尝试上限 **10 次**，总耗时上限 **3600 秒**（次数与总时长双重约束）。每次重试都先跑服务端状态预检，幂等保证不重复领取。

**「当日放弃」的唯一依据**是签到活动确实取消（状态预检 `data.active` 显式为 `false`）或人工标记 `feature_removed=true`；尝试达上限不代为放弃，只写 `state/pending_user_decision_<日期>` 留待用户决策。

---

## 合规说明

本技能通过 CDP 调用**本机**运行中的 WorkBuddy，属个人设备的本地自动化：不修改客户端、不绕过登录鉴权、令牌不落盘。仅供**个人学习与自用**，请遵守 WorkBuddy 服务条款与平台规则；若官方明确禁止此类自动化，请立即停止使用。请勿用于批量刷取或侵犯他人权益。

> **分发提示**：本项目以**私有仓库**分发，规避公开分发条款。企业微信 `notify.webhook_url` 即群写入权限，**切勿提交到公开仓库**。`state/`、`logs/`、`dist/`、`__pycache__/` 已被 `.gitignore` 排除，不会入库。

---

## 文件结构

```
workbuddy-auto-checkin/
├── SKILL.md              # 技能定义（触发词、流程、退出码、合规）
├── README.md            # 本文件（项目摘要）
├── CHANGELOG.md         # 版本变化明细
├── .gitignore           # 排除运行态与构建物
├── scripts/
│   ├── checkin_native.py  # 签到主流程（取令牌三段式 + 幂等 + 重试）
│   ├── tokenfile.py       # 明文 / DPAPI 取令牌
│   ├── wbcommon.py        # 共享工具（状态、配置、安装位置发现、幂等标记）
│   ├── calibrate.py       # asar 主动扫描端点发现
│   ├── setup.py           # 初始化、自检（--doctor）、.lnk 生成、弹性定位
│   ├── launch_and_checkin.py  # 「启动即签到」包装（.lnk 调用）
│   ├── sniff.py           # 被动嗅探（仅人工诊断，已移出自动链路）
│   ├── notify.py          # 企业微信推送（可选）
│   └── config.json        # 运行配置
├── state/               # 运行态（learnings.json / last_result.json / 标记）— gitignored
├── logs/               # 运行日志 checkin.log — gitignored
└── dist/               # 发布包 workbuddy-auto-checkin.zip — gitignored
```

---

## License

[MIT](LICENSE) — 详见仓库 LICENSE 文件（如缺失，按 MIT 许可理解：可自由使用、修改、分发，作者不对使用后果负责）。
