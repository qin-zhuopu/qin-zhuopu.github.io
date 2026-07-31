---
layout: post
title: "Home Assistant 的两个存储：数据库只记变化，日志每次都记"
date: 2026-07-31 08:30:00 +0800
categories: Home-Assistant
series: haier-series
---

接入海尔空调之后遇到一个看起来很奇怪的现象：

> 我在 HA 里加了 60 秒 polling，空调关机时室温稳定在 26°C。30 分钟后我想确认 polling 到底跑没跑，去看数据库——只增加了 1 行。但代码里 `_LOGGER.debug` 明明写了每分钟一行日志。

花了点时间排查，最后发现这是 HA **两个独立存储系统**的设计差异导致的。写下来给同样困惑的人。

## TL;DR

HA 有两套独立的存储：

| 存储 | 路径 | 记录策略 |
|---|---|---|
| **数据库（Recorder）** | `config/home-assistant_v2.db` | **只在状态变化时**写一行 |
| **日志** | `config/home-assistant.log` | **每次事件都写**，无去重 |

完全独立，没有同步关系。

## 实测证据

我的 polling 任务每 60 秒拉一次空调室温。空调关机，室温稳定 26.0°C 不变。

跑了 30 分钟后：

| 来源 | 记录数 |
|---|---|
| 日志里的 `polling device XXX got N attrs` | **30 行**（每分钟一条） |
| 数据库 `states` 表里该实体的新行 | **1 行**（只有第一次 unavailable → 26.0 那次算"变化"） |

30 倍的差距。

## 数据库（Recorder）的写入规则

Recorder 的设计哲学：**节省存储**。状态字符串变化时才写。

### 触发条件

- state 字符串变化：`"25.5"` ≠ `"26.0"` 算变（要写）
- 某些关键 attribute 变化：也可能触发写
- **值没变就不写**：即使实体被频繁 `schedule_update_ha_state`，值不变 Recorder 就跳过

### 表结构

主要表：

- `states`：每次状态变化一行
- `states_meta`：`entity_id` ↔ `metadata_id` 映射（数据库外键压缩）
- `statistics`：5 分钟聚合（短期统计）
- `statistics_long_term`：1 小时 / 1 天聚合（长期统计）

### 查询示例

```sh
sqlite3 config/home-assistant_v2.db "
SELECT datetime(last_updated_ts,'unixepoch','localtime') AS t, state
FROM states s JOIN states_meta e ON s.metadata_id=e.metadata_id
WHERE e.entity_id='number.bei_wo_shi_kong_diao_dang_qian_shi_nei_wen_du_polled'
ORDER BY last_updated_ts DESC LIMIT 20;
"
```

## 日志的写入规则

每次事件都写，无去重。

### 默认级别 WARNING

要看 DEBUG 信息必须打开：

```yaml
# configuration.yaml
logger:
  logs:
    custom_components.haier: debug
```

重启生效。

### polling 日志（加完整 payload）

每分钟一条，包含完整数据：

```
05:31:59 DEBUG polling device DC330D80F406 got 32 attrs: {'specialMode': '0', ..., 'indoorTemperature': '26.00', ...}
```

**关键**：我让日志里把完整 attrs 也输出（`%s` 占位符 + dict），这样排查时能直接看到温度值。

## 排查"数据没拿到"的标准流程

如果某个实体的状态长时间不变，按下面三步排查。

### 步骤 1：看 polling 是否在跑

```sh
grep 'polling device <设备ID> got' config/home-assistant.log | tail -10
```

- 没有 → polling 没跑（代码 bug 或集成没加载）
- 有 → 进入步骤 2

### 步骤 2：看拉到的数据值

日志里同一行有完整 JSON，检查关心的字段：

```sh
grep 'polling device <设备ID> got' config/home-assistant.log | tail -5
```

- 字段值真的没变（比如 `indoorTemperature` 一直是 26.00） → 数据库不写是正常的
- 字段值有变化但数据库没记 → 进入步骤 3

### 步骤 3：看实体是否在监听事件

```sh
curl -s -H "Authorization: Bearer $LLAT" \
  "http://localhost:8123/api/states/<entity_id>" | python3 -m json.tool
```

看 `last_updated` 时间：

- 是最近 60 秒内 → 实体状态更新了，只是值和上次一样，Recorder 跳过
- 不是最近 60 秒内 → 实体没收到事件，可能是 entity registry 问题

## 一个真实案例：为什么 polling 跑了 19 次数据库却只有 1 行

我遇到过一次。当时刚加完 polling，重启 HA，运行 20 分钟后查看：

- 日志：19 次 polling tick
- 数据库：1 行

差点以为 polling 没生效，跑了日志查询才确认是真在拉。然后才反应过来：**空调关机时室温稳定，值没变，Recorder 跳过**。

这就是为什么我后来坚持在 polling 日志里输出完整 attrs JSON。**否则查问题时只能瞎猜**。

## 想要"每次 polling 都写一行"怎么办

如果需要每分钟固定一行（便于画平滑曲线），有几种办法：

### 方案 A：开启 long-term statistics（推荐）

HA 默认对 `measurement` 类 sensor 自动开 5 分钟聚合。对 number 实体可能需要在 UI 手动启用统计，或改 entity 类别为：

```python
options['device_class'] = SensorDeviceClass.TEMPERATURE
options['state_class'] = SensorStateClass.MEASUREMENT
options['native_unit_of_measurement'] = UnitOfTemperature.CELSIUS
```

这样统计表会按时段聚合，即使值没变也会写。

### 方案 B：改 Recorder 配置（不推荐）

```yaml
recorder:
  commit_events:
    - number.xxx_polled
```

缺点：数据库膨胀，且对 number 实体效果有限。

### 方案 C：保留日志，事后分析

日志里已经存了完整 JSON，事后可以：

```sh
grep 'polling device DC330D80F406' config/home-assistant.log | \
  python3 -c "import sys, re, json; ..."
```

适合临时分析，不适合长期可视化。

## 总结

**HA Recorder 只记变化**，这是设计而非 bug。要让数据库写得多：

- 让值真的变化（监控真实波动的传感器）
- 或者打开 long-term statistics（按时段聚合）
- 或者改 Recorder 配置强制 commit

**日志每次都写**，所以排查问题时第一手看日志，**不要只看数据库**。在 polling 任务里把完整 payload 也打出来，永远不亏。

## 参考

- [HA 文档：Recorder](https://www.home-assistant.io/integrations/recorder/)
- [HA 文档：Long-term statistics](https://developers.home-assistant.io/docs/core/entity/sensor/#long-term-statistics)
- SQLite 查询技巧：直接用 `sqlite3 config/home-assistant_v2.db` 进 shell
