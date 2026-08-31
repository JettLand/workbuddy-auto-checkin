# Changelog

本文件记录 workbuddy-auto-checkin 的版本变化。所有版本均仅适配 Windows。版本号语义：次版本 / 主版本变动代表新增能力或结构性变更，补丁号变动代表文档 / 表述修正。

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
