# Codex Token Usage Meter

[English](README.md)

这是一个本地优先的 Codex 插件和 macOS 原生悬浮窗，用于查看 token 使用量、提示词缓存效果、账户限制、Codex credits 以及预估预算消耗（美元）。

![Codex Token Usage Meter 悬浮窗](plugins/token-usage-meter/assets/widget-preview.png)

## 功能

- 悬浮窗默认每 5 秒刷新一次，可在齿轮菜单中选择 1、5、10、30 或 60 秒。
- 支持英文（默认）和简体中文界面，并记住语言选择。
- token 数字使用 `K`（千）、`W`（万）、`M`（百万）和 `B`（十亿）简写，金额保持完整显示。
- 显示输入、未缓存输入、缓存输入、缓存命中率、输出、推理输出和总 token。
- 按模型和服务层级统计，并识别支持的 Fast 模式倍率。
- 每 6 小时自动获取官方模型价格和 Fast 模式倍率，支持离线缓存以及手动立即更新。
- 使用可配置的每 credit 美元价值换算预估 USD。
- 本地 rollout 元数据中包含账户限制时，显示最近的额度状态。
- 完全在本地运行，不需要 API Key，也不会上传对话数据。
- 汇总所有本地活动与归档 Codex 任务，多个窗口并行时不会在不同任务数字之间跳动。
- 排除子代理 rollout 中复制的父任务历史，并忽略重复的累计快照，避免用量被重复统计。
- 悬浮窗关闭期间 Codex 写入的用量，会在重新打开后读取新增记录并补算。
- 小组件使用固定大小的精简快照，并在计数脚本运行时持续读取输出，因此本地历史再多也不会卡在“正在连接 Codex…”。
- 使用 macOS 原生窗口关闭按钮，不再在面板右上角放置自制的关闭符号。
- 同时提供 macOS 原生置顶悬浮窗、终端看板和 JSON 输出。
- 记住悬浮窗位置，并在所有 macOS 空间中显示。

## 工作原理

Codex 会在 `~/.codex/sessions` 和 `~/.codex/archived_sessions` 中写入本地 JSONL rollout 元数据。计量器读取累计 `token_count` 快照，只累加相邻快照之间的非负变化，因此重复事件不会再次计数。子代理 rollout 中复制的父任务历史，以及新版分页历史中的继承基线，都不会计入子任务用量。仅提供单次增量的旧格式日志仍然兼容。全局模式会在 `~/.codex/token-usage-meter/all-index-v3.json` 保存紧凑索引，其中包含用量元数据、文件偏移及变化检测哈希，不包含对话正文。升级时从原始日志重建一次索引并保留旧索引；此后刷新时检查文件标识及少量内容指纹，读取新增内容或重新索引已变更文件。

缓存输入属于输入 token 的子集，推理 token 属于输出 token 的子集，因此不会重复计费。预估费用的计算方式为：

```text
未缓存输入 × 输入费率
+ 缓存输入 × 缓存输入费率
+ 输出 × 输出费率
```

费率单位为每一百万 token 对应的 credits，自动读取 [Codex 官方价格](https://learn.chatgpt.com/docs/pricing#token-rates)及 [Fast 模式说明](https://learn.chatgpt.com/docs/agent-configuration/speed)。自动识别官方新发布的模型行。USD 换算仍采用可配置的每 credit `$0.04` 假设值；实际购买价格和优惠取决于套餐或协议。Codex credits 与 API 账单属于不同计价体系，本工具只估算 Codex credits。

程序运行期间每 6 小时在后台检查价格，发现未知模型时提前检查，但两次尝试至少间隔 15 分钟。联网或文档解析失败时保留最后一次有效缓存，15 分钟后重试。缓存位于 `~/.codex/token-usage-meter/official-prices-v1.json`。首次离线启动使用 2026 年 9 月 11 日的内置快照。当前官方表中已移除的历史模型保留最后一次已验证价格，在 JSON 中标注为历史费率。尚未公布价格的模型或未知 Fast 倍率仍计入 token，但不计入金额，窗口以橙色提示价格未完整。如果官方修改页面结构，解析器可能需要升级，解析失败不会被当成零价格。

金额表示**本地历史用量按当前费率折算的价值**。价格变化后会重新折算，不代表每个历史日期的实际账单。齿轮菜单显示价格检查时间，并提供“立即更新价格”；鼠标悬停金额可查看估算口径及未计价模型。

显示的美元金额只是估算值，不是账单。ChatGPT 套餐中已经包含的使用量不一定会产生额外现金费用。

## 运行要求

- 能产生本地 rollout 元数据的 Codex 桌面端或 CLI。
- Python 3.9 或更高版本。
- 原生悬浮窗需要 macOS 13 或更高版本。
- 只有从 Swift 源码重新编译 App 时才需要 Xcode Command Line Tools。

如果存在兼容的 Codex 数据目录，终端和 JSON 报告也可以在 Linux 上运行。

## 快速使用：独立 macOS App

克隆仓库：

```bash
git clone https://github.com/kafuunochino/codex-token-usage-meter.git
cd codex-token-usage-meter
```

构建唯一的 `~/Applications/Token Usage Widget.app`、启用登录 Mac 后自动启动并立即打开：

```bash
python3 plugins/token-usage-meter/scripts/install_macos.py
```

如果不需要登录自启，可增加 `--no-autostart`。

安装完成后，从“应用程序”或 Spotlight 启动。App 已经内置 token 解析脚本，日常使用不需要再输入终端命令。如果 macOS 因临时签名阻止首次启动，请按住 Control 点击 App，然后选择“打开”。

关闭悬浮窗不会停止 Codex 记录用量。重新打开时会包含关闭期间写入的事件。独立 App 显示整个 Codex 本地安装中所有任务的汇总，而不是某个窗口或任务。如果本地历史很大，首次建立全局索引可能需要一些时间；后续启动会直接复用索引。

点击悬浮窗标题栏右侧的齿轮图标，可以选择界面语言和刷新时间。紧凑的底部信息以“刷新于”开头，并显示完整年月日、星期、时间及当前刷新间隔。

## 安装为 Codex 插件

在克隆后的仓库根目录执行：

```bash
codex plugin marketplace add "$PWD"
codex plugin add token-usage-meter@codex-token-usage-meter
```

新建一个 Codex 任务以加载插件技能，然后输入：

```text
打开实时 token 用量悬浮窗。
```

## 命令行使用

查看当前任务的一次性报告：

```bash
python3 plugins/token-usage-meter/skills/token-usage/scripts/token_usage.py --scope session
```

每 5 秒刷新的终端看板：

```bash
python3 plugins/token-usage-meter/skills/token-usage/scripts/token_usage.py --watch --interval 5 --scope session
```

汇总今天的所有任务：

```bash
python3 plugins/token-usage-meter/skills/token-usage/scripts/token_usage.py --scope today
```

输出 JSON：

```bash
python3 plugins/token-usage-meter/skills/token-usage/scripts/token_usage.py --scope session --json
```

增加 `--refresh-prices` 可立即检查官方价格，`--offline-prices` 可禁用联网并使用缓存或内置价格。`--dollars-per-credit 0.04` 可调整美元换算假设值。不需要 API Key。

## 重新编译 macOS App

```bash
cd plugins/token-usage-meter
./widget/build_widget.sh
```

构建脚本会把 `token_usage.py` 和 `official_pricing.py` 嵌入 App、应用本地临时签名，并更新同一个 `~/Applications/Token Usage Widget.app`，不会在仓库或插件缓存中留下额外 App 副本。

## 隐私和限制

- 用量只读取本地 rollout 元数据。价格更新仅以 HTTPS GET 请求固定的官方公开文档，无需认证，不调用模型 API，不发送本地用量或账户数据。
- 不保存或传输对话正文。
- `session` 范围只显示一个选定任务；如需汇总可使用 `--scope today` 或 `--scope all`。
- 未知模型仍会显示 token 数量，但费用会显示为不可用，不会猜测价格。
- 费率和产品行为可能变化，依赖估算前请检查文中链接的官方来源。
- Codex 插件不能向桌面端左下角原生界面添加自定义字段，因此使用原生置顶悬浮窗作为替代。

## 测试

```bash
python3 -m unittest discover -s plugins/token-usage-meter/tests -v
```
