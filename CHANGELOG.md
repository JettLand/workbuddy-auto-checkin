# Changelog

本文件记录 workbuddy-auto-checkin 的版本变化。所有版本均仅适配 Windows。版本号语义：次版本 / 主版本变动代表新增能力或结构性变更，补丁号变动代表文档 / 表述修正。

---

## [3.2.0] — 2026-11-23

**设备令牌直发 + 缺卡复核告警；项目脱技能化，收敛为纯后台常驻程序**

- **标签页头字体指定 Segoe UI（阁主令，2026-11-25）**：Tab 控件此前从未设过字体，一直渲染为 Win32 经典 System 位图字体（观感差）；现经 `WM_SETFONT` 为标签页头单独指定 **Segoe UI 约 11.25pt**（略小于正文更协调）。Segoe UI 不含中文字形，中文经 Windows 字体链接自动回退微软雅黑渲染，中西文观感统一。正文 EDIT 保持雅黑 12.75pt 不变。源码态冒烟标签读回自证正常，dist 已热替换 sha256 校验全 OK（未重打包）。
- **标签空白第二根因修复＋真流式追加（阁主令，2026-11-25 二轮）**：40 字节布局修复后真机自证 `[(1, ''), (1, '')]` 仍空——逐项核对消息号发现**第二处 bug：`TCM_GETITEMW` 误用 `0x133D`，该号实为 `TCM_SETITEMW`，正确值＝`TCM_FIRST+60＝0x133C`**。行为探针铁证：INSERTITEMW(0x133E) 插入后用 0x133C 读回 `'当前信息'`（文本一直都在控件里），用 0x133D "读"则 rc=1 返回空（实为 SETITEM 把空缓冲写入清空文本，此后 0x133C 再读也为空）——**自证行反而成了清文本器，把正确插入的标签清掉，UI 因此空白**；历史全部"读回为空"的假象系布局错位与消息号误用两 bug 叠加。已改 `TCM_GETITEMW＝0x133C`，冒烟读回 `[(1, '当前信息'), (1, '历史信息')] sizeof=40` 闭环。**流式改真追加**：由"镜像有变即 SetWindowTextW 全量重写"改为 **`EM_REPLACESEL` 只写增量**（光标不在末尾时不滚动、不打断翻阅；光标在末尾时 `EM_SCROLLCARET` 自动跟随），换页（新 `daemon started`）/镜像超 4MB 截尾/日志轮转才整页重置；占位符机制删除（空页即空白，语义清晰）。
- **标签空白根因修复＋流式更新＋时间戳人性化（阁主令，2026-11-25）**：① **标签空白根因**——阁主质询「是否传参错误」后复核 `commctrl.h` 原型确证：`TCITEMW.lpReserved1/2` 此前误声明为 `LPARAM`（8 字节），原型实为 `UINT`（4 字节），x64 下结构整体错位（48 字节、`pszText` 落 @24），而控件按原型布局（40 字节、`pszText`@16、`lParam`@32）读参——拿到 NULL 指针故**插入"成功"但标签文本恒空、lParam 同步"丢失"、mask（@0 偏移未错位）却正常往返**，全部怪象由单一布局错误完美解释；`sizeof(TCITEMW)=48` 违背原型 40 即铁证。已改为与原型严格一致的 40 字节定义；上文「注入清空 TCM 数据传递」结论系探针共用同一错误布局所致的误判，**予以撤回**。② **日志区流式更新**：刷新逻辑由每 2 秒全量重读重写改为**增量追加**——记录已消费字节偏移，每轮只读新增字节（UTF-8 增量解码，不完整结尾字符留作 carry 拼接下一批），按最后一个 `daemon started` 归页（标记前追加进历史页、标记起重置当前页），镜像有变化才重设控件文本；日志变短视为轮转自动全量重载，镜像超 4MB 截尾。③ **时间戳人性化**：全部日志输出由 `2026-11-25T12:02:14`（isoformat）改为 `2026-11-25 12:02:14`（`payload.py` 的 `log()`/`next run at`/`retry aborted` 与 `tray_host.py` 的 `host.log` 四处统一）。dist 已同步 sha256 校验全 OK（`tray_host.py`＋`payload.py` 热替换，未重打包）。
- **GUI 启动体验三修（阁主令，2026-11-25：居中 / 防重复拉起 / 标签页修复）**：① 启动后主窗口经 `GetWindowRect`＋`SPI_GETWORKAREA`＋`SetWindowPos` **居中到工作区**（排除任务栏，失败静默保持原位）。② **防重复拉起**：启动最前置命名互斥量（`CreateMutexW`，会话局部名 `WorkBuddyCheckin`，句柄存 `_state` 防 GC 提前释放），`ERROR_ALREADY_EXISTS` 时弹信息窗「已在运行，请从系统托盘打开」后退出——实测双实例冒烟第二实例正确拦截。③ **标签页两处实证缺陷修复**：Tab 项此前两次都插在 index=0，导致**默认选中页错位为第 1 页（历史信息）**且「当前信息/历史信息」页序颠倒、`GETCURSEL=1` 时刷新逻辑把文本写进隐藏页——**首次启动内容区空白、定时刷新也刷不出来，须手动切换标签才恢复**；改为 `enumerate` 显式递增索引（第 0 页＝当前信息＝默认选中，探针证实显式索引插入后 `GETCURSEL=0`），`_tab_sel()` 对控件无选中（-1）等异常一律按第 0 页兜底。④ 标签文本改**显式 buffer 保活**插入（`create_unicode_buffer`＋`cast` 后经局部列表保活），并在插入后**读回自证**——`_create_gui` 将控件实际持有的标签文本写入 `host.log`（`tab labels: [...]`），用于真机环境裁决字符串消息是否被破坏。**取证插曲**：本会话探针发现 TCM_INSERTITEMW/GETITEMW/SETITEMW 的文本与 lParam 在 WorkBuddy 会话内 python 进程中全部读回为空，逐层排查（结构布局/偏移扫描/ANSI 变体/完整消息循环/外部真实控件对照）后由进程模块快照定位元凶——**WorkBuddy 沙箱组件 `tsbx.dll`（`sandbox-cli.exe` 子进程注入）按进程树注入并清空控件结构消息的数据传递**（整数消息正常）；exe 由资源管理器/自启动启动不在该注入树内不受影响，真机行为以 exe 内读回自证日志为准。**（2026-11-25 复盘修正：真机自证 `tab labels: ['', '']` 经阁主质询「是否传参错误」后定位真正根因＝上文 `TCITEMW` 结构体声明错误，详见本条目首行记录；「注入清空 TCM」结论不成立，撤回。）**
- **GUI 主窗口替代控制台（阁主令：点 X 仅关窗口不退出，2026-11-25）**：exe 重打包改 `--noconsole`（无控制台窗口，误点 X 导致退出的风险归零），`tray_host.py` 自建 Win32 GUI 主窗口（`WBMain` 类，统一图标、标题 `WorkBuddy 自动签到`）承担原控制台的交互角色——内嵌**双标签页日志区**（阁主令 2026-11-25：Tab 控件 `SysTabControl32`＋两个只读 EDIT，雅黑约 12.75pt；「当前信息」＝最后一个 `daemon started` 起至文件尾即本次运行输出，「历史信息」＝此前运行日志尾部窗口，每 2 秒刷新；日志换行归一为 EDIT 所需 CRLF——文件本为文本模式 CRLF，二次替换曾产生 `\r\r\n` 致全文挤成一行，先归一 LF 再转 CRLF 治根；读取窗口上限 4MB）。**右上角关闭按钮（X，`WM_CLOSE`）仅 `SW_HIDE` 隐藏窗口，程序继续在托盘后台运行**；托盘「还原窗口」/双击图标唤回，「缩小到托盘」隐藏，「退出程序」彻底终止。随架构收敛删除 conhost 时代孤儿（`_visible_window`/`_watch` 最小化自动隐藏线程、`FreeConsole` 退出分支、`GA_ROOTOWNER`/`SW_RESTORE`/`IsIconic` 声明）；`boot.py` 缺文件诊断改 `MessageBoxW` 弹窗（无控制台下 print 不可见）。探针验证全 PASS（Tab+双 EDIT+单页可见 / 两轮刷新周期进程存活 / 同进程 EDIT SetText-GetText CRLF 闭环；注意跨进程 `GetWindowTextW` 对他进程 EDIT 按 MSDN 语义恒返回标题不可作文本断言）。
- **签到成功提示（阁主令，2026-11-25）**：签到受理成功（HTTP 200 首签/重试成功）时 `payload.py` 新增 `_announce_success()`——解析响应体积分与连续天数（兼容顶层与 `data` 内嵌、解析失败回退 `?`），输出明确成功日志行 `checkin SUCCESS: credit +N, streak M days` 并经注入的 `_tray_balloon`（轻量信息气泡，不弹模态窗）提示「今日积分 +N，连续签到 M 天」；`already`（当日早已签过）不弹泡以免骚扰。单测三种响应体全 PASS。
- **网络失败当日重试（阁主裁定，2026-11-25）**：签到因网络异常（连接失败/超时，`post()` 统一捕获后归为 `error`）时当日有限重试——间隔＝10 分钟×重试次数（10/20/…/60 分钟递增，`RETRY_MAX=6` 上限，累计约 3.5 小时）；等待将跨过下一定时点时提前让位（避免阻塞 00:05 定时触发，如深夜启动触发的重试窗口）；全部失败经 `_tray_notify` 发系统模态置顶弹窗，阁主点掉弹窗后主循环恢复，`next_run_at()` 已过即由定时触发自动补签。重试走 `force=False`（先状态预检，已签则 already 不重复 POST）；重试成功后照常走缺卡复核。三场景探针（全败告警/第 3 次重试恢复/让位提前放弃）全 PASS，正常路径限时冒烟零回归。

- **一键重打包脚本 `host/build.py`（阁主令：打包流程零记忆依赖，2026-11-24）**：固化完整打包链——① 从 `tray_host.py` 内嵌常量 `TICON_B64` 解码出完整 ICO 字节落临时目录生成 `icon.ico`（与托盘图标同源，不依赖 Pillow、磁盘不保留图片文件）→ ② 以固化参数（15 项 `--hidden-import` ＋ `--collect-all=cryptography` ＋ `--icon`）调 PyInstaller → ③ 打包后即删临时 ico 与 `build/`、spec 中间产物 → ④ **自动同步 dist 外置文件并逐个 sha256 校验**（治「打包后漏同步 dist」回归）。目标 exe 被运行中进程锁定时 fail-closed 中文提示先退出程序。用法：`<带 PyInstaller 的解释器> host/build.py`。实测全链路：图标像素采样正确（#15803D 绿底白勾透明角）、dist 同步 4 文件 sha256 全 OK、新 exe 限时冒烟全绿（令牌 695 → 400/10001 幂等 → `verify -> ok`）。

- **缺卡根因取证（21/22 显示成功但实际缺卡）**：真机日志证实两日 00:05 签到均 `200 OK` 且 `streak_days` 连续递增（50→51→52），程序侧无任何异常；但服务端活动日历（`checkin-activity-status`，真实状态源）缺这两日。asar 取证发现客户端 2026-11-20 升级（asar 修改时间 11-20 09:09）引入图灵盾设备风控：签到请求须附 `X-Device-Token`（由 `TuringShieldSDK.dll` / N-API 扩展 `turing_sdk.node` 在客户端 main 进程生成），无令牌的签到被服务端「**当场受理、事后不计**」——返回 200 与积分、`streak` 照常递增，但不写入活动日历。程序此前从未附带该头，与缺卡时间线完全吻合（另一先例 11-08）。阁主使用补签卡回填后状态已恢复（streak 53 连续）。
- **设备令牌直发（方案 A）**：本地用系统 Node（v22）直接加载客户端自带的 N-API 扩展（`native/turing-sdk`，`index.cjs` 入口），`configure(channelId, productName, productVersion)` 后 `fetchDeviceToken({usingCachedMessage, includesOutdatedMessage, includesDeviceInfo, timeoutMs})` 独立产出令牌——约 2 秒、**不依赖客户端进程运行**。参数取证：`channelId=109144`、`productName="WorkBuddy"`、`productVersion="5.11.3"`（来源 `app.asar.unpacked/cli/product.json` 的 `turingSdk` 段）。同族形态验证：本地令牌 `v3:` 前缀与客户端进程内存中扫描到的缓存令牌一致（三组只读对照调 `checkin-activity-status` 响应完全一致——服务端对该端点无即时校验，令牌有效性只能由签到后活动日历复核判定）。`payload.py` 新增 `device_token()`（addon 目录与通道参数走 `config.json` 的 `turing_*` 字段 + `WB_CHECKIN_TURING_ADDON` 环境变量覆盖；node 缺失 / 目录缺失 / 产令牌失败时安全退化为无令牌直发并记日志），签到 POST 经 `checkin_headers()` 附 `X-Device-Token`。
- **令牌形态对齐（2026-11-23 深挖）**：进程内存取证推翻早先「长度差异＝message 缓存世代」的推断——参数对照实验（A~D 四组）显示 `includesDeviceInfo` 才是决定性变量：`true` 时 SDK 附加 `#` 分隔的 3 段结构（约 472 字符设备信息段，令牌 ~1170），`false` 时为与客户端同构的**单段**（695~699）；客户端虽在代码里传 `includesDeviceInfo: true`，但其内存实时令牌均为单段（当前世代 683~687，旧世代 695），即 SDK 在客户端进程内实际未附加设备信息段。同时确认客户端后台刷新通道 `scheduleBackgroundRefresh` 用 `includesOutdatedMessage: false`（asar 取证）。`device_token()` 据此改为 `{usingCachedMessage:true, includesOutdatedMessage:false, includesDeviceInfo:false}`，产出与客户端**同构（单段）同世代**（前缀 `AAAAAaIG` 一致；长度随世代在 683~699 漂移，头部含时间编码，属正常时效特性）。configure 三参（`"WorkBuddy"` / `"5.11.3"` / `domestic` variant）经 exe 版本信息与 `turing-sdk-variant.json` 取证确认与客户端完全一致。
- **缺卡复核告警（方案 C）**：`payload.py` 新增 `verify_checkin()`——签到轮次（`ok` 或 `already (server confirmed)`）后查询 `checkin-activity-status`（`checkin-status` 为假状态不可用），今日不在 `today_checked_in=true` 或 `checkin_dates` 时隔 8 秒重试一次再判定，宁可迟报不漏报；仍缺卡则经壳注入的 `_tray_notify`（`NIM_MODIFY + NIF_INFO + NIIF_WARNING` 托盘气泡，不动图标注册）弹出中文告警提醒补签，并记 `verify -> MISSING` 日志。
- **告警升级为双通道（阁主裁定方案 A，2026-11-23）**：气泡约 10 秒自消且凌晨无人值守易错过，`_notify()` 升级为「气泡＋置顶模态弹窗」——气泡照发（`nid` 未注册时跳过、弹窗不受影响），同时弹 `MessageBoxW`（`MB_ICONWARNING | MB_SYSTEMMODAL | MB_TOPMOST | MB_SETFOREGROUND`），**不点击不消失**；后台进程无前台激活权时 `MB_TOPMOST` 实测不置顶，`MB_SYSTEMMODAL`（系统模态＝保持在全部窗口之上）为主旗标。弹窗阻塞 payload 线程直到点击——00:05 后本无其他任务，无实际影响。改动仅 `tray_host.py`（外置热替换，未重打包）。
- **脱技能化（阁主裁定）**：项目已由「技能 + 后台程序」收敛为**纯后台常驻程序**——① `git rm` 删除 `SKILL.md` 与 `scripts/`（v2.x 历史链路共 10 文件，git 历史可溯），清理仓库根级 v2 时代 `logs/`、`state/` 运行态残留；② 卸载两处部署副本（`skills/workbuddy-auto-checkin` 351K 与已死的 `workbuddy-auto-checkin-verify` 24K）；③ **配置链路自足化**（卸载前置，否则程序断粮）：`wbcredential.py` 的 `CONFIG_FILE` 由「技能安装目录 `scripts/config.json`」改为「程序同目录 `config.json`」（`WB_CHECKIN_CONFIG` 环境变量覆盖，动态推导），`config.json` 由 `scripts/` 迁至 `host/` 作为源真值并复制进 `dist/`，交付契约 **4 文件 → 5 文件**；④ `boot.py` 缺失文件检查扩为四项（`tray_host.py`、`payload.py`、`wbcredential.py`、`config.json`，退出码 2 + 中文清单诊断），按约定重打包 exe（打包命令补 `--hidden-import=ctypes --hidden-import=shutil --hidden-import=time`，覆盖 payload 新增 `import shutil` 等运行时依赖）。
- **自足性实证（卸载后冒烟 `RESULT: PASS`）**：部署副本删除后的机器上直接启动 exe——`device token ready len=1174` → 签到 POST 400/10001 → `startup trigger -> already (server confirmed)` → `verify -> ok (in activity calendar)` → `next run at 2026-11-24T00:05:00`，无残留进程；缺文件诊断：仅复制 exe 时退出码 2、中文提示完整列出四个缺失文件与动态程序目录。
- **图灵参数缓存式自适应（阁主裁定，2026-11-24）**：消除配置层硬编码残留——`payload.py` 原有三处代码内 fallback 默认值（`109144`/`"WorkBuddy"`/`"5.11.3"`）与 `config.json` 静态版本号在客户端升级后会过时。改为：配置有效（addon 目录存在且参数齐）直读；失效/缺失按候选安装根（配置路径上溯 → **注册表卸载登记**（`winreg` 枚举 Uninstall 的 `InstallLocation`/`DisplayIcon`，覆盖自定义安装位置）→ 常见位置环境变量拼接）动态发现——`cli/product.json` 单文件取全参数（`turingSdk.channelId` / `applicationName` / `genieVersion`），addon 同树推导，发现成功原子写回 `config.json`（保留其余字段）；发现全败但 addon 可用时以配置值/默认值兜底直发；连 addon 都没有则发警告弹窗＋退化无令牌直发（缺卡复核告警兜底）。四场景探针（首发现写回/有效直读/失效重拉/全败告警）全 PASS，本机自定义安装位置（`D:\Program Files\WorkBuddy`）经注册表发现命中。客户端升级后参数自动跟随，零人工同步。
- **config.json 死配置清理（阁主令，2026-11-24）**：逐字段核查消费者后移除 **17 项 v2 时代残留**（`calibrate.py` 校准链：`last_calibrated_client_version`/`asar_candidates`/`workbuddy_exe_path`/`workbuddy_asar_path`/`passive_capture_seconds`/`feature_removed`；明文令牌文件矩阵：`token_file_names`/`token_file_paths`；从未实现的开关：`cdp_fallback_allowed`/`token_dpapi_enabled`；默认值：`default_uid`/`default_domain`；`--retry` 重试组：`retry_max_attempts`/`retry_delay_min_sec`/`retry_delay_max_sec`/`retry_total_sec`；webhook 通知：`notify`）。配置 51 行精简至 31 行，保留 11 个活字段（`api_base`/`turing_*`×4/`checkin_paths`/`checkin_status_paths`/`auth_headers`/CDP 表达式×3）；`token_exprs` 等经消费者核查为 CDP 兜底专属配置而保留。Python 代码层经函数引用计数核查无死函数，未改动。精简后冒烟通过（令牌 687 单段、有效直读无重发现）。令牌本身零缓存确认：每轮签到现产现用即弃，从不落盘或驻留内存。
- **CDP 兜底退役（阁主裁定方案 A，2026-11-24）**：实测质询暴露「双路凭证」名存实亡——B 路（CDP）触发前提为客户端以 `--remote-debugging-port` 启动并存在有效 `DevToolsActivePort` 端口文件，现实部署中从不成立（现存 9222 端口文件为 v2 时代手动调试遗留物，时间戳 9 月 10 日，当前客户端未监听，`route_b()` 实调 `URLError` 失败）。A 路失败（真正需要兜底的场景）时 B 路同样失败，从未兑现。删除 `wbcredential.py` 的 `route_b`/`_cdp_eval`/`CDP_PORT_FILE` 及孤儿 `urllib.request` import、孤儿 `CONFIG_FILE` 常量（仅 `route_b` 消费），`get_identity()` 简化为单通道＋明确报错（含指引文案）；`config.json` 同步移除 CDP 表达式三项（净减 14 行，8 个活字段）；README 依赖声明（`websocket-client`）、打包清单（`--hidden-import=websocket`，下次重打包生效）、配置表、架构图、排障表、文件树同步收敛。主链路冒烟全绿（`get_identity` 令牌 1515 正常、失败路径报错文案清晰）。
- **托盘菜单新增「开机自启动」勾选项（阁主令，2026-11-24；应阁主令置于菜单首项，分隔线与命令项区分）**：勾选时经 ctypes 直调 advapi32（`RegSetValueExW`/`RegDeleteValueW`）写/删 HKCU `Software\Microsoft\Windows\CurrentVersion\Run` 注册表值 `WorkBuddyCheckin`，取消勾选即删除（重复删除幂等），切换后气泡反馈（轻量 `_balloon`，不弹模态窗）。启动命令动态推导：冻结态＝exe 本体、源码态＝`python boot.py`（含缺失文件诊断），含空格/非 ASCII 路径引号包裹，源码不含绝对目录。实现刻意绕开 `winreg`：该模块不在现 exe 冻结集合内（PyInstaller 只分析入口 `boot.py`），热替换后运行时 import 必崩消息循环——ctypes 直调零重打包即生效，且贴合壳的既有 WinAPI 风格。注册表 API 层探针（开→关→幂等删→还原）全 PASS。
- **统一图标（阁主令，2026-11-24）**：exe 与托盘图标此前均为无图标状态（PyInstaller 默认图 / `IDI_APPLICATION` 系统图），现统一为**绿色圆底＋白色对勾**（签到语义）——单一字节源：Pillow 内存绘制 16/32/48/256 四帧组成多帧 PNG-in-ICO 字节，base64 内嵌 `tray_host.py` 常量 `TICON_B64`（磁盘零图片文件，5 文件契约不变）。托盘运行时经 ctypes 解析 ICO 目录选最接近 `GetSystemMetrics(SM_CXSMICON)` 尺寸的帧，`CreateIconFromResourceEx` 创建 HICON（失败回退系统默认图标）；exe 图标经打包命令 `--icon` 嵌入 PE 资源（PyInstaller API 必须读文件——图标字节打包前临时落盘、打包后即删，构建零残留）。两处消费同一条字节，图案天然一致。属 exe 资源变化，已重打包一次；此后改动仍走热替换。验证：托盘 HICON 创建（16/32px）与 exe 资源提取（`ExtractIconW`）探针均通过。
- **边界**：本地令牌有效性尚未经「明日 00:05 实签 → 次日活动日历入账」闭环验证（服务端为事后判定模式）；若令牌被判无效，行为等同 v3.1.0（当场受理但缺卡），此时复核告警会第一时间弹泡提示补签，不会静默缺卡。（令牌有效性已闭环：见下方 2026-11-24 记。）

---

## [3.1.0] — 2026-11-13

**结构性变更：冻结边界重划——exe 改为薄引导器，界面/业务/凭证全部外置；路径全程动态推导**

- **动因**：阁主指出「每次改动都要重打包 exe，是否壳仍不够薄」。取证显示 v3.0.0 落地后连续多轮改动（托盘回调、控制台输出、Exit 关窗、00:05 定时、宿主窗口隐藏、菜单中文化、悬浮提示、`NIM_DELETE`）**100% 落在 `tray_host.py`**，而 `payload.py` + `wbcredential.py` 业务功能零改动；但打包入口恰是壳本身，导致唯一在变的代码被冻进 13 MB exe，热替换机制留给的却是从未变过的代码。**「薄」不是行数问题，是冻结粒度问题**。
- **方案 A 引导器**：新增 `host/boot.py`（十余行），冻结态取 `sys.executable` 目录、源码态取 `__file__` 目录，以 `runpy.run_path` 加载同目录 `tray_host.py`；`tray_host.py` 277 行**一字未改**（其 `_base()` 本就用 `sys.executable`/`__file__`，`payload.py` 本就用自身 `__file__` 并 `sys.path.insert`，两条路径机制独立于 PyInstaller 的 `sys.path`）。PyInstaller 入口由 `host/tray_host.py` 改为 `host/boot.py`，`dist/` 由 3 文件变 **4 文件契约**（exe + `tray_host.py` + `payload.py` + `wbcredential.py`）。此后**任何业务或界面改动只需替换对应 `.py`，不再重打包 exe**。
- **补充要求：路径动态推导**（阁主）：源码不含任何绝对目录；`boot.py` 增加缺文件诊断（退出码 2 + 中文提示 + 打印当前程序目录），避免搬迁后静默失败。新增**迁移实测**：四文件整体复制到含空格与非 ASCII 的全新目录 `迁移 测试 目录 v1`，启动、托盘注册、签到 POST 全部正常，日志只落在新目录（不回写原 `dist`），且 exe 的 sha256 与原目录完全一致。
- **静态探针测不出的运行时缺口（治本）**：首次冒烟「零日志、无任何报错」，用带硬超时的文件重定向探针捕获控制台，得到 `ModuleNotFoundError: No module named 'ctypes.wintypes'`（进程 8 秒内退出码 1）。根因＝PyInstaller 只静态分析入口 `boot.py`，外置脚本运行时才 `import` 的模块**不会被自动收集**；这也修正了施工前「`tray_host.py` 一字不动即可」的判断——壳代码确实不用改，但打包命令必须补齐依赖。修复为打包命令显式列出三份外置脚本的全部 `--hidden-import`（`ctypes.wintypes`、`urllib.request`、`urllib.error`、`json`、`base64`、`hashlib`、`re`、`subprocess`、`threading`、`datetime`、`runpy`）并保留 `--hidden-import=websocket --hidden-import=cryptography --collect-all=cryptography`。**此缺口不能靠改外置 `.py` 修复，属构建期配置**。
- **验证**（四类冒烟全绿 `RESULT: PASS`）：① 功能等价——`host.log` 出现 `tray_add=1 v4=1`，`daemon.log` 出现 `daemon started` → 签到 POST 400/10001 → `startup trigger -> already (server confirmed)` → `next run at 2026-11-14T00:05:00`，控制台无 `ModuleNotFoundError`/`Traceback`；② 热替换——临时副本只改 `tray_host.py` 注入标记、exe 的 sha256 不变，重启后日志出现标记且签到正常；③ 迁移——见上，含空格与非 ASCII 目录全部通过；④ 缺文件诊断——只放 exe 时退出码 2、中文提示与动态程序目录均正确。四轮均无残留进程。
- **打包命令诊断坑**：捕获 exe 控制台输出时不可用 `stdout=PIPE` 后无条件 `read()`——常驻进程的消息循环不退出会永久阻塞（本会话曾因此中断）；须用文件重定向 + 限时 `poll()` + 主动 `taskkill /T /F`。控制台 stderr 在重定向到文件时按系统代码页 GBK 编码，判读中文提示须以 GBK 解码。
- **文档对齐**：`SKILL.md` 升 3.1.0、架构表改为引导器 + 全外置、补 4 文件契约/路径动态推导/依赖显式冻结三条硬约束；`README.md` 架构树、打包命令（入口与完整 `--hidden-import` 清单）、快速开始、排障表、文件结构同步；部署目录 SKILL.md 同步；次版本变动按约定跑双基线全量审计。
- **边界**：exe 仍绑定 Python 依赖集合——若外置脚本将来引入**新的第三方库**，需重打包一次以冻结该库；仅调用已冻结标准库/已收集依赖的代码改动不受影响。`host/dist/` 为 gitignored 构筑产物，异机部署须按 README 重打包引导器 exe（或用同一 exe + 三份 `.py`）。

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
- **界面中文化与悬浮提示治本（2026-11-13）**：托盘右键三项改为中文「还原窗口」/「缩小到托盘」/「退出程序」；图标提示由 `WorkBuddy Checkin` 改为中文程序名 `WorkBuddy 自动签到`。取证发现提示此前不显示的根因**不是缺文字**——壳设 `NOTIFYICON_VERSION_4` 后标准 tooltip 默认被抑制（微软文档：v4 下须指定 `NIF_SHOWTIP` 才显示 `szTip`），原 `uFlags` 只有 `NIF_ICON|NIF_MESSAGE|NIF_TIP`；补 `NIF_SHOWTIP`(0x80) 后 `uFlags=135`。属纯壳改动，按约定重打包 exe；三文档菜单名与提示文本同步为中文。
- **本轮验证**：中文菜单文本经 `AppendMenuW` → `GetMenuStringW` 宽字符往返无损；结构探针确认 `NIF_SHOWTIP` 位与 `szTip` 中文读回正确；新 exe 冒烟 `tray_add=1 v4=1`、`startup trigger -> already (server confirmed)`、`next run at 2026-11-14T00:05:00`、无残留进程。真机日志另证实 `2026-11-13T00:05:01 schedule trigger -> ok`（每日 00:05 兜底实签到成功）。悬浮显示与菜单文案以真机复测为准。
- **托盘删除常量隐患治本（2026-11-13）**：上轮收尾时按精准修改原则报备的 `tray_host.py` 常量 `NIM_DELETE = 1` 已修正为官方值 `2`。微软 `Shell_NotifyIconW` 定义为 `NIM_ADD=0` / `NIM_MODIFY=1` / `NIM_DELETE=2` / `NIM_SETVERSION=4`；旧值 1 使退出分支实际向 Shell 发出「修改图标」而非「删除图标」，因紧随 `FreeConsole()` + `os._exit(0)`，图标随进程终止而消失，用户侧看不出异常，但退出路径从未真正注销图标，属潜在幽灵图标隐患。**验证**：真实 Shell 往返对照探针——旧值组 `modify(1)=True` 后紧接真 `delete(2)=True`（图标仍在，证明未删除）；新值组 `delete(2)=True` 且二次 `delete(2)=False`（证明首次已真删），`RESULT: PASS`。属纯壳改动，按约定重打包 exe；新 exe 冒烟 `tray_add=1 v4=1`、`startup trigger -> already (server confirmed)`、`next run at 2026-11-14T00:05:00`、无残留进程。
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
