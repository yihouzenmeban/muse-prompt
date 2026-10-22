# Muse 资源库自动备份 — Prompt 模板

一个给 Muse 定时任务用的 prompt 模板，用来搭建「家目录自动备份到 GitHub 私有仓库」功能：定时把 Muse 的家目录镜像同步到一个 git 仓库并推送，密钥文件严格排除、推送前做密钥特征扫描，成功静默、失败按统一协议处理。

这是从实际在用的版本脱敏泛化而来的：`{{双大括号}}` 是需要你替换的占位符。注意 prompt 本身只负责调度一个同步脚本——脚本需要你先写好（下方「同步脚本要点」列了它必须做的事）。

## 搭建前置

1. **一个私有 git 仓库**作为备份目标（只放备份，别作他用）。
2. **一把可推送的 SSH key**（账号级 key 或该仓库的 deploy key 均可），路径填入占位符。
3. **同步脚本**（如 `~/workspace/muse-backup/sync.sh`）：本仓库的 [scripts/sync.sh](scripts/sync.sh) 是可直接改用的实现——把仓库地址、key 路径和排除清单换成你的即可。它必须做到：
   - 用 rsync 把家目录同步到备份仓库的本地工作区（工作区即仓库克隆，镜像家目录结构）。
   - **排除三类，缺一不可**：
     - 密钥类：SSH 私钥目录、各类凭据/ token 文件（如 ngrok 配置、各项目的 config.local.json 与 token 文件、API key 文件、所有 `.env`）。把你机器上所有含密钥的文件逐个列进排除名单——漏一个就是泄密。
     - 可再生的臃肿物：`.venv/`、`__pycache__/`、`node_modules/`、`.git/`。
     - 运行时管理的目录：由平台托管、会自行重建的目录（agents/、assets/、bin/、docs/、hooks/、subscriptions/、data/、.cache/、.local/、.pki/ 等，按你的环境增减）。
   - commit 前跑一遍**密钥特征扫描**（如私钥头、常见 token 前缀），命中即中止并报错，绝不提交。
   - 通过扫描后 commit 并 push 到备份仓库。

## 占位符清单

| 占位符 | 含义 | 示例 |
| --- | --- | --- |
| `{{同步脚本}}` | 同步脚本路径 | `~/workspace/muse-backup/sync.sh` |
| `{{备份仓库}}` | 备份目标仓库（owner/repo） | `yourname/muse-backup` |
| `{{SSH_KEY}}` | 推送用的 SSH 私钥路径 | `~/.ssh/github-backup` |
| `{{排除清单摘要}}` | 你的排除名单一句话摘要（与脚本保持一致） | 密钥类（.ssh/、各项目凭据文件、所有 .env）、臃肿物（.venv/ 等）、运行时目录 |

---

## Prompt 正文（复制到定时任务，替换占位符后使用）

Run the Muse home-resource backup: execute `bash {{同步脚本}}`.

What the script does: rsyncs $HOME into the backup repo working tree (so the repo mirrors $HOME), excluding {{排除清单摘要}}. It then commits and pushes to the private GitHub repo {{备份仓库}} over SSH using the key at {{SSH_KEY}}. It runs a secret-pattern scan before committing and aborts if anything secret-looking is found.

Delivery: on success the script prints a one-line summary — stay silent and do not message the user. If the script exits non-zero: 需要人工介入的（如 SSH key 失效、密钥扫描命中）立即向用户报告并附 stderr；可重试的技术性失败（网络抖动等）按文末「失败处理（统一失败队列协议）」执行（进队列，不直接打扰用户）。One run is one attempt: do not retry the push in a loop, do not re-run the script.

---
失败处理（统一失败队列协议）：
- 本轮若执行失败，先按正文已有的恢复手段处理。
- 仍失败时：需要用户人工介入的（验证码/MFA/权限不足/配置错误等）→ 立即向用户报告，不进入队列。
- 可重试的技术性失败（网络超时、API 限流、服务抖动、脚本异常退出等）→ 如实上报错误详情（退出码/关键错误行），保持静默，不直接打扰用户；由主 agent 按失败队列协议统一处理（每 15 分钟重试，最多 3 次，3 次仍失败才通知用户）。
