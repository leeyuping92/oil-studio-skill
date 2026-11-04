# Oil Studio Agent Skill：语言选择

中文版入口是 `SKILL.md`，英文版入口是 `en/SKILL.en.md`。App 安装的同一个 Skill 包含两版；Agent 按用户当前对话语言选择入口，用户明确指定时以用户要求为准。两个入口的任务、命令、提案格式、权限边界和确认流程相同，不同时执行两遍。

英文入口加载 `en/references/`，中文入口加载 `references/`。两版都覆盖中文和英文口播；指令语言不等于音频语言。转录默认使用工程的识别语言，需要覆盖时用 `oilstudio transcribe <project> --locale en-US` 或 `--locale zh-CN`。命令行帮助、进度与错误默认跟随 App 的语言，可在任意命令上指定 `--lang en` / `--lang zh-Hans`；这不会更改用户的 App 设置，也不改变 JSON 字段名。

For English instructions, start at [SKILL.en.md](en/SKILL.en.md). The app installs both languages together. Choose one workflow based on the user's conversation language; do not run both. To override command output language without changing app preferences, use `--lang en` or `--lang zh-Hans`. Speech language is separate: use `transcribe --locale en-US` or `--locale zh-CN` when needed.

`en/SKILL.en.md` 与中文入口放在同一个包内，作为同一个已安装 Skill 的替代语言入口；它不是第二个需要安装或自动发现的 Skill。两版参考资料分别存放，便于按当前语言读取。

精剪默认检查重说、口误和可切开的犹豫音；句中的“呃、嗯”也会按词义和接缝判断。每个检测候选都有删除、保留或待复核的结论；校验方案合法不代表口头禅已全部处理。包内提供可选的 Python 3 覆盖检查器，仅使用标准库、只读分析文件，不修改工程，也不代替声音和画面判断。没有 Python 时仍可按相同规则人工核对，不影响 CLI 主流程。

## 安装与配置

在 Oil Studio 的「设置 › AI Agent」中安装 Agent 支持，再运行 `oilstudio status` 检查命令行与 Skill。App 会把两种语言一起分发，无需分别安装。需要更新时重新打开 App；不覆盖用户自行创建的同名 Skill。

在 App 的「设置 › 通用」选择界面语言，重启后生效；CLI 默认读取同一选择。临时覆盖只用 `--lang`，不写偏好。音频语言默认跟随界面语言，也可在生成字幕时单独选择，或给 `transcribe` 指定 `--locale`。

命令行自动识别优先使用所选地域已配置的云端 API Key，其次是已安装的本机 Whisper，再考虑已安装的系统模型；生成字幕需要至少一种可用模型。用 `--engine whisper` 或 `system` 可以明确要求本地处理。API Key 在 App「语音识别」设置中配置，Skill 不接收、存储或回显密钥。

## 数据、权限与边界

适用于 macOS 15 及以上的 Apple 芯片 Mac 和 Oil Studio 录屏工程。普通 MP4/MOV 的剪辑或加字幕不走这个 Skill。Agent 只通过 `oilstudio` 访问工程，不直接读写包内文件；旧录屏工程先只读导入，原件不改动。章节进度支持顶部和底部，AI 写入后直接生效，可在 App 中修改或删除。

录制权限由用户在系统和 App 中授予，只录用户指定的测试或演示窗口。本机识别不上传音频；自动模式选中已配置的百炼或明确指定百炼时，会上传到所选地区。初始字幕由 `subtitles generate` 经 App 生成、保存并可撤销，`transcribe` 仅准备转录缓存。工程配置通过 `settings schema/get/apply` 操作，导出支持 MP4/GIF 与工程已有导出选项。其他修改通过提案提交；普通工程默认等待用户确认，Agent 自己录的工程或用户明确开启自动应用的工程直接生效并可撤销。
