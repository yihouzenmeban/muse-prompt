# muse-prompt

六个 Muse 自动化任务的 **prompt 模板**，供参考搭建同款功能。模板从实际在用的版本脱敏泛化而来：具体赛事、个人数据、文件路径等都换成了 `{{占位符}}`，保留的是方法论本身——数据口径、判断规则、安全边界和失败处理。复制文件、替换占位符、填进你自己的任务即可。其中两个功能的核心代码在各自的开源仓库里，模板只沉淀 Muse 侧的调度安排并直接引用仓库。

## 内容

### [daily-training-brief.md](daily-training-brief.md) — 每晚训练播报

每晚自动拉取运动与健康数据（睡眠、静息心率、夜间 HRV、Body Battery、压力），结合多日天气预报、跑步习惯与备赛计划动态判断，产出结构化 JSON 渲染成 HTML 卡片播报；次日课表只在用户确认后才写入 intervals.icu。文件内含搭建前置（数据源、天气源、渲染管线）和完整占位符清单。

<img src="examples/training-brief.png" width="480" alt="每晚训练播报示例（虚构数据）">

*示例图仅用于展示效果，由 html_to_image.py 从示例 HTML 生成；实际投递是 HTML 卡片，不是截图。*

### [muse-backup.md](muse-backup.md) — Muse 资源库自动备份

定时把 Muse 家目录镜像同步到一个 GitHub 私有仓库：密钥类文件严格排除、commit 前做密钥特征扫描、成功静默、失败走统一失败队列协议。文件内含同步脚本必须实现的要点（三类排除清单 + 密钥扫描）和占位符清单。

### [post-run-review.md](post-run-review.md) — 跑后点评

事件驱动（不是定时任务）：活动平台 webhook 入队信号 → 60 秒轻量检测唤醒点评 worker → 对照课表与心率区写结构化点评 JSON → 渲染成图主导的点评卡投递。文件内含信号链设计、点评口径与文案禁令、点评 JSON 字段规范，以及卡片版式与投递规范（worker 只渲染片段、主 agent 在非 hook 回合里建卡拿 token 并贴 token 呈现，绝不退回纯文字）。

<img src="examples/review-card.png" width="480" alt="跑后点评卡示例（虚构数据）">

*示例图仅用于展示效果，由 html_to_image.py 从示例 HTML 生成；实际投递是 HTML 卡片，不是截图。*

### [zepp-weight-sync.md](zepp-weight-sync.md) — Zepp 体重同步到 Garmin

每天定时把 Zepp Life 的体重记录写入 Garmin Connect：同日只取最新一条、Garmin 当天已有任何记录就跳过、当日读取失败宁可整轮报错也绝不冒险写入；Zepp apptoken 与 Garmin token 都自动续期并回写。配套脚本（sync_weight.py + zepp_login.py）在 scripts/ 里。

### [garmin-coros-sync.md](garmin-coros-sync.md) — Garmin → COROS 同步的调度安排

同步代码在开源仓库 [garmin2coros](https://github.com/yihouzenmeban/garmin2coros)，本模板只沉淀调度：事件层（webhook 触发，本人账号）+ 周期层（每 30 分钟，密码账号）+ 兜底层（每日一次）的三层触发设计，两种认证形态各自失效时的处理手册，以及无人值守的网络批准粒度这个坑。

### [strava-weather-sync.md](strava-weather-sync.md) — Strava 活动天气与山峰标注

标注引擎在开源仓库 [update-strava-weather](https://github.com/yihouzenmeban/update-strava-weather)，本模板沉淀运行安排：webhook 通用钩子契约（钩子只发信号、拿不到活动 ID，干活端按状态自己对）、Strava 配额纪律（200/15 分钟、2,000/天，每次调用都计数、本地记账）、天气源为什么必须能查历史小时，以及 VM 重启后靠看门狗任务自愈的保活 prompt。

## 使用方式

1. 打开模板文件，先看「搭建前置」备齐依赖（脚本、账号、仓库）。
2. 按「占位符清单」把 `{{...}}` 全部换成你自己的值。
3. 把「Prompt 正文」粘贴为 Muse 定时任务的正文，设好调度时间。

## 配套脚本

六个功能依赖的脚本都在 [scripts/](scripts/) 目录里（已脱敏，配置项改为环境变量或示例值），明细和搭建要点见 [scripts/README.md](scripts/README.md)：

- [pull.py](scripts/pull.py) — Garmin 活动与健康数据拉取（依赖 [garmin2coros](https://github.com/yihouzenmeban/garmin2coros) 的账号配置与 garth 后端）
- [qw.py](scripts/qw.py) — 和风天气查询
- [render_brief.py](scripts/render_brief.py) — 播报 JSON 渲染成 HTML 卡片片段（建卡拿 token、投递方贴 token 呈现，不出图）
- [render_review.py](scripts/render_review.py) — 点评 JSON 渲染成 HTML 点评卡片段（worker 只渲染、不建卡；主 agent 在非 hook 回合里建卡拿 token 并贴 token 呈现，不出图）
- [html_to_image.py](scripts/html_to_image.py) + [export_shot.js](scripts/export_shot.js) — 指定内容转图片（独立脚本，只在用户明确指名要图片时用，不属于播报和点评）
- [sync_weight.py](scripts/sync_weight.py) + [zepp_login.py](scripts/zepp_login.py) — Zepp 体重 → Garmin 同步与 Zepp 登录续期
- [push_workout.py](scripts/push_workout.py) — intervals.icu 课表写入
- [sync.sh](scripts/sync.sh) — 资源库备份同步（自动备份功能的核心）

Garmin→COROS 同步与 Strava 天气标注的核心代码在各自仓库（[garmin2coros](https://github.com/yihouzenmeban/garmin2coros)、[update-strava-weather](https://github.com/yihouzenmeban/update-strava-weather)），不在本目录重复收录。

## 同步方式（本仓库维护）

- 本地目录：`~/workspace/muse-prompt/`（本仓库的 git 克隆）
- 改完文件后在该目录 `git add` / `git commit` / `git push` 即可
