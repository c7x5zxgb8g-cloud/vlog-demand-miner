# 下一条 NextTake

**让上一条，决定下一条。**

NextTake 是一个面向个人短视频创作者的 Agent Skill：从同赛道公开视频和评论中发现真实受众问题，生成本期文案，记录人工发布结果，分析播放和评论，再生成下一条推荐与下一期完整文案。

```text
同赛道内容与评论
  -> 内容机会
  -> 本期文案
  -> 人工拍摄和发布
  -> 播放、互动与评论复盘
  -> 下一条推荐
  -> 下一期文案
```

NextTake 不自动上传视频。创作者自行完成拍摄和平台发布，系统负责内容产出与优化分析。

第一次接入 AI 工具时，请从[《NextTake 完整使用手册》](docs/USER_MANUAL.md)开始。手册按真实操作顺序提供了可直接发送给 AI 的提示词、预期产物、数据格式和常见问题处理方法。

## 当前可用状态

截至 2026-07-18，当前仓库已经可以运行：

- `75` 项自动测试通过；
- 离线 Creator Studio 可以直接生成；
- 支持桌面和移动端；
- 支持 VDM Cluster 到创作者项目的内容机会桥接；
- 支持本期文案、发布前判断、表现复盘、下一条推荐和下一期文案；
- 完整复用内置内容实验引擎，并通过 NextTake 统一封装；
- 不需要真实平台发布权限即可完成黑客松演示。

## 仓库结构

仓库根目录负责 README 和改造方案，真正的 Codex Skill 位于子目录：

```text
vlog-demand-miner/                 # Git 仓库根目录
├── README.md
├── plans/
└── vlog-demand-miner/             # Skill 根目录
    ├── SKILL.md
    ├── scripts/
    ├── fixtures/
    ├── references/
    ├── tests/
    └── vendor/                     # 内部依赖与许可证
```

下面的命令均从 Git 仓库根目录执行。

## 安装或更新 Codex Skill

### 1. 克隆仓库

```bash
git clone https://github.com/c7x5zxgb8g-cloud/vlog-demand-miner.git
cd vlog-demand-miner
```

### 2. 同步到 Codex Skill 目录

```bash
mkdir -p "$HOME/.codex/skills/vlog-demand-miner"
rsync -a \
  --delete \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  "$PWD/vlog-demand-miner/" \
  "$HOME/.codex/skills/vlog-demand-miner/"
```

更新仓库后重复执行同一条 `rsync` 即可。重新打开 Codex task 后，使用 `$vlog-demand-miner` 触发 Skill。

设置常用路径：

```bash
export NEXTTAKE_SKILL="$HOME/.codex/skills/vlog-demand-miner"
export VDM_CLI="$NEXTTAKE_SKILL/scripts/vdm.py"
```

### 3. 验证安装

```bash
python3 "$VDM_CLI" --help
python3 -m unittest discover -s "$NEXTTAKE_SKILL/tests" -v
```

`--help` 应包含以下命令：

```text
content-prepare
creator-attach
creator-studio
creator-demo
```

## 三分钟离线演示

这是最快的使用方式，不需要网络、平台登录或模型 SDK：

```bash
export DEMO_DIR=/tmp/nexttake-demo
python3 "$VDM_CLI" --project "$DEMO_DIR" creator-demo
```

命令会返回：

```json
{
  "status": "ok",
  "product": "下一条 NextTake",
  "opportunities": 4,
  "studio": "/tmp/nexttake-demo/.vlog-demand-miner/creator-studio/61c7492abf1a/index.html"
}
```

在浏览器中打开返回的 `studio` 文件。演示页面包含：

1. 2026-07-15 团播试点形成的 4 个脱敏内容机会；
2. 本期完整文案；
3. 发布前判断；
4. 明确标记为演示数据的播放、互动和评论；
5. 被验证、被推翻和暂时无法判断的结论；
6. 受众变化；
7. 下一条推荐；
8. 下一期完整文案。

Discover 使用真实试点的脱敏 Evidence。发布和表现数据是合成演示数据，不代表作品真实发布。

## 真实使用需要两个目录

NextTake 把市场研究数据和个人创作数据分开保存：

```bash
export RESEARCH_DIR="$HOME/nexttake/research/group-live"
export CREATOR_DIR="$HOME/nexttake/creator/my-channel"

mkdir -p "$RESEARCH_DIR" "$CREATOR_DIR"
```

| Directory | Purpose |
| --- | --- |
| `RESEARCH_DIR` | 保存公开视频、评论 Evidence、Cluster 和研究 Artifact |
| `CREATOR_DIR` | 保存草稿、预测、发布记录、复盘、Persona 和下一期文案 |

不要把真实 Cookie、浏览器 Profile、Token 或平台私有响应放进任意项目目录。

## 第一次使用：初始化创作者项目

在 Codex 中将工作目录切换到 `CREATOR_DIR`，然后说：

```text
使用 $vlog-demand-miner 初始化创作者项目
```

NextTake 会询问内容类型、典型时长、发布节奏和历史样本，并创建：

```text
<creator-project>/
├── rubric_notes.md
├── audience.md
├── candidates.md
├── scripts/
├── predictions/
├── videos/
└── samples/
```

初始化成功后，下面的 `content-prepare` 才能写入内容机会。项目尚未初始化时会明确返回：

```text
creator_init_required
```

## 获取同赛道内容机会

### 路线 A：使用已经存在的 VDM Cluster

如果 `RESEARCH_DIR` 已经完成 Evidence 聚类，直接运行：

```bash
python3 "$VDM_CLI" --project "$RESEARCH_DIR" content-prepare \
  --cluster-id "OPP-..." \
  --creator-project "$CREATOR_DIR"
```

返回结果包含：

```json
{
  "status": "ok",
  "candidate_id": "...",
  "source_pack": "/path/to/creator/.nexttake/sources/<candidate-id>.md",
  "next_action": {
    "action": "generate_current_draft"
  }
}
```

该命令会：

- 创建不可变 `content.opportunity` Artifact；
- 写入符合上游 schema 的 `candidates.md` 条目；
- 写入 `.nexttake/sources/<candidate-id>.json/.md`；
- 保留支持证据、反证和样本限制；
- 不自行生成另一套评分或预测逻辑。

### 路线 B：从公开视频开始研究

首次真实研究的命令顺序为：

```text
init
  -> creator-add
  -> sync
  -> sample
  -> acquire
  -> transcript-import（需要时）
  -> prepare-analysis
  -> model-job-input
  -> submit-evidence
  -> cluster
  -> report
```

最小示例：

```bash
python3 "$VDM_CLI" --project "$RESEARCH_DIR" init --name "团播内容机会"

python3 "$VDM_CLI" --project "$RESEARCH_DIR" creator-add \
  --name "抖音博主 A" \
  --platform douyin \
  --account-id "<sec_user_id>"

python3 "$VDM_CLI" --project "$RESEARCH_DIR" sync \
  --creator-id "<creator-id>" --pages 1

python3 "$VDM_CLI" --project "$RESEARCH_DIR" sample \
  --creator-id "<creator-id>" --count 6
```

真实采集默认启用项目级串行门控：每个 Provider 操作完成后，下一次操作会等待 `6-12` 秒的随机间隔；不同 CLI 进程也共享同一门控。B站同步只接受一个创作者对应的一个账号，并强制 `--pages 1`：

```bash
python3 "$VDM_CLI" --project "$RESEARCH_DIR" creator-add \
  --name "B站博主 A" \
  --platform bilibili \
  --account-id "<uid>"

python3 "$VDM_CLI" --project "$RESEARCH_DIR" \
  --bilibili-cli "<setup 返回的 bili 绝对路径>" \
  sync --creator-id "<creator-id>" --platform bilibili --pages 1
```

需要更保守的间隔时，可在子命令前传入 `--request-delay-min-seconds` 和 `--request-delay-max-seconds`。间隔必须非负且最小值不能大于最大值。节流只能降低高频请求风险；遇到验证码、登录失效或风控时，NextTake 会停止并保留检查点，不会尝试绕过平台验证。

Provider、ASR 和 Evidence 提交的完整步骤见 [`vlog-demand-miner/SKILL.md`](vlog-demand-miner/SKILL.md) 与 [`local-environment-setup.md`](vlog-demand-miner/references/local-environment-setup.md)。

## 生成本期文案

`content-prepare` 完成后，在 Codex 的 `CREATOR_DIR` 中说：

```text
基于 .nexttake/sources/<candidate-id>.md 讨论并生成这一条文案
```

然后依次使用 NextTake 动作：

```text
给本期文案打分 scripts/<draft>.md
启动发布前预测 scripts/<draft>.md
登记已拍摄 scripts/<draft>.md
```

本期文案会保存在 `scripts/`，发布前判断保存在 `predictions/`。

## 人工发布和复盘

拍摄和平台发布由使用者自己完成。发布后在 Codex 中说：

```text
已发布 <视频链接>
```

NextTake 只登记人工发布，不会调用平台上传 API。

准备一个只包含原始指标的 JSON：

```json
{
  "views": 12840,
  "likes": 1126,
  "comments": 143,
  "shares": 216,
  "saves": 394,
  "follows": 87,
  "completion_rate": 0.38,
  "captured_at": "2026-07-16T20:00:00+08:00",
  "top_comments": [
    "能不能讲讲底薪、提成和流水到底怎么算？",
    "下一期想看怎么判断公司靠不靠谱。"
  ]
}
```

禁止加入：

- 平台用户 ID；
- 昵称、头像、电话或联系方式；
- Cookie、Token 或请求头；
- `likes_per_view` 等预计算比例。

然后在 Codex 中运行 NextTake 复盘：

```text
复盘本期内容 videos/<video-folder>/
更新受众画像
推荐下一条
```

## 生成下一期文案

得到下一条推荐后，继续说：

```text
根据刚才的下一条推荐，生成下一期完整文案
```

下一期稿件会写入 `scripts/<next-draft>.md`。

因此一个完整周期会产生两份文案：

```text
本期文案
  -> 人工发布
  -> 表现复盘
  -> 下一条推荐
  -> 下一期文案
```

## 生成 Creator Studio

原生流程完成后，将已有文件路径登记到 NextTake：

```bash
python3 "$VDM_CLI" --project "$RESEARCH_DIR" creator-attach \
  --creator-project "$CREATOR_DIR" \
  --candidate-id "<candidate-id>" \
  --script-path "scripts/<draft>.md" \
  --prediction-path "predictions/<prediction>.md" \
  --report-path "videos/<video>/report.md" \
  --performance-file /absolute/path/to/raw-performance.json \
  --audience-path "audience.md" \
  --recommendation-path ".nexttake/recommendation.md" \
  --next-script-path "scripts/<next-draft>.md"
```

其中 `script-path`、`prediction-path`、`report-path`、`audience-path`、`recommendation-path` 和 `next-script-path` 必须位于 `CREATOR_DIR` 内。

生成 Studio：

```bash
python3 "$VDM_CLI" --project "$RESEARCH_DIR" creator-studio \
  --creator-project "$CREATOR_DIR" \
  --candidate-id "<candidate-id>"
```

命令返回静态 HTML 路径。页面展示：

- 内容机会与观众原话；
- 本期文案及复制按钮；
- 发布前判断；
- 本期表现和评论；
- 受众变化；
- 下一条推荐；
- 下一期完整文案及复制按钮。

Studio 是只读页面，不会修改创作者项目文件。

## 安装真实采集环境

离线演示不需要执行本节。真实采集先检查现有抖音 Docker Sidecar 和 B站 CLI：

```bash
python3 "$VDM_CLI" --project "$RESEARCH_DIR" \
  --sidecar-url http://127.0.0.1:18080 \
  --bilibili-cli "<bili 绝对路径>" \
  doctor
```

当 Sidecar 的 `status` 为 `ok` 时，抖音采集直接使用 `--douyin-provider sidecar`，无需安装 Browser Provider。当前默认地址是 `http://127.0.0.1:18080`，NextTake 只检查本地 OpenAPI 能力，不读取容器内凭证。

缺少 B站 CLI 或需要抖音浏览器回退时，再运行：

```bash
python3 "$NEXTTAKE_SKILL/scripts/setup_local_environment.py" \
  --project "$RESEARCH_DIR"
```

安装器会准备：

- `ffmpeg` 与 `whisper-cpp`；
- 独立 Python 3.12 Browser Provider 环境；
- 固定版本 `bilibili-cli`；
- 项目级 Keychain 评论者 HMAC 引用；
- NextTake 抖音 Browser Adapter。

平台登录仍由用户在浏览器或上游 CLI 中交互完成。安装器不会读取或输出 Cookie。

## 常见错误

### `creator_init_required`

创作者项目尚未初始化。在 `CREATOR_DIR` 中对 Codex 说：

```text
使用 $vlog-demand-miner 初始化创作者项目
```

### `cluster_score_required`

研究项目还没有成功执行 `cluster`。先完成 Evidence 提交和聚类。

### `cluster_not_found`

传入的 `OPP-...` 不属于最新 Cluster Artifact。重新执行 `report` 或检查 `cluster` 输出。

### `incomplete_nexttake_link`

还没有通过 `creator-attach` 登记脚本、预测、复盘、表现或推荐文件。

### `views_must_be_positive`

表现 JSON 的 `views` 必须大于 0。

### `creator_path_outside_project`

传入的创作者文件路径越出了 `CREATOR_DIR`。将文件放回创作者项目内再登记。

### Browser Provider unavailable

若 Docker Sidecar 已健康，可继续使用 `--douyin-provider sidecar`，Browser Provider 不可用不会阻断抖音采集。Sidecar 也不可用时，再运行环境安装器，并根据返回的 `next_actions` 完成人工登录和 `doctor` 检查。

### `bilibili_sync_requires_single_page`

B站库存同步只允许 `--pages 1`。一次只同步一个创作者账号；需要同步另一个账号时，等待当前命令结束后再单独执行下一次。

### `request_delay_range_invalid`

请求缓冲区间非法。确保最小值和最大值均非负，且最小值不大于最大值。

## CLI 命令速查

| Command | Purpose |
| --- | --- |
| `creator-demo` | 生成完整离线 Creator Studio |
| `content-prepare` | 把 VDM Cluster 写入创作者候选池和 source pack |
| `creator-attach` | 登记原生创作生命周期文件与原始表现 JSON |
| `creator-studio` | 生成只读 Creator Studio |
| `init` | 初始化 VDM 研究项目 |
| `creator-add` | 登记同赛道博主 |
| `sync` | 同步作品库存 |
| `sample` | 选择待研究作品 |
| `acquire` | 采集详情、评论和可选媒体 |
| `transcript-import` | 导入外部字幕/ASR 时间轴 |
| `prepare-analysis` | 创建字幕/评论隔离 ModelJob |
| `model-job-input` | 输出模型允许读取的白名单输入 |
| `submit-evidence` | 校验并保存 Evidence |
| `cluster` | 聚类并排序内容机会 |
| `report` | 生成需求审核包 |
| `review` | 回写负责人审核决定 |
| `doctor` | 检查本机 Provider 状态 |
| `resume` | 恢复具有稳定输入的任务 |

## 测试

在仓库根目录运行：

```bash
python3 -m unittest discover -s vlog-demand-miner/tests -v
```

快速验证离线闭环：

```bash
python3 vlog-demand-miner/scripts/vdm.py \
  --project /tmp/nexttake-readme-check \
  creator-demo
```

## 能力边界

| Capability | Current status |
| --- | --- |
| 内容机会、两次文案、复盘和 Studio | 已实现并验证 |
| 内容生成、评分、预测和复盘引擎 | 已封装为 NextTake 自然语言动作 |
| 抖音 Browser Adapter | 已接入，真实使用需要人工登录 |
| B站、XHS、LinkedIn 上游 Adapter | 源码已保留，并非全部完成真实账号验证 |
| 自动上传或定时发布 | 不支持，发布由创作者手动完成 |
| 云端 SaaS、多用户和团队协作 | 不在当前范围 |

不要把“源码已保留”理解为“所有外部 Adapter 已完成真实平台端到端验证”。

## 安全边界

- 不读取、复制或输出 Cookie、Token 和浏览器存储；
- 评论在进入 Evidence 或 Studio 前必须匿名化；
- 模型输出、评论和用户文本在 HTML 中全部 escape；
- Creator Studio 是静态只读投影；
- Demand score 是内容研究排序信号，不是流量或收入承诺；
- 发布前判断在复盘前后通过 section hash 检查，复盘只能追加。

## 第三方许可证

NextTake 的公开接口不会暴露内部依赖。第三方来源、固定版本和许可证保留在 [`THIRD_PARTY_NOTICES.md`](vlog-demand-miner/THIRD_PARTY_NOTICES.md)。
