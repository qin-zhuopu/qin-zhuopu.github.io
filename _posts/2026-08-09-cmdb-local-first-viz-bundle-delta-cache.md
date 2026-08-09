---
layout: post
title: "CMDB 可视化的本地优先架构：bundle/delta + LocalStorage 缓存"
date: 2026-08-09 17:00:00 +0800
categories: [技术笔记]
tags: [cmdb, localstorage, neo4j, vanilla-js, 性能]
---

把 CMDB 数据可视化时，最初的设计是"前端直接打 Neo4j Aura 查图"。每次切换页面都往返云端一次，加载 1-3 秒。后来改成"本地优先"——首屏拉一次 bundle 全量入 LocalStorage，之后切页全走本地，只有查邻居才打 Aura。加载时间从秒级降到 17ms。

## 问题现象

- 旧版：页面每次切都去 Aura 查一遍 schema + 实例
- 卡顿明显：网络 RTT + Cypher 编译 + 反序列化 = 1-3s
- Aura Free 的连接也有限流，频繁查容易触发
- 视图本身不需要图遍历，纯粹是"列实体 / 看详情"，没必要每次都走图数据库

## 环境信息

- 后端：Python 3 标准库 `http.server`
- 前端：纯 vanilla JS（无框架），约 400 行
- 数据源：YAML 文件（source of truth）+ Neo4j Aura（图查询）
- 浏览器：LocalStorage（~5MB 配额够用）

## 排查过程

**第一个想法**：把数据塞 IndexedDB。
- 优点：容量大、结构化
- 缺点：API 啰嗦，纯 JSON 来回倒没必要
- LocalStorage 配额 ~5MB，CMDB 全量 schema + 几十个实例序列化后才几十 KB，远够用

**第二个想法**：每次进页面打一次 `/api/schema` + `/api/instances`。
- 还是要等网络
- 而且切页时会重复打

**第三个想法（最终方案）**：bundle + delta
- 首屏一个请求拿全部（schema + instances + edges）
- 后续访问只请求 delta（updatedAt 大于本地版本的实例）
- 邻居查询是少数真要打图数据库的场景，单独走 `/api/graph/neighbors`

## 根因分析

"网络慢"不是根本问题，**数据建模错配**才是。CMDB 的实体数据本质是：

- 读多写少（一周改一次 schema 算多的）
- 总量小（KB 级）
- 一致性要求不高（最新数据 vs 一天前的数据差异可忽略）

这种数据**就该放客户端**，让网络只承担"查关系"这种必须用图的事。

## 最终方案

### 三个接口

```python
# server.py
/api/bundle              # 首屏：schema + 全量 instances + edges
/api/delta?since=...     # 增量：updatedAt > since 的实例，schema 变了也带上
/api/graph/neighbors?id=...  # 唯一对外：查邻居（真打 Aura）
```

### 前端加载流程

```js
async function ensureData() {
  const cached = JSON.parse(localStorage.getItem('cmdb-cache-v1') || 'null');
  if (cached) {
    // 走 delta
    const since = cached.bundleUpdatedAt || '';
    const r = await fetch(`/api/delta?since=${since}`);
    const d = await r.json();
    if (d.schema) cache.schema = d.schema;  // schema 变了
    for (const [id, inst] of Object.entries(d.changed_instances)) {
      cache.instances[id] = inst;
    }
    cache.bundleUpdatedAt = d.current_updatedAt;
  } else {
    // 首次拉 bundle
    const r = await fetch('/api/bundle');
    const b = await r.json();
    cache = b;
    cache.bundleUpdatedAt = b.updatedAt;
  }
  localStorage.setItem('cmdb-cache-v1', JSON.stringify(cache));
}
```

### delta 的核心逻辑（服务端）

```python
def build_delta(since: str) -> dict:
    bundle = build_bundle()
    changed = {
        eid: inst for eid, inst in bundle["instances"].items()
        if inst["updatedAt"] > since
    }
    schema_changed = bundle["schema"]["updatedAt"] > since
    return {
        "schema": bundle["schema"] if schema_changed else None,
        "changed_instances": changed,
        # ...
    }
```

关键是 `schema_updated > since` 这一项：schema 没变就不重发，省一大坨 JSON。

### 缓存结构

LocalStorage key：`cmdb-cache-v1`，value：

```js
{
  schema: { entityTypes: [...], nodes: {...}, updatedAt: "..." },
  instances: { id1: {...}, id2: {...}, ... },
  edges: [...],
  bundleUpdatedAt: "2026-08-09T..."
}
```

邻居查询单独存：`cmdb-neighbors-v1`，LRU 200 条。

## 关键命令速查

```bash
# 健康检查
curl http://localhost:8765/api/health

# 看 bundle 大小
curl -s http://localhost:8765/api/bundle | wc -c

# 看 delta
curl "http://localhost:8765/api/delta?since=2026-08-09"
```

## 性能对比

| 场景 | 旧（直打 Aura） | 新（本地优先） |
|---|---|---|
| 首屏加载 | 1-3s | ~150ms（拉 bundle） |
| 切页（类型→详情） | 800ms-1.5s | 17ms（纯本地） |
| 查邻居 | 1-2s | 1-2s（仍然要打 Aura） |
| 第二次查邻居 | 1-2s | <50ms（LocalStorage 命中） |

## 总结

本地优先的核心不是"完全离线"，而是**把数据按访问模式分层**：

- schema + 实体画像（基本静态）→ 客户端缓存
- 关系遍历（必须算的）→ 服务端打图

这一刀切完，95% 的页面切换变成纯本地操作，Aura 也只承担它擅长的"图遍历"。
