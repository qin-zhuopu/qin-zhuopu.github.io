---
layout: post
title: "给不可靠的 LLM 会话写一个操作系统：我的外部 Agent 控制面"
date: 2026-09-14 05:05 +0800
categories: [AI, Agent]
tags: [agent-ops, supervisor, acp, claude-code, kiro, llm, watchdog]
---

## 引子：会话是不可靠的

过去两天，我在一台服务器上同时驱动着六到十条并行的 AI 会话流水线（Kiro 网页版、Kiro CLI、Claude Code 混编），让它们自主完成代码修复、测试补齐、Jenkins 排障、文档回填这类真实工程任务。跑下来唯一的确定结论是：**LLM 会话和进程一样不可靠，而大多数人对前者的容错投入接近于零。**

会话的故障模式，我实测遇到的至少有六种：

| 故障 | 真实案例 |
|---|---|
| API 报错 / 欠费 / 限流 | 会话中途模型直接停止响应，留下半截输出 |
| 上下文爆炸 / 压缩 | 长会话被自动压缩后丢失关键约束，行为回归 |
| hang 死 / 静默停摆 | 绿点还在转，30 分钟没有任何输出增量 |
| 失控循环 | 同一个失败操作反复重试，烧掉大量 credits |
| 假完成 | 会话写完成文件报捷，实际任务没做完——甚至把「阻塞」写进完成文件里 |
| 静默收工 | 重启次数达到上限后不吭声退出，无人察觉任务没完成 |

操作系统的答案早就有了：**进程不可靠，所以要有 supervisor；supervisor 也不可靠，所以要有监督树；「完成」不由进程自己说了算，由退出码和验收说了算。**

我把这套思路搬给了 AI 会话，用纯 Python 写了一个会话外的控制面（agent-ops），两天里从六条并行流水线的实战中迭代了十几轮。这篇文章把它完整讲清楚。

## 一、总体架构：OS 四层视图

```
┌─────────────────────────────────────────────┐
│ 策略层  任务书(mission) + steering + hook     │  ← 规定「怎么干活」
├─────────────────────────────────────────────┤
│ 监督层  monitor → supervisor → worker        │  ← 规定「死了怎么办」
├─────────────────────────────────────────────┤
│ 资源层  resreg 资源注册表 + worktree + 凭据   │  ← 规定「谁能用什么」
├─────────────────────────────────────────────┤
│ 状态层  ~/.local/state/kiro-ops/ 七种文件     │  ← 状态外置，重启不丢
└─────────────────────────────────────────────┘
```

### 策略层：让 agent 无处不在地知道纪律

- **任务书（mission）**：每次派发的书面任务契约，含目标、边界、资源、**完成信号条款**（必须写明什么算完成、完成文件叫什么）。
- **steering**（`shell-discipline.md`）：Kiro 每轮会话自动加载的纪律文件。R1-R8 条款：命令必须 `timeout 60` 前置、长任务必须 nohup+日志+哨兵文件、查进度先总量再增量、连续两轮无增量必须换策略、独占资源必须先 claim、遇登录滑块清自己的 profile 重试两次才准升级人工……
- **hook**（`pre-shell-timeout.sh`）：agent 每次 shell 调用前强制过一道闸——没有 `timeout` 或超时超过 60 秒直接 exit 2 阻断，并把完整规范回显到 stderr（防上下文压缩后规则丢失）。

三层防线的意义：hook 是硬约束（拦得住），steering 是软约束（看得见），任务书是契约（可验收）。agent 的上下文会被压缩，纪律必须放在会话之外。

### 监督层：三级监督树

```
monitor（每10min巡检，死亡重拉，夜间每线重启上限6次）
  └── supervisor（每20s查心跳，15min静默判死，杀进程树，resume续跑）
        └── worker（ACP驱动会话：心跳落盘、权限自动批、结果落盘）
              └── Kiro/Claude 会话（不可靠的执行体）
```

- **worker** 是一个 Python 进程，通过 stdio 上的 JSON-RPC（ACP 协议）驱动 Kiro CLI 会话：发任务书、收流式输出、维护心跳文件。Kiro 请求工具权限时自动批准（可配置），每轮 end_turn 事件落盘。
- **supervisor** 只做四件事：看心跳（20 秒一次）、判死（15 分钟无心跳/无输出增量）、杀（进程树整树清理）、续（`--resume` 拉起新 worker 接着跑）。**它不干活，也不懂任务内容。**
- **monitor** 监督 supervisor 本身——看门狗的看门狗问题在第二层解决：supervisor 死了按保留的 sessionid 重拉，上下文不丢。夜间模式给每条线设重启上限，防止 credit 失控（这就是 OTP 的 restart intensity）。

### 资源层：resreg，一个 50 行的轻量 CMDB

并行会话最容易互相踩踏：两个会话用同一个 Chrome profile、同一个 worktree、同一个端口。`resreg`（资源注册表）用 flock 保证原子性，claim/check/release/gc 四个子命令 + TTL 自动过期。纪律写进 steering：**独占资源用前必须 claim，即使它看起来空闲——因为你不知道别的线是不是正在来的路上。**

配合两件套：git worktree（同一仓库多线并行改代码互不干扰）+ 时间戳命名（产物只增不删，冒烟测试的容器、域名、报告全部带时间戳）。

### 状态层：会话外置，重启续命

`~/.local/state/kiro-ops/` 下七种文件：心跳、任务书、完成标记、resume 指令、会话注册（sessionid）、验证脚本、告警。**会话可以死，状态不能死。**最有价值的一条实战经验：让 agent 把进度事实源写成 git 里的文件（比如测试覆盖矩阵），每次重启后第一件事是读矩阵恢复现场——服务器半夜重启 /tmp 全丢，靠这个 2.5 分钟就恢复了全部上下文。

## 二、完成判定：这是整个系统最难的题

「怎么算完成」比「怎么重启」难得多。我们血泪迭代出了三层判据：

| 层 | 判据 | 可信度 | 事故来源 |
|---|---|---|---|
| L0 | 协议信号：turn 结束（end_turn / stopReason） | 必要但不充分 | 四条线曾顶着 40 轮上限静默收工 |
| L1 | 结构化自报：agent 写完成文件（状态+产物+证据） | 可作弊 | done 文件被当报告通道，「阻塞」也算完成；monitor 误判全部完成后集体退出 |
| **L2** | **客观验收：控制面自己跑真实测试套件，exit 0 才算完成** | **唯一可信** | 验收器上线后 agent 无法作弊 |

L2 的实现（`$BASE-verify.sh`）：supervisor 在 worker 每轮 end_turn 后**自己**执行验收脚本——跑测试、curl 断言、检查产物存在性——失败则把失败输出作为续跑指令回喂 agent：「你自称完成，但验收未通过，以下是失败详情，继续修。」这就是 TDD 语义：完成判据 = 可执行的测试，而不是 agent 的嘴。

后来做开源调研时发现这条路有人给出了数字：TDFlow 论文（arXiv 2510.23761）用「给定人写的测试、循环到全绿」的范式在 SWE-Bench Lite 上做到 88.8%，比次优基线高 27.8 个百分点。我们的教训换来了同一个结论：**agent 自报只是触发验收的信号，永远不是结论。**

配套设计：验收未过 ≠ 无限重试。supervisor 有重启上限（如 30 次），monitor 有夜间上限（每线 6 次），超限停线告警等人——这就是 OTP 的 restart intensity，防止「无限重启烧钱」。

## 三、会话接口面：9 个动词打天下

控制面和会话打交道，无论底下是 Kiro 网页版、Kiro CLI（ACP 协议）还是 Claude Code（Agent SDK），抽象出来就 9 个动词，像文件操作：

| 动词 | 类比 | Kiro ACP | Claude Agent SDK |
|---|---|---|---|
| LIST | readdir | 扫 `~/.kiro/sessions/` | `claude agents --json`（实时注册表） |
| META | stat | session.json | 注册表 + transcript（含 gitBranch/permissionMode） |
| CREATE | creat | session/new | query({prompt, cwd}) |
| ATTACH | open | session/load | --resume / resumeSessionAt（消息级） |
| READ | read | messages.jsonl | .jsonl transcript |
| SEND | write | session/prompt | query() / stdin 流 |
| RECEIVE | 读流 | session/update 通知 | async iterator / SSE |
| INTERRUPT | kill -INT | session/cancel | Query.interrupt() |
| FORK | fork() | —（load 接管） | --fork-session |

**真正的差异不在动词集合，在忙时语义**：

- Kiro ACP：turn 进行中插话直接被拒（"Prompt already in progress"）——不能排队不能插嘴，探活只能靠心跳。这就是为什么监督层靠心跳文件而不是靠「问一句」。
- Claude SDK：同进程 stdin 连续喂入=排队顺序执行；interrupt() 原生打断。
- 共同红线：跨进程同时接管同一会话 = 并发写同一个 transcript 文件，禁止。

长任务的最佳实践两引擎通用：**nohup 后台 + 哨兵文件 + 前台逐轮查哨兵**。让会话把长命令扔到后台立刻返回，控制面保持前台 turn 短平快，靠哨兵文件判断后台任务完成——这本质上是把「完成判定」从会话时间轴挪到了文件系统时间轴，文件系统才是控制面和会话共享的、可靠的记忆。

## 四、资源竞争：并发的前提三件套

多线并行实测踩出来的规矩：**worktree + resreg claim + 时间戳命名，缺一不可。**

- 同仓库多线改代码 → git worktree 各开目录，各占分支
- Chrome 登录态、调试端口、Jenkins job → resreg 先 claim 后使用
- 一切产物（仓库、容器、域名、报告）→ 时间戳命名，只增不删

有一次两条线同时 Jenkins 触发构建，靠的正是固定 job 天然排队（Jenkins job 串行）——资源冲突不一定都要发明新机制，识别出「哪些资源天然串行化」也是资源层设计的一部分。

## 五、踩过的坑（事故录精选）

1. **pkill 自匹配三次**：清理进程时模式串出现在同一命令行任何位置都会自杀。最终形态：清场一律 environ 定向扫描 + kill PID。
2. **rm glob 误删任务书**：`rm -f /tmp/xxx-*` 把刚写完的任务书一起删了，会话首启失败。清理必须用精确文件名，且放在写文件之前。
3. **done 文件信任危机**：agent 把 done 文件当报告通道，写「阻塞」也算完成。→ 完成文件降级为可选信号，验收器为准。
4. **MAX_LAUNCHES 静默收工**：40 轮上限耗尽后 supervisor 不吭声退出，四条线无声死亡。→ 每份任务书必须有完成信号条款；战果要直接查 git/产物，不信 supervisor 日志。
5. **checkpoint 静默损坏**（开源界同款坑）：序列化器遇未知类型静默丢状态，恢复后 bug 级联多步才暴露。→ 事实源文件要能被 schema 校验，最好进 git。
6. **浏览器驱动的暗坑**：React 受控组件必须用原生 value setter + input 事件；按钮点击在切会话后可能因 React 状态未同步而无效，Enter 键盘事件兜底；composer 清空是异步的，单次读取会把「已发出」误判为失败，要轮询；页面上有多个可见 textarea（有个恒为 "x" 的幽灵），必须按占位符定位；CLI 包装下 IIFE 必须显式 return。
7. **会话自动改名**：Kiro 会按内容给会话起英文名，按名字关键词找会话会失联。→ 派完立刻记录 session id，别信名字。

## 六、开源世界的互相印证

写完自己的版本再去调研开源，发现六条核心设计全部有对应的成熟实践（详见我的调研笔记）：

1. **状态外置 + checkpoint 续跑**：LangGraph checkpointer（Memory/Postgres/Redis 多后端）、Temporal durable execution（Event History 重放）、DBOS（一个 Postgres 起步）。我们的「矩阵文件进 git」是穷人版，方向完全一致。
2. **恢复与干活分离、分层**：OTP supervisor tree 的本义——「如何恢复」是独立关注点，由独立进程持有，排成层级。Vega 项目已把 Erlang 监督模型直接搬到 agent。
3. **完成判定用外部客观信号**：TDFlow / Otter / verification-gated loop。这是全场共识度最高的一条。
4. **结构化 verdict + 校验失败打回**：instructor（Pydantic re-ask）、guardrails（validators 链）。
5. **确定性规则优先、LLM 兜底**：autosentry——已知失败模式用确定性规则秒级恢复，不确定才升级 LLM/人。我们 hook 拦截 + steering 规范就是这个思路。
6. **restart intensity 上限**：OTP 原生概念，防无限重启。夜间 monitor 的每线上限就是它的实现。

同时别人也踩过我们没踩的坑，最值得记住的一条：**durable execution 恢复时会重放步骤，有副作用的 tool 调用（写文件、发请求、扣费）必须幂等**，否则重启=重复执行。

## 七、路线图

- ✅ 手术①：状态从 /tmp 迁移到 `~/.local/state/kiro-ops/`（防宿主重启丢失）
- ✅ 手术②：验收器从单线特权变成全员标配（done 降级为可选信号）
- 🔄 手术③：opsctl 统一操作入口（status/start/stop/answer + 安全清场内置）
- 🔄 手术④：问答回路（$BASE-question/answer 信箱，agent 提问不再石沉大海）
- ❌ 手术⑤：meta-supervisor 监督树——评审后不采用，monitor 的 20s 巡检已覆盖，避免冗余监控层

## 结语

一句话哲学：**「完成」由可执行的验收定义，不由 agent 的嘴定义；「恢复」由会话外的代码持有，不由会话的自觉保证。**

LLM 会话就是一个便宜的、不可靠的、但执行力惊人的进程。对它的正确态度不是信任，也不是不信任，而是像操作系统对待进程一样：给它纪律（hook/steering），给它资源（resreg），给它监督（supervisor tree），给它验收（verification），然后放手让它跑。

完整脚本与任务书归档在 [qin-zhuopu/agent-ops](https://github.com/qin-zhuopu/agent-ops)（私有仓库）。
