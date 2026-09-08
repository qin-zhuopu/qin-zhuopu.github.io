---
layout: post
title: "nb api workflow：命令行看工作流全貌与执行记录"
date: 2026-09-09 16:00:00 +0800
categories: [NocoBase]
tags: [nocobase, cli, nb-api, workflow]
---

NocoBase 的工作流在 UI 里编辑很直观，但排查「这个流程最近跑成什么样」「为什么没触发」时，命令行一把列出所有工作流和执行记录更高效。这篇记 `nb api workflow` 的实测。

## 命令用途

- `workflows`：工作流的 create / get / list / destroy
- `executions`：执行记录（每次触发产生一条）
- `flow-nodes`：流程里的节点配置
- `jobs`：节点级的执行结果
- `user-workflow-tasks`：人工任务（待办/审批类）

## 语法与常用参数

```bash
# 列出全部工作流
nb api workflow workflows list

# 创建一个 schedule 类型的工作流
nb api workflow workflows create \
  --title "每日巡检" --type schedule --config '{"mode":1}'

# 查看 / 删除
nb api workflow workflows get --filter-by-tk <id>
nb api workflow workflows destroy --filter-by-tk <id>

# 执行记录与节点结果
nb api workflow executions list
nb api workflow flow-nodes list
nb api workflow jobs list
```

## 实测效果

`workflows list` 在实例上返回了 20 个工作流（Recalc payment status、Quotation approval 之类，都来自各业务 Portal），每条带 `enabled` 状态，一眼能看出哪些流程是活的。

新建一个 schedule 工作流：

```bash
$ nb api workflow workflows create \
    --title "daily-demo" --type schedule --config '{"mode":1}'
{
  "data": {
    "id": 385625325109248,
    "title": "daily-demo",
    "type": "schedule",
    "config": { "mode": 1 },
    "enabled": false
  }
}
```

注意 `enabled: false`——**新建的工作流默认是停用的**。删除返回删除条数：

```bash
$ nb api workflow workflows destroy --filter-by-tk 385625325109248
{"data": 1}
```

`executions list` 返回 20 条执行记录，每条带工作流引用、触发时间与执行状态，是排查失败流程的第一现场。

## 踩坑点

**1. 创建后默认停用。** `enabled: false` 是刻意的安全默认——防止一个刚建好、节点还没配完的流程被意外触发。要启用得显式 update，或去 UI 里开。这也是「为什么我的工作流一直不跑」的最常见答案。

**2. `--filter-by-tk` 传的是工作流 ID。** 这里是雪花整数（如 `385625325109248`），不是 title。

**3. `--config` 的结构因 type 而异。** `schedule` 的 `{"mode":1}` 和 `collection`（事件触发）的 config 字段完全不同，写之前最好在一个现成工作流上 `get` 一下同类型的 config 作参照。

**4. 共享实例上别乱 create/destroy。** 实测我是建了就删、拿到结论就收手；生产实例上建议只做 list / get / executions 这类只读操作。

## 什么时候用

- 巡检：`workflows list` 看有没有意外停用的关键流程，`executions list` 看最近失败
- 排查「流程没触发」：先看 enabled，再看 executions 里有没有记录，有记录再下钻 jobs 看哪个节点挂了
- 脚本化生成测试流程（建 → 验证 → 删）三连

排查链路推荐固定下来：`workflows list`（enabled?）→ `executions list`（跑过没?）→ `jobs list`（哪一步挂?）→ `flow-nodes get`（配置对不对?）。四步下来绝大多数工作流问题都能定位。
