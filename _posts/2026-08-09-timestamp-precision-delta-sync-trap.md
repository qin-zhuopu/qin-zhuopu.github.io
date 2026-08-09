---
layout: post
title: "增量同步被日期精度坑了：schema updatedAt 改用文件 mtime"
date: 2026-08-09 18:00:00 +0800
categories: [技术笔记]
tags: [缓存, delta-sync, timestamp, 调试]
---

CMDB 可视化的增量同步坏了——ontology 改完后页面没刷新，新加的实体类型不出现。根因不在 diff 逻辑，而在**时间戳精度**：yaml 里手写的 `updatedAt: 2026-08-09` 是日期精度，同一天多次改 ontology，delta 比较的 `updatedAt > since` 永远不成立。改用文件 mtime（带时分秒）后修好。

## 问题现象

- 早上 10 点改 ontology，加了个新实体类型 StartupItem
- 跑 `yaml_to_neo4j.py` 推 Aura，Aura 里 23 个新节点都进去了 ✓
- 浏览器刷新页面，**新类型卡片没出现** ✗
- DevTools 看 `/api/delta` 响应：`schema: null`（schema 没变）

## 环境信息

- 后端 Python，bundle/delta 接口
- 前端 LocalStorage 缓存 schema + 实体
- ontology yaml 里手写 `updatedAt: 2026-08-09`（日期精度）

## 排查过程

### 第一步：怀疑前端没清缓存

点页面右上角"强制刷新"按钮（清 LocalStorage 重拉 bundle），新类型就出来了。但这只是绕过——下次再改 ontology 又会重现。

### 第二步：看 delta 接口

```python
def build_delta(since: str) -> dict:
    bundle = build_bundle()
    schema_changed = bundle["schema"]["updatedAt"] > since  # ← 关键
    return {
        "schema": bundle["schema"] if schema_changed else None,
        # ...
    }
```

`>` 是字符串比较。客户端发的 `since` 来自上次缓存里的 `schemaUpdatedAt`，等于 `2026-08-09`。服务端 `updatedAt` 也是 `2026-08-09`。比较：`"2026-08-09" > "2026-08-09"` → False。

schema 没被认为变了，delta 不发 schema，前端永远拿不到新 schema。

## 根因分析

**精度问题，不是逻辑问题**。

- yaml 里 `updatedAt: 2026-08-09` 是人写的，写到天
- 同一天多次改 ontology（开发期非常常见），所有版本都是同一个字符串
- delta sync 假定"updatedAt 单调递增"，但精度不够时它不单调

生产环境可能很少触发（一天改一次 ontology 就算多了）。但开发期一小时内改十次就稳定踩坑。

## 最终方案

**别用 yaml 里手写的字段**做 delta 比较——用文件 mtime，自然带时分秒：

```python
from datetime import datetime
from pathlib import Path

def _build_schema(ontology, entities, graph):
    # 旧版（坏）：
    # schema_updated = max(
    #     str(ontology["entities"].get("updatedAt", "")),  # "2026-08-09"
    #     str(ontology["properties"].get("updatedAt", "")),
    #     ...
    # )

    # 新版（好）：
    schema_files = [
        ONTOLOGY_DIR / "entities.yaml",
        ONTOLOGY_DIR / "properties.yaml",
        ONTOLOGY_DIR / "relations.yaml",
        GRAPH_FILE,
    ]
    schema_updated = datetime.fromtimestamp(
        max(f.stat().st_mtime for f in schema_files if f.exists())
    ).strftime("%Y-%m-%dT%H:%M:%S")
    # "2026-08-09T16:36:03"
```

跑一次：

```
schema.updatedAt: 2026-08-09T16:36:03   ← 之前是 2026-08-09
bundle.updatedAt: 2026-08-09T16:36:03
```

之后每次改 ontology 文件，秒级精度的 updatedAt 一定不同，delta `>` 一定命中。

## 验证

打开浏览器：

```js
// 改前
> JSON.parse(localStorage.getItem('cmdb-cache-v1')).schemaUpdatedAt
"2026-08-09"

// 改 ontology 文件，重启 server，刷新页面
// delta 返回 schemaChanged = true，schema 被刷新

> JSON.parse(localStorage.getItem('cmdb-cache-v1')).schemaUpdatedAt
"2026-08-09T16:36:03"
```

新实体类型立刻出现。

## 几个相关的坑

### 坑 1：mtime 不稳定

`git checkout` 切分支会把文件 mtime 改成当前时间——不会影响"文件被改了"的语义，但会让"updatedAt 一直变化"。可以接受。

### 坑 2：跨主机时间不一致

如果你把同一份 yaml 部署到多台机器，每台的 mtime 都不同——会导致 updatedAt 漂移。CMDB 单源写入没这个问题，分布式要注意。

### 坑 3：客户端时钟漂移

如果用客户端时间做 `now > updatedAt` 比较，注意客户端时钟不准也会出问题。本方案里 `since` 是从服务端拿的，没有客户端时间介入。

## 关键命令速查

```bash
# 看文件 mtime
stat -f "%Sm" ontology/entities.yaml
# 输出: 2026-08-09 16:36:03

# Python 拿 mtime
python3 -c "from pathlib import Path; import datetime; \
print(datetime.datetime.fromtimestamp(Path('ontology/entities.yaml').stat().st_mtime))"
```

## 总结

增量同步靠时间戳，**精度必须高于改动频率**。

- 改动频率：开发期可能几分钟一次
- 精度：日期 `YYYY-MM-DD` 远远不够

文件 mtime 自带秒级精度，免维护，永远单调递增。手写 `updatedAt:` 字段只用于人类阅读（"这个文件大概什么时候改的"），不要拿来做 sync 比较。

适用场景：

- API 缓存失效（ETag / Last-Modified）
- 浏览器 LocalStorage delta
- CDN 边缘缓存
- CI 缓存键

凡是涉及"自上次以来变了什么"的逻辑，都该问一句：时间戳精度够吗？
