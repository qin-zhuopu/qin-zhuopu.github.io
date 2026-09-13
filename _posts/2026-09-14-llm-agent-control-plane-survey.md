---
layout: post
title: "LLM Agent 控制面全景调研：从断点续跑到进程监督"
date: 2026-09-14 06:00 +0800
categories: [AI, Agent]
tags: [agent, supervisor, durable-execution, llm, survey]
---

## 引言：为什么 LLM 会话需要一个「会话外」的控制面

把一次 LLM Agent 会话当成一段短暂的对话，是很多人对它的默认心智模型：提问、回答、结束。但一旦你让 Agent 去自主完成真实的工程任务——修 bug、补测试、排查 Jenkins、回填文档——会话的形态就变了：它是一段**长时间运行、带副作用、会失败的执行过程**，本质上更接近一个进程，而不是一段聊天记录。

进程会崩，会 hang 死，会陷入失控循环，会在做完一半时被 kill。LLM 会话同样会：API 报错或欠费导致中途停摆、上下文被压缩后丢掉关键约束、绿点转着却 30 分钟没有输出、反复重试同一个失败操作烧掉 credits、甚至写完「完成文件」报捷而任务根本没做完。区别在于，操作系统为进程的不可靠准备了一整套答案——supervisor、监督树、退出码与验收——而我们对 LLM 会话的容错投入，往往接近于零。

答案不该藏在会话内部（让模型「自己小心一点」是靠不住的），而应该抽到会话之外：一个独立于会话生命周期的**控制面**，负责持久化执行进度、检测故障、决定重启、判定完成。这篇文章是我为搭建这样一个控制面做的两条主线调研的整理：

- **第一条主线**把 Agent 会话当作异步任务来管理，横扫 Python 生态 18 个项目，梳理出三档恢复模型；
- **第二条主线**横向对比主流 Agent 框架的恢复能力，并把视角抬到 OS 进程监督与「完成判定」的演进。

两条线最终收敛到同一个务实结论：控制面不是单一组件，而是三层叠加的架构。下面逐层展开。

---

## 第一章：把会话当异步任务——18 项目宽表与三档恢复模型

如果承认「会话即任务」，那么第一个要问的问题是：**这个任务失败之后，怎么恢复？** Python 异步任务生态里的项目，按恢复机制可以清晰地分成三档：

- **asyncio-task（进程内协程/任务）**：任务活在进程内的事件循环里，进程死则全丢。粒度最细、隔离性最弱。
- **外部队列（消息队列重投）**：任务被投进 broker，失败后整任务重投。粒度是「整个任务」，不是「跑到哪一步」。
- **durable-replay（事件日志 / checkpoint 持久化）**：每一步执行都记进 append-only 的日志或 checkpoint，崩溃后从断点续跑。**这一档才是 Agent 会话的真正解药**——它让一个已经跑了 5 次 LLM 调用的会话在崩溃后不必重头再来，既不重复烧钱，也不重复产生副作用。

下面这张宽表汇总了 18 个项目（star 数为 2026-09 通过 GitHub API 实测的量级）：

| # | 项目 | Star | 模型 | 会话失败后的恢复机制 |
|---|---|---|---|---|
| 1 | openai-agents-python（OpenAI Agents SDK） | ~29k | asyncio-task | `Runner.run` 是 coroutine，进程崩溃即丢；Session（SQLite/Conversations）只持久化对话历史——能恢复「聊到哪」，不能恢复「跑到哪一步」 |
| 2 | Temporal Python SDK | ~1.2k (py) | durable-replay | LLM 调用当作 Activity，append-only event history；worker 崩溃后 replay 跳过已完成 Activity（官方 openai_agents 集成） |
| 3 | DBOS Transact (py) | ~1.6k | durable-replay | workflow/step checkpoint 到 Postgres，崩溃后从最后完成步恢复，exactly-once；轻量库无需独立 server（Pydantic AI 官方集成） |
| 4 | Hatchet | ~7.9k | durable-replay | Postgres 上的 durable task queue，durable event log checkpoint + replay，专门宣传 agentic loop + human-in-the-loop |
| 5 | Restate | ~4.4k | durable-replay | 每步记 journal，崩溃后 replay 续跑；原生集成 OpenAI Agents SDK / Pydantic AI / Google ADK |
| 6 | Prefect | ~24k | 外部队列（结果持久化） | flow/task 级 retry + 结果持久化，跟随 Python 原生控制流；恢复粒度是 task，非指令级 replay |
| 7 | Dagster | ~16k | 外部队列（DAG） | op/asset 级 retry，面向数据管道而非会话续跑 |
| 8 | Celery | ~29k | 外部队列 | broker 消息重投；`acks_late` + `reject_on_worker_lost` 整任务重跑（默认 early-ack 会丢约 8%）；无 step checkpoint，需自己实现幂等 |
| 9 | arq | ~3k | 外部队列（asyncio 原生） | job 整体重试；官方维护模式，不建议新项目 |
| 10 | taskiq | ~2.3k | 外部队列（asyncio 原生） | async-first 的 Celery，task 级 retry 中间件，整任务重投 |
| 11 | Dramatiq | ~5.3k | 外部队列 | 类 Celery，retries + dead-letter，无 step replay |
| 12 | Windmill | ~18k | durable-replay（flow） | 「简化版 Temporal」，每 step 独立 job + per-step retry + suspend/resume |
| 13 | Trigger.dev | ~16k | durable-replay（TS 为主） | agent run 当「进程」：崩溃后从持久化对话历史重建上下文（`onRecoveryBoot` 钩子）；Python 支持较弱 |
| 14 | Inngest | ~5.8k | durable-replay（有 py SDK） | step 级 checkpoint，死在第 7 步就从第 7 步续；长等待零资源挂起 |
| 15 | DBOSify-py | DBOS 生态 | durable-replay | Temporal Python 的 Postgres drop-in 替代 |
| 16 | asyncio TaskGroup/timeout（stdlib 3.11+） | stdlib | asyncio-task | 结构化并发：子任务异常取消同组其余 + ExceptionGroup；进程崩则全丢 |
| 17 | aiojobs | ~0.9k | asyncio-task（supervisor 雏形） | 并发受限的后台任务 scheduler + 优雅关闭；不跨进程恢复 |
| 18 | aiomonitor(-ng) | ~0.8k | asyncio-task（监控） | 独立线程挂 REPL/CLI，循环卡死也能连上，查/取消 task；观测工具而非自动恢复 |

### 从表里读出的三条要点

**1）OpenAI Agents SDK——Agent 本质就是 asyncio 任务。** 它提供了漂亮的原语：`handoff`（控制权交接）、`guardrail`（输入/输出并行校验，用便宜模型拦截 + human approval 门）。但持久化上有个关键局限：**Session 只是消息 log，不是执行进度**——它不 checkpoint「跑到了哪一步」。想要真正的崩溃续跑，必须外挂 Temporal / Restate / DBOS（三者都提供官方集成）。

**2）恢复机制天然分层。** 纯消息队列（Celery/arq/taskiq/Dramatiq）只能「重投整任务」，会话中途崩了要么整轮重来（又贵又会重复副作用），要么自己写幂等；编排类（Prefect/Dagster）能「重跑失败的 task」，跟随 Python 控制流但仍非指令级 replay；只有 durable-replay 一档（Temporal/Restate/DBOS/Hatchet/Windmill/Inngest/Trigger.dev）能「从断点续同一次执行」。其中 DBOS / Hatchet / Windmill 只依赖 Postgres，运维最轻。

**3）asyncio 原生并没有成熟的「自愈 supervisor」。** stdlib 的 `TaskGroup`/`timeout` 只管进程内的生命周期、取消与超时；生态里**没有**成熟的「崩溃自动重启 + 状态恢复」的 asyncio supervisor——那正是 durable 引擎的地盘。最接近的只有 aiojobs（调度 + 优雅关闭）和 aiomonitor（观测 + 手动干预）；社区讨论过类比 Kotlin SupervisorScope 的 `PersistentTaskGroup`，但未进标准库。

### asyncio 任务 vs OS 进程监督：边界在哪

**什么时候用 asyncio 任务（进程内协程）**：单进程内大量并发会话、以 I/O 等待为主；会话短、可以容忍「崩了就丢」；或者已经外挂了 durable 引擎（asyncio 只负责进程内的并发编排）；需要细粒度的取消/超时/共享内存态。它的弱点是隔离性弱、崩溃爆炸半径大——一个会话失控（死循环、内存暴涨、阻塞事件循环）会拖垮同进程的所有会话，进程一崩内存态全丢。

**什么时候用 OS 进程监督（每 worker 一进程）**：需要故障隔离（单会话 OOM 或被 kill 不影响他人）；要给不可信代码、跑 shell 的 Agent 做 sandbox；CPU 密集需要绕开 GIL；需要资源配额（cgroups）；长时会话要跨进程续命。代价是进程/IPC/序列化开销大、并发密度低、通信必须走消息。注意：进程隔离本身不解决状态，跨进程续跑必须再配一层 durable 状态层，否则新拉起的进程是一张白纸。

**结论**：二者不互斥，而是分层组合。会话越长、副作用越贵、越依赖 human-in-the-loop 的长等待，就越应该滑向「OS 进程 + durable checkpoint」这一端；会话越短、越纯 I/O，纯 asyncio 就越划算。这条主线的最终架构式，正是本文终章要收敛的那句话。

---

## 第二章：Agent 框架恢复能力与进程监督矩阵

第一章从「任务基础设施」的角度看恢复；第二章换个视角，横向审视主流 **Agent 框架**自身把恢复做到了哪一步，并把参照系从 Python 库抬升到 OS/容器层的进程监督乃至 Erlang/OTP 监督树。

### 进程监督路线矩阵

| 方案 | 机制 | 内建/外挂 |
|---|---|---|
| **Vega** | 把 Erlang/OTP 监督模型直接搬到 Agent：每个 agent = 受监督进程（inbox / budget / retry / 监督树位置）；3 种重启策略（OneForOne / OneForAll / RestForOne）+ 7 类错误分类（4 类退避重试、3 类放弃）；SQLite 持久化 | 内建（这就是它的全部卖点） |
| Erlang/OTP 监督树 | Supervisor 观察子进程崩溃 → 重启 / 连带重启 / 上抛；「恢复与干活分离」，五个 9 的电话交换机 40 年验证 | 范式（Vega / MiniClaw 借用） |
| MiniClaw | WASM + Firecracker 沙箱内 10 个 actor，任一失败触发受监督重启，而非全系统崩溃 | 案例 |
| systemd unit | `Restart=always/on-failure` 自动拉起；`RuntimeMaxSec` 定期重启；watchdog 检测挂死 | 外挂（OS 级，只保证进程活着） |
| supervisord | ~9.1k，跨语言进程管家，容器内 / 非 root 场景常用 | 外挂 |
| s6-overlay | 容器内多进程监督，比 supervisord 更贴合容器语义 | 外挂 |
| immortal / monit | 轻量进程守护 | 外挂 |
| Temporal | Event History + replay：崩溃后重放历史，精确续到中断点 | 外挂（durable 引擎） |
| DBOS | ~1.6k，Postgres checkpoint 每步状态，重启后从最后完成步自动续 | 外挂（库形态，最轻） |
| Restate | ~4.4k，Journal 每步记账，重放跳过已完成步 | 外挂（durable 引擎） |

### 谁真正原生把「会话当进程监督」做了

**① 原生（最接近 Erlang 监督模型）**

- **Vega**——目前唯一整体照搬 OTP 监督树的 Agent 运行时：监督树 + 三种重启策略 + 七类错误分类 + 退避重试 + SQLite 持久化。它是「会话即受监督进程」这个理念最纯粹的落地。
- **Letta / MemGPT**——把 Agent 当作常驻的有状态服务（server + DB），「会话是长期存活的实体」这件事做得最彻底。

**② 半内建（能存能续，但不管恢复）**

- LangGraph、Agno、CrewAI Flows、Google ADK、Microsoft Agent Framework——都内建了 checkpoint / session 持久化，但失败检测与自动恢复要自己写（据 Diagrid 评测）；其中 Agno / LangGraph「配好后端即用」的体验最顺。
- ⚠️ 注意默认内存态会丢：OpenHands（`FILE_STORE=memory`）、ADK（`InMemorySessionService`）必须显式切换到持久后端。

**③ 必须外挂**

- smolagents（几乎零持久化）、AutoGen/AG2（有 `save`/`load` 但要自己调度）、Agency Swarm（只给钩子）、CAMEL（持久后端靠社区）。
- 落地路线二选一：**应用层 durable execution**（Temporal replay / DBOS checkpoint / Restate journal，补齐失败检测 + 自动恢复 + 去重；pydantic-ai 把这一层当成一等公民），或 **OS/容器层进程管家**（systemd / supervisord / s6，只保证进程活着，续跑仍看框架自身）。

一句话总结这一章：真正「原生把会话当进程监督」的只有 **Vega**（照搬 OTP）和 **Letta**（有状态服务）；主流大框架大多是「内建存状态、外挂管恢复」。

---

## 第三章：完成判定的演进——从「结构校验」到「任务完成判定」

有了恢复与监督，还剩最后一个、也是最容易被忽视的问题：**会话说自己「做完了」，凭什么信？** 我实测过的一种典型故障就是「假完成」——会话写完成文件报捷，甚至把「阻塞」二字写进完成文件里。完成判定的技术栈可以分成两个层次：

- **(A) 约束解码 / 结构校验**——保证「输出的格式对」；
- **(B) 任务完成判定**——保证「任务真的做完了」。

instructor / guardrails / outlines 这些耳熟能详的名字都在 (A) 层。而真正的演进方向，是从 (A) 走向 (B)：

| 方案 | Star | 类别 | 机制 | 内建/外挂 |
|---|---|---|---|---|
| XGrammar | ~1.9k | A 约束解码 | token 级屏蔽非法 token，主流三家之一（与 Outlines / LMFE 并列） | 外挂（vLLM 等推理引擎集成） |
| LM Format Enforcer | 中等 | A 约束解码 | 按语法逐 token 强制格式 | 外挂 |
| OpenAI Strict Mode | 平台内建 | A 约束解码 | 供应商侧严格模式，解析失败率 <0.1%（对比无强制的 8–15%） | 内建 |
| DeepEval | ~18.2k | B 完成判定 | Task Completion metric = LLM-as-a-judge，基于完整 trajectory 判定并自解释评分理由 | 外挂（可入 CI / 在线） |
| LLM-as-a-Judge | 范式 | B 完成判定 | 用一个 LLM 评审另一个的输出/轨迹是否完成任务，可作 RL reward | 范式 |
| Trajectory/Trace 评估 | 研究 | B 完成判定 | judge 检查 plans → tool calls → handoffs 是否完整有序，抓「答案相似但路径迥异」 | 外挂 |
| Agentic Reward Modeling | arXiv 2026 | B 完成判定 | 被动 judge 受「部分可观测」限制 → 主动交互式验证 GUI agent（探查隐藏环境状态再判完成） | 研究前沿 |

这条演进线的意义在于：**结构对不代表任务对。** 一个会话完全可以输出格式完美的 JSON，声称任务完成，而实际什么都没做成。DeepEval 的 Task Completion metric 直接基于完整 trajectory 打分并解释理由；trajectory 评估更进一步，检查从计划到工具调用再到 handoff 的整条路径是否合规，专门抓「终态看起来对、但过程根本不对」的情形；而 agentic reward modeling 则指出被动 judge 受限于「部分可观测」——很多环境状态藏在界面背后，judge 需要**主动交互去探查**才能判断任务是否真的完成。完成判定，正从静态的「格式校验」走向动态的「过程验收」。

---

## 终章：选型建议——durable 引擎 + OS 进程隔离 + 进程内 asyncio 三层叠加

把两条主线的结论合起来看，控制面从来不是单一组件的选择题，而是一个**三层叠加**的架构：

1. **durable 引擎——跨进程续跑的事实来源。** 这是唯一能让一个跑了多次 LLM 调用的会话在崩溃后从断点续上、既不重复烧钱也不重复副作用的机制。选型上：只依赖 Postgres 的 DBOS / Hatchet / Windmill 运维最轻，DBOS 以库的形态嵌入尤其省事；需要完整 workflow 编排能力时上 Temporal / Restate。这一层对应第一章的 durable-replay 档和第二章的「必须外挂」路线。

2. **OS 进程隔离——故障与安全的边界。** 每个 worker 一个进程，让单会话的 OOM、失控循环、被 kill 不会波及他人，也为跑 shell 的不可信 Agent 提供 sandbox 边界。用 systemd / supervisord / s6 保证「进程活着」，用 cgroups 做资源配额。但要牢记：进程隔离只管「活着」，不管「续跑」——它必须和第 1 层的 durable 状态配合，否则重启后的新进程是一张白纸。

3. **进程内 asyncio——单会话内的并发与取消。** 在单个 worker 进程内，用 stdlib 的 `TaskGroup`/`timeout` 做结构化并发、细粒度取消与超时。它管的是「进程内这一亩三分地」，不承担跨进程恢复——那不是它的职责。

再叠上第三章的完成判定，就是完整的控制面：**durable 引擎（续跑）+ OS 进程隔离（边界）+ 进程内 asyncio（并发）+ 任务完成判定（验收）。**

选型时沿着一条轴线滑动即可判断权重：**会话越长、副作用越贵、越依赖 human-in-the-loop 的长等待，就越往「OS 进程 + durable checkpoint」这一端靠；会话越短、越纯 I/O，纯 asyncio 就越划算。** 而无论落在轴的哪一端，「完成」都不该由会话自己说了算——就像进程的成败由退出码和验收决定一样，会话的成败，也应该交给会话之外的验收器来判定。

这正是操作系统四十年前就给出的答案：进程不可靠，所以有 supervisor；supervisor 也不可靠，所以有监督树；「完成」不由进程自己说，由退出码和验收说。把这套心智模型搬给 LLM 会话，就是这份调研想说的全部。

---

> 本文由两份内部调研报告整理润色而成：A 线《把 agent/LLM 会话当异步任务管理（Python 生态）》与 B 线《Agent 框架恢复能力与进程监督调研》。star 数为 2026-09 通过 GitHub API 实测的量级；机制结论综合自各项目官方文档与相关论文，个别维护状态参考第三方对比。
