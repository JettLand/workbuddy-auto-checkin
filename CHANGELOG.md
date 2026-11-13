# Changelog

本文件记录 workbuddy-auto-checkin 的版本变化。所有版本均仅适配 Windows。版本号语义：次版本 / 主版本变动代表新增能力或结构性变更，补丁号变动代表文档 / 表述修正。

---

## [3.0.0] — 2026-11-12

**破坏性变更：执行体重建，v2.x 明文链路整体废弃**

- **根因**：客户端把 `workbuddy-desktop.info` 的 `auth.accessToken` 改为 `$wbEncrypted` 加密信封（dict）；旧 `tokenfile.py:119` 只接受明文 `str`，主文件被跳过并退回 `expiresAt=2026-10-29` 的备用明文令牌，自 10-30 起持续 401。端点未漂移、`feature_removed=false`、重新登录无效；旧日志「请重新登录」为误导。
- **新执行体 `host/`**：独立后台常驻程序，不依赖客户端保持运行、不依赖其内置自动签到、不依赖 WorkBuddy 自动化任务。`tray_host.py` 为纯界面壳（命令提示符窗口＋系统托盘＋右键还原／缩小／退出，`runpy` 运行时加载外部脚本）→ `dist/wb-checkin-host.exe`；`payload.py` 负责启动强制签到、每日 00:05 常驻兜底、状态预检幂等、POST 签到；`wbcredential.py` 负责凭证。**业务变更只替换 `.py`、不重打包 exe**，仅改壳才需重打包。
- **凭证双路**（阁主裁定）：A 主＝取 32B 派生密钥自解 `sym-v1` 字段信封（AES-256-GCM，nonce 12B / tag 16B，`key=SHA256(atRestSecretKey)`，`keyId=SHA256(key)[:16]`）取当前有效令牌，过期硬阻断；B 兜底＝CDP `Runtime.evaluate`。双路失败明确报错，**不再静默退回过期备用明文文件**。
- **完全离线自足**（阁主授权）：派生密钥经 `CryptProtectData` 按当前 Windows 用户加密缓存于 `%LOCALAPPDATA%/WorkBuddyCheckin/keycache.json`（按 keyId 双重校验、原子替换）；首次从客户端进程内存只读扫描 44B canonical base64 调取并写缓存。客户端完全关闭仍可签到（截至令牌 `expiresAt`）。**明文令牌与明文密钥均不落盘**。
- **首轮报障修复**：壳兼容 `WM_CONTEXTMENU`；菜单移到主消息循环避免窗口过程重入；Restore 改 `SW_RESTORE`；新增 `logs/host.log`。`payload.log()` 同步 `print(flush)` 并输出 `next run at`，解决控制台空白。修过一处回归：`TrackPopupMenu` 不能以控制台窗口为 owner（conhost 拥有），已回退。
- **托盘右键复障的治本修复**：首轮黑盒探针直接向窗口过程投递消息，绕过了 Shell 通知区域链路，造成「全通过」假象；用户真机日志显示图标注册成功却无任何托盘消息。逐层取证定位三处确凿缺陷并修复：① `NIF_MESSAGE` 常量误写为 `4`（官方为 `1`，`4` 实为 `NIF_TIP`），致 `uFlags` 只启用图标与提示、**从未启用回调消息标志**，Shell 因此不转发任何托盘消息；② 图标挂在 message-only 窗口上，通知区域无法向其投递；③ 只解析自定义回调里的通知码，不处理直接投递的 `WM_CONTEXTMENU` 窗口消息。修复为：0×0 可见工具窗口（真实顶层、可取得菜单前台焦点）、`NIF_MESSAGE=1`、`NIM_SETVERSION` 设 `NOTIFYICON_VERSION_4`、回调与直接消息双通道、菜单请求去重排空，并给图标加 `WorkBuddy Checkin` 提示便于在溢出面板辨认。
- **启动触发点**：`payload.py` 把「启动即执行一轮」显式化为独立 `startup` 触发点，与 `schedule` 触发点以日志标签区分。**第三轮报障后改为启动强制签到**：`run_once(force=True)` 跳过状态预检、直接发签到 POST；实测当日重复签到返回 HTTP 400 + 业务码 10001「今天已签到，请明天再来」，据此归类为 `already (server confirmed)`，避免把服务端正常幂等答复误记为 `error`。定时轮次保持状态预检幂等不变。
- **托盘菜单补齐**：新增 `Minimize to tray`（右键缩小到托盘），菜单为 Restore / Minimize to tray / Exit 三项；同时收窄托盘诊断日志，只记录关键消息码，避免鼠标移动产生的 `WM_MOUSEMOVE` 刷屏。
- **实跑验证**：`get_identity()` 取到有效令牌 len=1515；模拟客户端完全关闭 0.0s 取到同一令牌；托盘真机日志已证实 `tray cb=0x7B` → `menu cmd=1` 生效。第三轮验证：`force=False` 返回 `already`，`force=True` 打印签到 POST 的 400 响应并返回 `already (server confirmed)`；菜单单元探针实测三项且 `cmd=2` 使测试窗口不可见、`cmd=1` 恢复可见；打包后 exe 冒烟输出 `daemon started → checkin ... → startup trigger -> already (server confirmed) → next run at`，`tray_add=1 v4=1`，无残留进程。**验证边界**：本会话合成鼠标／键盘注入不到其他进程窗口（光标移动生效但点击不达），端到端点选菜单项由真机日志佐证（`tray cb=0x7B` → `menu cmd=1` 还原、`cmd=3` 退出均生效）；首轮「探针全通过」的结论已按此更正。
- **废弃声明**：`scripts/` 旧链路（明文 → 旧版 DPAPI → 受控 CDP、`--retry`、退出码分级、两条单时点自动化）保留源码但**不再作为签到执行体**；配套 `workbuddy-auto-checkin-verify` v1.2.1 仅覆盖该历史链路，前置条件已失效，不适用于 v3.0.0。端点发现仍以 `calibrate.py` 的 asar 主动扫描为唯一可靠来源。
- **第四轮报障修复（退出与定时）**：① 真机日志显示 `cmd=3` 已命中但窗口仍在——旧退出分支只删托盘图标并 `DestroyWindow` 隐藏工具窗口，命令提示符窗口由 conhost 持有，销毁不可见窗口不会关闭它；改为退出分支显式 `FreeConsole()` 释放控制台 + `os._exit(0)` 强制终止进程，不再依赖消息循环优雅退出。② 定时收敛为**每日 00:05 唯一兜底点**：原 `SCHEDULE` 有 00:05/12:05 两点，且主循环 `wait = min(seconds_to_next(), 6*3600)` 醒后无条件执行 `schedule`，真机日志 `next run at 21:58:39`（整 6 小时）证实实际是每 6 小时假触发；改为按绝对目标时刻 `next_run_at()` 分段睡眠（6h 仅作最长单次睡眠上限），到点才触发一轮。③ 顺带消除浮点秒数反推时刻造成的 `00:04:59` 一秒漂移。
- **第四轮验证**：虚拟时钟单元探针实测 `next_run_at()` 五个时刻均精确指向下一个 `00:05:00`、`startup` 一次 + `schedule` 三次严格间隔 24h、日志无 `00:04:59`；退出子进程探针实测退出码 0、`FreeConsole` 真调用、控制台窗口销毁；打包后 exe 冒烟 `daemon started → checkin ... -> 400 → startup trigger -> already (server confirmed) → next run at 2026-11-13T00:05:00`，`tray_add=1 v4=1`，无残留进程。
- **第五轮报障修复（缩小到托盘）**：真机日志显示 `cmd=2` 已命中并打印 `minimized to tray`，但窗口只是最小化、并未隐藏。取证发现本机默认终端为 Windows Terminal：`GetConsoleWindow()` 返回的是 0×0 的 `PseudoConsoleWindow` 伪窗口（owner 为 `CASCADIA_HOSTING_WINDOW_CLASS` 宿主窗口），`SW_HIDE` 只作用在不可见伪窗口上，用户真正看到的宿主窗口不受影响；同时 `_watch()` 检测伪窗口的 `IsIconic` 恒为 false，「手动最小化自动隐藏」也从未生效。修复为新增 `_visible_window()`，用 `GetAncestor(c, GA_ROOTOWNER)` 沿 owner 链定位可见窗口，`_restore` / `_minimize` / `_watch` 统一改用它；传统 conhost 下 `GetConsoleWindow()` 自身即顶层窗口，行为不变。属纯壳改动，按约定重打包 exe，托盘诊断日志增记目标窗口句柄。
- **第五轮验证**：独立控制台探针实测 `GetAncestor` 定位到 `CASCADIA_HOSTING_WINDOW_CLASS`（rect 70,78–1199,713）；调用真实 `_minimize()` 后该窗口 `visible=false / iconic=false`（真隐藏而非最小化），`_restore()` 后 `visible=true`；把宿主窗口最小化后 `_visible_window()` 报告 `iconic=true`，`_watch` 判定生效。打包后 exe 冒烟 `tray_add=1 v4=1`、`startup trigger -> already (server confirmed)`、`next run at 2026-11-13T00:05:00`，无残留进程。托盘菜单点选仍以真机复测为准。
- **文档对齐**：`SKILL.md` / `README.md` 重写为 v3.0.0 架构并同步部署目录；主版本变动按约定跑全量审计。
- **边界**：DPAPI 绑定当前 Windows 用户（防其他用户/离线磁盘，**不防同一用户下的恶意进程**）；令牌到期或 at-rest 密钥轮换后，需客户端运行并登录一次刷新登录态与缓存。

---

## [2.4.1] — 2026-08-31

**死代码清理（等价替换，无能力变更）**

- `scripts/wbcommon.py`：删除零引用的真死代码——未使用的 `import hashlib`，以及仅定义、从未被调用的 `read_pending_cdp_consent` / `clear_pending_cdp_consent` / `read_pending_user_decision` 三个待决标记读写函数（实际被调用的是 `write_pending_cdp_consent` / `write_pending_user_decision` / `clear_pending_user_decision`，均保留）。
- `SKILL.md` frontmatter 补 `target_platform: windows` 与 `target_agent: workbuddy` 声明（消除 portability 误报，上轮已落地，本次随版本号固化）。
- 本次为补丁号变动（等价替换，未新增能力维度），仅 `doc` 检查器审计通过。

---

## [2.4.0] — 2026-08-31

**弹性化收尾 + 私有仓库发布就绪**

- **自动化拆分**：将单条多 `BYHOUR` 自动化拆分为两条单时点自动化（`00:05` 与 `12:05`），不再依赖平台对单条多 `BYHOUR` rrule 的支持，确保每点必然触发；agent token 消耗维持每日 2 次。
- **asar 弹性发现**：`calibrate.find_asar` 不再硬编码 `D:/`、`C:/` 盘符，改为复用新增的 `wbcommon.discover_workbuddy_bases()` 多层发现（运行中进程 → 注册表卸载项 → 环境变量安装根 → 全盘固定驱动器扫描），并支持 `WORKBUDDY_ASAR_PATH` / `config.workbuddy_asar_path` 显式覆盖。
- **find_exe 复用共享发现**：`setup.find_exe` 重写为复用 `discover_workbuddy_bases()`，删除与之重复的 `_run_cmd` / `_ps_cmd` / `_fixed_drives` 死代码，消除与 `find_asar` 的逻辑漂移；PATH 兜底改用 `shutil.which`。
- **清理硬编码盘符**：清空 `config.json` 与 `wbcommon.py` 中 `asar_candidates` 的写死 `D:/Program Files/...`、`C:/Program Files/...` 条目。
- **新增 `.gitignore`**：排除 `state/`、`logs/`、`dist/`、`__pycache__/`，本机接口记录与运行日志不入库。
- **发布**：以私有仓库（`github.com/JettLand/workbuddy-auto-checkin`）分发，规避公开分发条款，合规风险回落至 🟠。

---

## [2.3.0] — 2026-08-30

**CDP 模式 WorkBuddy.exe 弹性定位**

- `setup.find_exe` 由硬编码三盘符扫描改为**弹性多层发现**：显式覆盖（命令行参数 / 环境变量 `WORKBUDDY_EXE_PATH` / `config.workbuddy_exe_path`，首次指定即固化到 config）→ 运行中进程 → 注册表卸载项 → 环境变量安装根（不硬编码盘符）→ 全盘固定驱动器扫描 → PATH。
- 修复原文档写了却未接上的 `python setup.py <路径>` 显式覆盖。
- 修复中文系统下 PowerShell 输出 `UnicodeDecodeError` 导致进程路径被截断的隐患（`_run_cmd` 改抓字节 + 容错解码、PowerShell 强制 UTF-8）。

---

## [2.2.0] — 2026-08-30

**明文候选路径升级 + 新用户优化**

- **明文候选路径矩阵扩展**：产品目录 × 子路径 × 文件名全组合候选，并支持 `config.token_file_paths` 与环境变量 `WORKBUDDY_LOGIN_STATE_PATH`（`;` 分隔）显式覆盖（方案 A）。
- **新用户优化**：`setup.py` 新增 `self_check()` / `--doctor` 就绪度自检；SKILL.md 重写「新用户快速开始」，强调零配置、无需 `.lnk` / 调试端口。
- **改名联动**：配套验证技能 `workbuddy-checkin-verify` → `workbuddy-auto-checkin-verify`（6 处引用同步）。
- 注：本次为体验 / 文档层优化，未新增能力维度，但依发布惯例升到 v2.2.0。

---

## [2.1.0] — 2026-08-30

**DPAPI 兜底落地 + 企业微信推送**

- **DPAPI 完整落地**：三段式取令牌（明文 → DPAPI 旧版兜底 → CDP 受控回退）；`tokenfile.py` 新增 `read_identity_dpapi()` 等，惰性安装 `cryptography`。
- **企业微信推送**（接口预留 → 落地）：`notify.py` 支持 markdown 推送，`webhook_url` 空时静默跳过。

---

## [2.0.0] — 2026-08-30

**明文主路径重构（核心架构变更）**

- **主路径改为读明文登录态**：WorkBuddy v5.3.8+ 将鉴权令牌改为 `LOCALAPPDATA/CodeBuddyExtension/Data/Public/auth/workbuddy-desktop.info` 明文存储，旧 DPAPI Roaming 路径废弃。
- **CDP 从「前置条件」降为「受控回退」**：仅当明文与 DPAPI 均失败且已授权时触发；`.lnk` 从必需降为可选增强。
- **退出码 2 弃用**：CDP 不再是签到前置，该退出码不再产生。
- **自愈模型定型**：以 asar 主动扫描为端点发现的唯一可靠来源；被动嗅探（`sniff.py`）移出自动链路，仅作人工诊断。

---

## [1.9.0] 及之前

- **1.9.0**：技能改名 `workbuddy-checkin` → `workbuddy-auto-checkin`（区分 GitHub 同名第三方技能）；补记 `WORKBUDDY_CHECKIN_STATE_DIR`；修复改名暴露的 `setup.py` 快捷方式幂等缺陷。
- **1.8.0**：建立 TRACE 自评基线；明确「不自动持久化 `feature_removed`」原则。
- **1.x（更早）**：初始版本，依赖 CDP + `.lnk` 冷启动 + DPAPI Roaming 存储取令牌；被动嗅探作为端点发现手段（后于 1.7.7 移出自动链路）。

> 注：1.8.0 之前的逐版本细节已随历史快照归档，如需追溯可查阅项目记忆 `MEMORY.md` / 日期日志。
