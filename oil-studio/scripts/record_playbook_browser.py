"""Browser-side Playbook actions and screen-to-window coordinate conversion."""

from __future__ import annotations

import sys
sys.dont_write_bytecode = True

import json
import locale
import os
import secrets
import select
import subprocess
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from pathlib import Path
from typing import Any, Callable, Optional


MESSAGES: dict[str, dict[str, str]] = {
    "unsafeReport": {"zh-Hans": "报告路径不能位于工程包内、是符号链接或已存在：{path}", "en": "Report path must not be inside a project package, a symbolic link, or an existing file: {path}"},
    "interrupted": {"zh-Hans": "录制已中断。", "en": "Recording was interrupted."},
    "readPlaybookOS": {"zh-Hans": "无法读取 Playbook JSON 文件：{path}", "en": "Couldn’t read the playbook JSON file: {path}"},
    "readPlaybookJSON": {"zh-Hans": "Playbook JSON 格式错误（第 {line} 行，第 {column} 列）。", "en": "The playbook JSON is malformed (line {line}, column {column})."},
    "topLevelObject": {"zh-Hans": "Playbook 顶层必须是 JSON 对象。", "en": "The playbook’s top level must be a JSON object."},
    "sourceObject": {"zh-Hans": "source 必须是对象。", "en": "source must be an object."},
    "sourceFieldNonempty": {"zh-Hans": "source.{key} 必须是非空字符串。", "en": "source.{key} must be a non-empty string."},
    "sourceRequired": {"zh-Hans": "source 需要 sourceId，或 app/title 匹配条件。", "en": "source requires sourceId or an app/title matching condition."},
    "exactTitleBoolean": {"zh-Hans": "source.exactTitle 必须是布尔值。", "en": "source.exactTitle must be a Boolean."},
    "browserObject": {"zh-Hans": "browser 必须是对象。", "en": "browser must be an object."},
    "browserHost": {"zh-Hans": "browser.host 只支持 stage-window、cdp、browser 或 ego-browser。", "en": "browser.host supports stage-window, cdp, browser, or ego-browser."},
    "browserCdpURL": {"zh-Hans": "browser.cdpURL 必须是本机调试地址，例如 http://127.0.0.1:9222。", "en": "browser.cdpURL must be a local debugging address, such as http://127.0.0.1:9222."},
    "browserCdpURLHost": {"zh-Hans": "cdp 宿主需要 browser.cdpURL；browser.cdpURL 也只能和 cdp 宿主一起使用。", "en": "The cdp host requires browser.cdpURL, and browser.cdpURL works only with the cdp host."},
    "browserTabs": {"zh-Hans": "browser.tabs 必须是数组，每项包含唯一的 id（不能是 main）和 http(s) url。", "en": "browser.tabs must be an array whose items each have a unique id (not main) and an HTTP(S) url."},
    "tabsNeedBrowser": {"zh-Hans": "独立舞台只有一个页面；预先打开或切换标签页需要 cdp 或 browser 宿主。", "en": "The isolated stage has a single page. Opening or switching tabs requires the cdp or browser host."},
    "preflightBoolean": {"zh-Hans": "browser.preflight 必须是布尔值。", "en": "browser.preflight must be a Boolean."},
    "preflightForbidArray": {"zh-Hans": "browser.preflightForbid 必须是字符串数组，且各项非空。", "en": "browser.preflightForbid must be an array of non-empty strings."},
    "preflightForbiddenText": {"zh-Hans": "开录前的窗口快照里出现了不该录进画面的文字：{texts}。请先关掉这些浮层或提示（例如浏览器的自动化控制条、翻译弹窗）。浏览器被自动化接管时会一直显示控制条，请改用 cdp 宿主或独立舞台。已阻止录制。", "en": "The window snapshot before recording shows text that shouldn’t appear in the video: {texts}. Close these overlays or prompts first, such as a browser automation bar or a translation prompt. A browser under automation control keeps showing its control bar, so use the cdp host or the isolated stage instead. Recording didn’t start."},
    "stageSourceIdConflict": {"zh-Hans": "独立舞台（未指定 browser.host 与 browser.cdpURL 时的默认宿主）每次都是新窗口，不能指定 source.sourceId；请改用 source.title 或 app，或设置 browser.cdpURL 连接已打开的浏览器。", "en": "The isolated stage, the default when browser.host and browser.cdpURL aren’t set, opens a new window each time, so source.sourceId can’t be used. Use source.title or app instead, or set browser.cdpURL to connect to a browser that’s already open."},
    "browserSpaceType": {"zh-Hans": "browser.space 或 browser.spaceId 必须是字符串或整数。", "en": "browser.space or browser.spaceId must be a string or integer."},
    "browserPageFormat": {"zh-Hans": "browser.page 必须是 user 或已存在的 Page 标签（例如 p1）。", "en": "browser.page must be user or an existing page label, such as p1."},
    "cropBrowserChromeBoolean": {"zh-Hans": "browser.cropBrowserChrome 必须是布尔值。", "en": "browser.cropBrowserChrome must be a Boolean."},
    "preflightSecondsRange": {"zh-Hans": "browser.preflightSeconds 必须在 0–10 秒。", "en": "browser.preflightSeconds must be between 0 and 10 seconds."},
    "preflightContainsArray": {"zh-Hans": "browser.preflightContains 必须是字符串数组，且各项非空。", "en": "browser.preflightContains must be an array of non-empty strings."},
    "preflightTextNeedsPreflight": {"zh-Hans": "设置了 browser.preflightContains 或 preflightForbid 时不能关闭开录前检查（browser.preflight）。", "en": "browser.preflightContains and preflightForbid require the pre-recording check (browser.preflight) to stay on."},
    "scratchDirectoryNonempty": {"zh-Hans": "browser.scratchDir 必须是非空路径字符串。", "en": "browser.scratchDir must be a non-empty path string."},
    "settingsObject": {"zh-Hans": "settings 必须是非空设置分组对象。", "en": "settings must be a non-empty object containing setting groups."},
    "beatsNonempty": {"zh-Hans": "beats 必须至少包含一拍。", "en": "beats must contain at least one beat."},
    "beatObject": {"zh-Hans": "beats[{index}] 必须是对象。", "en": "beats[{index}] must be an object."},
    "beatIdNonempty": {"zh-Hans": "beats[{index}].id 必须是非空字符串。", "en": "beats[{index}].id must be a non-empty string."},
    "duplicateBeatId": {"zh-Hans": "拍子 id 重复：{identifier}", "en": "Duplicate beat id: {identifier}"},
    "subtitleRequired": {"zh-Hans": "拍子 {identifier} 的字幕必须是字符串。", "en": "The subtitle for beat {identifier} must be a string."},
    "beatActionsArray": {"zh-Hans": "拍子 {identifier} 的 actions 必须是数组。", "en": "actions for beat {identifier} must be an array."},
    "beatHudObject": {"zh-Hans": "拍子 {identifier} 的 hud 必须是对象。", "en": "hud for beat {identifier} must be an object."},
    "hudPositionInvalid": {"zh-Hans": "拍子 {identifier} 的 hud.position 无效。", "en": "hud.position for beat {identifier} is invalid."},
    "hudFieldString": {"zh-Hans": "拍子 {identifier} 的 hud.{key} 必须是字符串。", "en": "hud.{key} for beat {identifier} must be a string."},
    "hudPillsArray": {"zh-Hans": "拍子 {identifier} 的 hud.pills 必须是数组。", "en": "hud.pills for beat {identifier} must be an array."},
    "hudPillFields": {"zh-Hans": "拍子 {identifier} 的 HUD pill 需要 label 和 value。", "en": "Each HUD pill for beat {identifier} requires label and value."},
    "hudPillColor": {"zh-Hans": "HUD pill color 只接受十六进制颜色。", "en": "HUD pill colors must be hexadecimal values."},
    "beatZoomObject": {"zh-Hans": "拍子 {identifier} 的 zoom 必须是对象。", "en": "zoom for beat {identifier} must be an object."},
    "zoomLevelRange": {"zh-Hans": "拍子 {identifier} 的 zoom.level 必须在 1–3。", "en": "zoom.level for beat {identifier} must be between 1 and 3."},
    "zoomSelectorTarget": {"zh-Hans": "拍子 {identifier} 的手动缩放需要 selector 或 target 二选一；自动缩放不能指定目标。", "en": "Manual zoom for beat {identifier} requires exactly one selector or target; automatic zoom cannot specify a target."},
    "zoomModeInvalid": {"zh-Hans": "拍子 {identifier} 的 zoom.mode 无效。", "en": "zoom.mode for beat {identifier} is invalid."},
    "zoomTargetRange": {"zh-Hans": "拍子 {identifier} 的 zoom.target x/y 必须在 0–1。", "en": "zoom.target x/y for beat {identifier} must be between 0 and 1."},
    "zoomTransitionInvalid": {"zh-Hans": "拍子 {identifier} 的 zoom.transition 无效。", "en": "zoom.transition for beat {identifier} is invalid."},
    "firstOpenRequired": {"zh-Hans": "第一拍的第一个动作必须是 open，用来准备录制开始画面。", "en": "The first action of the first beat must be open so it can prepare the opening recording frame."},
    "actionPrefix": {"zh-Hans": "拍子 {beat_id} 的 actions[{index}]", "en": "Beat {beat_id}, actions[{index}]"},
    "actionObject": {"zh-Hans": "{prefix} 必须是对象。", "en": "{prefix} must be an object."},
    "actionUnsupported": {"zh-Hans": "{prefix}.action 不支持。", "en": "{prefix}.action is unsupported."},
    "actionWheelDelta": {"zh-Hans": "{prefix} 需要有限数值的 deltaX 或 deltaY，且至少一个不为 0。", "en": "{prefix} requires finite deltaX or deltaY values, at least one of them nonzero."},
    "actionSwitchTab": {"zh-Hans": "{prefix}.tab 必须是 main 或 browser.tabs 里的 id。", "en": "{prefix}.tab must be main or an id from browser.tabs."},
    "actionOpenURL": {"zh-Hans": "{prefix} 需要 http(s) URL。", "en": "{prefix} requires an HTTP(S) URL."},
    "actionSelectorFraction": {"zh-Hans": "{prefix} 需要 selector 或 fraction 二选一。", "en": "{prefix} requires exactly one of selector or fraction."},
    "actionFractionRange": {"zh-Hans": "{prefix}.fraction u/v 必须在 0–1。", "en": "{prefix}.fraction u/v must be between 0 and 1."},
    "actionScrollTarget": {"zh-Hans": "{prefix} 需要 y 或 selector 二选一。", "en": "{prefix} requires exactly one of y or selector."},
    "actionFiniteY": {"zh-Hans": "{prefix}.y 必须是有限数值。", "en": "{prefix}.y must be a finite number."},
    "actionSelectorNonempty": {"zh-Hans": "{prefix}.selector 必须是非空字符串。", "en": "{prefix}.selector must be a non-empty string."},
    "actionDurationNonnegative": {"zh-Hans": "{prefix}.durationMs 必须非负。", "en": "{prefix}.durationMs must be non-negative."},
    "actionInputSelector": {"zh-Hans": "{prefix} 缺少 selector。", "en": "{prefix} is missing selector."},
    "actionInputValue": {"zh-Hans": "{prefix} 需要 value 或 to。", "en": "{prefix} requires value or to."},
    "actionFromToPair": {"zh-Hans": "{prefix} 使用渐变时需要同时提供 from 和 to。", "en": "{prefix} requires both from and to for a transition."},
    "actionFromToFinite": {"zh-Hans": "{prefix} 的渐变 from/to 必须是有限数值。", "en": "Transition from/to values for {prefix} must be finite numbers."},
    "actionEvalScript": {"zh-Hans": "{prefix} 缺少 script。", "en": "{prefix} is missing script."},
    "actionWaitNonnegative": {"zh-Hans": "{prefix}.ms 必须非负。", "en": "{prefix}.ms must be non-negative."},
    "commandNoJSON": {"zh-Hans": "命令没有返回 JSON：{command}（第 {line} 行，第 {column} 列）；输出：{output}", "en": "The command didn’t return JSON: {command} (line {line}, column {column}); output: {output}"},
    "commandFailed": {"zh-Hans": "命令失败：{command}\n{result}", "en": "The command failed: {command}\n{result}"},
    "sourceMatchCount": {"zh-Hans": "录制来源匹配到 {count} 个窗口；请调整 sourceId、app 或 title 匹配条件。", "en": "The recording source matched {count} windows. Adjust the sourceId, app, or title conditions."},
    "sourceWindowOnly": {"zh-Hans": "Playbook 只录制窗口来源。", "en": "Playbooks can record window sources only."},
    "sourceDimensions": {"zh-Hans": "录制来源缺少窗口尺寸。", "en": "The recording source has no window dimensions."},
    "pageTitleMissing": {"zh-Hans": "实际页面没有可用于匹配录制窗口的标题。", "en": "The actual page has no title that can identify the recording window."},
    "pageTitleMismatch": {"zh-Hans": "实际页面标题与 source.title 匹配条件不一致。", "en": "The actual page title doesn’t satisfy the source.title condition."},
    "cliDescription": {"zh-Hans": "按 Playbook 编排网页录制、字幕、HUD 与缩放。", "en": "Record a web demonstration with beat captions, HUD cards, and zooms from a playbook."},
    "helpPlaybook": {"zh-Hans": "Playbook JSON 文件", "en": "Playbook JSON file"},
    "helpOutReport": {"zh-Hans": "写入录制与处理结果 JSON", "en": "Write the recording and processing report as JSON"},
    "helpExport": {"zh-Hans": "可选的 MP4 导出路径", "en": "Optional MP4 export path"},
    "helpDryRun": {"zh-Hans": "只校验 Playbook，不启动浏览器或录制", "en": "Validate the playbook without opening a browser or recording"},
    "inspectConflict": {"zh-Hans": "--inspect 不能与 --rehearse、--dry-run 或 --preflight-only 一起使用。", "en": "--inspect cannot be combined with --rehearse, --dry-run, or --preflight-only."},
    "rehearseConflict": {"zh-Hans": "--rehearse 不能与 --dry-run、--preflight-only 或 --export 一起使用。", "en": "--rehearse cannot be combined with --dry-run, --preflight-only, or --export."},
    "helpInspect": {"zh-Hans": "在舞台窗口检查网页元素", "en": "Inspect page elements in a stage window"},
    "helpRehearse": {"zh-Hans": "在舞台窗口试跑 Playbook，不录制", "en": "Rehearse the playbook in a stage window without recording"},
    "inspectURL": {"zh-Hans": "--inspect 需要 http(s) URL。", "en": "--inspect requires an HTTP(S) URL."},
    "actionPressKey": {"zh-Hans": "{prefix}.key 需要有效按键及可选修饰键。", "en": "{prefix}.key requires a valid key and optional modifiers."},
    "stageUnstable": {"zh-Hans": "等待网页渲染稳定超时。", "en": "Timed out waiting for the page to settle."},
    "helpPreflightOnly": {"zh-Hans": "只做开录前的窗口快照与文字检查，不开始录制", "en": "Run only the pre-recording window snapshot and text check, without recording"},
    "helpHelp": {"zh-Hans": "显示此帮助并退出", "en": "Show this help and exit"},
    "usagePrefix": {"zh-Hans": "用法：", "en": "usage:"},
    "optionsHeading": {"zh-Hans": "选项：", "en": "options:"},
    "requiredArguments": {"zh-Hans": "缺少必需参数：{arguments}", "en": "The following arguments are required: {arguments}"},
    "unrecognizedArguments": {"zh-Hans": "无法识别参数：{arguments}", "en": "Unrecognized arguments: {arguments}"},
    "expectedArgumentValue": {"zh-Hans": "参数 {argument} 需要一个值。", "en": "Argument {argument} expects one value."},
    "ignoredExplicitArgument": {"zh-Hans": "参数 {argument} 不接受值 {value}。", "en": "Argument {argument} doesn’t accept value {value}."},
    "argumentError": {"zh-Hans": "参数错误", "en": "Argument error"},
    "invalidArguments": {"zh-Hans": "参数无效：{detail}", "en": "Invalid arguments: {detail}"},
    "cliNotFound": {"zh-Hans": "找不到命令行：{command}", "en": "Command-line tool not found: {command}"},
    "nodeUnavailable": {"zh-Hans": "舞台页面控制所需的 JavaScript 运行环境不可用。", "en": "The JavaScript runtime required to control the stage page is unavailable."},
    "browserAutomationUnavailable": {"zh-Hans": "网页自动化运行环境不可用。", "en": "The browser automation runtime is unavailable."},
    "exportExtension": {"zh-Hans": "--export 需要 .mp4 路径。", "en": "--export requires an .mp4 path."},
    "exportExists": {"zh-Hans": "导出文件已存在；请选择新的输出路径。", "en": "The export file already exists. Choose a new output path."},
    "pageURLMismatch": {"zh-Hans": "浏览器页面地址与 Playbook 演示页不一致。", "en": "The browser page URL doesn’t match the playbook demonstration page."},
    "stagePageUnavailable": {"zh-Hans": "独立舞台页面不可用。", "en": "The isolated stage page is unavailable."},
    "nativeTitleMismatch": {"zh-Hans": "原生采集窗口或活动页面标题不匹配。", "en": "The native capture window or active page title doesn’t match."},
    "stageStyleObject": {"zh-Hans": "settings.style 必须是对象，无法确认舞台画面边界。", "en": "settings.style must be an object so the stage frame bounds can be verified."},
    "browserViewportInvalid": {"zh-Hans": "浏览器视口尺寸无效，无法安全裁掉顶部浏览器区域。", "en": "The browser viewport dimensions are invalid, so browser chrome can’t be cropped safely."},
    "browserCropInvalid": {"zh-Hans": "浏览器顶部裁切范围无效。", "en": "The browser’s top crop range is invalid."},
    "browserStyleObject": {"zh-Hans": "settings.style 必须是对象，无法设置顶部裁切。", "en": "settings.style must be an object so the top crop can be set."},
    "preflightOnlyNeedsPreflight": {"zh-Hans": "--preflight-only 需要开启开录前检查（browser.preflight）。", "en": "--preflight-only requires the pre-recording check (browser.preflight) to be on."},
    "preflightOCRMissing": {"zh-Hans": "开录前的窗口快照没有识别到 preflightContains 的全部文字，已阻止录制。", "en": "The window snapshot before recording didn’t show every preflightContains string. Recording didn’t start."},
    "recordingSourceChanged": {"zh-Hans": "录制采集窗口已变化；录制已中止以避免混入其他页面。", "en": "The recording capture window changed. Recording stopped to avoid capturing another page."},
    "recordingNotActive": {"zh-Hans": "录制已暂停或结束；Playbook 已停止，没有继续执行浏览器动作。", "en": "Recording is paused or has ended. The playbook stopped before running another browser action."},
    "recordingStoppedUnexpectedly": {"zh-Hans": "录制由 {stopped_by} 停止；Playbook 不会继续处理这段工程。", "en": "Recording stopped by {stopped_by}. The playbook won’t continue processing this project."},
    "beatZeroDuration": {"zh-Hans": "拍子 {identifier} 的录制时长为零。", "en": "Beat {identifier} has zero recording duration."},
    "projectMissing": {"zh-Hans": "录制已停止，但没有返回工程路径。", "en": "The recording stopped without returning a project path."},
    "attachObject": {"zh-Hans": "attach 必须是对象，包含 project（口播工程路径）与 atOutputMs（非负成片毫秒）。", "en": "attach must be an object with project (the voice-over project path) and atOutputMs (non-negative output milliseconds)."},
    "attachProjectPath": {"zh-Hans": "attach.project 必须是 .oilstudio 工程路径。", "en": "attach.project must be a .oilstudio project path."},
    "attachPlanPath": {"zh-Hans": "attach.plan 必须是方案 JSON 文件路径。", "en": "attach.plan must be the path to a plan JSON file."},
    "attachReplaceRange": {"zh-Hans": "attach.replaceUntilOutputMs 必须大于 attach.atOutputMs（成片毫秒）。", "en": "attach.replaceUntilOutputMs must be greater than attach.atOutputMs (output milliseconds)."},
    "attachDurationRange": {"zh-Hans": "attach.durationMs 必须是正数（毫秒）。", "en": "attach.durationMs must be a positive number of milliseconds."},
    "attachExportUnsupported": {"zh-Hans": "补画面模式不导出成片；所有片段补完后再对口播工程运行 export。", "en": "Attach mode doesn’t export. Run export on the voice-over project after all clips are in place."},
    "actionAtMsRange": {"zh-Hans": "{prefix}.atMs 必须是非负毫秒，且只用于补画面模式（attach）。", "en": "{prefix}.atMs must be non-negative milliseconds and is only allowed in attach mode."},
    "actionAtMsOpen": {"zh-Hans": "{prefix} 是开场 open，在录制开始前执行，不能带 atMs。", "en": "{prefix} is the opening open action, which runs before recording starts, so it can’t have atMs."},
    "screenClipMissing": {"zh-Hans": "录制已并入口播工程，但没有返回录屏片段。", "en": "The recording was added to the voice-over project, but no screen clip was returned."},
    "autoZoomRemovalReason": {"zh-Hans": "替换录制点击自动缩放，避免与 Playbook 镜头段重叠", "en": "Replace recorded click zooms to avoid overlapping playbook zoom ranges"},
    "manualZoomOverlap": {"zh-Hans": "已有手动缩放与 Playbook 镜头段重叠；请先处理重叠后再提交。", "en": "An existing manual zoom overlaps a playbook zoom range. Resolve the overlap before submitting."},
    "zoomPlanSummary": {"zh-Hans": "网页演示重点缩放", "en": "Web demonstration zoom highlights"},
    "exportPendingReason": {"zh-Hans": "项目修改仍在等待应用。", "en": "Project changes are still waiting to be applied."},
    "commandTimeout": {"zh-Hans": "命令超过 {timeout} 秒未完成：{command}", "en": "The command didn’t finish within {timeout} seconds: {command}"},
    "osOperationFailed": {"zh-Hans": "文件或子进程操作失败：{detail}", "en": "A file or subprocess operation failed: {detail}"},
    "missingDataField": {"zh-Hans": "缺少必需数据字段：{field}", "en": "Required data field missing: {field}"},
    "runtimeJSONError": {"zh-Hans": "运行数据 JSON 格式错误（第 {line} 行，第 {column} 列）。", "en": "Runtime data contains malformed JSON (line {line}, column {column})."},
    "runtimeTypeError": {"zh-Hans": "运行数据类型无效。", "en": "The runtime data has an invalid type."},
    "unexpectedError": {"zh-Hans": "操作失败：{detail}", "en": "The operation failed: {detail}"},
    "stageBuildFailed": {"zh-Hans": "无法构建隔离舞台窗口宿主：{detail}", "en": "Couldn’t build the isolated stage window host: {detail}"},
    "stageNoPort": {"zh-Hans": "舞台窗口宿主没有输出本地控制端口。", "en": "The stage window host didn’t provide a local control port."},
    "stageExited": {"zh-Hans": "舞台窗口宿主提前退出：{detail}", "en": "The stage window host exited early: {detail}"},
    "stagePortTimeout": {"zh-Hans": "等待舞台窗口本地控制端口超时。", "en": "Timed out waiting for the stage window’s local control port."},
    "stageLoadFailed": {"zh-Hans": "舞台页未能加载到指定地址并取得实际标题：{detail}", "en": "The stage page couldn’t load the requested URL and report its actual title: {detail}"},
    "stageOperationFailed": {"zh-Hans": "舞台页操作失败：{detail}", "en": "The stage page operation failed: {detail}"},
    "unknownError": {"zh-Hans": "未知错误", "en": "unknown error"},
    "emptyOutput": {"zh-Hans": "无输出", "en": "empty output"},
    "targetOutsideWindow": {"zh-Hans": "网页目标换算后落在录制窗口之外；请检查窗口尺寸或选择器。", "en": "The web target falls outside the recording window after conversion. Check the window dimensions or selector."},
    "fractionOutsideViewport": {"zh-Hans": "窗口比例位置落在网页视口之外。", "en": "The window-relative position falls outside the web viewport."},
    "noUserPage": {"zh-Hans": "浏览器任务没有可同步的用户页面。", "en": "The browser task has no user page to synchronize."},
    "pageNotManagedPrefix": {"zh-Hans": "页面不属于当前浏览器任务：", "en": "The page isn’t managed by this browser task: "},
    "stageRequestFailed": {"zh-Hans": "舞台控制请求失败。", "en": "The stage control request failed."},
    "stageWaitTimeout": {"zh-Hans": "等待舞台页面状态超时。", "en": "Timed out waiting for the stage page."},
    "stageControllerUnavailable": {"zh-Hans": "舞台页面控制器不可用。", "en": "The stage page controller is unavailable."},
    "browserBridgeMissing": {"zh-Hans": "网页自动化桥接进程尚未启动。", "en": "The browser automation bridge hasn’t started."},
    "browserBridgeStartFailed": {"zh-Hans": "无法启动网页自动化桥接进程：{detail}", "en": "Couldn’t start the browser automation bridge: {detail}"},
    "browserBridgeExited": {"zh-Hans": "网页自动化桥接进程已退出：{detail}", "en": "The browser automation bridge exited: {detail}"},
    "browserOperationFailedDetail": {"zh-Hans": "网页操作失败：{detail}", "en": "The browser operation failed: {detail}"},
    "cdpNeedsNode": {"zh-Hans": "cdp 宿主需要 Node.js 22 或更新版本。", "en": "The cdp host requires Node.js 22 or later."},
    "cdpUnavailable": {"zh-Hans": "无法连接浏览器调试端口；请确认浏览器已用 --remote-debugging-port 启动，且 browser.cdpURL 正确。", "en": "Couldn’t connect to the browser’s debugging port. Make sure the browser was started with --remote-debugging-port and that browser.cdpURL is correct."},
    "cdpClosed": {"zh-Hans": "与浏览器调试端口的连接已断开。", "en": "The connection to the browser’s debugging port closed."},
    "cdpLoadTimeout": {"zh-Hans": "等待页面加载超时。", "en": "Timed out waiting for the page to load."},
    "tabsUnsupported": {"zh-Hans": "当前浏览器宿主不支持多个标签页。", "en": "This browser host doesn’t support multiple tabs."},
    "tabUnknownPrefix": {"zh-Hans": "没有这个标签页：", "en": "No such tab: "},
    "noElementPrefix": {"zh-Hans": "没有元素匹配选择器：", "en": "No element matches selector: "},
    "zoomSelectorOutsidePrefix": {"zh-Hans": "缩放选择器不在当前视口内：", "en": "The zoom selector is outside the current viewport: "},
}


def selected_language() -> str:
    override = os.environ.get("OILSTUDIO_LANGUAGE")
    if override:
        candidates = [override]
    else:
        candidates = [os.environ.get("LC_ALL"), os.environ.get("LC_MESSAGES"), os.environ.get("LANG")]
        try:
            candidates.append(locale.getlocale()[0])
        except ValueError:
            pass
    for candidate in candidates:
        if not candidate:
            continue
        normalized = candidate.replace("_", "-").casefold()
        if normalized.startswith("zh"):
            return "zh-Hans"
        if normalized.startswith("en"):
            return "en"
    return "en"


def message(message_key: str, **values: Any) -> str:
    return MESSAGES[message_key][selected_language()].format(**values)


def js_message(message_key: str, **values: Any) -> str:
    return json.dumps(message(message_key, **values), ensure_ascii=False)


# The persistent bridge (record_playbook_bridge.BrowserBridge) that browser_call uses; set by its `activate`.
_ACTIVE_BRIDGE: Any = None


def comparable_urls_match(actual: Any, target: Any) -> bool:
    if not isinstance(actual, str) or not isinstance(target, str):
        return False
    try:
        opened, requested = urlsplit(actual), urlsplit(target)
        schemes_match = opened.scheme.lower() == requested.scheme.lower() or (
            requested.scheme.lower() == "http" and opened.scheme.lower() == "https")
        return (schemes_match and opened.hostname is not None and requested.hostname is not None
            and opened.hostname.lower() == requested.hostname.lower()
            and opened.port == requested.port and opened.username == requested.username
            and opened.password == requested.password and (opened.path or "/") == (requested.path or "/")
            and opened.query == requested.query and opened.fragment == requested.fragment)
    except ValueError:
        return False


class StageWindowHost:
    """Launch an isolated, non-activating WKWebView window for recording."""

    def __init__(self, process: subprocess.Popen[str], base_url: str, log_path: Path, token: str):
        self.process = process
        self.base_url = base_url
        self.log_path = log_path
        self.token = token

    @classmethod
    def start(cls, url: str, scratch_dir: Path) -> "StageWindowHost":
        scratch_dir.mkdir(parents=True, exist_ok=True)
        binary = scratch_dir / "record_playbook_stage"
        source = Path(__file__).with_name("record_playbook_stage.swift")
        compiled = subprocess.run(["swiftc", "-framework", "AppKit", "-framework", "WebKit", "-framework", "Network",
            str(source), "-o", str(binary)], capture_output=True, text=True, timeout=120)
        if compiled.returncode != 0:
            raise ValueError(message("stageBuildFailed", detail=compiled.stderr[-3000:]))
        token = secrets.token_urlsafe(32)
        environment = os.environ.copy()
        environment["OILSTUDIO_PLAYBOOK_STAGE_TOKEN"] = token
        log_path = scratch_dir / "stage-host.log"
        log_file = log_path.open("w", encoding="utf-8")
        process = subprocess.Popen([str(binary), url], stdout=subprocess.PIPE, stderr=log_file, env=environment,
            text=True, bufsize=1, start_new_session=True)
        log_file.close()
        try:
            return cls._finish_start(process, url, log_path, token)
        except BaseException:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            if process.stdout:
                process.stdout.close()
            raise

    @classmethod
    def _finish_start(cls, process: subprocess.Popen[str], url: str, log_path: Path, token: str) -> "StageWindowHost":
        if process.stdout is None:
            process.terminate()
            raise ValueError(message("stageNoPort"))
        ready = None
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if process.poll() is not None:
                detail = log_path.read_text(encoding="utf-8", errors="replace")[-3000:]
                raise ValueError(message("stageExited", detail=detail))
            readable, _, _ = select.select([process.stdout], [], [], 0.25)
            if not readable:
                continue
            line = process.stdout.readline().strip()
            if line.startswith("STAGE_READY "):
                ready = json.loads(line.removeprefix("STAGE_READY "))
                break
        if not ready or not isinstance(ready.get("port"), int):
            process.terminate()
            raise ValueError(message("stagePortTimeout"))
        host = cls(process, f"http://127.0.0.1:{ready['port']}", log_path, token)
        try:
            host.wait_until_ready(url)
        except Exception:
            host.close()
            raise
        return host

    def wait_until_ready(self, url: str) -> dict[str, Any]:
        deadline = time.monotonic() + 30
        last_error: Optional[Exception] = None
        while time.monotonic() < deadline:
            try:
                state = self._request("GET", "/state")
                actual_url = state.get("url")
                if (isinstance(state.get("title"), str)
                        and state.get("readyState") in ("interactive", "complete")
                        and (comparable_urls_match(actual_url, url)
                             or (isinstance(actual_url, str) and actual_url.startswith(("http://", "https://"))
                                 and state.get("readyState") == "complete"))):
                    return state
            except (OSError, ValueError, urllib.error.URLError) as exc:
                last_error = exc
            if self.process.poll() is not None:
                break
            time.sleep(0.1)
        detail = self.log_path.read_text(encoding="utf-8", errors="replace")[-3000:]
        raise ValueError(message("stageLoadFailed", detail=last_error or detail))

    def _request(self, method: str, path: str, body: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {"Authorization": f"Bearer {self.token}"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base_url + path, data=data, method=method, headers=headers)
        with urllib.request.urlopen(request, timeout=15) as response:
            result = json.loads(response.read().decode("utf-8"))
        if not result.get("ok"):
            raise ValueError(message("stageOperationFailed", detail=result.get("error") or message("unknownError")))
        return result.get("result", {})

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.process.stdout:
            self.process.stdout.close()


def require(condition: bool, message_key: str, **values: Any) -> None:
    if not condition:
        raise ValueError(message(message_key, **values))


def browser_call(space: Any, body: str, timeout: float = 60, page_ref: str = "p1") -> Any:
    """Runs `body` (an async JavaScript function body with `page` and `task` in scope) in the active bridge.

    `space` and `page_ref` were bound when the bridge started (record_playbook_bridge.BrowserBridge.start);
    the parameters stay so call sites read the same for every host."""
    bridge = _ACTIVE_BRIDGE
    require(bridge is not None, "browserBridgeMissing")
    return bridge.call(body, timeout=timeout)


def switch_tab(tab: str) -> None:
    bridge = _ACTIVE_BRIDGE
    require(bridge is not None, "browserBridgeMissing")
    bridge.switch_tab(tab)


def open_tab(tab: str, url: str) -> None:
    bridge = _ACTIVE_BRIDGE
    require(bridge is not None, "browserBridgeMissing")
    bridge.open_tab(tab, url)


def page_metrics(space: Any, source: dict[str, Any], page_ref: str = "p1") -> dict[str, float]:
    metrics = browser_call(space, 'return await page.evaluate(() => ({ innerWidth, innerHeight, outerWidth, outerHeight }));', page_ref=page_ref)
    metrics["sourceWidth"] = source["width"]
    metrics["sourceHeight"] = source["height"]
    return metrics


def to_window_point(metrics: dict[str, float], source: dict[str, Any], x: Optional[float] = None,
    y: Optional[float] = None) -> dict[str, float]:
    chrome_x = max(0, (metrics["outerWidth"] - metrics["innerWidth"]) / 2)
    chrome_y = max(0, metrics["outerHeight"] - metrics["innerHeight"])
    view_x = metrics["x"] if x is None else x
    view_y = metrics["y"] if y is None else y
    # Browser metrics are CSS pixels; normalize against the browser's outer frame
    # so capture resolution and display scale do not skew the reported point.
    u = (chrome_x + view_x) / metrics["outerWidth"]
    v = (chrome_y + view_y) / metrics["outerHeight"]
    require(0 <= u <= 1 and 0 <= v <= 1, "targetOutsideWindow")
    return {"u": u, "v": v, "viewX": view_x, "viewY": view_y}


def selector_point(space: Any, selector: str, source: dict[str, Any], scroll: bool = True,
    enter_beat: Optional[int] = None, page_ref: str = "p1") -> dict[str, float]:
    data = {"selector": selector, "enterBeat": enter_beat}
    measured = browser_call(space, f'''const input = {json.dumps(data, ensure_ascii=False)};
let probe = null;
for (let attempt = 0; attempt < 65; attempt++) {{
  await page.waitForLoadState();
  probe = await page.evaluate((input) => {{
    if (input.enterBeat !== null) {{
      if (typeof window.enterBeat !== "function") return {{ missingController: true }};
      window.enterBeat(input.enterBeat);
    }}
    const node = document.querySelector(input.selector);
    if (!node) return null;
    const r = node.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return null;
    let fixedOrSticky = false;
    for (let el = node; el; el = el.parentElement) {{
      if (["fixed", "sticky"].includes(getComputedStyle(el).position)) {{ fixedOrSticky = true; break; }}
    }}
    return {{ fixedOrSticky, top: r.top, bottom: r.bottom, left: r.left, right: r.right, width: r.width, height: r.height, innerWidth, innerHeight, outerWidth, outerHeight }};
  }}, input);
  if (probe && probe.missingController) throw new Error({js_message("stageControllerUnavailable")});
  if (probe) break;
  await page.waitForTimeout(120);
}}
if (!probe) throw new Error({js_message("noElementPrefix")} + input.selector);
if (input.enterBeat !== null) await page.waitForTimeout(420);
if ({str(scroll).lower()} && !probe.fixedOrSticky && (probe.top < 48 || probe.bottom > probe.innerHeight - 48)) {{
  const didScroll = await page.evaluate(async (selector) => {{
    const nextFrame = fn => setTimeout(() => fn(performance.now()), 16);
    const root = document.scrollingElement || document.documentElement;
    const element = document.querySelector(selector);
    if (!element) return false;
    let scroller = root;
    for (let node = element.parentElement; node; node = node.parentElement) {{
      const style = getComputedStyle(node);
      if (node.scrollHeight > node.clientHeight && /auto|scroll/.test(style.overflowY)) {{ scroller = node; break; }}
    }}
    const r = element.getBoundingClientRect();
    const c = scroller === root ? {{ top: 0, height: innerHeight }} : scroller.getBoundingClientRect();
    const target = Math.max(0, scroller.scrollTop + r.top - c.top - c.height / 2 + r.height / 2);
    const start = scroller.scrollTop, delta = target - start;
    if (Math.abs(delta) > 8) {{
      const begin = performance.now(), duration = 450;
      await new Promise(resolve => {{
        const step = now => {{
          const t = Math.min(1, (now - begin) / duration);
          const eased = t < .5 ? 2*t*t : 1 - Math.pow(-2*t + 2, 2)/2;
          scroller.scrollTop = start + delta * eased;
          if (t < 1) nextFrame(step); else resolve();
        }};
        nextFrame(step);
      }});
      return true;
    }}
    return false;
  }}, input.selector);
  if (didScroll) await page.waitForTimeout(520);
}}
const rect = await page.evaluate((selector) => {{
  const node = document.querySelector(selector);
  if (!node) throw new Error({js_message("noElementPrefix")} + selector);
  const r = node.getBoundingClientRect();
  if (!{str(scroll).lower()} && (r.bottom < 0 || r.right < 0 || r.top > innerHeight || r.left > innerWidth))
    throw new Error({js_message("zoomSelectorOutsidePrefix")} + selector);
  return {{ x: r.left + r.width / 2, y: r.top + r.height / 2, innerWidth, innerHeight, outerWidth, outerHeight }};
}}, input.selector);
return rect;''', page_ref=page_ref)
    return to_window_point(measured, source)


def action_point(space: Any, action: dict[str, Any], source: dict[str, Any], page_ref: str = "p1") -> dict[str, float]:
    if action.get("selector"):
        return selector_point(space, action["selector"], source, enter_beat=action.get("enterBeat"), page_ref=page_ref)
    metrics = page_metrics(space, source, page_ref)
    fraction = action["fraction"]
    chrome_x = max(0, (metrics["outerWidth"] - metrics["innerWidth"]) / 2)
    chrome_y = max(0, metrics["outerHeight"] - metrics["innerHeight"])
    view_x = fraction["u"] * metrics["outerWidth"] - chrome_x
    view_y = fraction["v"] * metrics["outerHeight"] - chrome_y
    require(0 <= view_x <= metrics["innerWidth"] and 0 <= view_y <= metrics["innerHeight"],
        "fractionOutsideViewport")
    return {"u": fraction["u"], "v": fraction["v"], "viewX": view_x, "viewY": view_y}


def inject_hud(space: Any, hud: Optional[dict[str, Any]], page_ref: str = "p1") -> None:
    if hud is None:
        browser_call(space, 'await page.evaluate(() => document.querySelector("[data-oilstudio-playbook-hud]")?.remove()); return true;', page_ref=page_ref)
        return
    encoded = json.dumps(hud, ensure_ascii=False)
    browser_call(space, f'''const data = {encoded};
await page.evaluate((data) => {{
  document.querySelector("[data-oilstudio-playbook-hud]")?.remove();
  const host = document.createElement("div"); host.dataset.oilstudioPlaybookHud = "";
  Object.assign(host.style, {{ position: "fixed", zIndex: "2147483647", pointerEvents: "none",
    top: data.position === "bottom-left" ? "auto" : "24px", bottom: data.position === "bottom-left" ? "24px" : "auto",
    left: data.position === "top-left" || data.position === "bottom-left" ? "24px" : "auto", right: data.position === "top-right" ? "24px" : "auto" }});
  const root = host.attachShadow({{ mode: "open" }});
  const style = document.createElement("style");
  style.textContent = `:host{{all:initial}} .card{{max-width:440px;padding:18px 22px;border:1px solid #f5d46b;border-radius:18px;background:rgba(13,18,27,.94);box-shadow:0 12px 36px rgba(0,0,0,.45);color:#fff;font:500 16px/1.4 -apple-system,BlinkMacSystemFont,sans-serif}} .badge{{color:#111;background:#f5d46b;border-radius:999px;padding:4px 9px;font-size:12px;font-weight:800;letter-spacing:.04em}} h2{{margin:11px 0 4px;font-size:23px;line-height:1.15}} p{{margin:0;color:#d5dbe5;font-size:15px}} .pills{{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}} .pill{{border-radius:999px;padding:5px 10px;background:#263349;font-size:12px}} .pill b{{color:#f5d46b;margin-left:5px}}`;
  const card = document.createElement("section"); card.className = "card";
  if (data.badge) {{ const badge = document.createElement("span"); badge.className = "badge"; badge.textContent = data.badge; card.append(badge); }}
  if (data.title) {{ const title = document.createElement("h2"); title.textContent = data.title; card.append(title); }}
  if (data.detail) {{ const detail = document.createElement("p"); detail.textContent = data.detail; card.append(detail); }}
  if (data.pills?.length) {{ const pills = document.createElement("div"); pills.className = "pills";
    for (const item of data.pills) {{ const pill = document.createElement("span"); pill.className = "pill";
      const label = document.createElement("span"); label.textContent = item.label + " ";
      const value = document.createElement("b"); value.textContent = item.value;
      if (item.color && CSS.supports("color", item.color)) value.style.color = item.color;
      pill.append(label, value); pills.append(pill); }} card.append(pills); }}
  root.append(style, card); document.documentElement.append(host);
}}, data);
return true;''', page_ref=page_ref)


def run_action(cli: str, space: Any, source: dict[str, Any], beat: dict[str, Any], action_index: int,
    action: dict[str, Any], preopened: bool, run_cli: Callable[..., dict[str, Any]], page_ref: str = "p1",
    ensure_recording_active: Optional[Callable[[], Any]] = None,
    point: Optional[dict[str, float]] = None) -> Optional[dict[str, Any]]:
    """Runs one action. A pointer action given a pre-measured `point` is due now (its `atMs` has arrived),
    so it skips the extra recorder checks before the declaration and the page action.
    Returns the declaration response of pointer actions."""
    def ensure_active() -> None:
        if ensure_recording_active is not None:
            ensure_recording_active()

    kind = action.get("action", action.get("type"))
    identifier = f"play-{beat['id']}-{action_index + 1}"
    declared: Optional[dict[str, Any]] = None
    if kind == "open":
        if preopened:
            return None
        ensure_active()
        browser_call(space, f'await page.goto({json.dumps(action["url"])}); return {{ url: await page.url(), title: await page.title() }};', timeout=120, page_ref=page_ref)
        ensure_active()
        inject_hud(space, beat.get("hud"), page_ref)
    elif kind in ("click", "move"):
        due = point is not None
        if not due:
            ensure_active()
            point = action_point(space, action, source, page_ref)
            ensure_active()
        command = "click" if kind == "click" else "move"
        declared = run_cli(cli, "record", command, "--at-fraction", f"{point['u']:.6f},{point['v']:.6f}", "--id", identifier)
        if not due:
            ensure_active()
        if action.get("selector"):
            method = "click" if kind == "click" else "hover"
            browser_call(space, f'await page.{method}({json.dumps(action["selector"])}); return true;', page_ref=page_ref)
        else:
            mouse_method = "click" if kind == "click" else "move"
            browser_call(space, f'await page.mouse.{mouse_method}({point["viewX"]}, {point["viewY"]}); return true;', page_ref=page_ref)
    elif kind == "scroll":
        ensure_active()
        data = {"selector": action.get("selector"), "y": action.get("y"), "durationMs": action.get("durationMs", 600)}
        browser_call(space, f'''const data = {json.dumps(data, ensure_ascii=False)};
await page.evaluate(async (data) => {{
  const nextFrame = fn => setTimeout(() => fn(performance.now()), 16);
  const root = document.scrollingElement || document.documentElement;
  let element = data.selector ? document.querySelector(data.selector) : null;
  if (data.selector && !element) throw new Error({js_message("noElementPrefix")} + data.selector);
  let scroller = root;
  if (element) for (let node = element.parentElement; node; node = node.parentElement) {{
    const style = getComputedStyle(node); if (node.scrollHeight > node.clientHeight && /auto|scroll/.test(style.overflowY)) {{ scroller = node; break; }}
  }}
  if (!element && root.scrollHeight <= root.clientHeight + 1) {{
    const candidates = Array.from(document.querySelectorAll("*"));
    const visibleArea = node => {{ const r = node.getBoundingClientRect();
      return Math.max(0, Math.min(innerWidth, r.right) - Math.max(0, r.left)) *
        Math.max(0, Math.min(innerHeight, r.bottom) - Math.max(0, r.top)); }};
    const scrollable = candidates.filter(node => node !== root && node.scrollHeight > node.clientHeight + 1 &&
      /auto|scroll/.test(getComputedStyle(node).overflowY) && visibleArea(node) > 0);
    scrollable.sort((a, b) => visibleArea(b) - visibleArea(a));
    if (scrollable.length) scroller = scrollable[0];
  }}
  let target = data.y;
  if (element) {{ const r = element.getBoundingClientRect(); const c = scroller === root ? {{ top: 0, height: innerHeight }} : scroller.getBoundingClientRect();
    target = scroller.scrollTop + r.top - c.top - c.height / 2 + r.height / 2; }}
  const start = scroller.scrollTop, delta = target - start, begin = performance.now(), duration = data.durationMs;
  await new Promise(resolve => {{ const step = now => {{ const t = duration ? Math.min(1, (now - begin) / duration) : 1;
    const eased = t < .5 ? 2*t*t : 1 - Math.pow(-2*t + 2, 2)/2; scroller.scrollTop = start + delta*eased;
    if (t < 1) nextFrame(step); else resolve(); }}; nextFrame(step); }});
}}, data);
return true;''', timeout=max(60, action.get("durationMs", 600) / 1000 + 15), page_ref=page_ref)
    elif kind == "input":
        due = point is not None
        if not due:
            ensure_active()
            point = action_point(space, action, source, page_ref)
            ensure_active()
        declared = run_cli(cli, "record", "click", "--at-fraction", f"{point['u']:.6f},{point['v']:.6f}", "--id", identifier)
        if not due:
            ensure_active()
        data = {key: action[key] for key in ("selector", "value", "from", "to", "durationMs") if key in action}
        if "to" in data:
            data.setdefault("durationMs", 800)
        browser_call(space, f'''const data = {json.dumps(data, ensure_ascii=False)};
await page.click(data.selector);
await page.evaluate(async (data) => {{
  const nextFrame = fn => setTimeout(() => fn(performance.now()), 16);
  let el = document.querySelector(data.selector);
  if (!el && document.activeElement && (document.activeElement.matches("input,textarea,[contenteditable=\\"true\\"]") || document.activeElement.isContentEditable)) {{
    el = document.activeElement;
  }}
  if (!el) throw new Error({js_message("noElementPrefix")} + data.selector);
  if (typeof el.focus === "function") el.focus();
  const set = (value, ch) => {{ const descriptor = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), "value");
    const text = String(value);
    if (el.isContentEditable) el.textContent = text;
    else if (descriptor?.set) descriptor.set.call(el, text); else el.value = text;
    try {{ if (typeof el.setSelectionRange === "function") el.setSelectionRange(text.length, text.length); }} catch {{}}
    el.dispatchEvent(typeof InputEvent === "function" && ch ? new InputEvent("input", {{ bubbles: true, data: ch, inputType: "insertText" }}) : new Event("input", {{ bubbles: true }})); }};
  if ("to" in data && typeof data.from === "number" && typeof data.to === "number" && data.durationMs > 0) {{
    const start = performance.now(); await new Promise(resolve => {{ const step = now => {{ const t = Math.min(1, (now-start)/data.durationMs);
      set(data.from + (data.to-data.from)*t); if (t < 1) nextFrame(step); else resolve(); }}; nextFrame(step); }});
  }} else {{
    const chars = Array.from(String(data.to ?? data.value ?? ""));
    const totalMs = typeof data.durationMs === "number" ? data.durationMs : Math.min(1600, Math.max(320, chars.length * 48));
    if (chars.length === 0 || totalMs <= 0) {{
      set(chars.join(""));
    }} else {{
      set("");
      const stepMs = Math.max(18, Math.round(totalMs / chars.length));
      for (let i = 1; i <= chars.length; i++) {{
        const ch = chars[i - 1];
        el.dispatchEvent(new KeyboardEvent("keydown", {{ key: ch, bubbles: true }}));
        set(chars.slice(0, i).join(""), ch);
        el.dispatchEvent(new KeyboardEvent("keyup", {{ key: ch, bubbles: true }}));
        await new Promise(resolve => setTimeout(resolve, stepMs));
      }}
    }}
  }}
  el.dispatchEvent(new Event("change", {{ bubbles: true }}));
}}, data);
return true;''', timeout=max(60, action.get("durationMs", 1600) / 1000 + 15), page_ref=page_ref)
    elif kind == "press":
        ensure_active()
        data = {"key": action["key"], "selector": action.get("selector")}
        browser_call(space, f'''const data = {json.dumps(data, ensure_ascii=False)};
await page.evaluate(async (data) => {{
  let el = null;
  if (data.selector) {{
    for (let attempt = 0; attempt < 40; attempt++) {{
      el = document.querySelector(data.selector);
      if (el) break;
      await new Promise(resolve => setTimeout(resolve, 120));
    }}
    if (!el && document.activeElement && document.activeElement !== document.body) {{
      el = document.activeElement;
    }}
  }} else {{
    el = document.activeElement || document.body;
  }}
  if (!el) throw new Error({js_message("noElementPrefix")} + data.selector);
  if (data.selector && typeof el.focus === "function") el.focus();
  const parts = data.key.split("+"); const key = parts.pop();
  const keyCodes = {{Enter: 13, Escape: 27, Tab: 9, Backspace: 8, Space: 32, ArrowLeft: 37, ArrowUp: 38, ArrowRight: 39, ArrowDown: 40}};
  const keyCode = keyCodes[key] || (key.length === 1 ? key.toUpperCase().charCodeAt(0) : 0);
  const code = key.length === 1 ? (/[a-zA-Z]/.test(key) ? "Key" + key.toUpperCase() : /[0-9]/.test(key) ? "Digit" + key : key) : key;
  const modifiers = {{metaKey: parts.includes("Meta"), ctrlKey: parts.includes("Control"),
    altKey: parts.includes("Alt"), shiftKey: parts.includes("Shift")}};
  const options = {{key, code, keyCode, which: keyCode, ...modifiers, bubbles: true, cancelable: true, composed: true, view: window}};
  const accepted = el.dispatchEvent(new KeyboardEvent("keydown", options));
  if (key === "Escape") {{
    document.dispatchEvent(new KeyboardEvent("keydown", options));
    window.dispatchEvent(new KeyboardEvent("keydown", options));
  }}
  if (accepted && key === "Enter" && !parts.length) {{
    if (el.tagName === "INPUT" && el.type === "search") el.dispatchEvent(new Event("search", {{bubbles:true}}));
    const form = el.form || el.closest("form");
    if (form && el.tagName !== "TEXTAREA" && !el.isContentEditable && typeof form.requestSubmit === "function") form.requestSubmit();
  }} else if (accepted && key === "Tab") {{
    const nodes = Array.from(document.querySelectorAll('a[href],button,input,select,textarea,[tabindex]'))
      .filter(node => !node.disabled && node.tabIndex >= 0 && node.getClientRects().length);
    if (nodes.length) {{ const index = nodes.indexOf(el); const next = index < 0 ? (modifiers.shiftKey ? nodes.length - 1 : 0) : (index + (modifiers.shiftKey ? -1 : 1) + nodes.length) % nodes.length; nodes[next].focus(); }}
  }}
  el.dispatchEvent(new KeyboardEvent("keyup", options));
  if (key === "Escape") {{
    document.dispatchEvent(new KeyboardEvent("keyup", options));
    window.dispatchEvent(new KeyboardEvent("keyup", options));
  }}
}}, data);
return true;''', page_ref=page_ref)
    elif kind == "wheel":
        # Native wheel input at a point reaches scroll containers that DOM scrolling can't, such as
        # cross-origin iframes; the cursor is declared there first so the picture shows where it scrolls.
        due = point is not None
        if not due:
            ensure_active()
            point = action_point(space, action, source, page_ref)
            ensure_active()
        declared = run_cli(cli, "record", "move", "--at-fraction", f"{point['u']:.6f},{point['v']:.6f}", "--id", identifier)
        if not due:
            ensure_active()
        data = {"x": point["viewX"], "y": point["viewY"], "deltaX": action.get("deltaX", 0),
            "deltaY": action.get("deltaY", 0), "durationMs": action.get("durationMs", 600)}
        browser_call(space, f'''const data = {json.dumps(data)};
await page.mouse.move(data.x, data.y);
const steps = Math.max(1, Math.round(data.durationMs / 50));
const begin = Date.now();
for (let step = 1; step <= steps; step++) {{
  await page.mouse.wheel(data.deltaX / steps, data.deltaY / steps);
  const wait = begin + data.durationMs * step / steps - Date.now();
  if (wait > 0) await new Promise(resolve => setTimeout(resolve, wait));
}}
return true;''', timeout=max(60, action.get("durationMs", 600) / 1000 + 15), page_ref=page_ref)
    elif kind == "switchTab":
        ensure_active()
        # The HUD belongs to the tab on screen; take it along.
        inject_hud(space, None, page_ref)
        switch_tab(action["tab"])
        ensure_active()
        inject_hud(space, beat.get("hud"), page_ref)
    elif kind == "eval":
        ensure_active()
        browser_call(space, f'const value = await page.evaluate({json.dumps(action["script"], ensure_ascii=False)}); return value ?? true;', page_ref=page_ref)
        ensure_active()
        inject_hud(space, beat.get("hud"), page_ref)
    elif kind == "wait":
        ensure_active()
        time.sleep(action["ms"] / 1000)
    elif kind == "mark":
        ensure_active()
        run_cli(cli, "record", "mark")
    return declared


def wait_for_render_stability(space: Any = None, page_ref: str = "p1") -> None:
    """Wait for several consecutive layout samples to agree before inspection."""
    deadline = time.monotonic() + 15
    previous = None
    stable_since = None
    complete_since = None
    while time.monotonic() < deadline:
        sample = browser_call(space, '''return await page.evaluate(() => ({
  url: location.href, ready: document.readyState, width: innerWidth, height: innerHeight,
  scrollHeight: document.documentElement.scrollHeight, bodyHeight: document.body?.scrollHeight ?? 0,
  elements: document.getElementsByTagName("*").length,
  geometry: Array.from(document.querySelectorAll("body *")).filter(el => el.getClientRects().length).slice(0, 500).map(el => {
    const r = el.getBoundingClientRect(); return [r.x, r.y, r.width, r.height].map(n => Math.round(n * 10) / 10);
  })
}));''', page_ref=page_ref)
        now = time.monotonic()
        if sample.get("ready") == "complete":
            complete_since = complete_since or now
            if sample == previous:
                stable_since = stable_since or now
                if now - stable_since >= 0.6:
                    return
            else:
                previous, stable_since = sample, None
            if now - complete_since >= 2.5:
                return
        else:
            previous, stable_since, complete_since = sample, None, None
        time.sleep(0.15)
    raise ValueError(message("stageUnstable"))


def inspect_page(space: Any = None, page_ref: str = "p1") -> dict[str, Any]:
    wait_for_render_stability(space, page_ref)
    return browser_call(space, '''return await page.evaluate(() => {
  const isStableId = id => Boolean(id) && !/(:|^radix-|^base-ui-|^headlessui-|^react-aria)/.test(id);
  const landmarks = new Set(["header", "nav", "main", "aside", "footer", "section", "article", "form", "body"]);
  const selector = node => {
    if (isStableId(node.id)) {
      const id = "#" + CSS.escape(node.id); if (document.querySelectorAll(id).length === 1) return id;
    }
    const tag = CSS.escape(node.localName);
    for (const attr of ["data-testid", "data-demo", "name", "aria-label", "placeholder", "title"]) {
      const val = node.getAttribute(attr);
      if (val && val.length <= 80 && !val.includes("\\n")) {
        const candidate = `${tag}[${attr}=${JSON.stringify(val)}]`;
        if (document.querySelectorAll(candidate).length === 1) return candidate;
      }
    }
    if (node.localName === "a") {
      const href = node.getAttribute("href");
      if (href && href.length > 1 && href.length <= 80 && !href.startsWith("javascript:")) {
        const candidate = `a[href=${JSON.stringify(href)}]`;
        if (document.querySelectorAll(candidate).length === 1) return candidate;
      }
    }
    const path = [];
    let hasLandmark = false;
    for (let el = node; el && el.nodeType === 1; el = el.parentElement) {
      if (isStableId(el.id)) {
        const prefix = "#" + CSS.escape(el.id);
        const candidate = path.length ? `${prefix} > ${path.join(" > ")}` : prefix;
        if (document.querySelectorAll(candidate).length === 1) return candidate;
      }
      let part = CSS.escape(el.localName);
      if (landmarks.has(el.localName)) hasLandmark = true;
      if (el.parentElement) {
        const siblings = Array.from(el.parentElement.children).filter(child => child.localName === el.localName);
        if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(el) + 1})`;
      }
      path.unshift(part);
      const value = path.join(" > ");
      if (hasLandmark && document.querySelectorAll(value).length === 1) return value;
    }
    return path.join(" > ");
  };
  const describe = node => {
    const r = node.getBoundingClientRect();
    let fixedOrSticky = false;
    for (let el = node; el; el = el.parentElement) {
      if (["fixed", "sticky"].includes(getComputedStyle(el).position)) { fixedOrSticky = true; break; }
    }
    return {tag: node.localName, role: node.getAttribute("role"),
      text: (node.innerText || node.getAttribute("aria-label") || node.getAttribute("title") || "").trim().slice(0, 300),
      selector: selector(node), rect: {x:r.x,y:r.y,width:r.width,height:r.height}, fixedOrSticky};
  };
  const nodes = Array.from(document.querySelectorAll("*"));
  const visible = node => { const r = node.getBoundingClientRect(), style = getComputedStyle(node);
    return r.width > 4 && r.height > 4 && r.bottom > 0 && r.right > 0 &&
      style.display !== "none" && style.visibility !== "hidden" && parseFloat(style.opacity || "1") > 0.05; };
  const scrollContainers = nodes.filter(node => node.scrollHeight > node.clientHeight + 1 &&
    (node === document.scrollingElement || /auto|scroll/.test(getComputedStyle(node).overflowY)) && visible(node)).map(describe);
  const interactiveElements = nodes.filter(node => node.matches('a[href],button,input,select,textarea,summary,[role="button"],[role="link"],[role="textbox"],[role="searchbox"],[role="checkbox"],[role="radio"],[role="switch"],[role="tab"],[role="menuitem"],[role="combobox"],[role="slider"],[role="option"],[tabindex],[contenteditable="true"],[onclick]') && visible(node)).map(describe);
  return {url: location.href, title: document.title,
    viewport: {innerWidth, innerHeight, scrollHeight: document.scrollingElement?.scrollHeight ?? document.documentElement.scrollHeight},
    scrollContainers, interactiveElements};
});''', page_ref=page_ref)
