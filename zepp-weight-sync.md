# Zepp 体重同步到 Garmin — Prompt 模板

一个给 Muse 定时任务用的 prompt 模板，用来搭建「体重秤数据自动汇入 Garmin」功能：每天定时把 Zepp Life（小米/Amazfit 体重秤）的体重记录同步写入 Garmin Connect，让体重曲线只在一个地方看。同步逻辑全在脚本里，prompt 只负责调度、静默与失败处理。

这是从实际在用的版本脱敏泛化而来的：`{{双大括号}}` 是需要你替换的占位符，方法论（严格去重、读不到就不写、token 自动续期、失败分级）可以直接照用。

## 搭建前置

1. **同步脚本**：本仓库的 [scripts/sync_weight.py](scripts/sync_weight.py) + [scripts/zepp_login.py](scripts/zepp_login.py)。前者是主流程（拉 Zepp 记录 → 逐日去重 → 写 Garmin），后者是 Zepp 登录链（apptoken 失效时用保存的账号密码自动重新登录换取，登录方式逆向自华米网页登录流程）。
2. **Garmin 认证复用**：脚本不自己维护 Garmin 登录，而是复用 [garmin2coros](https://github.com/yihouzenmeban/garmin2coros) 项目的账号配置与加密 garth token（与 Garmin→COROS 同步同一套 token 刷新机制）。先按那个仓库把账号配好，本脚本用环境变量 `GARMIN_PROJECT`（项目路径）、`GARMIN_ACCOUNT_ID`（用哪个账号，默认 account_a）指过去。
3. **Zepp 凭证**：脚本目录放一个 0600 权限的 `.zepp_credentials` 文件，两行 `ZEPP_USERNAME=` / `ZEPP_PASSWORD=`（手机号要带国家区号前缀，如 +86，否则登录 401）。apptoken 缓存在同目录 `.apptoken`（0600），同步进度在 `state.json`。这几个文件都要加进你的备份排除清单和 .gitignore——凭证只留本地。
4. **调度**：每天一次即可（体重一天最多几条），时间选在晨称之后，如每天 10:00。

## 占位符清单

| 占位符 | 含义 | 示例 |
| --- | --- | --- |
| `{{同步命令}}` | 同步脚本的完整执行命令（用带 requests/garth 的 venv python） | `/path/to/venv/bin/python ~/workspace/zepp-weight-to-garmin/sync_weight.py` |
| `{{执行时间}}` | 每日执行时刻 | 每天 10:00 |

---

## Prompt 正文（复制到定时任务，替换占位符后使用）

每天把 Zepp Life 体重数据同步到 Garmin Connect。执行时间 {{执行时间}}。

执行命令：
{{同步命令}}

脚本行为（已验证）：
- 自动从 Zepp 云端拉取体重记录；apptoken 失效时用保存的凭证自动重新登录换取。
- 每天只取 Zepp 当天最新的一条记录；state.json 记录已同步到的时间戳，只处理更新的日期（首次运行即全量回填历史）。
- 严格去重：Garmin 当天已有任何体重记录则跳过不写；当日记录读取失败时报错退出，绝不因「读不到」而冒险写入造成重复。
- 退出码 0 表示成功（无论有无新数据写入）。

报告要求：
- 成功（退出码 0）时静默，不要打扰用户。
- 失败（退出码非 0）时按文末「失败处理」执行。

## 同步规则要点（改脚本时别破坏）

- **去重优先于完整**：目标端当天已有数据（哪怕来源是别的秤或手填）一律跳过，宁可漏一条，不可写重一条。体重写错了很难批量清理。
- **读失败 = 不写**：判断「当天有没有」这一步失败时整轮报错退出，不要降级成「假设没有、直接写」。
- **一天一条**：同日多次上秤只同步最新一条，与 Garmin 里按日看曲线的习惯一致。
- **写入格式**：POST Garmin weight-service 的 user-weight，sourceType 用 MANUAL、单位 kg，时间戳同时给本地与 GMT 两个字段（格式对齐 python-garminconnect 的 add_weigh_in）。
- **登录成功后回写 token**：Zepp apptoken 与 Garmin garth token 每次自动续期后都要落盘，否则每天都要重新登录、容易触发风控。

---

## 失败处理（统一失败队列协议，各模板通用）

- 本轮若执行失败，先按正文已有的恢复手段处理（如 token 刷新、服务重启、重查一次）。
- 仍失败时：需要用户人工介入的（验证码/MFA/权限不足/配置错误、API key 失效等）→ 立即向用户报告，不进入队列。
- 可重试的技术性失败（网络超时、API 限流、服务抖动、脚本异常退出等）→ 如实上报错误详情（退出码/关键错误行），保持静默，不直接打扰用户；主 agent 按失败队列协议统一处理（每 15 分钟重试，最多 3 次，3 次仍失败才通知用户）。
