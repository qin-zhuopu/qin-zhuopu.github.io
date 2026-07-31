---
layout: post
title: "同一个设备两套名字：海尔空调 WS 实体名 vs Polled 实体名不一致的问题"
date: 2026-07-31 08:45:00 +0800
categories: Home-Assistant
series: haier-series
---

给 banto6/haier 加完 polling 之后，我撞上了一个看起来莫名其妙的问题：

> 数据库里查 `sensor.living_room_ke_ting_kong_diao_dang_qian_shi_nei_wen_du`（去掉 `_polled`），查不到。但 polling 日志里明明显示客厅空调在不停拉数据。

折腾半天才反应过来：**同一个设备在数据库里有两套完全不同的实体名前缀**。

## 现象

接入的两台空调：

| 设备 | WS 实体前缀 | Polled 实体前缀 |
|---|---|---|
| 北卧室空调 | `bei_wo_shi_kong_diao_` | `bei_wo_shi_kong_diao_` ✅ 一致 |
| 客厅空调 | `2pkong_diao_` | `living_room_ke_ting_kong_diao_` ❌ 不一致 |

**两个空调的命名规则完全不同**。北卧室空调的 WS 和 Polled 实体名一致，客厅空调的不一致。

## 排查过程

### 一开始以为是 attribute 没解析

我在数据库里查客厅空调的 WS 实体：

```sh
sqlite3 config/home-assistant_v2.db "
SELECT entity_id FROM states_meta
WHERE entity_id LIKE '%living_room%' OR entity_id LIKE '%ke_ting%'
ORDER BY entity_id;
"
```

只返回 6 个 `_polled` 实体，没有对应的 WS 版。

第一反应：**客厅空调的 attribute 解析挂了？**

继续查：

```sh
grep 'DC330DEC1560' config/home-assistant.log | head -20
```

日志里没有任何 parsing error。polling 拉到了完整 25 个 attrs。

### 真相：WS 实体用的是另一套命名

打开 HA 的 entity registry：

```sh
python3 -c "
import json
with open('config/.storage/core.entity_registry') as f:
    data = json.load(f)
entities = data['data']['entities']
living = [e for e in entities if e.get('device_id') == 'f58160b4731736fc3529e9e2710a5026']
for e in sorted(living, key=lambda x: x['entity_id']):
    print(f\"  {e['entity_id']}\")
"
```

输出（节选）：

```
binary_sensor.2pkong_diao_dian_jia_re_gong_neng_zhuang_tai
climate.2pkong_diao_climate
sensor.2pkong_diao_dang_qian_shi_nei_wen_du        ← WS 版的室温实体
sensor.2pkong_diao_feng_su
sensor.2pkong_diao_gong_neng_mo_shi
...
sensor.living_room_ke_ting_kong_diao_dang_qian_shi_nei_wen_du_polled   ← Polled 版
sensor.living_room_ke_ting_kong_diao_feng_su_polled
...
```

**WS 实体一直存在**，只是叫 `2pkong_diao_*`。我之前一直查 `living_room_*` 当然查不到。

## 为什么命名会不一致

### WS 实体名的来源

banto6/haier 在解析 attribute 时，把海尔云返回的中文 `desc` 字段直接当作实体名。

比如海尔的 attribute 列表里有：

```python
{
    "name": "indoorTemperature",
    "desc": "当前室内温度",
    ...
}
```

设备名是"2P空调"。HA 的 entity_registry 把"<设备名><attribute名>"按拼音音译生成 object_id：

```
"2P空调" + "当前室内温度" → "2pkong_diao_dang_qian_shi_nei_wen_du"
```

而北卧室空调的 deviceName 是"北卧室空调"，所以：

```
"北卧室空调" + "当前室内温度" → "bei_wo_shi_kong_diao_dang_qian_shi_nei_wen_du"
```

### Polled 实体名的来源

我加 `HaierPolledEntity` 时，只改了 unique_id 和 display_name：

```python
class HaierPolledEntity(HaierAbstractEntity):
    def __init__(self, device, attribute):
        super().__init__(device, attribute)
        self._attr_unique_id = self._attr_unique_id + '_polled'
        self._attr_name = (self._attr_name or '') + ' (Polled)'
        ...
```

但是 entity_registry 生成 object_id 时**重新走了 name → 拼音音译**的路径。`display_name` 此时变成了"当前室内温度 (Polled)"——但设备名呢？

关键来了：**两台空调的 deviceName 在云端设置不同**：

- 北卧室：`deviceName: "北卧室空调"`
- 客厅：`deviceName: "2P空调"`

但**显示用的 friendly_name 或 name 字段**可能是另一回事。Polled 实体注册时拿到的某个 name 字段是"客厅空调"（living_room_ke_ting_kong_diao），不是云端 deviceName "2P空调"（2pkong_diao）。

具体来源我没深挖，可能是 attribute 里有别名字段，或者 HA 内部对设备名做了 normalize。

### 简单的总结

- **WS 版**：直接用 `deviceName` + `attribute.desc`，所以是 `2pkong_diao_*`
- **Polled 版**：走了 HA 内部更复杂的 name 处理流程，变成了 `living_room_ke_ting_kong_diao_*`

## 解决思路

### 方案 A：暂不修，建立映射表（当前选择）

短期内不修，但保留一份明确的命名映射：

| 数据 | WS 实体 | Polled 实体 |
|---|---|---|
| 客厅室温 | `sensor.2pkong_diao_dang_qian_shi_nei_wen_du` | `sensor.living_room_ke_ting_kong_diao_dang_qian_shi_nei_wen_du_polled` |
| 客厅目标温度 | `sensor.2pkong_diao_mu_biao_wen_du` | `sensor.living_room_ke_ting_kong_diao_mu_biao_wen_du_polled` |
| 客厅风速 | `sensor.2pkong_diao_feng_su` | `sensor.living_room_ke_ting_kong_diao_feng_su_polled` |
| 客厅模式 | `sensor.2pkong_diao_gong_neng_mo_shi` | `sensor.living_room_ke_ting_kong_diao_gong_neng_mo_shi_polled` |
| 客厅上下摆风 | `sensor.2pkong_diao_shang_xia_bai_feng` | `sensor.living_room_ke_ting_kong_diao_shang_xia_bai_feng_polled` |
| 客厅左右摆风 | `sensor.2pkong_diao_zuo_you_bai_feng` | `sensor.living_room_ke_ting_kong_diao_zuo_you_bai_feng_polled` |

查询时两个都查：

```sql
SELECT datetime(s.last_updated_ts,'unixepoch','localtime') AS t, e.entity_id, s.state
FROM states s JOIN states_meta e ON s.metadata_id=e.metadata_id
WHERE (e.entity_id LIKE '%2pkong_diao%dang_qian_shi_nei_wen_du%'
    OR e.entity_id LIKE '%living_room%kong_diao%dang_qian_shi_nei_wen_du%')
  AND s.state != 'unavailable'
ORDER BY s.last_updated_ts;
```

### 方案 B：给 Polled 实体强制指定 object_id

在 `HaierPolledEntity.__init__` 里设置 `self._attr_has_entity_name = True` 并显式指定 `suggested_object_id`：

```python
class HaierPolledEntity(HaierAbstractEntity):
    def __init__(self, device, attribute):
        super().__init__(device, attribute)
        self._attr_unique_id = self._attr_unique_id + '_polled'
        # 显式设置 suggested_object_id 让它和 WS 版对齐
        # ...
```

但 HA 的 entity_registry 处理 object_id 比较复杂，要确保 unique_id + suggested_object_id 路径都对。我没急着改。

### 方案 C：删除 Polled 实体，让 HA 重新生成

如果改了命名规则，最稳妥的是在 entity_registry 里把旧的 Polled 实体删掉，下次启动时按新规则重建。

## 教训

### 教训 1：实体命名要早做决定

一旦 entity_registry 里有了一个 entity_id，HA 不会自动重命名。要改的话得手动删，重启后重新生成。**接入早期就把命名规则定好**。

### 教训 2：用 device_id 而不是 entity_id 前缀做匹配

如果想找某个设备的所有实体，**用 `device_id` 匹配，而不是用 entity_id 前缀**：

```python
import json
with open('config/.storage/core.entity_registry') as f:
    data = json.load(f)
target_device_id = 'f58160b4731736fc3529e9e2710a5026'
entities = [e for e in data['data']['entities']
            if e.get('device_id') == target_device_id]
```

`device_id` 是稳定的，entity_id 是可改的。

### 教训 3：新加实体时检查 entity_registry

加新实体后，第一时间查 entity_registry 确认 entity_id 符合预期：

```sh
python3 -c "
import json
data = json.load(open('config/.storage/core.entity_registry'))
for e in data['data']['entities']:
    if 'polled' in e['entity_id']:
        print(e['entity_id'])
"
```

否则等到数据库塞了一堆数据，再改名就麻烦了。

## 参考

- [HA 文档：Entity Registry](https://developers.home-assistant.io/docs/entity_registry_index/)
- [HA 文档：Entity naming](https://developers.home-assistant.io/docs/core/entity/#has_entity_name)
- 之前写的接入文章里有完整的实体列表
