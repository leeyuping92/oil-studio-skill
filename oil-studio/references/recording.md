# 录制

用命令行录一段操作演示时的规矩。返回 [SKILL.md](../SKILL.md)。

按拍编排网页演示、解剖卡片或重点缩放时，使用下面的[网页 Playbook](#网页-playbook)。该脚本只用网页自动化 Node 接口控制页面，严禁使用 Computer Use。演示默认不加字幕，除非用户明确要求。

## 分工

- `oilstudio record` 负责准备窗口与控制录制；点击和移动可选择用 `--perform` 原生执行。
- 操作桌面应用时，按手头工具选择最稳的方式：
  1. **若你有自带且好用的 Computer Use 工具**：可直接操作目标窗口（真实鼠标点击落入被录窗口会被自动记录，也可在点击前调用 `oilstudio record click --at <x>,<y>` 申报精确中心点）。
  2. **若没有自带桌面工具或希望免截图精准操作**：优先使用 `agent-desktop`（`agent-desktop snapshot --app <App名> -i --compact --include-bounds` 获取元素 `@ref` 与 `bounds`，将元素中心换算为窗口比例后调用 `oilstudio record click --at-fraction <u>,<v>`，再调用 `agent-desktop click <ref>`；输入文字时使用 `agent-desktop type --headed --interval-ms 55 <ref> <文本>` 逐字输入并显示输入框内的竖线光标，全程不抢物理鼠标）。
  3. 若以上工具都不可用，告诉用户"我可以替你开始和停止录制，操作需要你来做"，由用户决定是否继续。

## 录之前

- 先和用户确认要演示什么、从哪个画面开始、到哪一步结束。步骤多于十步时先把步骤列给用户看。
- 用 `oilstudio record prepare --source <id> --size 1280x800 --center --activate` 调整窗口，也可把 `--size`、`--position X,Y`、`--center`、`--activate` 加到 `record start`。`--position` 与 `--center` 互斥；调整外部窗口需要辅助功能权限。窗口被其他窗口挡住也能录到，但你自己的工具通常需要它在最前面才能操作。
- 关掉或移开会弹出通知、会出现在被录窗口里的无关内容。
- 只录用户要的那个窗口。不要录整块屏幕，除非用户明确要求；不要去录聊天、邮件这类无关的窗口。

## 申报位置

成片里的光标和点击来自你的申报，不来自真实鼠标。每次点击前运行 `oilstudio record click`，返回后立刻执行点击；或给 `record click` 加 `--perform`，由 Oil Studio 同时执行原生点击，不要再点一次。`record move --perform` 同时移动真实光标。原生操作需要辅助功能权限。

位置给目标元素的中心，两种写法任选：

- `--at <x>,<y>`：屏幕坐标（点）。你的工具按屏幕坐标点击时，直接把同一组坐标传进来。它和 `record sources` 返回的 `x / y / width / height` 是同一个坐标系。
- `--at-fraction <u>,<v>`：目标在被录窗口里的比例，0–1。你手里是这个窗口的截图时用它：`u = 目标的横坐标 ÷ 截图宽度`，`v = 目标的纵坐标 ÷ 截图高度`。截图必须正好是被录的那个窗口（含标题栏）。

其他规矩：

- 只知道网页内坐标（浏览器自动化）时，先截一张整个窗口的图，量出网页区域左上角在窗口里的位置，再换算成窗口内的比例。
- 工具重试同一步操作时，给申报加 `--id <这一步的名字>`，同名的只记一次，不会出现两次点击。
- 某一步实在给不出位置：可以不申报，但要在汇报里说明哪几步没有光标。
- 申报了却没点成：继续录，停止后在汇报里说明，或者按"出错时"重录。
- 滚动和打字不用申报。
- 录制期间不要改变被录窗口的大小；移动窗口不影响比例坐标。

## 录的时候

- 一次只做一个动作，做完确认画面已经变化再做下一个。动作之间的等待不用担心，录完会删掉。
- 打字用正常输入，不要粘贴大段文字后立刻跳走，给画面一秒左右显示结果。
- 每个重要步骤完成后可以运行 `oilstudio record mark`，在工程里留一个标记。
- 需要离开被录窗口处理别的事（例如查资料）：先 `oilstudio record pause`，回来后 `oilstudio record resume`。
- 不要去点 Oil Studio 的录制指示（屏幕上的小药丸），用命令行控制。
- 默认最长录 10 分钟，到时自动停止并保存。需要更长时在开始时加 `--max-duration <秒>`，最长 3600。

## 出错时

| 情况 | 处理 |
| --- | --- |
| 操作走错了，画面已经乱了 | `oilstudio record stop --discard`，把窗口恢复到开场状态后重新开始 |
| 只错了一小步，后面重做了一遍 | 继续录完；停止后用 `plan submit` 按源时间删掉错的那一段（`category` 写 `false_start`） |
| `record stop` 返回 `stoppedBy: "user"` | 用户自己按了停止。工程已经保存，问用户是继续处理还是重录 |
| `record stop` 返回 `stoppedBy: "limit"` | 到了时长上限。告诉用户录到了哪一步，问是否加长后重录 |
| `record stop` 返回 `CANCELLED` | 用户放弃了这次录制，没有工程。停止，问用户接下来怎么做 |
| `NO_RECORDING` | 当前没有你发起的录制。运行 `oilstudio record status` 看 `last` 里有没有刚才的结果 |
| `SOURCE_NOT_FOUND` | 窗口已经关闭或换了。重新运行 `record sources` |
| `APP_REQUIRED` | Oil Studio 没有运行。运行 `open -a "Oil Studio"` 后重试一次 |

你的工具中途失败、无法继续操作时，先运行 `oilstudio record stop`（或 `--discard`），不要让录制一直开着。

## 录完之后

1. `oilstudio idle <工程> --submit`：删掉操作之间的等待，并对齐延迟点击、按保留片段与画面变化区域重构自动缩放。你自己录的工程会直接生效。
2. 想确认结果：`oilstudio context <工程> --out <临时文件>` 看新的时长和片段；用 `oilstudio frame <工程> --output-ms <毫秒> --out <png>` 抽查几个时刻。
3. 自动生成的缩放跟随你申报的点击。画面上的小字看不清，或某一步没有申报而需要推近时，按 SKILL.md 的"调整缩放"补充或修改。
4. 用户要成片：`oilstudio export <工程> --out <路径.mp4>`。

## 网页 Playbook

两种模式都需要 `node`。`stage-window` 模式使用系统自带 WebKit 与 Xcode 命令行工具的 `swiftc`，无需安装特定第三方浏览器；当未显式指定浏览器宿主且本机未安装 `ego-browser` 时，脚本会自动使用 `stage-window`。录制前先确认所选模式的依赖可用，缺少时请用户安装后再继续。

适合网页步骤多、需要连续演示，或要在画面上突出指标与重点的录制。脚本在开始前用网页自动化运行环境打开首个 URL，之后用 Oil Studio CLI 选取并录制唯一匹配的浏览器窗口；需要 App 已运行，并由用户完成录制授权。录制默认关闭麦克风、摄像头、系统声音和字幕（除非用户明确要求加字幕，否则不要开启字幕或填写 `subtitle`）。

```sh
python3 -B <Skill目录>/scripts/record_playbook.py \
  --playbook <演示.json> --out-report <结果.json> --export <成片.mp4>

python3 -B <Skill目录>/scripts/record_playbook.py --playbook <演示.json> --dry-run
python3 -B <Skill目录>/scripts/record_playbook.py --inspect https://example.com
python3 -B <Skill目录>/scripts/record_playbook.py --playbook <演示.json> --rehearse
```

Playbook JSON 形状如下：

```json
{
  "source": {"app": "Browser", "title": "Example"},
  "beats": [
    {
      "id": "overview",
      "hud": {
        "badge": "案例拆解", "title": "从入口开始", "detail": "确认核心路径",
        "pills": [{"label": "步骤", "value": "01", "color": "#F5D46B"}],
        "position": "top-right"
      },
      "zoom": {"level": 1.26, "selector": "[data-demo=overview]", "transition": "smooth"},
      "actions": [
        {"action": "open", "url": "https://example.com"},
        {"action": "click", "selector": "[data-demo=overview]"},
        {"action": "scroll", "selector": "#details", "durationMs": 700},
        {"action": "wait", "ms": 500}
      ]
    }
  ]
}
```

- `source` 用显式 `sourceId`，或 `app` / `title` 匹配窗口；同时给出多个条件时必须全部满足，结果必须唯一且是窗口。`app` 按大小写不敏感的完整名称匹配；`title` 默认按大小写不敏感的子串匹配，设 `exactTitle:true` 时改为精确匹配。首拍首个动作必须是 `open`，它只用于预置录制开场，不会在录制开始后重复导航。
- 脚本从已打开页面读取实际标题，再核对原生采集窗口的标题；只给 `sourceId` 时不需要另写 `title`，实际标题仍会用于确认没有选错窗口。
- 可选 `browser.host` 为 `browser` / `ego-browser` 或 `stage-window`；未指定时浏览器匹配失败可回退到舞台，显式指定浏览器或 `browser.page: user` 时不会回退。显式使用 `stage-window` 时不能同时设置 `source.sourceId`，因为新舞台会获得新的窗口 ID；校验会在启动舞台前拒绝该组合，请改用 `source.title` 或 `app`。`browser.scratchDir` 指定临时文件的父目录；每次运行都会在系统临时目录或该父目录下创建独立目录，不能复用固定目录。独立舞台的本机控制接口使用每次运行随机生成的会话令牌。
- `browser.preflightSeconds` 可设 0–10；大于 0 时先短录并抽帧 OCR，抽帧源时间取 `min(500, max(0, 试拍毫秒数 - 1))`，不会超出短试拍的实际时长。`browser.preflightContains` 是可选的字符串数组，配置后每项都必须在 OCR 文本中出现（忽略大小写和空白）；不配置时不假定演示页包含任何特定文字。`--preflight-only` 只执行短试拍，必须同时设置正的 `preflightSeconds`。
- 命令行帮助、校验和运行错误优先使用 `OILSTUDIO_LANGUAGE`（`zh-Hans` 或 `en`），未设置时跟随系统 locale，无法识别时使用英文。JSON 字段名不随语言变化。
- `settings` 是 `settings apply` 的 `settings` 对象，可选；只写要改的分组和字段。
- **默认不加字幕**：只有当用户明确要求加字幕时，才设置 `"settings": {"subtitles": {"enabled": true}}` 并在各拍填写 `subtitle`。未显式开启 `settings.subtitles.enabled: true` 时不提交字幕，导出也固定使用 `--subtitles none`。
- `hud` 可写 `badge`、`title`、`detail`、`pills:[{label,value,color?}]` 和 `position`。浮卡使用独立 Shadow DOM、`pointer-events:none`，不会接管页面交互，录制结束或失败清理。
- `zoom` 可写 `level`、`transition` 和 `mode`：默认或 `manual` 必须指定 `selector` / `target:{x,y}` 之一；`auto` 跟随意图轨迹，不能同时指定目标。`selector` 在该拍动作执行前解析，滚动后不会重新定位。`selector` 取当前视口元素中心；`target` 是网页视口的 0–1 比例。脚本读取 `outerWidth - innerWidth` 与 `outerHeight - innerHeight`，加上视口坐标后换算为整个录制窗口的 `u,v`。目标必须在当前视口可见；缩放时长仍受至少 600 毫秒的校验限制。
- `actions` 的类型：`open` 打开 URL；`click` / `move` 用 CSS `selector` 或视口比例 `fraction:{u,v}`；`scroll` 用 `y` 或 `selector`，可设 `durationMs`；`input` 用 `selector` + `value`，或 `from` / `to` / `durationMs` 平滑调整；`press` 用 `key`（如 `Enter`、`Escape`、`Tab`、`Meta+k`）和可选 `selector` 派发按键；`eval` 执行给定网页 JavaScript；`wait` 等待 `ms`；`mark` 添加录制标记。选择器相对于页面 DOM。
- 对 CSS 点击或悬停，脚本先滚入视口并测量元素中心，调用 `record click --at-fraction` 或 `record move --at-fraction` 后马上触发真实网页动作。显式 `fraction:{u,v}` 按整个录制窗口比例理解，并换算成网页视口里的鼠标位置；CSS 元素中心则会把地址栏和标题栏等偏移计入窗口比例。
- 完成录制后，脚本按需调用 `settings apply`，为所有缩放生成带当前指纹的方案并执行 `plan validate` / `plan submit`，有字幕且已启用时再用 `subtitles apply` 写入字幕。`--export` 根据字幕状态选择 `burn` 或 `none`；若任何提案返回 `autoApplied:false`，脚本将跳过导出并在报告里保留待办。出错时会尝试放弃未完成的录制。
- `--dry-run` 只验证 JSON 字段与结构，不启动浏览器、App 或录制。`--out-report` 可写出匹配窗口、字幕源时间、缩放方案、提案回执和导出结果。

`PERMISSION_REQUIRED` 表示缺少录制或辅助功能授权；窗口匹配不唯一、目标被遮挡或窗口拒绝调整返回 `VALIDATION_FAILED`。

`--inspect <url>` 打开独立舞台并等待页面稳定，输出视口、可滚动容器和交互元素的选择器与位置；无需 Playbook。`--rehearse` 在独立舞台按顺序运行所有动作并检查缩放选择器，不启动录制；页面动作仍会产生实际效果，请只对允许操作的页面使用。
