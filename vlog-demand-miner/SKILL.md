---
name: vlog-demand-miner
description: NextTake 下一条：从同赛道公开视频和评论 Evidence 发现内容机会，直接复用完整 cheat-on-content 完成 seed、score、blind predict、shoot、manual publish、retro、persona 和 recommend，再生成 Creator Studio。触发词包括“找选题”“生成脚本”“启动预测”“已发布”“复盘”“下一条”“分析同赛道评论”。
---

# 下一条 NextTake

> 让上一条，决定下一条。

本 Skill 是个人创作者内容创作与发布优化系统。平台发布由创作者手动完成；系统负责证据发现、内容生成、发布前判断、发布后复盘和下一条推荐。

## 最高实现原则：Reuse First

`vendor/cheat-on-content/` 已有的业务能力必须直接复用，不在 NextTake 中另写第二套实现。

执行任何创作生命周期动作前，读取对应的 vendored 子 Skill：

| User intent | Required source of truth |
| --- | --- |
| 初始化内容项目 | `vendor/cheat-on-content/skills/cheat-init/SKILL.md` |
| 找对标 | `vendor/cheat-on-content/skills/cheat-learn-from/SKILL.md` |
| 讨论选题、生成 draft | `vendor/cheat-on-content/skills/cheat-seed/SKILL.md` |
| 打分 | `vendor/cheat-on-content/skills/cheat-score/SKILL.md` |
| 启动发布前预测 | `vendor/cheat-on-content/skills/cheat-predict/SKILL.md` |
| 登记已拍摄 | `vendor/cheat-on-content/skills/cheat-shoot/SKILL.md` |
| 登记人工发布 | `vendor/cheat-on-content/skills/cheat-publish/SKILL.md` |
| 导入表现并复盘 | `vendor/cheat-on-content/skills/cheat-retro/SKILL.md` |
| 更新真实受众画像 | `vendor/cheat-on-content/skills/cheat-persona/SKILL.md` |
| 推荐下一条 | `vendor/cheat-on-content/skills/cheat-recommend/SKILL.md` |
| 热点、Rubric、状态、迁移 | 对应 `cheat-trends`、`cheat-bump`、`cheat-status`、`cheat-migrate` |

如果输入格式不同，只写 converter/adapter；如果上游暂时跑不通，优先修兼容或使用上游的手工入口，不立即造替代流程。

## Product Flow

```text
VDM research
  -> Demand Cluster
  -> content-prepare
  -> candidate + source pack
  -> native cheat-seed / score / predict
  -> native cheat-shoot / publish
  -> native cheat-retro / persona / recommend
  -> creator-attach
  -> creator-studio
```

## Offline Demo

用户说“演示 NextTake”“打开创作者闭环”或“用团播数据演示”时：

```bash
python3 scripts/vdm.py --project /tmp/nexttake-demo creator-demo
```

返回的 `studio` 是静态 HTML 绝对路径。Discover 使用 2026-07-15 真实团播试点的脱敏 Evidence；发布和表现是固定演示数据，页面必须保留清晰的“演示数据”标记。

## Evidence To Creator Project

使用者必须先在 creator project 中运行原生 `cheat-init`。NextTake 不自行创建 `.cheat-state.json`。

```bash
python3 scripts/vdm.py --project <research-project> content-prepare \
  --cluster-id <OPP-id> \
  --creator-project <creator-project>
```

该命令只做薄桥接：

- 读取最新成功的 `analysis.cluster_score`；
- 验证 Cluster 和 Evidence 白名单；
- 创建不可变 `content.opportunity` Artifact；
- 按上游 candidate schema 写 `candidates.md`；
- 写 `.nexttake/sources/<candidate-id>.json/.md`；
- 返回调用原生 `cheat-seed` 的下一步指令。

收到 source pack 后，读取并执行 `cheat-seed/SKILL.md`。生成稿仍写到上游规定的 `scripts/`；后续 score/predict/shoot/publish/retro 同理。

## Attach And Studio

原生生命周期完成后，用 `creator-attach` 只登记已有文件路径，并导入无身份字段的原始表现 JSON：

```bash
python3 scripts/vdm.py --project <research-project> creator-attach \
  --creator-project <creator-project> \
  --candidate-id <id> \
  --script-path scripts/<file>.md \
  --prediction-path predictions/<file>.md \
  --report-path videos/<folder>/report.md \
  --performance-file <raw-json> \
  --audience-path audience.md \
  --recommendation-path .nexttake/recommendation.md \
  --next-script-path scripts/<next-draft>.md
```

运行 `cheat-recommend` 得到下一条方向后，继续读取并执行 `cheat-seed/SKILL.md` 生成下一期 draft，再通过 `--next-script-path` 一并登记。完整 Studio 必须同时展示本期文案和下一期文案。

然后：

```bash
python3 scripts/vdm.py --project <research-project> creator-studio \
  --creator-project <creator-project> \
  --candidate-id <id>
```

Creator Studio 是只读静态页面。所有模型文本、评论和用户输入必须 escape；预测段 hash 不得因 Retro 追加而变化。

## VDM Evidence Workflow

需要真实同赛道研究时，继续使用现有流程：

```text
init -> creator-add -> sync -> sample -> acquire
-> transcript-import (optional)
-> prepare-analysis -> model-job-input -> submit-evidence
-> cluster -> report -> review
```

关键纪律：

- Provider 采集和模型 Evidence 提取分离；
- 转录与评论 ModelJob 通道隔离；
- `quote_snippet` 必须是白名单来源的逐字子串；
- Demand Cluster 只是内容机会假设，不证明市场或流量；
- 遇到登录失效、验证码、风控或协议漂移时停止并保留检查点，不绕过验证。

详细 Provider、ASR、恢复和验收契约见 `references/local-environment-setup.md` 及现有 CLI 帮助。

## Local Environment

用户说“安装环境”“初始化本机”或“配置 Provider”时，读取 `references/local-environment-setup.md`，运行：

```bash
python3 scripts/setup_local_environment.py --project <path>
```

安装器默认使用仓库内固定版本：

```text
vendor/cheat-on-content/adapters/perf-data/douyin-session
```

可通过 `VDM_CHEAT_ROOT` 或 `VDM_CHEAT_DOUYIN_ADAPTER_DIR` 覆盖。浏览器 Profile、Cookie 和登录态必须留在仓库外。

## Capability Honesty

- `preserved`：源码完整存在；
- `validated`：当前仓库测试已覆盖；
- `exposed`：根 Skill 或 CLI 已接入；
- `demoed`：离线演示主路径实际展示。

不要把 preserved 说成所有外部 Adapter 已端到端验证。查看 `references/cheat-on-content-integration.md` 获取完整矩阵。
