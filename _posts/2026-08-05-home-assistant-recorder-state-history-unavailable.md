---
layout: post
title: "Home Assistant 历史曲线为什么断开：recorder 的「只在变化时记录」与 unavailable 约定"
date: 2026-08-05 06:20:43 +0800
categories: [技术踩坑]
tags: [home-assistant, recorder, sqlite, state-history]
---

排查 Home Assistant 历史图里出现断线的问题，挖出两个 HA 的核心约定：recorder 只在状态变化时入库，以及 `unavailable` 是所有实体共用的"不可用"信号。把这两件事讲清楚，再给出一个让外部传感器"连续相同值不入库 + 超时变 unavailable"的方案。

## 问题现象

集成跑得好好的，每分钟都能从设备端拉到数据，日志里看到属性一直在更新：

```
2026-08-05 06:00:09 DEBUG polling device DC330D80F406 got 32 attrs: {...}
2026-08-05 06:01:09 DEBUG polling device DC330D80F406 got 32 attrs: {...}
2026-08-05 06:02:09 DEBUG polling device DC330D80F406 got 32 attrs: {...}
```

但前端历史图里：

1. 曲线**稀疏得离谱**，相邻两个点能隔一两个小时
2. 中间还有**整段断开**，hover 上去显示 `unavailable`
3. 数据库里查这个温度实体，5 天只有 173 行

## 环境信息

- OS: macOS
- Home Assistant Core：本地源码运行
- 数据库：SQLite（默认 recorder 后端），文件 `config/home-assistant_v2.db`
- 集成：自定义第三方集成，每分钟 polling

## 排查过程

### 第一步：看实际入库数据

HA 数据库的 `states` 表用 `metadata_id` 关联 `states_meta`，不是直接 `entity_id`，所以 join 一下查：

```sql
SELECT datetime(s.last_updated_ts,'unixepoch','localtime') AS ts, s.state
FROM states s
JOIN states_meta sm ON s.metadata_id = sm.metadata_id
WHERE sm.entity_id = 'number.xxx_temperature'
ORDER BY s.last_updated_ts DESC LIMIT 30;
```

结果（节选）：

```
2026-08-05 06:12:15  unavailable
2026-08-05 00:56:29  26.50
2026-08-04 23:30:47  26.00
2026-08-04 22:59:22  25.50
2026-08-04 22:43:23  25.00
...
```

每行之间间隔几分钟到几小时不等，但日志里明明每分钟都有值。说明**不是 polling 没拉到，是 recorder 没存**。

### 第二步：列出该实体的所有不同 state

```sql
SELECT state, COUNT(*) FROM states s
JOIN states_meta sm ON s.metadata_id = sm.metadata_id
WHERE sm.entity_id = 'number.xxx_temperature'
GROUP BY state ORDER BY COUNT(*) DESC;
```

```
state        n
-----------  --
unavailable  31
26.00        23
24.00        21
25.50        20
...
unknown      1
```

温度字段（`number` 平台、浮点类型）里，除了实际温度字符串，还混着 `unavailable` 和 `unknown`。`states.state` 列类型是 `VARCHAR(255)`，对数据库来说"26.5" 和 "unavailable" 都是普通字符串。

## 根因分析

### 根因一：recorder 只在状态变化时写一行

这是 HA 的设计契约，不是 bug，也没有开关关掉：

> 同一个实体，如果新 state 等于 old state，**不入库**。

所以每分钟推/拉一次相同的 26.5℃，数据库里就**只有第一次的 26.5**，后面 5 个小时的 26.5 全部丢弃。曲线看起来稀疏，是因为相邻两个变化点之间确实只有两个数据点——前端在它们之间拉一条直线。

### 根因二：`unavailable` 是所有实体共用的"不可用"标记

HA 里每个实体有**两层**：

- **state（字符串）**—— 永远是字符串，永远允许几个特殊值：`unavailable` / `unknown` / `none`
- **native_value**—— 才是真正的数值（浮点、枚举值等）

只要集成把 `_attr_available = False`，Entity 基类会自动把 state 写成字符串 `"unavailable"`，**所有平台（sensor、number、switch、climate……）都一样**。集成代码不需要自己处理。

`unavailable` 触发场景：

- HA 重启中（实体还没被集成注册）
- 集成的网关断开（典型 callback：`self._attr_available = False`）
- 设备本身被报告离线（haier 这种第三方集成有 `Device Offline` 事件）
- 显式调用 `entity` 的某些方法

`unknown` 不一样：实体可用，但当前值未知（第一次轮询还没回来、解析失败）。

**前端画图规则是统一的**：碰到 `unavailable` / `unknown` 就**断开曲线**，不连线。

### 根因三：`unavailable` 段后面常常是大段空白

看时间线：

```
2026-08-05 00:56:29  26.50      ← 最后一次正常值
2026-08-05 06:12:15  unavailable ← 6 小时后突然变成 unavailable
```

中间 6 小时一条记录都没有。两个原因叠加：

1. 这段时间温度一直是 26.5 → 没变化 → recorder 不写
2. 06:12 设备掉线 → 集成把 `_attr_available=False` → 写一条 `unavailable`

所以图上看到的效果是：先一段长时间"没数据"（其实是没变化），然后突然断开（unavailable），再然后曲线重新开始。

## 最终方案

### 想让曲线连续？三种思路

1. **关掉"只在变化时记录"** —— 不行，HA recorder 没这个开关。
2. **用长期统计 `statistics` 表** —— recorder 默认 5 分钟聚合一次到 `statistics` / `statistics_short_term`，**固定周期采样**、不断点。前端"统计图表"或 Energy Dashboard 用的就是这个，比 `states` 平滑得多。
3. **接 InfluxDB** —— 真正的"每分钟一条原始报文"时序存储，曲线永远连续。

### 反过来：自己接外部传感器，希望"连续相同值不入库 + 超时变 unavailable"

这是 HA 默认就能做到一半的：**相同值不入库是默认行为**；超时变 `unavailable` 需要自己加看门狗。

最省事的架构是 webhook 推送 + template sensor 包一层：

```yaml
# 1. 接收推送
automation:
  - alias: "接收外部温度推送"
    trigger:
      - platform: webhook
        webhook_id: "mcu-temp-push-secret-id"
    action:
      - service: input_number.set_value
        target:
          entity_id: input_number.mcu_temp
        data:
          value: "{{ trigger.json.value }}"
      - service: input_datetime.set_datetime
        target:
          entity_id: input_datetime.mcu_last_seen
        data:
          timestamp: "{{ now().timestamp() }}"

# 2. 看门狗 + 真正对外暴露的 sensor
template:
  - sensor:
      - name: "MCU Temperature"
        unit_of_measurement: "°C"
        state_class: measurement
        state: >
          {% if (now() - states('input_datetime.mcu_last_seen') | as_datetime).total_seconds() < 90 %}
            {{ states('input_number.mcu_temp') }}
          {% else %}
            unavailable
          {% endif %}
        available: >
          {{ (now() - states('input_datetime.mcu_last_seen') | as_datetime).total_seconds() < 90 }}
```

外部设备推送：

```bash
curl -X POST http://localhost:8123/api/webhook/mcu-temp-push-secret-id \
  -H "Content-Type: application/json" \
  -d '{"value": 26.5}'
```

效果：

| 场景 | 数据库写入 | 图表显示 |
|---|---|---|
| 26.5 → 26.5 → 26.5 | 只写第一条 26.5 | 一条直线 |
| 26.5 → 27.0 | 写 27.0 | 直线段 |
| 推送停了 90 秒+ | 写一条 `unavailable` | **断开** |
| 推送恢复 | 写新值 | 重新开始 |

## 关键命令速查

```bash
# 查某个实体的近期 state（注意要 join states_meta）
sqlite3 config/home-assistant_v2.db "
SELECT datetime(s.last_updated_ts,'unixepoch','localtime') AS ts, s.state
FROM states s JOIN states_meta sm ON s.metadata_id = sm.metadata_id
WHERE sm.entity_id = 'number.xxx_temperature'
ORDER BY s.last_updated_ts DESC LIMIT 30;"

# 该实体所有不同值统计
sqlite3 config/home-assistant_v2.db "
SELECT state, COUNT(*) FROM states s
JOIN states_meta sm ON s.metadata_id = sm.metadata_id
WHERE sm.entity_id = 'number.xxx_temperature'
GROUP BY state ORDER BY COUNT(*) DESC;"

# 查表结构
sqlite3 config/home-assistant_v2.db ".schema states"

# 列出所有实体元数据
sqlite3 config/home-assistant_v2.db "SELECT * FROM states_meta;"
```

## 几条结论速记

- `states.state` 是字符串列，**任何平台的实体**都能存 `unavailable` / `unknown`，不只是数值类。
- recorder **只在变化时写**，不每分钟写——这是设计契约，没开关。
- 前端画图**碰到 `unavailable`/`unknown` 自动断线**，所有平台统一。
- 想看连续曲线，用 `statistics` 表 / 统计图表，别看 `states`。
- 想让外部传感器"超时变 unavailable"，**HA 不会自动判定**，需要 webhook + template sensor + 看门狗自动化。

## 参考

- [Home Assistant Recorder documentation](https://www.home-assistant.io/integrations/recorder/)
- [Home Assistant State Objects](https://developers.home-assistant.io/docs/core/entity/state)
- [Home Assistant Template Sensors](https://www.home-assistant.io/integrations/template/)
