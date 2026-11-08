# 提案格式

精剪、缩放、布局、画面元素与打码方案，以及字幕修改文件的格式。提交前一律先用命令行校验或由 `subtitles apply` 当场核对。返回 [SKILL.md](../SKILL.md)。

## 目录

- [精剪方案](#精剪方案-plan-validate--plan-submit)
- [口头禅覆盖检查](#口头禅覆盖检查)
- [缩放](#方案里的缩放-zooms)
- [布局](#方案里的布局-layouts)
- [标题、图片与 B-roll](#方案里的标题图片与-b-roll-overlays)
- [打码](#方案里的打码-redactions)
- [提交后的返回](#提交后的返回)
- [字幕修改](#字幕修改-subtitles-apply)
- [脚本字幕整轨](#脚本字幕整轨-subtitles-apply)

## 精剪方案（`plan validate` / `plan submit`）

```json
{
  "schemaVersion": 1,
  "projectFingerprint": "从 context 原样复制",
  "contextFingerprint": "从 context 原样复制",
  "summary": "删除 3 处重说、2 处口误，预计缩短 48 秒",
  "decisions": [
    {
      "decision": "cut",
      "confidence": "high",
      "range": {"from": "U0012", "to": "U0015"},
      "category": "abandoned_take",
      "removedText": "被删的原话",
      "keptText": "后面保留下来、覆盖了它的原话",
      "keptRange": {"from": "U0020", "to": "U0022"},
      "reason": "后一遍完整覆盖了前一遍的信息",
      "screenAction": "redundant",
      "visualAssessment": "同一个设置在 U0021 处重新演示了一遍"
    },
    {
      "decision": "review",
      "confidence": "low",
      "sourceMs": [61200, 64850],
      "category": "filler",
      "removedText": "可能可以删的原话",
      "keptText": "",
      "reason": "像是闲聊，但提到了一个后面没再出现的设置"
    }
  ]
}
```

| 字段 | 取值 |
| --- | --- |
| `decision` | `cut`（建议删除）、`keep`（明确保留，用于说明）、`review`（拿不准，请用户看） |
| `confidence` | `high`、`medium`、`low`；只有 `cut` 且 `high` / `medium` 会进入待确认列表 |
| `category` | `abandoned_take`、`false_start`、`slip`、`filler`、`silence` |
| `range` | 发言编号，`from` 和 `to` 都包含在内；整句删除时优先用它 |
| `sourceMs` | `[开始, 结束]` 源时间毫秒；只删半句时用它，按词级时间取边界 |
| `keptRange` | 覆盖被删内容的那几句的发言编号；`abandoned_take` 必填，其他类别可省略 |
| `screenAction` | 只在删减与画面操作重叠时写：`redundant`（看过画面，操作在后面重做了或与讲解无关）；不确定就不写 |
| `visualAssessment` | 写了 `screenAction` 时必填，一句话说明看到的画面 |

`range` 和 `sourceMs` 每条只写一个。不要写成片时间。时间直接用 context 里的整数毫秒，不用自己补小数；剪到某个片段或整段录制的末尾时，照抄它的结束时间即可。

精剪先用 `pauses <工程> --out-plan <json>` 取得停顿清理草案，将语义删减追加到同一份 `decisions`。草案的指纹必须与 context 一致；不提前提交清理。`plan preview <方案文件> --index <从 0 开始的条目编号> --out <wav>` 可试听合并全部可执行删减后的接缝，只读取原始麦克风声音，不修改工程。变速、重复或重排时间线不支持。

## 口头禅覆盖检查

把每个候选的结论写进 `decisions`：确认可删用 `cut`，明确保留用 `keep`，缺证据用 `review`，都使用源时间和具体 `reason`。整段删减完整覆盖候选时不再单独切一次。不要给提案添加未定义的候选 ID 或审核字段；覆盖报告保存在工程外。

有 Python 3 时，在 `plan validate` 前运行随 Skill 分发的只读检查器（路径中的 Skill 目录是当前加载的根目录）：

```sh
python3 -B <Skill目录>/scripts/check_filler_coverage.py --context <当前context.json> --plan <方案.json> --out <新的覆盖报告.json>
```

[检查器](../scripts/check_filler_coverage.py)核对两份指纹、整段范围与词级范围，按源时间并集合计覆盖；只切掉一个词的一部分不算已删除，低置信度 `cut` 不算可执行。退出码 0 表示每项已有去向，1 表示仍有 `unresolved`，2 表示输入/指纹/文件错误。输入失配要重新读取工程，不手工换指纹。报告不覆盖旧文件。

没有 Python 或旧版 context 缺 `fillerCandidates` 时，按现有词级转录逐项建立同样的人工清单，不安装依赖、不把缺失字段当成零候选。无论用哪种方法，都要让每项有去向，再校验提案。覆盖通过不证明语义、接缝或画面判断正确；`review` 仍是未完成的编辑判断。

`keep`、`review` 不进入 App 的可执行删减列表；不能说用户可在 App 勾选这些 `review`。汇报待复核项的具体范围、理由与清单路径。不要为让一项显示在列表中而把不确定判断改成 `cut`。对于已有充分删减依据、仅操作保护要求复核的 `cut`，保留校验器的 `uncheckedByDefault`。

应用后以回执的接受/跳过条目为准，重新读当前保留部分；对照已接受范围检查预期删掉的词是否还在。保留、复核和用户未接受的删减都可能合理残留，不能按剩余候选数量宣称失败，也不能把“校验通过”说成“没有漏删”。

## 方案里的缩放（`zooms`）

同一份方案可以包含 `decisions`、`zooms`、`layouts` 的任意组合。

```json
"zooms": [
  {"action": "add", "sourceStartMs": 84200, "sourceEndMs": 89600, "level": 1.8, "mode": "manual",
   "target": {"x": 0.72, "y": 0.31}, "transition": "smooth", "reason": "讲解右上角的报错文字，字很小"},
  {"action": "update", "id": "z7", "level": 1.4, "reason": "2.2 倍裁掉了正在讲的按钮"},
  {"action": "remove", "id": "z9", "reason": "镜头在两处之间来回推拉，和讲解无关"}
]
```

| 字段 | 取值 |
| --- | --- |
| `action` | `add`、`update`（只写要改的字段）、`remove` |
| `id` | `update` 和 `remove` 必填，从 context 的 `zooms` 复制 |
| `sourceStartMs` / `sourceEndMs` | 源时间毫秒，至少相隔 600；按同一方案所有更新后的结果检查重叠；必须与保留画面有交集，允许跨过被剪掉的部分 |
| `level` | 1.0–3.0 |
| `mode` | `auto`（跟随点击）或 `manual`（固定在 `target`） |
| `target` | `manual` 时必填，录屏画面上的归一化坐标，`x`、`y` 都在 0–1 |
| `transition` | `smooth` 或 `instant` |

同一缩放 `id` 在一份方案里最多出现一条 `update` 或 `remove`，避免重复操作的先后顺序改变最终结果。

## 方案里的布局（`layouts`）

只用于有摄像头的工程。时间用提交前的**成片时间**毫秒（这是唯一用成片时间的地方），从 context 的 `layouts` 读取现有分段。

```json
"layouts": [
  {"action": "add", "outputStartMs": 2000, "outputEndMs": 9500, "type": "camera", "transitionDuration": 0.5, "reason": "开场只看讲解者"},
  {"action": "update", "id": "l7", "type": "side-by-side", "reason": "同时展示操作与讲解者"},
  {"action": "remove", "id": "l9", "reason": "恢复默认布局"}
]
```

| 字段 | 取值 |
| --- | --- |
| `action` | `add`、`update`（只写要改的字段）、`remove` |
| `type` | `both`（画面 + 摄像头）、`screen`（只有画面）、`camera`（只有摄像头）、`side-by-side`（并排） |
| `transitionDuration` | 0.3、0.5 或 0.8 秒 |
| `outputStartMs` / `outputEndMs` | 至少相隔 600；分段之间不能重叠 |

## 方案里的标题、图片与 B-roll（`overlays`）

方案可以同时包含 `decisions`、`zooms`、`layouts`、`overlays` 和 `redactions`。`overlays` 与 `redactions` 是计划顶层数组；计划字段为扁平结构，不使用 `context.overlays` 读取结果中的嵌套 `content`。

```json
"overlays": [
  {
    "action": "add", "id": "o-title-1", "kind": "text", "text": "先看核心流程",
    "template": "title", "anchorSourceMs": 84200, "durationOutputMs": 3200,
    "frame": {"x": 0.5, "y": 0.13, "fontSize": 0.055}, "opacity": 1,
    "enter": {"style": "pop", "durationMs": 300}, "exit": {"style": "fade", "durationMs": 250}
  },
  {
    "action": "add", "id": "o-image-1", "kind": "image", "layer": "screen",
    "sourcePath": "/absolute/local/path/feature.png", "anchorSourceMs": 120000, "durationOutputMs": 2400,
    "fit": "fit", "focus": {"x": 0.5, "y": 0.5},
    "enter": {"style": "dissolve", "durationMs": 300}, "exit": {"style": "dissolve", "durationMs": 300}
  },
  {"action": "update", "id": "o-title-1", "durationOutputMs": 4000},
  {"action": "remove", "id": "o-image-old"}
]
```

| 字段 | 取值与规则 |
| --- | --- |
| `action`、`id` | `add`、`update`、`remove`；每项都要有唯一且非空的 `id`。`add` 的 id 不得与工程中已有 id 冲突；`update` / `remove` 的 id 必须在工程中唯一命中。`remove` 只需 `action` 与 `id`。 |
| `kind` | `text` 或 `image`，直接写在条目顶层。 |
| `text`、`template` | `text` 类型必填 `text`；可选 `template` 为 `title` 或 `label`。文字只放在 `float` 层；`layer` 省略时默认为 `float`，显式填写也只能是 `float`。 |
| `sourcePath`、`file` | `image` 类型二选一：`sourcePath` 是本机图片的绝对路径；`file` 是工程 `assets/overlays/` 中已存在的文件名。不要在 `file` 中写目录路径。 |
| `layer` | 图片必填，取 `float`（浮在录屏上）或 `screen`（替换录屏画面）。 |
| `anchorSourceMs`、`durationOutputMs` | 图片与文字都必填。锚点是源时间毫秒；显示时长是成片时间毫秒。 |
| `frame` | 可选的浮层位置与大小，坐标是画布归一化中心点：图片用 `{x,y,width}`，文字用 `{x,y,fontSize}`；显式值均为 0–1，`width` / `fontSize` 必须大于 0。缺省图片位置为中心且宽度为 0.25；文字字号为 0.055。 |
| `opacity` | 仅浮层可选，不透明度 0–1；`screen` 图片不接受显式 `opacity`，用 `enter` / `exit` 设置无效果或溶解过渡。 |
| `fit`、`focus` | 仅 `screen` 图片使用。`fit` 为 `fill` 或 `fit`；`focus` 为归一化 `{x,y}`，范围 0–1。 |
| `enter`、`exit` | 可选 `{style,durationMs}`。浮层 `style` 为 `none`、`fade`、`pop` 或 `rise`；替换画面为 `none` 或 `dissolve`。缺省时浮层进入用 `pop`/300 ms、退出用 `fade`/250 ms；替换画面均为 `dissolve`/300 ms。 |

`update` 只传需要改变的字段，按字段合并并保留未提供字段与未知工程字段；新增项要提供对应类型的必需信息。`sourcePath` 图片只有在应用被接受时才导入 `assets/overlays/`，以 SHA-256 去重。`plan validate` 只读校验，不写工程或导入图片。应用之后核对 plan 回执的实际 `applied` / `skipped` 项，并用 `frame --text` 检查关键时刻；需要交付成片时导出并复核最终画面。

## 方案里的打码（`redactions`）

打码条目单独作为顶层 `redactions` 数组，不嵌套在 `overlays`。`region` 是录屏原始画面上的固定归一化矩形；不会自动跟踪移动对象。

```json
"redactions": [
  {
    "action": "add", "id": "r-account-1",
    "sourceStartMs": 50000, "sourceEndMs": 61500,
    "region": {"x": 0.61, "y": 0.08, "width": 0.27, "height": 0.09},
    "style": "pixelate", "reason": "遮盖画面右上角的账号信息"
  },
  {"action": "update", "id": "r-account-existing", "style": "blur", "reason": "改用模糊遮盖账号信息"},
  {"action": "remove", "id": "r-obsolete"}
]
```

| 字段 | 取值与规则 |
| --- | --- |
| `action`、`id` | `add`、`update`、`remove`；`id` 必须唯一且非空。`add` 的 id 不得冲突；`update` / `remove` 必须唯一命中现有条目。`remove` 只需 `action` 与 `id`。 |
| `sourceStartMs`、`sourceEndMs` | 源时间毫秒，必须是有效的正向范围并落在同一录制片段内。 |
| `region` | `{x,y,width,height}` 归一化矩形，须完全落在 0–1 画面范围内，宽高均大于 0。 |
| `style` | `pixelate`、`blur` 或 `fill`。 |
| `reason` | 新增时必填非空字符串；更新后的合并结果必须有非空 `reason`，已有条目有值时可继承，没有时要在更新中补写。 |

`update` 是局部合并，只传需要改的字段；需要保留或补写有效的时间、区域、样式与非空 `reason`。移动内容要在各自时间段指定并检查对应区域，不要把矩形遮盖描述为对象跟踪。校验通过不代表遮盖已应用：应用后用 `oilstudio frame <工程> --source-ms <毫秒> --text --out <png>` 核对画面与识别文字；若用户需要导出，抽查并播放导出成片，确认遮盖在整个指定区间生效后再汇报完成。敏感内容仍可见时先修正方案并重新校验，不要把未验证的遮盖说成已完成。

## 提交后的返回

`plan submit`、`pauses --submit`、`idle --submit`、`subtitles apply`、`chapters apply` 都返回 `proposalId` 和 `autoApplied`。

```json
{"ok": true, "proposalId": "…", "autoApplied": true, "applied": [0, 1, 3], "skipped": [{"index": 2, "reason": "你改过这个缩放"}]}
```

- `autoApplied: false`：提案在等用户确认，用 `proposal status <proposalId> --wait` 等结果。
- `autoApplied: true`：`applied` 里的条目已经生效，`skipped` 里的没有应用。

`applied`、`skipped` 的索引按同一个 plan 的顺序编号：`decisions`、`zooms`、`layouts`、`overlays`、`redactions` 依次排列。核对每一项后，已生效的修改可在 Oil Studio 里用 ⌘Z 撤销。

## 字幕修改（`subtitles apply`）

```json
{
  "schemaVersion": 1,
  "edits": [
    {
      "id": "c0042",
      "expectedText": "我平时用 cloud code 写代码",
      "text": "我平时用 Claude Code 写代码"
    }
  ],
  "glossary": [
    {"wrong": "cloud code", "correct": "Claude Code"}
  ]
}
```

- `id` 与 `expectedText` 分别从 `subtitles get` 结果的 `id`、`text` 原样复制（不是 `displayText`，那是去掉标点后用于显示的文字）；`expectedText` 与当前字幕不一致的条目会被拒绝。
- 只改文字，不改时间。
- `glossary` 可以省略；只放会反复出现的错误。

## 脚本字幕整轨（`subtitles apply`）

无口播的演示工程可以直接提交按源时间编写的字幕；`cues` 与上面的 `edits` 是两种互斥格式。

```json
{
  "schemaVersion": 1,
  "cues": [
    {"id": "intro", "sourceStartMs": 0, "sourceEndMs": 2400, "text": "先看项目首页"},
    {"sourceStartMs": 2400, "sourceEndMs": 5100, "text": "这里可以调整访问权限"}
  ]
}
```

- `id` 可省略；省略时由 Oil Studio 生成。时间用录屏源时间毫秒，校验前会将距离片段边界不超过 0.5 毫秒的值吸附到边界。
- 时间须满足 `0 <= sourceStartMs < sourceEndMs <= durationSourceMs`；按起始时间升序排列，区间不能重叠；`text` 不能为空。每条字幕建议只写一句自然的口语短句（中文约 10–18 字），不要把两个分句拼成一条长字幕。
- 校验通过后，整条字幕轨道替换为 `cues`。每项按源时间绑定到对应 recording session，并写入 `edited: true`；跨 session 的字幕在边界拆分，首段保留原 ID，后续段使用确定性的 `<原ID>-session-<sessionIndex>`（如有冲突再追加序号），各段复制原英文翻译。没有有效 session 区间或 ID 冲突会拒绝，不会静默丢弃。开启字幕显示；新轨道里 ID 相同的字幕保留原英文翻译，其余旧翻译清除。
- 修改以字幕提案提交。Agent 自录工程会按 `autoApply` 直接应用；随后可运行 `subtitles get`、`subtitles export` 或 `export --subtitles burn`。普通文字校对继续使用 `edits`，逐项按旧字幕 ID 和 `expectedText` 核对。
