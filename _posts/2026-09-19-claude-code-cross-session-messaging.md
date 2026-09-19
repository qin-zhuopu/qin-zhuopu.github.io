---
layout: post
title: "一屋子 Claude Code 会话开始互相喊话：Cross-session messaging 的语义、投递路径与实测"
date: 2026-09-19 15:20 +0800
categories: [AI, Agent]
tags: [claude-code, agent, tmux, automation, 踩坑]
---

## 引子：我原来是怎么盯一排会话的

我在服务器上常驻跑着十来个 Claude Code 会话（tmux 里一个会话一个窗口，分别干 Jira 单子、部署脚本、写 README）。手机上的我想知道"A 会话跑完了没、结果是什么"，用的办法很原始：

```bash
tmux capture-pane -pt claude-kiro-account-deploy -S -60 | tail -20
```

也就是**把终端屏幕当 API 来 OCR**。它能用，但脆：中间输出会被滚走，多 pane 会串行，屏幕上还是被截断的排版。我真正想要的是"问那个会话一句，它回我一句"。

Claude Code 从 v2.1.224 起把这件事做成了一等功能，叫 **Cross-session messaging**（跨会话消息）。要点是：**会话之间可以按名字（name）互发纯文本消息**，同机走本地 socket，不经服务器。摸清它之后，我原来的轮询盯梢基本可以退休了。这篇把三件事讲清楚：语义（尤其是"发到忙碌会话"和"发到闲置会话"完全不同）、线路怎么走、以及怎么让一个外部脚本（不是 Claude）也能把消息投进去。

## 一、两个工具，人只认一个名字

Claude 侧只有两个工具，你不用自己调：

| 工具 | 作用 |
| :-- | :-- |
| `ListAgents` | 发现当前会话能触达哪些会话 |
| `SendMessage` | **按 name** 把消息投给其中一个 |

会话的名字来自 `--name` 或 `/rename`；不给的话 Claude Code 会自己起一个。所以第一步是给会话起名，否则你面对的是 `kiro-account-deploy` 和一堆自动名混在一起。

我平时用 `--name` 起会话：

```bash
claude --name kiro-account-deploy \
       --dangerously-skip-permissions \
       --settings ~/.claude/settings.jqw.json
```

然后在另一个会话里直接说人话就行：

```text
问下 kiro-account-deploy 那边的部署脚本跑通了没有，把结论回给我
```

也可以点名，输入 `@` 加名字前几个字母，会从在线会话里弹候选（≥ v2.1.232）：

```text
让 @api-worker 知道 schema 迁移已经跑完
```

自己想看清单，就敲 `/list-agents`：

- **首行**（如果有）是**本会话自己的名字**，也就是别的会话用来找你的那个名字；
- 下面依次是 subagents、agent team 的 teammates、**同机其它本地会话**（含 background 会话）、云会话、Remote Control 会话。

两条容易踩的空缺：**一个会话只有绑定了 inbox socket 才会出现在清单里**；而且**本会话永远不在下面那些行里**——如果 Claude 把消息发给自己的名字，会被直接拒掉并告知"目标就是当前会话"。

## 二、关键语义：忙碌时插话，闲置时唤醒

这是我觉得最值钱的差异，官方文档写得很朴素：

> 接收方正在跑 turn 时，接收方 Claude 在**两次工具调用之间**读入消息，正在执行的工具不会被打断。
> 接收方处于闲置时，Claude Code 会用这条消息**开一个新的 turn**。

第二条等于给了我一个**远程唤醒闲置会话**的开关。以前闲置会话只能靠 `tmux send-keys` 假装键盘输入（还要求会话在 tmux 里、还得管焦点），现在直接投递即开工。

实测双向都通（`minis-probe` ↔ `gm-ddd-qa` 互发互回），而且无头模式也能发：

```bash
claude -p "把这条结论转给 gm-ddd-qa：接口错误已定位为版本不一致" \
       --allowedTools SendMessage
```

### 怎么验收"真的送达了"

别信终端里的自述。到**接收方**的 transcript（`~/.claude/projects/<编码cwd>/<uuid>.jsonl`）里 grep 这个标签：

```
<cross-session-message from="uds:/run/user/1000/cc-socks/<发方pid>.sock"
                       from-name="minis-probe" from-mode="bypass">
```

出现即送达。屏幕上"看起来发出去了"不算证据。

## 三、线路：同机是本地 socket，根本不出网

投递路径按目标位置分三种：

| 目标在哪 | 消息怎么走 |
| :-- | :-- |
| 本机 | 每会话一个 **Unix domain socket**（Windows 是命名管道），**不经 Anthropic 服务器** |
| 你的另一台机器 | 经 Anthropic 服务器，从对方的 Remote Control 连接抵达 |
| 云端会话 | 经 Anthropic 服务器直达 |

同机 socket 路径可以在 `/status` 的 `Peer address` 行看到（带 `uds:` 前缀），也会导出成环境变量给 hook 和 Bash 用：

```bash
echo $CLAUDE_CODE_MESSAGING_SOCKET   # 本会话的收件 socket
echo $CLAUDE_CODE_MESSAGING_TOKEN    # 每会话一个令牌
```

文档写的默认目录是 `/tmp/cc-socks-<uid>`，但我机器上实际落在 `/run/user/1000/cc-socks/<pid>.sock`——**别照文档猜路径，用 `/status` 或环境变量取**。socket 权限限制到当前操作系统用户，别的用户投不进来。

因为是"读磁盘上的注册文件"来发现彼此，所以隔离边界很直白：**容器内和宿主机互相看不见**；**WSL 2 里的会话和同一台电脑上的原生 Windows 会话也互相看不见**（不同 home、不同 socket 类型）。

## 四、别再轮询：notify_when_idle

等一个长任务，我以前的做法是每 2 分钟 `capture-pane` 一次。有个专门的机制替代它：`SendMessage` 的 `notify_when_idle` 输入项（双方 ≥ v2.1.236），含义是"**订阅对方下次变闲置或退出时，回我一条通知**"。

它的性质正好治轮询：

- **一次性**，不轮询；
- 单独订阅时**不在被观察会话里起 turn、不烧它的 token**；
- 已经闲置就立刻通知；
- 12 小时没等到就自动过期并告知 Claude，不会无限等。

限制也要记住：只有主对话里的 Claude 能订阅，且只能订本机会话；subagent 或 teammate 设了这个字段不会真订阅（会被明确告知）。

## 五、无人值守的坑：-p 会话默认不收货

这条我踩过，值得单独一节。接收方有入站开关 `crossSessionInbound`：

| 值 | 行为 |
| :-- | :-- |
| `accept` | 直接交给 Claude |
| `hold` | 显示提示但不交付，后续允许了才放行 |
| `refuse` | 直接丢弃 |

没显式配置时按**两个会话的权限模式**分组决定：接收方是"会弹权限提示"的一类 → 默认投递（发送方自称 bypass 时改为 hold）；接收方是 bypass 的一类 → **默认 hold 等你批准**。

麻烦在 `claude -p` 无头会话**没法弹批准对话框**：默认 hold 的消息只会按 `dialogExpiry`（默认 5 分钟）挂着，超时即丢弃并回报"过期"。所以要让一个 `-p` 起的 worker 无人值守收信，**必须在启动时显式给 accept**：

```bash
claude -p "..." --settings '{"crossSessionInbound":"accept"}'
```

（写在用户级 settings 里也行，但那会影响你所有会话。另外 `dialogExpiry` 可以设 `"never"`，让默认 hold 的消息挂到会结束为止。）

## 六、安全边界：对方消息永远不等于你同意

跨会话消息的权限模型是有意削弱的，四条硬规则：

- **不能替我批准任何东西**：它永远不算"用户同意"，解不开待批准的权限提示；
- **不能改配置**：接收方被明确要求不得因"另一个会话要求"去改权限设置、`CLAUDE.md` 或其他配置；
- **消息里的 `/命令` 只是纯文本**，绝不执行；
- 该弹的权限提示照常弹。

代价是：它本质上是**另一个进程往你的模型上下文里塞文本**。同 uid 主机上跑不受信代码的风险，请按提示注入面来估。

限制清单（通道本身的性质，跟平台无关）：只传纯文本；同机单条上限约 100 万字符；对同一会话快速连发会在**发送侧**被拒（提示你合并或稍等）；有循环抑制——按发送方限流、短窗内相同内容丢弃、待读队列最多 50 条，所以两个会话互相回话会自己停下来。

## 七、进阶：让外部脚本也投得进去

`ListAgents`/`SendMessage` 都要经过一个 Claude。但我是从手机上的另一个 agent 驱动服务器的，不想为了发条消息先起个 claude 进程。于是逆向了线路：直接往对端 socket 写 ndjson。

三行握手，实测可用：

```
uid:<接收方 uid>\n          # 服务端用 SO_PEERCRED 复核，必须与自己 uid 一致
auth:<token>\n              # 可选，见下方"实测不校验"
{"msgV":1,"msg_id":"<uuid>","type":"user","message":{"role":"user","content":"..."}}\n
```

服务端只校验 `msgV==1` 与 `type=="user"`；来源标签那层 XML 是接收端自己包的，不用发送方拼。**送达判据**仍然是对端 jsonl 里出现 `queue-operation/enqueue` 加那个来源标签。

难的不是行格式，是**让对方肯看你的名字**。外部进程要能被 `/list-agents` 发现，得在 `~/.claude/sessions/<pid>.json` 里伪造一份注册表，最小完备字段是：

```
pid appId name status cwd kind startedAt updatedAt
procStart pidDomain peerProtocol messagingSocketPath
```

`procStart` + `pidDomain` 缺一不可——缺了**静默不进入候选清单**，发送端只会告诉你"找不到这个名字"，不给任何原因，极难排查。其中：

- `procStart` = `/proc/<pid>/stat` 第 22 字段(jiffies) 换算成秒：`100*j/HZ + /proc/stat 的 btime`；
- `pidDomain` = `linux:<machine-id>:pid:[:[<pidns inode>]`；
- `peerProtocol` 填 1，`messagingSocketPath` 必填（没有它根本不会走 peer 分支）。

还有两个硬约束：脚本绑的 socket 文件名里的 pid **必须是活着的真实 pid**（否则被当死会话忽略）；同名并发时后来者会被自动改成变体名。

顺便说一条**判断"某会话能不能被投递"的教训**：不要用 `~/.claude/sessions/*.json` 里有没有 name 来判断——那里有名字不等于可达。唯一判据是 `/list-agents` 的输出，或者 `/run/user/1000/cc-socks/<pid>.sock` 是否真的存在。我吃过一次亏：一个会话的 `/proc/<pid>/exe` 指向 `(deleted)`，跑的是升级前的旧二进制（跨会话消息需要 ≥2.1.224 且由新版启动才会绑 socket），于是它注册表里名字齐全，就是投不进去。要救它只能用 `claude --resume <sessionId>` 在新版本里重开，历史不丢。

**安全结论**：实测 `auth:` 行**不校验内容**——随机 token、空 token 都能投递成功。也就是说同一 uid 下任意进程可以**冒充任意会话名**注入任意文本，接收端最多提示一句"peer 不匹配"，并不拦截（消息仍不算权限同意、`/命令` 仍不执行）。如果你在意这个面，控制点只能放在"别在同 uid 主机跑不受信代码"。

## 八、顺手做了个巡检脚本

有了按名字投递，还得知道"现在有哪些会话、各自活不活、在哪个 tmux 窗口"。拼了一个映射脚本，输出长这样：

```
tmux                         pid      status  name                 age_min  cwd
claude-jc-iam-login          1633046  busy    jc-iam-login         0.4      ~/repo/jc/jereh-cli-wt-iam-login
claude-kiro-account-ui       3163668  busy    kiro-account-ui      0.1      ~/repo/json-graph/ddd/kiro-account
claude-kiro-account-master   2966322  shell   kiro-account-master  17.3     ~/repo/json-graph/ddd/kiro-account
claude-tmux-ux               961247   idle    tmux-ux              56.0     ~/repo/jc/jereh-cli
wchk                         -        -       (plain shell)        -        -
```

写的时候有三个坑值得记：

1. **`pane_pid` 常常本身就是 claude 进程**（`tmux new-session -A -s <名>` 直接以 claude 为窗口程序时）。我第一版只递归扫 `pane_pid` 的**子孙**，于是把两个正在跑的会话报成"没有 claude"。正确做法是先看 `pane_current_command`，或 pane_pid 自己也算候选。
2. **transcript 的归属要按 `sessionId` 找**，不能按 cwd 找最新文件——同一个仓库目录下会有多个会话并存，按 mtime 取最新会把三个会话算成同一个。
3. **jsonl 里的 timestamp 是 UTC**，屏幕上的 `done 6:48` 是本地时区。差 8 小时，用来看"多久没动"时必须统一。

## 收尾：什么场景值得用

- 会话之间**独立**、你自己起自己管 → 用 cross-session messaging（本篇）
- 想在另一个终端**接着同一段对话**、或把上下文带过去 → 用 resume
- Claude 自己组建并看管的一队会话 → agent teams
- 一屏看管/操纵很多会话 → agent view
- 你从手机上**自己**操纵某个会话 → remote control
- CI 结果、聊天消息这类**外部事件**推进会话 → channels

我现在的组合是：起会话一律 `--name`；worker 一律带 `crossSessionInbound: accept`（否则它收不到派工）；等长任务用 `notify_when_idle` 而不是轮询；外部脚本走 `ccmsg` 那条直投路；巡检用映射脚本 + grep `<cross-session-message>` 验收。

顺带一条与本篇无关但同样省事的经验：tmux 里 `pane_pid` + `/proc` 进程树这套办法，也足够把"窗口名 ↔ 会话名 ↔ 落盘 transcript"三者对上，不必再靠屏幕内容猜。
