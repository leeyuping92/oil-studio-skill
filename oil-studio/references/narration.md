# 字幕配音

用户要求配音时，先用 `oilstudio narration status <工程>` 查看每句状态。凭据在 App 的语音合成设置中配置，命令行不接收明文密钥。

```sh
oilstudio narration generate "<工程>"
oilstudio narration generate "<工程>" --provider bailian --region beijing --model qwen-audio-3.1-tts-flash --voice longanhuan_v3.1 --speed 1.15
oilstudio narration generate "<工程>" --cue cue-1 --cue cue-2
oilstudio narration import "<工程>" /tmp/narration.json
```

默认仅生成缺失与过期的配音。`--outdated` 只更新过期句；`--force` 重新生成全部；`--speed <0.5–2.0>` 覆盖本次合成语速（未指定时沿用本机已保存的 TTS 语速，初始默认 `1.0`）。`--cue` 可重复指定句子。生成后再次读取 status，遇到 `overflow` 时精简文字或调整字幕和画面的时间。

撰写或整理配音字幕（`subtitles apply`）时，每条 `cue` 只写一句简短自然的口语短句（中文约 10–18 字、英文一个短分句），不要用逗号把两层意思拼成一条长字幕。

外部音频清单示例：

```json
{"schemaVersion":1,"mode":"replaceMicrophone","volume":1,"items":[{"cueID":"cue-1","expectedText":"当前完整字幕文字","audioPath":"/绝对路径/音频.mp3"}]}
```

`expectedText` 必须与当前字幕一致。导入会统一音频格式，并与生成使用相同排期规则。App 中打开的工程一步可撤销；离线工程直接保存。开启配音后，字幕显示与 SRT 时间跟随有效配音，旧配音不会用于已修改的句子。
