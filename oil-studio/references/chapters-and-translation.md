# 章节与翻译

用于"划分章节"和"英文字幕"。返回 [SKILL.md](../SKILL.md)。

## 章节

目标：观众看进度条就知道视频分几段、每段讲什么。宽粒度，不是目录式的细分。

- 先通读全部字幕，按内容的主要阶段划分：开场与问题、实际操作、结果、总结这类大块。
- 三到五分钟的视频 2–4 章，更长的 4–6 章；章节起点之间至少相隔 75 秒（更近的会被合并）。
- 第一章从视频开头开始。
- 标题用 2–8 个中文字或简短英文短语，说这一段讲什么，不用"第一部分"这类序号，不加标点。标题过长会在进度条上被截断。
- 章节起点放在新话题第一句的开头：用该句的 `id` 写 `fromCue`，或写它的 `sourceStartMs`。
- `chapters get` 返回章节、`outputDurationMs`、`enabled` 和 `position`；只生成严格超过 180000 毫秒的成片。已有章节时，没有明确的重新划分要求就不要覆盖。
- 目标工程在前台打开且没有进行中的审阅时，`chapters apply` 校验后自动整组替换章节并开启进度条；应用后可以撤销，也可以在 App 中改标题或删除章节。调用后仍须检查 JSON 响应中的 `autoApplied` 和 `pendingReason`：有审阅进行中或工程未在前台打开时，提案可能排队等待。
- 位置是独立外观设置：用 `settings get/apply` 修改 `subtitles.chapterProgressPosition`（`bottom` / `top`），不要写进章节文件。

章节文件：

```json
{
  "schemaVersion": 1,
  "chapters": [
    {"fromCue": "7DA2608E-572F-49E5-A91A-BB05812FFF97", "title": "开场与效果"},
    {"fromCue": "0F4CD005-949D-4F90-8B26-35BACBD1B1F2", "title": "安装与配置"}
  ]
}
```

## 翻译

目标：英文字幕逐句对应中文，意思忠实，读起来自然。

- 只翻译每句的 `text`；句子的 `id`、数量和顺序必须和中文完全一致，不合并、不拆分。
- 忠实翻译，不加营销语气，不扩写；保留第一人称、事实范围和语气强度。
- 产品名、命令、文件名、版本号保持原样（例如 `Claude Code`、`tasks.ts`）。
- 口语填充词（嗯、那个）不译。
- 每句尽量短；中文一句很长时，英文也只用一句表达，不加换行。英文由 App 按单词断行，默认目标约 42 字符。

翻译文件（`--locale en`）：

```json
{
  "schemaVersion": 1,
  "edits": [
    {"id": "7DA2608E-572F-49E5-A91A-BB05812FFF97", "text": "Hi everyone, today I'm sharing a skill I open-sourced recently"}
  ]
}
```

必须覆盖全部句子，缺句或多句都会被拒绝。
