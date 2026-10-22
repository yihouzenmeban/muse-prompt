# muse-prompt

两个 Muse 定时任务的 **prompt 模板**，供参考搭建同款功能。模板从实际在用的版本脱敏泛化而来：具体赛事、个人数据、文件路径等都换成了 `{{占位符}}`，保留的是方法论本身——数据口径、判断规则、安全边界和失败处理。复制文件、替换占位符、填进你自己的定时任务即可。

## 内容

### [daily-training-brief.md](daily-training-brief.md) — 每晚训练播报

每晚自动拉取运动与健康数据（睡眠、静息心率、夜间 HRV、Body Battery、压力），结合多日天气预报、跑步习惯与备赛计划动态判断，产出结构化 JSON 渲染成图片播报；次日课表只在用户确认后才写入 intervals.icu。文件内含搭建前置（数据源、天气源、渲染管线）和完整占位符清单。

### [muse-backup.md](muse-backup.md) — Muse 资源库自动备份

定时把 Muse 家目录镜像同步到一个 GitHub 私有仓库：密钥类文件严格排除、commit 前做密钥特征扫描、成功静默、失败走统一失败队列协议。文件内含同步脚本必须实现的要点（三类排除清单 + 密钥扫描）和占位符清单。

## 使用方式

1. 打开模板文件，先看「搭建前置」备齐依赖（脚本、账号、仓库）。
2. 按「占位符清单」把 `{{...}}` 全部换成你自己的值。
3. 把「Prompt 正文」粘贴为 Muse 定时任务的正文，设好调度时间。

## 配套脚本

两个功能依赖的脚本都在 [scripts/](scripts/) 目录里（已脱敏，配置项改为环境变量或示例值），明细和搭建要点见 [scripts/README.md](scripts/README.md)：

- [pull.py](scripts/pull.py) — Garmin 活动与健康数据拉取（依赖 [garmin2coros](https://github.com/yihouzenmeban/garmin2coros) 的账号配置与 garth 后端）
- [qw.py](scripts/qw.py) — 和风天气查询
- [render_brief.py](scripts/render_brief.py) + [export_brief.py](scripts/export_brief.py) + [export_shot.js](scripts/export_shot.js) — 播报 JSON 渲染成图片
- [push_workout.py](scripts/push_workout.py) — intervals.icu 课表写入
- [sync.sh](scripts/sync.sh) — 资源库备份同步（自动备份功能的核心）

## 同步方式（本仓库维护）

- 本地目录：`~/workspace/muse-prompt/`（本仓库的 git 克隆）
- 改完文件后在该目录 `git add` / `git commit` / `git push` 即可
