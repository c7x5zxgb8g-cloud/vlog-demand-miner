# NextTake Hackathon Transformation - Solution Design v3

> Revised after confirming that the complete `cheat-on-content` capability set must be preserved in this repository.

## Overview

**Working product name**: 下一条 NextTake  
**Tagline**: 让上一条，决定下一条。  
**Generated**: 2026-07-17  
**Planning readiness**: 92/100  
**Review score**: 8.4/10, passed revision round 3

### Implementation Status - 2026-07-17

Implemented and verified:

- complete pinned `cheat-on-content` vendoring with MIT license, provenance and SHA-256 manifest;
- vendored Douyin adapter preferred by installer, provider and CLI;
- VDM Cluster -> immutable Opportunity Artifact -> upstream candidate/source-pack bridge;
- native lifecycle file attachment without reimplementing `cheat-*` business rules;
- desensitized four-opportunity group-livestreaming fixture derived from the 2026-07-15 pilot;
- offline Creator Studio with Discover/Create/Learn/Next and explicit Demo performance labels;
- deterministic interaction-rate recomputation, HTML escaping, path containment and prediction-section hashing;
- root Skill routing to all vendored sub Skills;
- desktop and mobile Chrome/Playwright verification with zero console errors and no horizontal overflow.

Verification snapshot: 61 automated tests passed. The offline demo generated a static Studio with 4 opportunities and recomputed `saves_per_view = 0.030685` from raw fixture counts.

### Goal

在 7 天、50 个开发小时内，把现有 Vlog Demand Miner 改造成可参加“个人创作者内容创作与发布系统”赛道的 Agent Skill：从真实同赛道视频和评论中发现值得创作的主题，生成可拍摄内容，复用完整 `cheat-on-content` 创作实验闭环，登记人工发布结果，并把播放、互动和评论转成下一条内容建议。

核心承诺：

> 从证据找到这一条，从结果找到下一条。

本次改造同时满足两个不同层面的目标：

1. **能力资产完整保留**：把固定版本的 `cheat-on-content` 全量复制进仓库，不丢弃子 Skill、协议、模板、迁移、Hooks、Rubric、工具和 Adapter；
2. **黑客松主路径可交付**：本周只把评审需要的关键闭环接入 NextTake，未接入 UI 的上游能力仍作为可继续启用的完整源码保留。

## Requirements Summary

### Problem Statement

个人短视频创作者通常在三个环节依赖直觉：

1. 不知道同赛道观众真正反复关心什么；
2. AI 可以生成稿子，但无法解释为什么值得拍；
3. 发布后只看到播放数字，不知道哪些判断被验证、下一条该延续什么。

NextTake 把每条内容当成一次创作实验：发布前保留市场证据和盲预测，发布后用真实指标与评论对账，并把结论带进下一次选题。

### Target User

- 中文短视频个人创作者；
- MVP 聚焦抖音风格的 60-90 秒观点或经验内容；
- 使用者自行完成拍摄和平台发布；
- 使用 Codex、Claude Code 或其他兼容 Agent Skill 的宿主完成研究、生成和复盘。

### Hackathon Alignment

参赛类别为“个人创作者内容创作与发布系统”。

系统负责：

- 同赛道受众信号发现；
- 有真实 Evidence 的选题候选生成；
- 标题、Hook、脚本、镜头、发布文案和 CTA 生成；
- 稿件打分与发布前盲预测；
- 拍摄和人工发布登记；
- 播放、互动和评论复盘；
- 受众画像、Rubric 演进和下一条推荐；
- 评审用 Creator Studio 投影。

系统不负责自动上传视频。人工发布是明确的产品边界，不伪装为平台发布能力。

### Success Criteria

- 完整 vendor 固定版本 `cheat-on-content`，保留 MIT `LICENSE` 和上游来源说明；
- `cheat-on-content` 已有的同类能力必须直接调用或编排，禁止在 NextTake 中重新实现第二套 `seed/score/predict/shoot/publish/retro/persona/recommend`；
- 新增代码必须能说明它填补的是 VDM 与 `cheat-on-content` 之间的真实能力缺口，而不是仅因接口形式不同就重造轮子；
- vendor 清单与固定上游版本一致，排除 `.git`、`__pycache__`、`.pyc`、Cookie、登录态、虚拟环境和本机调试文件；
- 原有 15 个 `cheat-*` 子 Skill、Hooks、Migrations、Shared References、Starter Rubrics、Templates、Tools 和 Adapters 均被保留；
- 从现有团播试点证据生成至少 4 个内容机会；
- 选择其中 1 个机会，生成 1 份带 Evidence 引用的可拍摄脚本；
- 关键演示链路实际走过 `seed/score/predict/shoot/publish/retro/persona/recommend` 中适用的步骤，而不是另写一套同名流程；
- 登记 1 次人工发布，导入 1 份表现数据和 Top 评论；
- 独立重算互动率，不从 fixture 读取预计算结果；
- 对发布前押注给出 `validated`、`refuted` 或 `inconclusive`；
- 输出至少 1 条具体改进和 1 个带 Evidence 或评论来源的下一条建议；
- 生成桌面与移动端可用的 Creator Studio HTML；
- 离线演示从启动到完整结果少于 3 分钟；
- 现有 VDM 测试、旧研究项目和抖音 Browser Provider 继续可用。

### Constraints

- 排期：2026-07-17 起 7 天；
- 总开发时间：50 小时；
- 不接入真实平台发布 API；
- 不建设云端 SaaS、登录、团队协作或营销获客；
- 不破坏 VDM 现有 Artifact、Provider、Evidence 和恢复能力；
- 不修改 vendored 上游业务协议来制造“已兼容”的假象；
- 完整保留源码不等于本周验证所有外部 Adapter；
- 凭证、Cookie、平台原始用户 ID、浏览器 Profile 和调试文件不得进入仓库、Artifact、模型输入或报告。

## Product Decision

### Recommended Direction

NextTake 不是重新实现一个缩水版 `cheat-on-content`，而是把两个已有优势组合起来。默认决策是 **reuse first**：只要上游已经有同样的业务语义，就直接复用；只有上游确实不存在的能力才允许新增。

```text
Vlog Demand Miner
  真实同赛道视频、评论、Evidence、需求 Cluster
            |
            v
NextTake Bridge
  Evidence -> cheat candidate/source pack
            |
            v
Vendored cheat-on-content
  seed/draft -> score -> blind predict -> shoot -> publish -> retro
       -> persona / recommend / trends / bump / status / migrate
            |
            v
Creator Studio
  Discover -> Create -> Learn -> Next
```

职责原则：

- **VDM** 回答“市场在问什么、证据在哪里”；
- **`cheat-seed`** 在 VDM Evidence 约束下回答“基于这些证据，这条具体怎么拍”；
- **`cheat-on-content`** 回答“发布前怎么下注、发布后怎么对账、长期怎么进化”；
- **Creator Studio** 把上述文件和 Artifact 投影成评审可理解的一页体验。

### Reuse-First Decision Rule

每个拟开发功能在编码前按以下顺序判断：

1. `cheat-on-content` 是否已有相同业务语义；
2. 如果已有，是否可以通过路由、参数、fixture 或薄适配直接复用；
3. 只有答案为“确实没有”时，才进入 NextTake 新开发；
4. 如果只是输入格式不同，开发 converter/adapter，不复制业务规则；
5. 如果上游能力暂时跑不通，先修兼容或保留手工入口，不立即写替代实现。

| Product capability | Owner | NextTake action |
| --- | --- | --- |
| Topic discussion and draft generation | `cheat-seed` | 注入 VDM source pack，不另写生成器 |
| Draft scoring | `cheat-score` | 直接路由，不另建评分 schema |
| Blind prediction | `cheat-predict` | 直接路由并保持 immutable |
| Shoot registration | `cheat-shoot` | 直接路由 |
| Manual publication registration | `cheat-publish` | 直接路由，不实现平台上传 |
| Performance and comment retro | `cheat-retro` | 直接路由；仅做输入清洗和确定性指标校验 |
| Audience persona | `cheat-persona` | 直接路由 |
| Next-topic recommendation | `cheat-recommend` | 直接路由 |
| Trends, rubric evolution, status, migration | Existing `cheat-*` skills | 完整保留，按本周优先级暴露 |
| Public niche evidence mining | VDM | 保留现有实现 |
| Evidence cluster to creator source pack | NextTake bridge | 新增，这是两套系统之间的真实缺口 |
| Hackathon visual projection | Creator Studio | 新增，只读展示，不复制业务判断 |

### Source Preservation Versus MVP Exposure

| Layer | This Week | Preserved For Later |
| --- | --- | --- |
| Source | 全量 vendor 固定版本源码 | 同一份完整源码持续升级 |
| Runtime | 验证关键本地文件型工作流 | 逐个验证所有外部 Adapter 与 Hook 宿主 |
| NextTake routing | 接入创作闭环主路径 | 接入迁移、热点、多平台自动数据源等高级入口 |
| Creator Studio | 展示单条完整创作实验 | 多内容历史、长期 Rubric 和节奏工作台 |
| Acceptance | 评审现场离线可重复 | 真实账号长期运营校准效果 |

### Hard MVP Boundary

一个完整演示只要求：

- 1 个选中的需求 Cluster；
- 1 个写入候选池的 Content Opportunity；
- 1 份生成并打分的脚本；
- 1 份发布前 Blind Prediction；
- 1 次 Shoot 与人工 Publication Record；
- 1 份 Performance/Comment Retro；
- 1 个 Persona 或 Next Recommendation 更新；
- 1 个包含 Discover/Create/Learn/Next 的静态 Creator Studio 页面。

源码层面仍完整保留所有 `cheat-on-content` 能力；MVP 边界只约束本周接线、测试和 UI，不约束仓库中保留的功能。

## Vendoring Strategy

### Stable Path

完整上游放置于：

```text
vlog-demand-miner/vendor/cheat-on-content/
```

来源固定为：

- Repository: `https://github.com/XBuilderLAB/cheat-on-content.git`
- Commit: `9c42fe0c932fe81a12f07428492bdf7ae8488f41`
- License: MIT

### Required Vendor Contents

- Root `SKILL.md`, `README.md`, `CHANGELOG.md`, `LICENSE`；
- `skills/cheat-*` 全部子 Skill；
- `hooks/`；
- `migrations/`；
- `shared-references/`；
- `starter-rubrics/`；
- `templates/`；
- `tools/`；
- `adapters/`；
- `examples/`；
- 安装和卸载脚本。

### Provenance And Integrity

新增：

- `vendor/cheat-on-content/UPSTREAM.md`：记录仓库、固定 commit、vendor 日期、许可证和本地适配策略；
- `vendor/cheat-on-content/MANIFEST.sha256`：对清理后的 vendored 文件生成哈希清单；
- `references/cheat-on-content-integration.md`：记录 NextTake 调用边界和已验证能力矩阵。

禁止复制：

- 上游 `.git/`；
- `__pycache__/`、`.pyc`、`.DS_Store`；
- `.auth*`、Cookie、Token、浏览器 Profile；
- 虚拟环境、下载模型、运行日志和本机缓存；
- 任何用户内容项目中的私有 `predictions/`、`videos/` 或 `.cheat-state.json`。

### Modification Policy

- vendored 源码默认只读，NextTake 通过外部 bridge 和路由集成；
- 如必须修上游兼容问题，改动必须最小，并在 `UPSTREAM.md` 记录文件、原因和 diff；
- 不在 vendor 内混入 NextTake 自有业务文件；
- 后续升级先对新固定 commit 做 manifest diff，再重放已记录补丁。

## Architecture

### Source Of Truth

系统明确存在两个业务所有权域：

1. **VDM Artifact 域**：市场 Evidence、Cluster、Opportunity 和生成输入；
2. **Creator Project 域**：由 `cheat-on-content` 管理的 `scripts/`、`predictions/`、`videos/`、`candidates.md`、`audience.md`、`rubric_notes.md` 和 `.cheat-state.json`。

`nexttake-link.json` 只保存两域之间的引用：

```json
{
  "schema_version": "1.0.0",
  "content_id": "20260717-group-live-income",
  "opportunity_artifact": "sha256:...",
  "evidence_ids": ["..."],
  "script_path": "scripts/2026-07-17_group-live-income.md",
  "prediction_path": "predictions/2026-07-17_group-live-income.md"
}
```

它不复制完整 Evidence、预测或复盘正文，避免第三份真相。

### Components

| Component | Responsibility | Must Not Do |
| --- | --- | --- |
| `scripts/vdm.py` | 参数解析和薄命令路由 | 不重写 `cheat-*` 生命周期 |
| `scripts/content.py` | Opportunity、Evidence source pack 和确定性指标的纯验证 | 不生成脚本、不评分、不复盘 |
| `scripts/creator_flow.py` | VDM Artifact 与原生 creator project 文件之间的薄桥接 | 不复制 `cheat-seed` 或其他生命周期逻辑 |
| `scripts/creator_reports.py` | 安全生成 Creator Studio HTML | 不修改业务状态 |
| `vendor/cheat-on-content/` | 原生创作实验协议和全部能力 | 不依赖 NextTake 才能保持完整 |
| Root `SKILL.md` | 将自然语言请求路由到 VDM、生成桥或 vendored Skill | 不复制子 Skill 规则到另一套 prompt |

### Self-Contained Runtime

- 新增 `VDM_CHEAT_ROOT`，默认指向仓库内 vendored 根目录；
- `VDM_CHEAT_DOUYIN_ADAPTER_DIR` 仍可显式覆盖；
- `setup_local_environment.py` 优先使用仓库内固定版本，再兼容已安装位置和受管 checkout；
- Browser Provider 的 Profile 继续写到仓库外状态目录；
- 不因为源码已 vendor 就自动安装 Playwright、登录平台或启用网络 Adapter。

## Integrated Workflow

### 1. Discover

VDM 从公开视频、字幕和匿名评论生成 Evidence 与 Demand Cluster。`content-prepare` 选择真实 `cluster_id`，产生 `content.opportunity` Artifact，并通过 bridge 写入 `candidates.md`：

- 标题和目标受众问题；
- demand score 与 confidence；
- supporting/counter Evidence ID；
- coverage limitations；
- `source=vdm` 和 Opportunity Artifact hash。

### 2. Create

NextTake 把 Opportunity 转成 `cheat-seed` 可读取的 source pack。原生 `cheat-seed` 读取 Opportunity、creator profile、`audience.md` 和允许读取的写作模式，生成：

- 1-3 个标题；
- 1 个 Hook；
- 60-90 秒脚本；
- 镜头提纲；
- 发布文案与 CTA；
- Evidence/Creator Original 来源标签。

生成稿由 `cheat-seed` 写入 creator project 的 `scripts/`，随后直接调用原生 `cheat-score` 与 `cheat-predict`。NextTake 不创建自有 draft、score 或 prediction 协议。

### 3. Publish

- 使用原生 `cheat-shoot` 登记已拍摄；
- 使用原生 `cheat-publish` 登记人工发布平台、时间和链接；
- 不调用平台上传 API；
- 演示 fixture 明确标记为 Demo publication。

### 4. Learn

- 使用原生 `cheat-retro` 写入原始表现数据与评论；
- NextTake 确定性重算互动率并提供给 Studio；
- 使用原生 `cheat-persona` 从评论派生受众画像；
- 使用原生 `cheat-recommend` 从候选池产生下一条建议；
- 长期样本达到门槛后，完整保留的 `cheat-bump` 可升级 Rubric，但不作为本周演示硬条件。

### 5. Continue

新的 Audience、Rubric observations 和 Recommendation 回到下一轮 `seed/create`。这使 NextTake 不只是生成一篇稿，而是能解释“为什么下一条与上一条不同”。

## Data And Safety Contracts

### Evidence Grounding

- 每个 VDM 候选必须引用当前 Opportunity 白名单中的 Evidence ID；
- 脚本中的事实段标 `origin=evidence` 并保留 ID；
- 创作者表达标 `origin=creator_original`，不得伪装为外部事实；
- 反证和覆盖限制必须进入生成上下文与 Studio；
- 不允许引用其他项目、其他 Cluster 或未知来源。

### Blind Prediction Integrity

- 发布前预测必须由原生 `cheat-predict` 创建；
- 预测写入后不可根据实际数据回填修改；
- Creator Studio 只读预测与复盘，不提供编辑入口；
- fixture 预测必须在 fixture 表现数据之前生成并固定；
- Codex 无 Hook 强制时，测试通过文件 hash 验证预测段未被改写。

### Performance Snapshot

- `views > 0`；
- 点赞、评论、分享、收藏、关注为非负整数；
- `completion_rate` 可选且范围 `0..1`；
- Top 评论最多 30 条，每条最多 500 字；
- 不接受平台用户 ID、头像、联系方式或 Cookie；
- Fixture 只保存原始值，不保存计算后的互动率。

NextTake 确定性计算：

- `likes_per_view`；
- `comments_per_view`；
- `shares_per_view`；
- `saves_per_view`；
- `follows_per_view`。

### Retro And Next Recommendation

- 对发布前主要押注标记 `validated`、`refuted` 或 `inconclusive`；
- 理由必须引用指标或匿名 Comment ID；
- 必须包含 `what_worked`、`what_failed` 和 `improvement`；
- 下一条建议至少引用一个 Opportunity Evidence ID 或匿名 Comment ID；
- 不声称单条评论与某句脚本之间存在因果关系。

## Creator Studio

Creator Studio 是静态、可重建、只读 HTML，不是服务器。

### Discover

- 当前机会与受众问题；
- Demand score 和 confidence；
- 支持证据、反证和覆盖限制；
- 候选池中的来源标记。

### Create

- 标题、Hook、脚本、镜头、文案和 CTA；
- Evidence/Creator Original 标签；
- 原生 score 结果；
- Blind Prediction 与发布前 Bet；
- 复制按钮。

### Learn

- 人工发布元数据；
- 独立重算的互动率；
- Top 评论分类；
- Bet 与结果对账；
- 具体改进；
- Persona 变化。

### Next

- 原生 `cheat-recommend` 推荐；
- 来源 Evidence 或评论；
- 稳分/实验性理由；
- 若数据不足，明确显示 `inconclusive`，不制造确定性。

所有模型文本、评论和用户输入必须 HTML escape。输出路径只能由校验后的 Content ID 或 Artifact hash 派生，HTML 最大 2 MiB。

## Implementation Plan - 50 Hours

### Hours 0-6: Vendor And Provenance

Actions:

- 从固定 commit 的干净源码生成 vendor 副本；
- 排除生成物、本机状态和凭证类文件；
- 保留 MIT License；
- 生成 `UPSTREAM.md` 和 `MANIFEST.sha256`；
- 新增 vendor 完整性与禁止文件测试；
- 让现有 Douyin Browser Provider 可优先使用 vendored adapter。

Deliverable:

- 仓库内存在可追溯、无私有状态、可哈希验证的完整 `cheat-on-content` 源码。

Hard checkpoint H6:

- 如果无法联网拉取上游，使用现有本地安装作为来源，但必须按固定 commit 文件清单校验；
- 不因时间压力省略 License、来源说明或禁止文件扫描。

### Hours 6-18: Evidence-To-Content Bridge

Actions:

- 新增薄层 `content.py` 和 `creator_flow.py`；
- 从真实 Cluster 构建 Opportunity；
- 将 Opportunity 以 `source=vdm` 写入 `candidates.md` 和 source pack；
- 让原生 `cheat-seed` 基于 source pack 生成带 Evidence/Creator Original 标签的脚本；
- 建立 `nexttake-link.json`；
- 添加纯验证和集成测试。

Deliverable:

- 一个真实团播 Cluster 可以进入 creator project，并生成一份有证据的脚本。

Hard checkpoint H18:

- 多标题未稳定时只保留一个标题；
- 复杂镜头结构降级为字符串数组；
- 不削减 Evidence 白名单、反证和限制说明。
- 不允许通过新增独立脚本生成器来绕过 `cheat-seed` 的兼容问题。

### Hours 18-31: Native Creator Lifecycle Integration

Actions:

- Root `SKILL.md` 路由到 vendored `cheat-init/seed/score/predict/shoot/publish/retro/persona/recommend`；
- 创建隔离 Demo creator project；
- 验证 Blind Prediction 不被复盘修改；
- 导入原始 performance/comment fixture；
- 确定性重算互动率；
- 记录各子 Skill 的兼容状态。

Deliverable:

- 演示 fixture 可以走通原生创作实验生命周期，不使用平行重实现。

Hard checkpoint H31:

- 若 Persona 数据不足，显示 benchmark-seed 或 inconclusive；
- 若真实平台 Adapter 不稳定，保留源码并改走手工导入；
- 不把 `bump/trends/migrate` 从 vendor 删除，只是不列为现场主路径。

### Hours 31-41: Creator Studio And Demo

Actions:

- 新增 `creator_reports.py`；
- 生成 Discover/Create/Learn/Next 四段页面；
- 加入脱敏团播 Opportunity、脚本、预测、表现和复盘 fixture；
- 完成 `creator-demo`；
- 标注 Demo publication/performance data。

Deliverable:

- 无网络、无真实账号、无外部试点目录时可生成完整演示页面。

Hard checkpoint H41:

- Tab/JS 未稳定时降级为四个纵向区块；
- Evidence 高亮降级为可点击锚点；
- 不削减 HTML escape、数据标记和移动端可读性。

### Hours 41-50: QA, Documentation And Rehearsal

Actions:

- 运行旧 VDM 测试、新测试和 vendor smoke checks；
- 浏览器桌面/移动端截图验证；
- 修复文字溢出、空状态和不安全 HTML；
- 更新 README、SKILL 路由和集成矩阵；
- 准备模型 fixture 兜底；
- 排练 3 分钟演示；
- H41 后冻结功能。

Deliverable:

- 可重复、可解释、无需真实发布权限的黑客松演示。

## Planned File Changes

Modify:

- `README.md`；
- `vlog-demand-miner/SKILL.md`；
- `vlog-demand-miner/scripts/vdm.py`；
- `vlog-demand-miner/scripts/setup_local_environment.py`；
- 相关现有测试与环境文档。

Add:

- `vlog-demand-miner/vendor/cheat-on-content/**`；
- `vlog-demand-miner/vendor/cheat-on-content/UPSTREAM.md`；
- `vlog-demand-miner/vendor/cheat-on-content/MANIFEST.sha256`；
- `vlog-demand-miner/scripts/content.py`；
- `vlog-demand-miner/scripts/creator_flow.py`；
- `vlog-demand-miner/scripts/creator_reports.py`；
- `vlog-demand-miner/references/cheat-on-content-integration.md`；
- `vlog-demand-miner/references/content-experiment-protocol.md`；
- `vlog-demand-miner/fixtures/creator-demo/**`；
- `vlog-demand-miner/tests/test_vendor_integrity.py`；
- `vlog-demand-miner/tests/test_content.py`；
- `vlog-demand-miner/tests/test_creator_flow.py`；
- `vlog-demand-miner/tests/test_creator_reports.py`；
- `vlog-demand-miner/tests/test_creator_demo.py`。

Not modified unless a compatibility test proves it necessary:

- vendored upstream protocols and sub Skill semantics；
- VDM Evidence envelope；
- existing demand scoring rules；
- existing market review packet semantics；
- platform Provider acquisition behavior。

## Test Plan

### Vendor Integrity

- Required root files and all 15 sub Skills exist；
- `LICENSE` exists and contains the MIT notice；
- `UPSTREAM.md` records repository and pinned commit；
- Manifest verifies cleanly；
- no `.git`、`__pycache__`、`.pyc`、Cookie、auth/profile or venv files；
- Douyin Browser Provider resolves vendored adapter without network checkout。

### Unit

- Opportunity fields, enums, ranges and payload limits；
- Evidence ID whitelist；
- `creator_original` and Evidence isolation；
- interaction-rate recomputation；
- views equal to zero；
- HTML escape；
- link schema drift and path traversal。

### Integration

- VDM Cluster -> source pack -> native `cheat-seed` draft；
- script -> native score -> native prediction；
- native shoot -> publish -> retro；
- persona/recommend output available or honestly inconclusive；
- prediction section hash unchanged after retro；
- duplicate and malformed input handling；
- old VDM demo、report、recovery and Browser Provider tests do not regress。

### Browser Verification

- 1440px desktop screenshot；
- 390px mobile screenshot；
- content-only waiting state；
- full retro state；
- long Chinese script and comments；
- no horizontal overflow or overlap；
- buttons keyboard reachable and visibly focused；
- core content is nonblank；
- demo data labels remain visible。

## Demo Fixtures

仓库内包含一个脱敏、版本固定、隔离的 creator project：

```text
fixtures/creator-demo/
├── source/                 # VDM Opportunity and Evidence references
├── scripts/                # generated draft
├── predictions/            # immutable pre-publication prediction
├── videos/                 # report with demo performance/comments
├── candidates.md
├── audience.md
├── rubric_notes.md
├── .cheat-state.json
└── nexttake-link.json
```

- Opportunity fixture 来自真实团播试点的脱敏需求与 Evidence；
- Script 和 Prediction 是预生成模型输出，但必须通过正式校验；
- Performance 只含原始播放、互动和评论，不含比率；
- 所有虚构发布后数据在 HTML 和演示旁白中显示 `Demo performance data`；
- fixture 不含真实账号、用户 ID、Cookie、联系方式或浏览器状态。

## Three-Minute Demo

1. `0:00-0:20`：创作者不知道团播观众真正关心收入、边界还是工作强度；
2. `0:20-0:45`：展示 4 个来自真实试点的内容机会，选择其中一个进入候选池；
3. `0:45-1:20`：生成标题、Hook、脚本、镜头、文案和 CTA，并展示 Evidence 来源；
4. `1:20-1:40`：原生 `cheat-score/predict` 完成发布前打分和盲预测；
5. `1:40-1:55`：登记已拍摄、已人工发布，导入明确标记的演示表现数据；
6. `1:55-2:20`：现场重算互动率并执行 Retro；
7. `2:20-2:40`：展示押注被验证、推翻或暂时无法判断，以及 Persona 变化；
8. `2:40-2:55`：下一条建议引用原始 Evidence 或新评论；
9. `2:55-3:00`：强调完整创作闭环已保留，平台发布仍由创作者掌控。

## Risk Management

| Risk | Impact | Likelihood | Mitigation |
| --- | --- | --- | --- |
| 完整源码被误解为全部功能本周已接通 | High | High | 发布兼容矩阵，分开标记 preserved / runnable / exposed / demoed |
| 50 小时超范围 | High | Medium | H6/H18/H31/H41 硬检查点，H41 后冻结功能 |
| 重写上游生命周期导致冲突 | High | Medium | 原生 Skill 是唯一生命周期实现，NextTake 只做 bridge 和 projection |
| 因输入格式差异而误造第二套功能 | High | Medium | 编码前执行 reuse-first decision rule，只允许 converter/adapter |
| Vendor 混入本机状态或凭证 | High | Low | clean source、禁止文件扫描、manifest、code review |
| Upstream 升级困难 | Medium | Medium | 固定 commit、UPSTREAM、manifest、最小补丁记录 |
| Codex 缺少 Claude Hook 强制 | Medium | High | 文档说明 + prediction hash integration test |
| 外部 Adapter 依赖登录或 Playwright | Medium | High | 源码保留，现场走手工导入和离线 fixture |
| 生成内容像通用 AI 文案 | High | Medium | Evidence 引用、反证、Creator Original 标签 |
| 演示被认为使用假结果 | High | Medium | 所有合成数据醒目标记，派生指标现场重算 |
| 恶意评论或模型 HTML | High | Medium | payload limit、HTML escape、只读静态页面 |

## Not Doing This Week

以下能力**不会被删除**，只是本周不承诺完成 NextTake UI 接入或真实平台验证：

- 自动发布、定时发布或平台草稿上传；
- 所有 perf-data Adapter 的真实账号端到端验证；
- 所有 trend-source Adapter 的联网稳定性验证；
- Claude Code Hook 在所有宿主中的等价实现；
- 多内容实验历史看板；
- Rubric bump 的长期样本效果证明；
- 内容节奏 buffer 的完整可视化工作台；
- Schema migration 的可视化入口；
- 视频剪辑、渲染、画面生成和视觉分析；
- CRM、广告、落地页和销售获客；
- 云部署、账号登录、多用户和团队协作。

## Review Summary

| Dimension | Round 1 | Round 2 | Revision Round 3 |
| --- | ---: | ---: | ---: |
| Clarity | 8/10 | 8/10 | 9/10 |
| Completeness | 6/10 | 7/10 | 9/10 |
| Feasibility | 4/10 | 8/10 | 8/10 |
| Risk Assessment | 5/10 | 8/10 | 9/10 |
| Requirement Alignment | 8/10 | 9/10 | 9/10 |
| **Overall** | **6.2/10** | **8.0/10** | **8.4/10** |

Round 3 的主要修正：

- 从“借鉴 `cheat-on-content`”改为“完整 vendor 并原生复用”；
- 删除平行实现 score/predict/publish/retro 的计划；
- 把“源码保留、运行兼容、UI 暴露、评审验收”拆成四个独立边界；
- 为 vendor 来源、许可证、禁止文件和升级路径增加明确验收；
- 在 50 小时内新增 6 小时 vendoring 预算，并通过复用上游生命周期收回重复开发时间。

补充约束：`cheat-seed` 同样作为脚本生成主入口，NextTake 不再规划独立内容生成器。VDM 只向它提供更高质量、更可追溯的 source pack。

剩余主要风险不是功能缺失，而是评审误以为“源码存在”等于“所有 Adapter 已验证”。演示和 README 必须始终使用 preserved、validated、exposed、demoed 四种状态说明能力。

## Approval Gate

进入业务实现前确认以下五项：

1. 以“个人创作者内容创作与发布系统”参赛；
2. 使用 NextTake/下一条作为工作产品名；
3. 完整 vendor 固定版本 `cheat-on-content`，不删除已有功能；
4. 相同功能一律原生复用，本周优先打通单条创作实验，其他能力保留但分批接入；
5. 使用静态 Creator Studio 和 Agent Skill 编排，不建设独立 SaaS。
