# Internal Content Engine Boundary

This document is an implementation-only routing map. Never quote its engine name, workflow names, hidden state paths or vendor paths in user-facing replies, CLI output, Creator Studio, README examples or generated creator documents.

## Source Of Truth

NextTake vendors `NextTake Content Engine` at commit `9c42fe0c932fe81a12f07428492bdf7ae8488f41` under `vendor/content-engine/` and reuses its behavior directly.

Read `vendor/content-engine/ENGINE.md` for the invariant protocols. Read exactly one mapped workflow before acting:

| Public NextTake action | Internal workflow |
| --- | --- |
| 初始化创作者项目 | `vendor/content-engine/skills/initialize/WORKFLOW.md` |
| 导入对标账号 | `vendor/content-engine/skills/learn-from/WORKFLOW.md` |
| 生成本期文案 / 生成下一期文案 | `vendor/content-engine/skills/ideate/WORKFLOW.md` |
| 给本期文案打分 | `vendor/content-engine/skills/score/WORKFLOW.md` |
| 启动发布前预测 | `vendor/content-engine/skills/predict/WORKFLOW.md` |
| 登记已拍摄 | `vendor/content-engine/skills/shoot/WORKFLOW.md` |
| 登记已发布 | `vendor/content-engine/skills/publish/WORKFLOW.md` |
| 复盘本期内容 | `vendor/content-engine/skills/retro/WORKFLOW.md` |
| 更新受众画像 | `vendor/content-engine/skills/persona/WORKFLOW.md` |
| 推荐下一条 | `vendor/content-engine/skills/recommend/WORKFLOW.md` |
| 更新评分规则 | `vendor/content-engine/skills/calibrate/WORKFLOW.md` |
| 抓取热点 | `vendor/content-engine/skills/trends/WORKFLOW.md` |
| 查看创作状态 | `vendor/content-engine/skills/status/WORKFLOW.md` |
| 升级项目状态 | `vendor/content-engine/skills/migrate/WORKFLOW.md` |

The blind scorer remains an internal sub-agent at `vendor/content-engine/skills/score-blind/WORKFLOW.md` and must never be presented as a user action.

## Translation Contract

Translate internal labels before presenting results:

| Internal concept | Public label |
| --- | --- |
| initialize | 初始化创作者项目 |
| ideate | 生成本期文案 / 生成下一期文案 |
| score | 给本期文案打分 |
| predict | 启动发布前预测 |
| shoot | 登记已拍摄 |
| publish | 登记已发布 |
| retro | 复盘本期内容 |
| persona | 更新受众画像 |
| recommend | 推荐下一条 |
| status | 查看创作状态 |
| `.nexttake-state.json` | NextTake 创作者项目状态 |
| `.nexttake-hooks/` | NextTake 预测保护 |
| `.nexttake-cache/` | NextTake 本地缓存 |

Internal hidden filenames remain unchanged for upstream compatibility. Do not ask users to edit them directly. When initialization is missing, return `creator_init_required` and tell the user to say “初始化创作者项目”.

## Reuse Rule

Input differences are handled by converters and output translation. Do not copy lifecycle semantics into a second implementation. Licenses and provenance remain available in `THIRD_PARTY_NOTICES.md` and `vendor/content-engine/UPSTREAM.md`.

The detailed preservation, validation, exposure and demo matrix is maintained in `references/internal-content-engine-matrix.md`.
