# claude-team-demo

**中文** | [English](README.md)

一套**多 Agent 自主管理项目**框架。装一次，让 Claude agent 团队接管你的项目：自动规划、自动干活、自动复盘、自动改方向 —— 直到项目收敛或 token 耗光自己停下。

```
                 ┌──────────────────────────────────┐
                 │  SUPERVISOR (Claude, 主脑)         │  L3-L6 元决策
                 │  - 巡视 / 写周报 / 决定升级路径    │
                 │  - 改 goal.md / promote workspace │
                 │  - 决定何时 shutdown              │
                 └──────────────┬───────────────────┘
                                │ note / shutdown
                                ▼
   ┌────────────────┐   ┌──────────────────────┐   ┌────────────────────┐
   │  PLANNER       │──▶│   pm-daemon.py        │──▶│  EXECUTOR × N      │
   │  Claude (灵感)  │   │   Python (派活机)      │   │  Claude (干活)     │
   │  add_task      │   │   ✓ 确定性、零 token    │   │  在 workspace/ 改代码│
   │  ⨯ 不写代码     │   │   ✓ FOREVER 模式不退出  │   │  tm-done 报告完成  │
   └────────────────┘   └──────────────────────┘   └────────────────────┘
                                ▲
                                │ events/*.json (文件邮箱)
                                │
                          所有四方解耦
```

**核心理念**：把 LLM 用在该用的地方（创造、判断、写代码），把基础设施留给确定性 Python（派活、跟踪状态、催活、回收 worker）。

---

## 主要能力

按成熟度等级（L0-L6 全部已就位）：

| 等级 | 能力 | 怎么实现 |
|---|---|---|
| L0 | 单 agent 干活 | 一个 Claude 窗口 |
| L1 | 多 agent 并发 | PM 派活给多个 executor，文件邮箱通信无锁 |
| L2 | Planner 持续生成新 task | `tm-profile` 写项目专属 manifest.json + planner 据此找事 + 5min clean cooldown |
| L3 | Supervisor 元决策 | `tm-claude-supervisor` + 周报 + 决策日志 |
| L4 | Agent 改自己源码 | executor 在 workspace/ 编辑产品代码 |
| L5 | 改动自动同步到 production | `tm-promote` 带 stale-snapshot 检测 |
| L6 | Goal 自动演进 | `tm-supervise revise-goal` + version snapshot |
| 创新通道 | 人/LLM 双源注入野心 | `vision.md`（你写）+ `tm-vision propose`（LLM brainstorm）→ supervisor 决定何时 promote |

> **关于 L7**：你可能预期 ladder 应该有 L7（跨项目编排）。**故意没加**。L7 不是 L6 的自然延续，是不同类别的问题（多租户、跨项目状态汇聚），架构上需要重写底座。99% 的「我有多个项目都想自动管」用例，**跑 N 次 `tm-init` + `tm-team-up` 各自独立运行**就解决了 —— 这其实就是简化版的 L7，零额外代码。真要做完整 L7 是另一个项目（多租户 SaaS），不是这个 framework 的下一个版本。

## 创新性的限制（坦诚说）

这套系统**擅长 gap-filling，不擅长 invention**：planner 看 manifest 找漏洞、补测试、硬化代码。但它**不能**自己想到「这项目其实可以变成 SaaS / 加 web UI / 跨项目编排」这种跳脱当前 scope 的方向。

解决方案是 **人是创新源头**，加了两个通道把创新接入系统：

| 通道 | 谁产生 | 写到哪 | 谁消费 |
|---|---|---|---|
| `vision.md` | **你（人类）** 直接写 | repo 根目录 | planner 每轮读，supervisor 也读 |
| `proposals/` | LLM brainstorm 产生（`tm-vision propose`） | `proposals/<iso>-<slug>.md` | supervisor 决定 promote / defer / reject |

vision 项**不**直接进任务队列。supervisor 看到合适的会通过 `tm-supervise revise-goal` 把它 promote 到 goal.md，然后 planner 自然会派任务实现它。这层 gating 防止 LLM 头脑发热的「点子」直接污染项目方向。

PM 角色：
- **PM (Python daemon)** — 派活、跟踪、GC、escalation 升级。零 token。
- **SUPERVISOR (Claude)** — 项目经理：写周报、记决策、改方向、决定停。
- **PLANNER (Claude)** — 持续找事。**维度从项目自身导出**：`tm-profile`
  读 workspace/ 后写 `manifest.json`，里面的 3-7 个 dimension 是对
  THIS project 量身的（候选池含 correctness/robustness/perf/security/
  features/UI/docs/distribution/integrations/data_model，以及项目领域
  专属如 frame_pacing / audio_latency / numerical_stability）。**不适用
  的维度不进 manifest，不浪费 token 审计**。Planner 只读 manifest 工作。
- **EXECUTOR × N (Claude)** — 真动手改代码的 agent。可并行多个。

---

## 快速开始

### 用法 A: 在这个 demo 项目里跑（自我优化模式）

workspace/ 是这个项目自己的副本，agent 团队会优化它。

```bash
cd claude-team-demo
./bin/tm-team-up 2          # 弹出 4 个 Terminal 窗口（1 supervisor + 1 planner + 2 executor）
./bin/tm-pm watch           # 另一个 terminal 看实时进度
```

每个新窗口里 Claude 自动收到 `go`，立刻开始工作，**无需手动输入**。

### 用法 B: 装到你自己的项目（推荐）

```bash
# 1. clone 框架
git clone <this-repo-url> ~/tools/claude-team-demo

# 2. 用 tm-init 装到任意目标目录
~/tools/claude-team-demo/bin/tm-init ~/my-project

# 3. 配置项目目标
cd ~/my-project
$EDITOR goal.md             # 描述你的项目"做完"长什么样
cp -r ~/old-source/* workspace/   # 把要被管理的代码放进 workspace/

# 4. 起飞
./bin/tm-team-up 2
```

`tm-init` 会帮你创建：
- `bin/` 工具集
- `.claude/settings.json` (hooks + permissions + statusLine)
- `CLAUDE.md` (executor 工作指南)
- `goal.md` 模板
- `workspace/` (executor 唯一能编辑的地方)
- `.gitignore` (PM runtime state 不入 git)

---

## 使用

### 启动 / 停止

```bash
./bin/tm-team-up [N]              # 一键起整队（默认 1 executor，传 2/3 加并行）
./bin/tm-pm shutdown "<reason>"   # 优雅停机（让 in-flight task 跑完再退）
./bin/tm-pm stop                  # 强制停 daemon
./bin/tm-pm reset                 # 清所有运行时状态从头来
```

### 监控（任意终端跑，0 token 消耗）

```bash
./bin/tm-pm watch                 # 实时 dashboard，1Hz 刷新
./bin/tm-pm status                # 一次性快照
./bin/tm-pm tail                  # 实时滚 PM 事件日志
./bin/tm-status-report            # 生成 markdown 周报到 status-reports/
./bin/tm-status-report --stdout   # 周报直接打到屏幕
./bin/tm-risk-list                # 看哪些 task 风险高（reclaim 多/失败多/卡得久）
./bin/tm-pm escalations           # 永久 fail 的任务列表
./bin/tm-context list             # 看所有 task 状态
./bin/tm-context done             # 看完成的 task 摘要
./bin/tm-decision list            # 看 supervisor 写过的决策日志
```

**每个 Claude 窗口的标题栏自动显示项目实时状态**（绕开 Claude Code statusLine 的回合边界限制）：

```
● claude-team-demo · 8/13 · ▶3 · 3/4w · sup
```
项目名 · `done/total` · `▶进行中` · `busy/total worker` · 角色简写

### 单独起角色（不用 tm-team-up）

```bash
./bin/tm-claude-supervisor        # 主脑（元决策）
./bin/tm-claude-planner           # 规划（持续加 task）
./bin/tm-claude-executor          # 执行（在 workspace/ 写代码）
```

每个 wrapper 都自动注入 `go`，背后跑 title-keeper，关掉窗口自动清理。

### Supervisor 的 PM 工具集（它自己用，你也能跑）

```bash
./bin/tm-decision new "<title>" "<context>" "<decision>" "<consequences>"
./bin/tm-decision list
./bin/tm-supervise revise-goal "<rationale>"      # L6: 改 goal.md 前自动 snapshot
./bin/tm-promote                                   # L5: 看 workspace 改动 diff
./bin/tm-promote --apply pm-daemon.py              # 显式 promote 单个文件
./bin/tm-goal-snapshot list                        # 看 goal.md 历史快照
./bin/tm-goal-snapshot diff 1                      # 当前 vs 上一版
```

### 你自己加创新点（在终端里）

任何时候，你都可以直接给系统注入一个野心方向：

```bash
# 一行命令加一条想法到 vision.md
./bin/tm-vision add "Web UI dashboard with real-time agent activity stream"

# 或者用编辑器自由发挥
./bin/tm-vision edit               # 等于 $EDITOR vision.md

# 看现在 vision.md 里有什么 + 已有哪些 LLM 提案
./bin/tm-vision list

# 让 LLM 帮你 brainstorm 2 个野心方向（写到 proposals/）
./bin/tm-vision propose 2

# 看具体某个 proposal
./bin/tm-vision show 1

# 清空所有 LLM proposal（vision.md 不动）
./bin/tm-vision clear-proposals
```

加进去之后**不需要重启**任何东西。下个 cycle planner 和 supervisor 都会读到。supervisor 的工作流里包含「看 vision/proposals → 决定 promote 或 defer」。

`vision.md` 是 **user-authored**（像 goal.md 一样不被 reset 清掉）。`proposals/` 是 **agent-generated**，会被 reset 清。

---

## 项目产物（每次跑都会留下，可审计）

```
project/
├── goal.md                  # 当前迭代的 done 标准（你写）
├── vision.md                # 长期野心方向（你写，创新源头）
├── status-reports/          # supervisor 周报系列
│   └── 2026-05-08T10-30Z.md
├── decisions/               # ADR 决策日志
│   └── 001-skip-promoting-tm-statusline.md
├── proposals/               # LLM brainstorm 出的野心提案（待 supervisor 评估）
│   └── 2026-05-08T11-15Z-web-dashboard.md
├── goal-history/            # goal.md 每次演进的快照
├── escalations/             # 永久 fail 的任务（理想为空）
├── workspace/               # executor 真实编辑的代码
├── pm.log                   # PM 全部 event 流水
├── supervisor.log           # supervisor 决策流水
└── bin/.promoted-bak/       # 每次 L5 promote 的备份
```

跑完后任何人能从 status-reports 看进度、从 decisions 看为什么这么做、从 goal-history 看方向怎么演变的、从 escalations 看哪里出过问题。

---

## token 经济

| 进程 | 干啥 | token 成本 |
|---|---|---|
| `pm-daemon.py` | 状态机派活 | **0** |
| `tm-title-keeper` (×N) | 标题栏实时刷 | **0** |
| `tm-pm watch` / `tail` / `status-report` 等 | 监控只读 | **0** |
| supervisor (Claude) | 巡视写决策 | ~5% |
| planner (Claude) | 跨维度找 task | ~25% |
| executor × N (Claude) | 真改代码 | ~70% |

**99% 的 LLM 预算花在 executor 写代码上**，这是设计目标。

token 耗光时：planner / executor 调 LLM 失败 → escalation → supervisor 看到 → 自主 shutdown → PM 优雅退出。**整个系统能自己判断什么时候停**。

---

## 配置（环境变量）

| Env | 默认 | 控制 |
|---|---|---|
| `PM_FOREVER` | 0 | 1 = 队列空也不退出，等新 task 或 shutdown event |
| `PM_STRICT` | 0 | 1 = 每个 done 调 tm-review 严格审查 |
| `PM_GOAL_REVIEW` | 0 | 1 = 每轮结束前调 tm-goal-review 判定 goal 是否真满足 |
| `STALE_AFTER_SEC` (代码常量) | 120 | worker 多久没事件 = 死 |
| `NAG_AFTER_SEC` | 40 | worker 干活多久开始催 |
| `TM_PLAN_CLEAN_COOLDOWN` | 300 | planner 宣告 clean 后冷却多久才能再评 |
| `SUPERVISE_INTERVAL` | 600 | supervisor 巡视间隔（秒） |
| `TM_TITLE_INTERVAL` | 2 | 标题栏刷新频率（秒） |
| `PLANNER_INTERVAL` | 60 | bash 版 tm-planner daemon 节奏 |

---

## 架构特点

**为什么 PM 是 Python 不是 Claude**：PM 的工作（扫 events、配对、改 status 字段）是纯状态机，不需要 LLM 判断。让 LLM 来做这种事每秒 4 次会烧爆预算且引入幻觉风险。LLM 价值在创造、判断、上下文理解 —— 派给 supervisor / planner / executor。

**为什么用文件邮箱不是 socket / RPC**：四方完全解耦。PM 死了 worker 还能继续干（写在 events/ 里等 daemon 重启）；worker crash 了 PM 自动 GC + reclaim task 给别人。文件 IO 比网络 IPC 简单 10 倍，调试时直接 `ls events/` 看。

**为什么所有 agent 通过 SessionStart hook 注册角色而不是 CLI flag**：role 由 `TM_ROLE` 环境变量决定，wrapper 注入。PM 通过 join event 知道 worker 角色，进而决定派不派活给它（supervisor 和 planner 不接 exec task）。

---

## 故障处理

| 现象 | 怎么办 |
|---|---|
| 某个 worker 不干活 | `./bin/tm-pm status` 看 role 是不是对；不是就 GC 后重开窗口 |
| 任务卡 in-progress 不动 | `./bin/tm-context show <id>` 看 signal_history；可能是 signal_cmd 有问题 |
| Worker 数一直涨 | 用户开太多窗口/反复 /clear；`./bin/tm-pm gc` 立刻清死 worker |
| PM 自己挂了 | 看 `pm.log` 末尾 traceback；`./bin/tm-pm start` 重启 |
| 全跑完想再来一次 | `./bin/tm-pm reset && ./bin/tm-team-up 2` |

---

## 目录速查

```
bin/
├── pm-daemon.py              # 后台 PM
├── tm-pm                     # PM 控制（start/stop/status/watch/...）
├── tm-team-up                # 一键起整队
├── tm-init                   # 装框架到目标目录
├── tm-claude-supervisor      # 起 supervisor 窗口
├── tm-claude-planner         # 起 planner 窗口
├── tm-claude-executor        # 起 executor 窗口
├── tm-launch-helpers         # 只起 planner + N executor（不含 supervisor）
├── tm-status-report          # 写 markdown 周报
├── tm-decision               # ADR 决策日志
├── tm-risk-list              # 风险列表
├── tm-promote                # L5: workspace → bin 同步
├── tm-goal-snapshot          # L6: goal.md 历史
├── tm-supervise              # supervisor 的 CLI (note/shutdown/revise-goal)
├── tm-plan-cycle             # planner 的 CLI (add/clean)
├── tm-done                   # executor 的 CLI
├── tm-context                # 任务/历史查询
├── tm-vision                 # 创新通道：add / propose / list / show / edit
├── tm-title-keeper           # 标题栏实时刷新
├── tm-status-title           # 标题栏文本生成
├── tm-statusline             # Claude Code statusLine 命令
├── tm-{session,prompt,stop,tool}-hook    # Claude Code hooks
└── tm-{plan,review,assess,goal-review,profile}    # 一次性 claude -p 工具
```

---

## 鸣谢

构建于 [Claude Code](https://claude.com/claude-code)。设计灵感来自 agent-self-iteration 项目（同 repo 上一代的单 agent 自循环器）。

License: [MIT](LICENSE)
