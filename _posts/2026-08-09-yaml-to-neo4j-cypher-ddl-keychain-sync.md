---
layout: post
title: "YAML → Cypher DDL 生成 + Neo4j Aura 同步链路"
date: 2026-08-09 17:50:00 +0800
categories: [技术笔记]
tags: [neo4j, cypher, yaml, etl, 数据建模]
---

把 YAML 当 source of truth、Neo4j 当查询层，需要一个稳定的"YAML → Aura"同步链路。三个脚本：

- `gen_schema.py` — ontology YAML → Cypher DDL（约束 + 索引）
- `load_schema.py` — DDL 灌进 Aura（幂等）
- `yaml_to_neo4j.py` — 实例 YAML + graph.yaml → 节点 + 边（MERGE 幂等）

密码不入 repo，走 macOS Keychain。

## 问题现象

最初的两版都踩坑：

1. **手写 DDL**：ontology 一改约束就忘改 DDL，Aura 里漂移
2. **生成器只输出 CREATE CONSTRAINT**：跑两次就报"constraint already exists"
3. **MERGE 不带 `ON CREATE SET`**：属性更新丢失
4. **密码硬编码在脚本里**：差点进 git

## 环境信息

- Neo4j Aura 5.x（支持 `NODE KEY`、关系约束、`IF NOT EXISTS`）
- Python 3 + `pyyaml` + `neo4j` 官方驱动
- macOS Keychain（凭据存储）

## 排查过程

### 坑 1：约束要幂等

第一版生成器输出：

```cypher
CREATE CONSTRAINT device_hostname IF NOT EXISTS
  FOR (n:Device) REQUIRE (n.hostname, n.deviceType) IS NODE KEY;
```

看起来对——`IF NOT EXISTS` 是 Neo4j 5.x 加的。但**改名时**会出问题：约束名是 `device_hostname`，定义是 `(hostname, deviceType)`，重跑没事；但如果你改成 `(hostname)` 重跑，会报"constraint exists with different definition"。

**修复**：每次改 ontology 先 DROP 再 CREATE，或者跑 `DROP CONSTRAINT name IF EXISTS`。生产环境上要小心。

### 坑 2：MERGE 不带 ON CREATE SET 会丢数据

错误版本：

```cypher
MERGE (n:Device {hostname: $h, deviceType: $dt})
SET n += $props  // 这会覆盖，包括 createdAt
```

正确版本：

```cypher
MERGE (n:Device {hostname: $h, deviceType: $dt})
ON CREATE SET n.createdAt = $now, n.createdBy = 'yaml_to_neo4j'
SET n.updatedAt = $now, n += $props
```

`ON CREATE SET` 只在节点新建时跑一次，保护 `createdAt` 不被覆盖；`SET` 每次都跑，更新 `updatedAt`。

### 坑 3：密码硬编码

第一版 `.env` 里写密码，差点 commit。最终改成 Keychain：

```bash
# 一次性写入 Keychain
security add-generic-password -s "Neo4j Aura" -a "<instance-id>" -w "<password>" -U
```

```python
# 脚本里读
def get_password() -> str:
    return subprocess.check_output(
        ["security", "find-generic-password",
         "-s", "Neo4j Aura",
         "-a", AURA_USER, "-w"],
        text=True,
    ).strip()
```

`.env` 里只放 URI/user/db，不放进 git。

## 根因分析：YAML → Cypher 的命名转换

YAML 里我们用 camelCase：

```yaml
installedOn:
  from: Software
  to: Device
```

Cypher 里 SCREAMING_SNAKE_CASE 才是惯例：

```cypher
MATCH (s:Software)-[:INSTALLED_ON]->(d:Device)
```

转换函数：

```python
def to_screaming_snake(camel: str) -> str:
    return "".join(
        "_" + c.lower() if c.isupper() else c
        for c in camel
    ).lstrip("_").upper()

# installedOn → INSTALLED_ON
# hostRunsOn → HOST_RUNS_ON
```

## 最终方案

### gen_schema.py

```python
def gen_node_constraints(entity_types: dict) -> str:
    out = []
    for etype, spec in entity_types.items():
        keys = spec.get("keyProperties", [])
        if not keys:
            continue
        if len(keys) == 1:
            out.append(
                f"CREATE CONSTRAINT {etype.lower()}_{keys[0]} IF NOT EXISTS\n"
                f"  FOR (n:{etype}) REQUIRE n.{keys[0]} IS UNIQUE;"
            )
        else:
            key_tuple = ", ".join(f"n.{k}" for k in keys)
            out.append(
                f"CREATE CONSTRAINT {etype.lower()}_key IF NOT EXISTS\n"
                f"  FOR (n:{etype}) REQUIRE ({key_tuple}) IS NODE KEY;"
            )
    return "\n\n".join(out)
```

### 多标签（subType）

ontology 里：

```yaml
Device:
  subTypes: [Workstation, Laptop, Server, VM]
```

Neo4j 里多标签：`:Device:Workstation`。约束挂在 `:Device` 共用，子类型筛选用标签：

```cypher
MERGE (n:Device:Workstation {hostname: $h})
```

`yaml_to_neo4j.py` 里拼：

```python
labels_cypher = ":" + ":".join([primary] + sub_labels)
# :Device:Workstation
```

### yaml_to_neo4j.py

```python
from neo4j import GraphDatabase

drv = GraphDatabase.driver(
    AURA_URI,
    auth=(AURA_USER, get_password()),
)

def upsert_node(session, ent: dict, labels: list[str]):
    label_cypher = ":".join(labels)
    session.run(f"""
        MERGE (n:{label_cypher} {{id: $id}})
        ON CREATE SET n.createdAt = $now
        SET n.updatedAt = $now, n += $props
    """, id=ent["id"], now=TODAY, props=ent)

def upsert_edge(session, edge: dict):
    session.run(f"""
        MATCH (a {{id: $from}}), (b {{id: $to}})
        MERGE (a)-[r:{to_screaming_snake(edge['relationType'])}]->(b)
        ON CREATE SET r.createdAt = $now
        SET r.updatedAt = $now
    """, **edge, now=TODAY)
```

跑完会输出统计：

```
节点: 38 (Device: 2, Host: 3, Software: 2, Service: 1, Artifact: 7, StartupItem: 23)
边: 40 (CONFIGURED_BY: 5, DEFINED_IN: 23, INSTALLED_ON: 2, ...)
```

## 关键命令速查

```bash
# 改完 ontology
python3 scripts/gen_schema.py           # 重新生成 .cypher
python3 scripts/load_schema.py          # 灌进 Aura

# 改完实例 yaml
python3 scripts/yaml_to_neo4j.py        # MERGE 节点 + 边

# Dry-run
python3 scripts/load_schema.py --dry-run
python3 scripts/yaml_to_neo4j.py --dry-run

# 看约束
cypher-shell -a "<bolt-uri>" -u <user> \
  "SHOW CONSTRAINTS YIELD * RETURN count(*)"
```

## 文件清单

```
cmdb/
├── ontology/
│   ├── entities.yaml          # 实体类型 + 属性
│   ├── properties.yaml        # 属性字典（type + 占位符）
│   └── relations.yaml         # 关系类型 + cardinality
├── schema/ddl/
│   ├── schema.cypher          # 生成产物：约束 + 索引
│   └── relationships.cypher   # 生成产物：关系约束 + MERGE 模板
├── entities/**/*.yaml         # 实例
├── graph.yaml                 # 边
└── scripts/
    ├── gen_schema.py
    ├── load_schema.py
    └── yaml_to_neo4j.py
```

## 总结

YAML 是 source of truth，Aura 是查询层。三个脚本分工：

- **gen_schema**：定义 → DDL
- **load_schema**：DDL → Aura schema
- **yaml_to_neo4j**：实例 → Aura data

密码走 Keychain 不入 repo。MERGE 必带 `ON CREATE SET` 保护 createdAt。Cypher 命名用 SCREAMING_SNAKE，camelCase 自动转换。
