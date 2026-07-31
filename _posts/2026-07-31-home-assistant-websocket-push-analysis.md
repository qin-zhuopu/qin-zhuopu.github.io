---
layout: post
title: "Home Assistant 实体的「数据库行数」≠「事件次数」：以海尔 WebSocket 为例"
date: 2026-07-31 08:35:00 +0800
categories: Home-Assistant
series: haier-series
---

接入海尔空调之后，我看数据库里 `climate.bei_wo_shi_kong_diao_climate` 这一个实体就有 17 行 WS 推送记录，差点以为云端每分钟都在推。深入分析之后才发现：

> **数据库行数 ≠ 推送次数**。一次 WS 推送会同时刷新整台设备的所有 attribute（约 33 个实体），所以 17 次推送 ≈ 1000 行数据库记录。

这篇文章用真实数据拆解这个误区。

## 误区的产生

接入集成半小时后，我查数据库：

```sh
sqlite3 config/home-assistant_v2.db "
SELECT COUNT(*) FROM states s
JOIN states_meta e ON s.metadata_id=e.metadata_id
WHERE e.entity_id LIKE '%bei_wo%' AND e.entity_id NOT LIKE '%polled%';
"
```

返回 **1009 行**。

第一反应：**WS 这么频繁？半小时推 1000 多次？**

但这和我之前对 WebSocket 的理解不符——WS 应该是事件驱动的，不应该这么频繁地推。

## 把每次推送拆出来

关键 SQL：用 `DISTINCT last_updated_ts` 把同一秒的所有行合并成一个事件：

```sql
SELECT COUNT(DISTINCT last_updated_ts) AS push_events
FROM states s
JOIN states_meta e ON s.metadata_id = e.metadata_id
WHERE e.entity_id LIKE '%bei_wo%' AND e.entity_id NOT LIKE '%polled%';
```

返回 **17**。

所以这半小时 WS **只推送了 17 次**。1009 行 ÷ 17 次 ≈ 60 行/次——也就是说每次推送会同时刷新大约 60 个实体（北卧室空调有 33 个 attribute，加上重连时的 unavailable 切换等）。

## 这 17 次推送都是什么

把这 17 个时间戳列出来看：

```
03:53:17  WS 首次连接
03:53:19  首次快照推送
04:04:10  WS 断开
04:04:23  重连中
04:04:24  重连成功
04:06:06  WS 断开
04:06:15  重连中
04:06:16  重连成功
04:09:37  WS 断开
04:09:48  重连中
04:09:49  重连成功
04:22:45  HA 重启
04:22:57  HA 重启后
04:24:31  WS 重连+真实变化(室温 25.5 → 26.0)
04:25:44  HA 重启
04:25:54  HA 重启后
04:25:55  WS 重连
```

按类别分：

| 类别 | 次数 | 说明 |
|---|---|---|
| WS 首次连接 | 1 | 集成刚启动时 |
| WS 断开 → 重连 | 6 组（12 次） | 每组 = 1 次 unavailable + 1 次重连快照 |
| HA 重启触发 | 3 次 | 重启后重新建立 WS |
| **真实状态变化** | **1 次** | 室温 25.5°C → 26.0°C |

**真正有意义的推送只有 1 次**。其余 16 次都是连接生命周期事件。

## WS 在空调关机时的硬证据

为了验证"关机时 WS 不推"，我把空调关掉，HA 重启后观察 30 分钟：

```sh
grep 'Received websocket data' config/home-assistant.log | head -3
```

输出：

```
05:00:33  Received websocket data: {"topic": "HeartBeatAck", ...}
05:01:33  Received websocket data: {"topic": "HeartBeatAck", ...}
05:02:33  Received websocket data: {"topic": "HeartBeatAck", ...}
```

统计：

| 消息类型 | 数量 |
|---|---|
| HeartBeatAck（心跳响应） | 33 |
| **真实数据推送** | **0** |

空调关机时，云端**完全不推数据**，只发心跳保活。每分钟一次的心跳不会被实体接收，所以数据库也没新行。

## 这个认知误区的危害

如果不理解"行数 ≠ 事件次数"，会出现两种错误判断：

### 错误 1：以为 WS 推送很频繁

看到 1000 行数据库记录，以为 WS 每分钟推几十次。**实际上一小时可能就推 5 次**。

### 错误 2：以为 polling 没工作

加了 60 秒 polling 之后，数据库 30 分钟只增加 1 行。第一反应是"polling 没跑"。

**实际上 polling 跑了 30 次**（看日志），只是值没变 Recorder 不写。

## WS 推送频率的本质

WS 是**事件驱动**，不是定时推送。触发条件：

- 设备开关机、模式切换、温度设定 → 立即推送
- 设备状态稳定 → **不推送**
- 设备关机 → **几乎不推送**（只有心跳）
- WS 断开/重连 → 推送一次全量快照
- HA 重启 → 重新建立 WS，推一次全量快照

**这是 polling 必须存在的根本原因**：关机时只有主动拉才能拿到室温。

## 算法验证

回到最初的算式：

```
数据库行数 = WS 推送次数 × 单次推送的实体数
```

举例（北卧室空调）：

- 集成启动时，实体从 unavailable → 真实值：33 行
- WS 断开：33 行（所有实体 → unavailable）
- WS 重连快照：33 行（所有实体 → 真实值）
- HA 重启一次：约 66 行（一次 unavailable + 一次重连快照）

半小时里：

- 1 次首次连接 ≈ 33 行
- 6 次断开重连 ≈ 6 × 66 = 396 行
- 3 次 HA 重启 ≈ 3 × 66 = 198 行
- 1 次真实变化 ≈ 33 行

合计 ≈ 660 行。实际 1009 行包含了一些边缘情况（unavailable 状态、attribute 变化等）。**数量级完全对得上**。

## 怎么避免这种误判

### 1. 用 `COUNT(DISTINCT timestamp)` 而不是 `COUNT(*)`

```sql
-- 错误:把每行当一个事件
SELECT COUNT(*) FROM states WHERE entity_id = '...';

-- 正确:同一秒的所有行合并成一个事件
SELECT COUNT(DISTINCT last_updated_ts) FROM states WHERE entity_id = '...';
```

### 2. 看日志，不只看数据库

```sh
grep 'Received websocket data' config/home-assistant.log | wc -l
```

日志里每次 WS 收到消息都有一条，**这是真实的事件次数**。

### 3. 区分"事件"和"行"

每次事件 = N 个实体的状态变化 = N 行数据库记录。**N 等于一台设备的 attribute 数量**（海尔空调 25~33 个）。

## 总结

| 概念 | 含义 |
|---|---|
| **事件次数** | WS 真实推送了几次 / polling 真实跑了几次 |
| **数据库行数** | 实体状态变化的次数（每实体一行） |
| **关系** | 数据库行数 ≈ 事件次数 × 单次影响的实体数 |

记住这个公式，**永远不要用数据库行数直接判断事件频率**。

## 参考

- 上一篇《给 HA 集成加定时任务踩的三个 asyncio 坑》
- HA 文档：[Entity state and attributes](https://developers.home-assistant.io/docs/core/entity/)
- HA 文档：[Recorder - State recording](https://www.home-assistant.io/integrations/recorder/)
