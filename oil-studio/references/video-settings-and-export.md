# 工程配置与导出

用于调整录屏工程的画面、声音、字幕样式和导出选项。只通过命令行操作，不直接改工程包。

## 读取与修改

```sh
oilstudio settings schema
oilstudio settings get <工程> --out <新临时文件.json>
oilstudio settings apply <工程> <修改.json> --review
```

`schema.fields` 是当前版本的可修改字段清单，包含 `section`、`key`、`type`、`default`、`minimum`、`maximum`、`values`。不要凭猜测填字段或数值。`settings get` 返回 `schemaVersion`、`projectFingerprint` 与 `settings`；在临时文件里写补丁，只放用户要改的字段。例如：

```json
{
  "schemaVersion": 1,
  "projectFingerprint": "来自 settings get",
  "settings": {
    "style": {"backdropMode": "none", "pointerScale": 1.5},
    "subtitles": {"fontScale": 1.1},
    "export": {"quality": "minimal", "hevc": true}
  }
}
```

指纹可选，建议带上；工程已变化就重新读取，不用旧补丁覆盖当前修改。省略的字段保持原值。`default` 描述缺少字段时的基准，实际工程以 `get` 为准，不能拿默认值覆盖整组。

- `style`：画幅 `canvasAspect: {x,y}`、留白、裁剪 `cropNormalized: {x,y,width,height}`、背景、阴影、光标、摄像头、音量与静音。坐标为归一化的 0–1；`cameraAnchor` 会同步摄像头位置，同一补丁给出 `cameraCenterNormalized` 时以明确位置为准。背景 `none/system/gradient/color/image`；`system` 表示壁纸。渐变 `backdropGradient` 为 `null` 或 `{start:{x,y},end:{x,y},stops:[{at:0,color:"#112233"},{at:1,color:"#445566"}]}`，2–16 个色标。`pointerIdleSourceMs` 是源时间毫秒，`null` 关闭闲置隐藏。
- `layout`：默认布局 `type`；分段布局、缩放、删减仍按主流程提交剪辑方案。
- `cameraAutomation`、`voice`、`beauty`、`avatar`、`music`：摄像头自动处理、人声增强、美颜、头像、背景音乐。
- `subtitles`：语言、样式、位置、大小、底色、章节进度。`chapterProgressEnabled` 控制显示，`chapterProgressPosition` 为 `bottom` / `top`；不改字幕正文或章节内容，正文走 `subtitles apply`，章节走 `chapters apply`。
- `transitions`：剪切点效果和成片时间毫秒的 `spanMs`。
- `export`：保存 MP4/GIF、分辨率、帧率、质量、HEVC、字幕、SRT、GIF 宽度与帧率选项。

媒体选项引用已有素材：背景图片须为工程内的相对路径；音乐 `id` 是已有内置曲目 ID 或工程已导入的音乐文件名，头像 `packID` 是已安装的素材包 ID。可沿用 `get` 返回的引用；不要编造 ID，也不把任意磁盘路径当素材。此接口不导入素材、不读取或修改云端密钥、录制偏好或工程的 AI 自动应用开关。

提案按分组确认，遵循工程现有直接生效开关；`--review` 强制先确认。`autoApplied: false` 时等待 `proposal status <id> --wait`，不能据此说已修改。若返回 `changed: false`，说明没有差异，无需等待提案。生效后再 `settings get` 回读具体值，确认后才能导出；⌘Z 可撤销。App 未运行时会排队，不直接写工程。

## 导出

```sh
oilstudio export <工程> --out <成片.mp4>
oilstudio export <工程> --out <小体积.mp4> --quality minimal --codec hevc --no-srt
oilstudio export <工程> --out <预览.gif> --gif-width 640 --gif-fps 15 --no-srt
oilstudio export <工程> --out <片段.mp4> --output-from-ms 1000 --output-to-ms 6000
```

未指定的参数沿用工程已保存的导出设置。命令行参数只作用于本次导出，不修改工程选项。格式由输出扩展名决定，也可用 `--format mp4|gif`，两者必须一致。

MP4 可指定 `--quality minimal|compact|standard|high`、`--codec h264|hevc`、`--resolution 720p|1080p|1440p|2160p`、`--fps <整数>`。`minimal` 是极小档，清晰度和体积需取舍；HEVC 不改变设定的分辨率与帧率，部分旧设备或软件可能不支持。当前不支持 AV1、VP9 或手填 Mbps，不编造这些参数。

GIF 使用 `--gif-width <像素>`、`--gif-fps <帧率>`；不接受 MP4 的质量、编码、分辨率参数，也不含音频。`--fps` 可作 GIF 帧率别名，优先 `--gif-fps`。长度和尺寸仍受 App 的现有导出限制。

`--subtitles burn|none` 控制画面字幕，`--srt` / `--no-srt` 控制是否同时输出 SRT；不传则沿用工程选项。明确要求烧录或 SRT 而字幕不存在时，先按主入口生成字幕。`--output-from-ms` / `--output-to-ms` 是**成片时间**的起止毫秒，左闭右开，不是源素材时间；SRT 会裁到这个范围并从 0 计时。只导出部分时不会改工程时间线。

目标已存在时按用户已有覆盖授权处理，未获授权则询问；带 `--overwrite` 才会覆盖。导出需满足 App 的授权要求，不能绕过。最终回执包含 `path`、`format`、`width`、`height`、`fps`、`quality`、`codec`、`durationMs`，另有实际导出的 `srt` 路径；GIF 的 `codec` 为 null。完成前不宣称文件已导出。
