# 录制

用命令行录一段操作演示时的规矩。返回 [SKILL.md](../SKILL.md)。

录制时不直接绘制标题、图片或打码。录制结束后如需添加标题、标签、图片/B-roll 或遮盖敏感画面，按 SKILL.md 的「添加画面元素与打码」用 `plan submit` 提交；提案字段、素材导入和画面验证步骤见[提案格式](proposal-formats.md)。

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
| `PERMISSION_REQUIRED` | 把 `message` 和 `hint` 告诉用户后停止：缺屏幕录制等授权时请用户在 App 的权限页授权；提示沙箱限制本机连接时请用户允许在沙箱外运行 `oilstudio`（不要重开 App）；提示 App 已被移动或删除时，请用户退出 Oil Studio，再从“应用程序”文件夹重新打开 |

你的工具中途失败、无法继续操作时，先运行 `oilstudio record stop`（或 `--discard`），不要让录制一直开着。

## 录完之后

1. `oilstudio idle <工程> --submit`：删掉操作之间的等待，并对齐延迟点击、按保留片段与画面变化区域重构自动缩放。你自己录的工程会直接生效。
2. 想确认结果：`oilstudio context <工程> --out <临时文件>` 看新的时长和片段；用 `oilstudio frame <工程> --output-ms <毫秒> --out <png>` 抽查几个时刻。
3. 自动生成的缩放跟随你申报的点击。画面上的小字看不清，或某一步没有申报而需要推近时，按 SKILL.md 的"调整缩放"补充或修改。
4. 需要标题、标签、图片/B-roll 或打码时，按 SKILL.md 的"添加画面元素与打码"提交并核对提案回执。打码是固定区域，不会自动跟踪移动对象；应用后用 `frame --text` 检查遮盖，再检查导出成片。
5. 用户要成片：`oilstudio export <工程> --out <路径.mp4>`。有打码时先确认遮盖已应用，并抽查导出的敏感区间。

## 网页 Playbook

适合网页步骤多、需要连续演示，或要在画面上突出指标与重点的录制。脚本先在所选浏览器宿主里打开首个 URL，再用 Oil Studio CLI 选取并录制唯一匹配的窗口；需要 App 已运行，并由用户完成录制授权。录制默认关闭麦克风、摄像头、系统声音和字幕（除非用户明确要求加字幕，否则不要开启字幕或填写 `subtitle`）。整段运行只启动一个常驻的网页自动化进程，每一步几乎没有调度延迟。

### 浏览器宿主

成片里不能出现任何自动化痕迹：Agent 接管浏览器时画的控制条（例如“Agent 正在控制 / 接管 / 终止任务”）、页面四周的边框、光标旁的动作气泡，以及翻译提示这类浏览器弹窗。宿主只由 `browser.host` 与 `browser.cdpURL` 决定，不随本机装了什么而变：

| 宿主 | 何时用 | 说明 |
| --- | --- | --- |
| `stage-window`（默认） | 公开页面，不需要登录 | 系统 WebKit 的无边框独立窗口，没有任何浮层；只有一个页面，不能切换标签页。需要 `node` 与 Xcode 命令行工具的 `swiftc`。 |
| `cdp` | 需要登录态、多个标签页，或要滚动跨域内嵌页面 | 经调试端口连接用户自己启动的 Chromium 系浏览器（Chrome、Edge、Brave 等），用原生鼠标与滚轮事件操作，不画任何浮层。写 `"browser": {"cdpURL": "http://127.0.0.1:9222"}` 即使用。需要 Node.js 22 或更新版本。 |
| `browser` / `ego-browser` | 只在用户明确要求时 | Agent 浏览器的任务空间。接管期间会一直显示控制条和动作气泡，开录前检查会拦下，通常无法录制。 |

cdp 浏览器由用户启动，或经用户同意后由你运行。用一个专门的资料目录，登录一次以后可以反复使用，不影响日常浏览器：

```sh
open -na "Google Chrome" --args --remote-debugging-port=9222 --user-data-dir="$HOME/Library/Application Support/Oil Studio Demo Browser"
```

其他 Chromium 浏览器换掉应用名即可。`browser.cdpURL` 只接受本机地址（`127.0.0.1`、`localhost` 或 `[::1]`）。首个 `open` 的地址已经在某个标签页里打开时（例如用户刚登录好的页面），脚本直接使用这个标签页，不重新加载；`browser.tabs` 里的地址同理。脚本不会关闭用户的浏览器或标签页。

### 开录前检查

外部浏览器宿主（`cdp`、`browser`）默认在开录前截一张窗口快照（`oilstudio record screenshot --text`，不建工程，也不切换编辑器里打开的工程），只对成片里会出现的区域做文字识别：

- 出现默认禁止清单里的文字（Agent 浏览器的控制条与动作气泡、翻译提示、“正受到自动测试软件的控制”等）就停止，不开始录制；报告的 `preflight.ocr.forbidden` 列出命中的文字。关掉浮层或换宿主后重跑。
- `browser.preflightForbid` 替换默认清单（`[]` 表示不拦）；`browser.preflightContains` 列出必须出现的文字，用来确认录的是对的页面。
- `browser.preflight: false` 关闭检查；独立舞台默认不检查，设 `true` 可开启。旧字段 `preflightSeconds` 大于 0 等同开启。`--preflight-only` 只做这项检查。

### 命令与格式

使用 cdp 宿主时先按上一节启动浏览器。录制前确认所选宿主的依赖可用，缺少时请用户安装后再继续。

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
- `browser.host` 与 `browser.cdpURL` 见[浏览器宿主](#浏览器宿主)；`browser.page` 只用于 `browser` 宿主（任务空间里的页面标签，或 `user`）。独立舞台每次都是新窗口，不能设置 `source.sourceId`，请改用 `source.title` 或 `app`；`sourceId` 适合 cdp 宿主下已打开的浏览器窗口。`browser.scratchDir` 指定临时文件的父目录；每次运行都会在系统临时目录或该父目录下创建独立目录，不能复用固定目录。常驻进程与独立舞台的本机控制接口都使用每次运行随机生成的会话令牌，只监听本机。
- `browser.tabs` 是开录前预先打开的其他标签页：`[{"id": "admin", "url": "https://…"}]`，`id` 不能是 `main`（首个 `open` 的页面）。只有 cdp 与 `browser` 宿主支持。录制中用 `{"action": "switchTab", "tab": "admin"}` 切过去，用 `"tab": "main"` 切回；切换是瞬时的，不会重新加载，HUD 会跟到切过去的标签页上。
- 命令行帮助、校验和运行错误优先使用 `OILSTUDIO_LANGUAGE`（`zh-Hans` 或 `en`），未设置时跟随系统 locale，无法识别时使用英文。JSON 字段名不随语言变化。
- `settings` 是 `settings apply` 的 `settings` 对象，可选；只写要改的分组和字段。
- **默认不加字幕**：只有当用户明确要求加字幕时，才设置 `"settings": {"subtitles": {"enabled": true}}` 并在各拍填写 `subtitle`。未显式开启 `settings.subtitles.enabled: true` 时不提交字幕，导出也固定使用 `--subtitles none`。
- `hud` 可写 `badge`、`title`、`detail`、`pills:[{label,value,color?}]` 和 `position`。浮卡使用独立 Shadow DOM、`pointer-events:none`，不会接管页面交互，录制结束或失败清理。
- `zoom` 可写 `level`、`transition` 和 `mode`：默认或 `manual` 必须指定 `selector` / `target:{x,y}` 之一；`auto` 跟随意图轨迹，不能同时指定目标。`selector` 在该拍动作执行前解析，滚动后不会重新定位。`selector` 取当前视口元素中心；`target` 是网页视口的 0–1 比例。脚本读取 `outerWidth - innerWidth` 与 `outerHeight - innerHeight`，加上视口坐标后换算为整个录制窗口的 `u,v`。目标必须在当前视口可见；缩放时长仍受至少 600 毫秒的校验限制。
- `actions` 的类型：`open` 打开 URL；`click` / `move` 用 CSS `selector` 或视口比例 `fraction:{u,v}`；`scroll` 用 `y` 或 `selector`，可设 `durationMs`；`wheel` 在 `selector` 中心或 `fraction:{u,v}` 处派发原生滚轮，`deltaY` / `deltaX` 为像素（至少一个不为 0），可设 `durationMs`（默认 600）；`input` 用 `selector` + `value`，或 `from` / `to` / `durationMs` 平滑调整；`press` 用 `key`（如 `Enter`、`Escape`、`Tab`、`Meta+k`）和可选 `selector` 派发按键；`switchTab` 切换到 `browser.tabs` 里的标签页；`eval` 执行给定网页 JavaScript；`wait` 等待 `ms`；`mark` 添加录制标记。选择器相对于页面 DOM。
- `scroll` 只能滚动顶层页面里的容器；内嵌的跨域页面（例如小程序实时预览、第三方组件）用 `wheel`，把位置放在那个内嵌区域上。cdp 与 `browser` 宿主的 `wheel` 是真实滚轮事件，能进入跨域内嵌页面；独立舞台退化为滚动该位置下最近的可滚动容器。
- 对 CSS 点击或悬停，脚本先滚入视口并测量元素中心，调用 `record click --at-fraction` 或 `record move --at-fraction` 后马上触发真实网页动作；`wheel` 先用 `record move` 把光标移到滚动位置。动作不给浏览器传说明文字，Agent 浏览器不会在光标旁显示动作气泡。显式 `fraction:{u,v}` 按整个录制窗口比例理解，并换算成网页视口里的鼠标位置；CSS 元素中心则会把地址栏和标题栏等偏移计入窗口比例。
- 完成录制后，脚本按需调用 `settings apply`，为所有缩放生成带当前指纹的方案并执行 `plan validate` / `plan submit`，有字幕且已启用时再用 `subtitles apply` 写入字幕。`--export` 根据字幕状态选择 `burn` 或 `none`；若任何提案返回 `autoApplied:false`，脚本将跳过导出并在报告里保留待办。出错时会尝试放弃未完成的录制。
- **补画面（`attach`）**：给口播工程补一段网页操作时，在顶层加 `"attach": {"project": "<口播工程>", "atOutputMs": <这段开始的成片毫秒>, "durationMs": <可选，这段录多久>, "plan": <可选，未提交的精剪方案>, "replaceUntilOutputMs": <可选，重录时这段结束的成片毫秒>}`。脚本用 `record start --into … --at-output-ms …` 录制（有 `plan` 时加 `--plan`，`atOutputMs` 与词的时间都按方案剪后的时间算；有 `replaceUntilOutputMs` 时加 `--replace-until-output-ms`，先清掉这段里的旧片段；有 `plan` 和 `durationMs` 而没写 `replaceUntilOutputMs` 时，自动用 `atOutputMs + durationMs` 作终点），停止后片段直接挂到口播上；报告的 `planProjection` 是换算结果；不提交删空档、字幕、章节和转场，也不能加 `--export`（全部补完后再对口播工程导出）。动作可以加 `atMs`：录制开始后第几毫秒执行这一步，脚本按录制时钟等到那一刻，用来让点击落在讲到它的时候（`atMs = 词的 outputStartMs − atOutputMs`）。首拍的开场 `open` 在录制开始前执行，不能带 `atMs`；设了 `durationMs` 时，最后一步之后会录到这个时长再停止。缩放按这段录制在工程里的源时间提交。带 `atMs` 的点击、悬停和输入会在等待前先滚到目标、量好位置，到点后直接申报并执行，所以到那一刻页面要已经稳定（图片懒加载、动画未完时在前面加 `wait`）。报告的 `timedActions` 列出每步计划的 `atMs` 和实际申报的 `declaredMs`（都是这段录制开始后的毫秒）；相差超过约 100 毫秒时，调整 `atMs` 后重录这一段。
- `--dry-run` 只验证 JSON 字段与结构，不启动浏览器、App 或录制。`--out-report` 可写出匹配窗口、字幕源时间、缩放方案、提案回执和导出结果。

`PERMISSION_REQUIRED` 表示缺少录制或辅助功能授权，或 App 需要重新打开（见“出错时”）；窗口匹配不唯一、目标被遮挡或窗口拒绝调整返回 `VALIDATION_FAILED`。

`--inspect <url>` 打开独立舞台并等待页面稳定，输出视口、可滚动容器和交互元素的选择器与位置；无需 Playbook。`--rehearse` 在独立舞台按顺序运行所有动作并检查缩放选择器，不启动录制；页面动作仍会产生实际效果，请只对允许操作的页面使用。
