---
name: vlog-demand-miner
description: NextTake 下一条：根据赛道寻找或登记对标账号，从同赛道公开视频和评论中发现内容机会，生成本期文案，完成发布前判断、人工发布登记、数据复盘、受众更新、下一条推荐和下一期文案。触发词包括“寻找对标账号”“初始化创作者项目”“找选题”“生成脚本”“启动预测”“已发布”“复盘”“下一条”“分析同赛道评论”。
---

# 下一条 NextTake

> 让上一条，决定下一条。

NextTake 是面向个人短视频创作者的内容创作与发布优化系统。平台发布由创作者手动完成；NextTake 负责证据发现、内容生成、发布前判断、发布后复盘和下一条推荐。

## Public Contract

对使用者只暴露 NextTake 品牌和以下自然语言动作：

| 用户意图 | NextTake 动作 |
| --- | --- |
| 首次使用 | 初始化创作者项目 |
| 自动寻找参考 | 根据赛道寻找对标账号 |
| 用户提供参考 | 登记用户提供的对标账号 |
| 讨论选题并写稿 | 生成本期文案 |
| 检查稿件质量 | 给本期文案打分 |
| 发布前承诺 | 启动发布前预测 |
| 拍摄完成 | 登记已拍摄 |
| 用户手动发布后 | 登记已发布 |
| 导入播放与评论 | 复盘本期内容 |
| 从评论更新认知 | 更新受众画像 |
| 选择下一条 | 推荐下一条 |
| 延续推荐写稿 | 生成下一期文案 |
| 查看进度 | 查看创作状态 |
| 调整评分体系 | 更新评分规则 |

不得在面向用户的回复、错误、CLI JSON、Studio、README 示例或生成文档中输出内部引擎品牌、内部命令前缀、内部状态文件名和内部工作流路径。

执行创作者生命周期动作前，读取 `references/internal-content-engine.md`，再读取其中映射的内部工作流。内部实现只负责复用，所有输入提示和输出必须翻译成上表中的 NextTake 动作。

## Product Flow

```text
同赛道研究
  -> 内容机会
  -> 写入创作者候选池
  -> 本期文案 / 打分 / 发布前预测
  -> 登记拍摄 / 登记人工发布
  -> 表现复盘 / 受众更新 / 下一条推荐
  -> 下一期文案
  -> Creator Studio
```

## Offline Demo

用户说“演示 NextTake”“打开创作者闭环”或“用团播数据演示”时：

```bash
python3 scripts/vdm.py --project /tmp/nexttake-demo creator-demo
```

返回的 `studio` 是静态 HTML 绝对路径。Discover 使用真实团播试点的脱敏 Evidence；发布和表现是固定演示数据，页面必须保留清晰的“演示数据”标记。

## Creator Project

真实使用前，先在创作者目录执行“初始化创作者项目”。初始化由 NextTake 路由到内部内容实验引擎，使用者不需要知道或调用内部工作流名称。

研究项目已经形成内容机会后运行：

```bash
python3 scripts/vdm.py --project <research-project> content-prepare \
  --cluster-id <OPP-id> \
  --creator-project <creator-project>
```

该命令会：

- 读取最新成功的需求聚类；
- 验证内容机会和 Evidence；
- 创建不可变内容机会 Artifact；
- 写入创作者候选池和 `.nexttake/sources/` source pack；
- 返回公开动作 `generate_current_draft`。

随后按公开动作依次生成本期文案、完成发布前判断、登记人工发布并复盘。推荐下一条后，再执行“生成下一期文案”。

## Attach And Studio

创作生命周期完成后登记已有文件：

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

生成只读 Studio：

```bash
python3 scripts/vdm.py --project <research-project> creator-studio \
  --creator-project <creator-project> \
  --candidate-id <id>
```

完整 Studio 必须同时展示本期文案和下一期文案。所有模型文本、评论和用户输入必须 escape；预测段 hash 不得因复盘追加而变化。

## Evidence Workflow

需要真实同赛道研究时使用现有流程：

```text
init -> creator-discover（自动）或 creator-add（用户提供）
-> sync -> sample -> acquire
-> transcript-import (optional)
-> prepare-analysis -> model-job-input -> submit-evidence
-> cluster -> report -> review
```

关键纪律：

- Provider 采集和模型 Evidence 提取分离；
- 自动账号发现最多使用 3 个关键词、每个平台只查第 1 页，并只登记 `1-5` 个候选；
- B站自动发现复用本地 CLI；抖音自动发现使用人工登录的公开 Browser Provider，Sidecar负责用户分享链接解析和后续采集；
- 真实 Provider 操作默认串行，并在操作之间使用项目级 `6-12` 秒随机缓冲；
- B站每次只同步一个账号且只允许 `sync --pages 1`，其他账号必须在前一命令结束后单独同步；
- 转录与评论 ModelJob 通道隔离；
- `quote_snippet` 必须是白名单来源的逐字子串；
- 内容机会只是待验证假设，不证明市场或流量；
- 遇到登录失效、验证码、风控或协议漂移时停止并保留检查点，不绕过验证。

## Local Environment

用户说“安装环境”“初始化本机”或“配置 Provider”时，读取 `references/local-environment-setup.md`，运行：

```bash
python3 scripts/setup_local_environment.py --project <path>
```

浏览器 Profile、Cookie 和登录态必须留在仓库外。公开参数使用 `--douyin-adapter-dir`，不得向使用者推荐内部兼容参数或内部环境变量。

## Capability Honesty

- `preserved`：内部引擎源码存在；
- `validated`：当前仓库测试已覆盖；
- `exposed`：已通过 NextTake 公开动作或 CLI 接入；
- `demoed`：离线演示主路径实际展示。

不要把源码保留说成所有外部 Adapter 已端到端验证。内部能力矩阵见 `references/internal-content-engine.md`。
