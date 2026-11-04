# 字幕校对

用于"校对字幕"第 2 步：找出并改正字幕里的识别错误、同名异写、残留书面语气词/口吃与断行问题。返回 [SKILL.md](../SKILL.md)。

## 目标

字幕和说话人实际表达一致，专有名词、产品名、命令、文件名写对且全片大小写统一，字幕里不残留无意义的书面语气词或口吃叠字，每行不超过 20 个字宽且双行字数均衡。只改识别错误和无意义语气词/口吃，不改写句式、不润色文风。

## 步骤

1. 先读 `subtitles get` 返回的 `diagnostics`、`glossary` 和全部可见字幕（`outputStartMs` 非 null），弄清主题和反复出现的名词：
   - `diagnostics.inconsistentTerms`：同一个英文词或产品名在片中出现了不同大小写（如 `Skill` 与 `skill`），全片统一为 `suggested` 或正确规范写法，不只改第一处；
   - `diagnostics.residualFillers`：因与前后词连读或画面有操作而保留在成片里的无词义犹豫音（如句首或孤立的“呃、嗯、唉、诶、额、啊”），从字幕文字中删掉（注意区分“额度、额外、金额”等实词，分词器只标记孤立的单字语气词）；
   - `diagnostics.repeatedWords`：因连读未在音轨切掉的口吃重复（如“然后然后”“比较比较”“我我”），在字幕文字里保留一遍即可；
   - `diagnostics.glossaryMatches` 与 `diagnostics.lowConfidenceWords`：结合上下文重点核对是否有同音误识；
   - `diagnostics.layoutWarnings`：检查是否有单行超过 20 字宽（`over_width`）或双行中第二行不足 4 字宽的孤字行（`orphan_second_line`）。**总宽 ≤ 20 字宽的句子一律保持单行（绝不插入 `\n`）**；只有总宽 > 20 字宽必须折成两行时，才用 `\n` 在自然语义边界处调整为均衡双行。
2. 除 `diagnostics` 提示外，逐句通读找出可疑句子：
   - 读不通、像同音字错误的句子（如“打标”误写成“达标”、“试错”误写成“失措”）；
   - 英文名、产品名、代码、命令、版本号、文件名、路径；
   - 同一个词前后写法不一致。
3. 对每个可疑句子找证据，按可信程度从高到低：
   - `subtitles get` 结果里的 `script`（录制时的提词稿，没有时为空）：稿子里专有名词的写法通常是对的。只用来核对用词，讲解者经常不照稿念，不要把字幕改成稿子上的句子；
   - 同一视频里其他地方写对的同一个词；
   - 当时屏幕上的文字：运行 `oilstudio frame <工程> --source-ms <这句的开始毫秒> --out <png> --text`，看 `text` 里有没有对应的词；
   - 主题常识（例如讲编程工具时的常见产品名）。
4. 已有错词规则也要与当前语境核对，避免将普通词误改成产品名。改完按同一个词的其他变体再扫一次全片。
5. 有证据才改同音词和专有名词；没有证据保留原文，在最终汇报里列为"拿不准"。证据只用来帮你做判断，不写进修改文件：每条修改只有 `id`、`expectedText`、`text`。

## `subtitles get` 诊断与 `subtitles apply` 映射示例

`subtitles get` 返回（节选）：

```json
{
  "diagnostics": {
    "inconsistentTerms": [{"term": "skill", "suggested": "Skill", "variants": [{"text": "skill", "cueIds": ["c02"]}]}],
    "residualFillers": [{"id": "c02", "fillers": ["呃"]}],
    "repeatedWords": [{"id": "c02", "repeated": ["然后然后"]}],
    "glossaryMatches": [{"id": "c01", "wrong": "Clock", "correct": "Claude"}],
    "layoutWarnings": []
  },
  "cues": [
    {"id": "c01", "outputStartMs": 800, "text": "使用 Clock，写代码。", "displayText": "使用 Clock 写代码"},
    {"id": "c02", "outputStartMs": 2100, "text": "这个呃 skill 然后然后继续。", "displayText": "这个呃 skill 然后然后继续"}
  ]
}
```

对应生成的修改文件（`expectedText` 必须原样复制 `cues[].text`，不能复制 `displayText`）：

```json
{
  "schemaVersion": 1,
  "edits": [
    {"id": "c01", "expectedText": "使用 Clock，写代码。", "text": "使用 Claude，写代码。"},
    {"id": "c02", "expectedText": "这个呃 skill 然后然后继续。", "text": "这个 Skill 然后继续。"}
  ]
}
```

## 屏幕文字的使用

- 只有屏幕上的词和口播说的是**同一个东西**时才能用。窗口标题、侧边栏、背景里碰巧出现的项目名不能直接替换进字幕。
- 屏幕上的大小写和拼写以屏幕为准（例如 `Claude Code`、`tasks.ts`）。

## 格式规则

- 中文显示规则会清理标点；不要只为了“加标点”提交修改。英文保留自然标点、空格、缩写和完整单词。
- 中文与英文、数字之间已经自动加空格；只因空格不同不提交修改。
- 保留数字、小数点、版本号和 `1:20:100` 这类比例的原样写法。

## 术语表建议

同一个错误在多句里出现，或者以后的视频很可能再出现（例如某个产品名总被识别错），把它写进修改文件的 `glossary`，供用户在 App 的学习提示中加入词库。提交纠错或接受提案本身不等于已加入。一次性的错误不要放进去。

## 应用后验收

按主流程检查实际回执，应用后重新 `subtitles get`：逐条核对已接受的 `id` 和改后 `text`，说明 `skipped`，确认 `diagnostics` 中的同名异写、残留语气词/口吃和版式告警已清零。独立停顿中的“呃、啊”优先在剪辑方案里剪掉声音；因连读或画面操作保留在成片里的“呃、嗯、额、啊”和口吃叠词，在字幕校对里清理干净。
