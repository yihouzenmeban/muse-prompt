# 配套脚本

六个 prompt 模板依赖的脚本（其中两个功能的核心代码在各自的开源仓库，本目录只收调度侧脚本），都已脱敏：个人数据换成环境变量或示例值，保留的是接口口径和踩过的坑。按下面顺序备齐，再把 prompt 里的 `{{数据脚本命令}}` 等占位符换成你的实际命令。

## 每晚训练播报

| 脚本 | 作用 | 搭建要点 |
| --- | --- | --- |
| `pull.py` | 只读拉取 Garmin 活动与健康数据，输出 JSON（睡眠时间线、整晚 HRV/心率、官方基准带、训练负荷等） | 先克隆 [garmin2coros](https://github.com/yihouzenmeban/garmin2coros) 并在它的 `config.local.json` 里配好 Garmin 账号与 Personal API key；脚本头部注释列了环境变量（项目路径、账号 id、时区） |
| `qw.py` | 和风天气查询（实况/逐日/逐小时），输出紧凑 JSON | key 不经过脚本：默认从 Muse 的 custom.qweather 连接器 helper 读 vault 里的 key；不用连接器时按脚本头部说明换成自己的调用。`PLACES` 地点表换成你自己的城市 |
| `render_brief.py` | 把播报 JSON 渲染成 HTML 卡片片段（含 HRV 散点图与睡眠阶段图） | 输入 JSON 的字段规范见文件头注释，与 `daily-training-brief.md` 里的规范一致 |
| `export_brief.py` + `export_shot.js` | 把卡片截成夜间模式 PNG（600px 宽、3 倍图） | 依赖 node 与 Chromium（走 CDP 截图，`CHROME_BIN` 可改路径）、Python PIL |
| `push_workout.py` | 把确认后的课表以 intervals.icu 原生文本格式写入日历（upsert 幂等） | 把 API key 放进 0600 文件（默认 `~/workspace/intervals-icu/.api_key`，可用环境变量改路径）；key 官方获取方式见 intervals.icu 设置页 |

## 跑后点评

| 脚本 | 作用 | 搭建要点 |
| --- | --- | --- |
| `render_review.py` | 把点评 JSON 渲染成 HTML 点评卡片段（时间线图 + 行内数字 + 心率区间条） | 输入 JSON 的字段规范见 `post-run-review.md` 的 Prompt 正文第 5 步；纵轴刻度取整规则在脚本里，勿改成数据 min-max 拉伸 |
| `export_review.py` | 把点评卡截成夜间模式 PNG（投递兜底形态） | 与播报共用同目录的 `export_shot.js` 和同一套夜间主题（底色 #161615、600px 宽、3 倍图）；底部留白按顶部实测镜像裁切，不要改回固定尾巴 |

## Zepp 体重同步到 Garmin

| 脚本 | 作用 | 搭建要点 |
| --- | --- | --- |
| `sync_weight.py` | 主流程：拉 Zepp 体重记录 → 逐日取最新一条 → Garmin 当天无记录才写入 | Garmin 认证复用 garmin2coros 项目（环境变量 `GARMIN_PROJECT` / `GARMIN_ACCOUNT_ID` / `TZ_NAME`）；去重与「读失败不写」的规则在脚本里，勿改松 |
| `zepp_login.py` | Zepp 登录链：账号密码 → access → apptoken，失效时自动续期并落盘 | 凭证放脚本目录 `.zepp_credentials`（0600，两行 ZEPP_USERNAME=/ZEPP_PASSWORD=，手机号带 +86 前缀）；凭证与 `.apptoken`、`state.json` 都要进备份排除与 .gitignore |

## Muse 资源库自动备份

| 脚本 | 作用 | 搭建要点 |
| --- | --- | --- |
| `sync.sh` | rsync 家目录到备份仓库工作区 → 密钥特征扫描 → commit + push | 先把你的私有备份仓库 clone 到脚本里的 `REPO_DIR` 并配好 origin、把 `KEY` 改成你的 SSH key 路径；**最关键的一步**：把你机器上所有凭据文件逐个加进脚本里的 secrets 排除清单 |

各功能的失败处理都遵循同一套约定：技术性失败静默重试（最多 3 次），需要人工介入的（验证码、权限、key 失效）立即通知——细则在各 prompt 文件末尾。
