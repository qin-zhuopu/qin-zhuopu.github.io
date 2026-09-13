---
layout: post
title: "把 Kiro CLI 变成可看管的「数字员工」：ACP 协议的两个关键语义与一套看门狗架构"
date: 2026-09-13 15:30:00 +0800
categories: AI 工程
tags: [ACP, Kiro, AI-Agent, 自动化, Python]
---

想让 AI 编码代理自己跑几个小时的长活（比如"照着 PRD 把整个产品的测试驱动开发做完"），最怕的不是它干不动，而是**它悄悄挂掉没人知道**。这篇记录我把 Kiro CLI 接入 ACP 协议、用脚本搭控制面的全过程：先摸清协议的两个关键语义（turn 并发、后台工具调用），再据此设计"心跳看门狗 + 断点续跑"架构。全部结论都经过实测。

## 背景：我要什么样的控制面

目标架构很简单：

```
我（手机上的 AI 助手）
   │ ssh
   ▼
GB10 服务器上的控制面脚本（supervisor 看门狗）
   │ ACP 协议（JSON-RPC over stdio，ndjson）
   ▼
Kiro CLI（agent 引擎，干活的"数字员工"）
   │ 工具调用
   ▼
代码仓库 / 构建 / 测试
```

Kiro CLI 自带 `acp` 子命令（Agent Client Protocol，Zed 编辑器牵头的标准），stdio 上跑 ndjson JSON-RPC 2.0。握手流程：

```
initialize (protocolVersion: 1)
  → session/new (cwd, mcpServers)
  → session/prompt (prompt: [{type:"text", text}])
  → 流式收 session/update 通知（agent_message_chunk / tool_call / …）
  → 最终响应 result.stopReason = "end_turn"
```

也就是说，**控制面就是一个普通 Python 脚本**：spawn `kiro acp`，往 stdin 写 JSON 行，从 stdout 读 JSON 行。没有 HTTP 服务、没有 SDK 依赖。

## 先踩三个环境坑

**坑 1：代理包装。** `~/.local/bin/kiro` 是个 bash 包装脚本，设了 `HTTP(S)_PROXY` 后再 `exec kiro-cli`。直接调裸的 `kiro-cli`：模型列表少一半（19 个变 8 个，整个 Claude 家族都不见了），v3 引擎报 `InvalidModelError`。**规则：一切 Kiro 命令必须走 `kiro` 包装，包括脚本里 spawn 的 `acp`。**

**坑 2：引擎代数。** `--agent-engine v1/v2/v3`（默认 v2）是 Kiro 内部引擎的代数，不是 ACP 协议版本（线协议恒为 `protocolVersion: 1`）。实测三引擎差异：

| | v1/v2 | v3 |
|---|---|---|
| 认证 | 免认证 | 要 `--auth-method cli` |
| sessionId | 裸 UUID | `sess_` 前缀 |
| 模式 | kiro_default/planner/guide | vibe/spec/bug-fix/plan/autonomous… |
| update 流 | 只有文本块 | 还有 tool_call / session_info / steering 等 |
| 不支持 | — | `-a/--trust-all-tools`（传了直接拒启！） |

**坑 3：会话单向兼容。** v3 引擎能 `session/load` 加载 v2 的会话（向下兼容读两种存储），v2 引擎完全看不见 v3 会话。**升级单行道，没有回头路。**

另外 v3 显式传 `--model auto` 会拒启——不传参数才等于 auto。这个和直觉相反。

## 实验 1：turn 进行中能不能插话？——不能

设计这个实验，是因为我需要知道：**任务静默时，能不能通过 ACP"喊它一声"来探活？**

方法：让 Kiro 前台跑 `sleep 25`，第 8 秒往同一个会话插第二条 prompt。

结果干脆利落：

```json
{"code": -32603, "message": "Internal error", "data": "Prompt already in progress"}
```

**一个会话同一时刻只接受一个 prompt。** turn 进行中（包括卡死僵住的 turn）再发新指令会被直接拒绝。这意味着：

- 静默期探活**不能靠插话**，只能靠外部观测——这就是后面心跳看门狗的存在理由；
- "发个 ping 看它响不响"这种自然的探活方案，在 ACP 的会话语义下走不通。

## 实验 2：后台工具调用 + 前台对话——完全可行

第二个问题：Kiro 能不能把任务丢到后台跑，前台继续跟我对话？

方法：让它启动 `nohup bash -c 'sleep 40; date > /tmp/kiro-bg-sleep-done' >/dev/null 2>&1 &` 并立即回复，然后我在宿主机上验证进程、同时继续跟它聊天。

结果四个全绿：

| 步骤 | 结果 |
|---|---|
| 启动后台任务并立即回复 | 回复"已启动"，**耗时 0.0 秒**，turn 正常 end_turn |
| 宿主机查进程 | `sleep 40` 真实存在（独立 PID）✅ |
| 后台任务运行中，前台问"1+1=？" | 秒答"2"，对话能力完好 ✅ |
| 40 秒后查完成标记文件 | 存在，时间戳正确——任务独立跑完了 ✅ |

## 由实验推出的最佳实践

两个实验合起来，长任务的标准姿势就定了：

```
短平快 turn 循环：
  1. "用 nohup 启动 XX，完成时写哨兵文件 /tmp/xx.done，启动完立即回复"
     → 秒回 end_turn，无长静默
  2. "查哨兵文件。没好就等 60 秒再查；好了就基于结果继续"
     → 每轮都是短 turn
  3. 需要限时的话，nohup 里套 timeout：nohup timeout 900 命令 …
```

前台 turn 永远短平快，心跳几乎不会长静默，看门狗误判率大幅下降。辅以硬约束：所有命令带 `timeout` 前缀（检查类 600s、构建类 900s）、禁止交互式命令、跑不起来的测试 `it.skip` 注明原因。

## 控制面架构：worker + supervisor 看门狗

```
supervisor.py（nohup 脱离会话，独立存活）
 ├─ 等待前序任务清场（pgrep 轮询 + 超时强杀）
 ├─ 写任务书 /tmp/kiro-tdd-mission.txt
 └─ 循环：
     ├─ 启动 worker.py（带 prompt）
     ├─ 每 20s 检查心跳文件 mtime
     │    └─ 静默 > 15 分钟 → 判定挂死 → kill worker + acp 进程树
     ├─ worker 退出后读结果文件：
     │    ├─ end_turn + 完成标记文件 → ✅ 收工
     │    ├─ end_turn 无完成标记 → 下一轮续跑（不占重启额度）
     │    └─ error/timeout/挂死 → 冷却 30s → 重启续跑
     └─ 上限：40 轮 / 30 次重启，防无限烧钱
```

几个设计要点：

**心跳 = touch 文件。** worker 每收到一条 ACP 消息（任何 update、通知、权限请求）就 `os.utime` 一下心跳文件。supervisor 只看 mtime，零耦合。这和"看会话目录文件的更新时间"是同一个原理，但心跳粒度更细、判定更及时。

**续跑 = 会话持久化 + 磁盘事实源。** worker 每次启动都 `session/load` 恢复同一个会话（对话上下文还在），再发"继续"指令。更关键的是，任务书里规定 **进度矩阵文件是唯一事实源**（比如 PRD-测试覆盖矩阵），Kiro 每完成一批就写盘。就算会话上下文丢了，读文件就能恢复现场——"重启后绝不从头重来"。

**权限自动批准。** v3 引擎每个工具调用都发 `session/request_permission` 请求（这是 JSON-RPC **请求**，必须应答，否则任务就卡在"等授权"——我们第一个任务就是这么挂的）。worker 里对每个请求自动选 `allow_always` 选项应答。

**完成信号 = 哨兵文件。** 任务书最后一步：全绿且推送成功后写 `/tmp/kiro-tdd-done`。supervisor 看到它就退出。用文件而不是"Kiro 说做完了"，避免幻觉性完工。

## 踩坑清单（都是真金白银的时间）

1. **pkill 自匹配**：`pkill -f xxx_driver` 会匹配到包含该字符串的当前 shell 命令行，把自己杀掉，SSH 莫名断开。用 `pkill -f "^python3 /tmp/xxx"` 锚定开头。
2. **v3 不支持 `-a`**：argparse 直接拒启，进程秒退，表现为 initialize 超时——先怀疑参数组合。
3. **脚本在远程跑时不能用本机 SSH 别名**：脚本内部 `ssh gb10` 会失败，别名只存在于我的客户端；远程脚本里该用本地命令。
4. **长字符串转义**：复杂的任务书文本经 SSH 传 Python 再传 JSON，裸写必炸；先 `file_write` 落地再管道执行。
5. **显式 `--model auto` 拒启**：默认值不能显式传，同样表现为进程秒退。

## 现状

这套控制面正在跑一个真实任务：以 `docs/prd/` 的产品 PRD 为唯一需求源，建立端到端覆盖矩阵，补全测试，失败项分类处理（未开发→开发、bug→修、回归→修），全绿后提交推送——相当于把"测试驱动开发"整条链路交给一个有看门狗看着的数字员工。

可控、可续、可观测。挂了会自己爬起来，做完了会留一张字条。

## 附：核心脚本

- `worker.py`：ACP 客户端。initialize → session/load → prompt，权限自动批准，心跳 touch，结果落盘
- `supervisor.py`：看门狗循环。心跳巡检、挂死重启、完成检测、额度上限

两个脚本加起来不到 300 行 Python，没有第三方依赖。
