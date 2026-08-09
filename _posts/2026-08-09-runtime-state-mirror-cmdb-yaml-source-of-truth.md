---
layout: post
title: "CMDB 实体建模：runtime 状态镜像型实体（开机项、服务进程）"
date: 2026-08-09 17:40:00 +0800
categories: [技术笔记]
tags: [cmdb, 数据建模, source-of-truth, yaml]
---

建模"开机启动项"这种实体时遇到一个根本问题：实体的存在由 yaml 决定，但实体的 `loaded`/`enabled` 状态又是运行时事实，每次开关机/卸载都会变。两套事实来源打架——yaml 写死了就会被现实漂移，让 yaml 跟现实跑又会污染 git 历史。最后用"快照镜像"模式解决：实体存在以 yaml 为准（git 历史），运行时状态由 sync 脚本定期镜像到 yaml。

## 问题现象

StartupItem 实体有两个属性：

- `loaded`（launchd 是否加载了）
- `enabled`（是否被 launchctl disable 了）

用户在终端跑一句 `launchctl unload -w ~/Library/LaunchAgents/com.foo.plist`，状态就变了。问题：

- yaml 里写死了 `loaded: true`，过时了
- 但 yaml 是 source of truth，不能让运行时随便改它
- 改完 yaml 还得同步到图数据库，否则前端看到的还是旧的

## 环境信息

- source of truth：YAML（git tracked）
- 图数据库：Neo4j Aura
- 前端：从 yaml 起的 server，bundle/delta 推到浏览器 LocalStorage

## 排查过程

### 想法 1：yaml 不要存 runtime 字段，前端直查 launchctl

- 问题：`launchctl list` 50ms，但前端 server 跑一次完整扫描要 200-500ms，多用户访问会爆
- 而且 CMDB 的本质是"全局视图"——多个主机都要上报，前端只看本机不合适

### 想法 2：yaml 存 runtime 字段，但不写脚本，让人手改

- 问题：人会忘改
- 而且这种字段本来就该自动化

### 想法 3：实时把 runtime 状态推到 Aura，绕过 yaml

- 问题：破坏了 "yaml 是 source of truth"——Aura 里多出 yaml 没有的字段，下次 MERGE 会被 yaml 覆盖
- Git 也追不到了

### 想法 4（最终方案）：runtime 字段镜像到 yaml

承认 yaml 不能 100% 实时反映现实，把"runtime 状态"当成"上次 sync 时的快照"。定期跑 sync 脚本，diff 出变化，写回 yaml + 推 Aura。

## 根因分析

**这是 CMDB 的本质，不是 bug**：

- CMDB 一般都有更新延迟（"最近一次扫描时的状态"）
- 实时性要求高的，走监控（Prometheus/Zabbix），不走 CMDB
- CMDB 的价值是"结构化关系" + "追溯历史"，不是"实时"

把"实时"和"快照"分开建模后，问题消失了。

## 最终方案

### 字段分类

| 字段类型 | 例子 | 事实来源 | 何时改 |
|---|---|---|---|
| **结构字段**（实体存在） | id, label, domain, managedBy, program | YAML | 人/装机时改 |
| **运行时字段**（状态） | loaded, enabled | 探测结果 | sync 脚本镜像 |
| **生命周期字段** | status: removed | 探测结果（找不到） | sync 脚本软删 |

### sync 脚本核心逻辑

```python
# scripts/sync_startup_items.py

DIFF_FIELDS = ("loaded", "enabled", "runAtLoad", "keepAlive", "program",
               "programArgs", "plistPath")

# 1. 扫当前系统
scanned = {ent["id"]: ent for ent in (scan.to_yaml_entity(it) for it in items)}

# 2. 读已有 yaml
existing = {ent["id"]: ent for ent in (read_yaml(f) for f in startup_dir.glob("*.yaml"))}

# 3. diff 四种情况
for eid, cur in existing.items():
    if eid not in scanned:
        # yaml 有，扫不到 → 软删
        if cur.get("status") != "removed":
            cur["status"] = "removed"
            cur["updatedAt"] = TODAY
            write_yaml(yf, cur)
    elif cur.get("status") == "removed":
        # 之前 removed，又扫到 → 恢复
        cur.pop("status", None)
        for f in DIFF_FIELDS:
            cur[f] = scanned[eid].get(f)
        write_yaml(yf, cur)
    else:
        # 正常状态：diff 关键字段
        changed = [f for f in DIFF_FIELDS if cur.get(f) != scanned[eid].get(f)]
        if changed:
            for f in changed:
                cur[f] = scanned[eid].get(f)
            cur["updatedAt"] = TODAY
            write_yaml(yf, cur)

# 4. yaml 没有，扫到 → 新建
for eid, ent in scanned.items():
    if eid not in existing:
        write_yaml(yf, ent)
```

### 生命周期：软删而非真删

启动项被卸载后，直接删 yaml 文件是个糟糕选择：

- git 历史还是有的，但当前 working tree 看不到
- Aura 那边对应节点不会被 yaml_to_neo4j 清理（它只 MERGE 不 DELETE）
- 用户没法在页面上看到"这玩意儿以前装过，现在没了"

软删方案：

```yaml
# 一个被卸载的启动项
id: startup-ua-com.foo.bar
status: removed    # ← 软删标记
updatedAt: '2026-08-09'
```

页面上可以专门展示 `status: removed` 的项（灰色 / 划线），或者直接过滤掉。Aura 那边 `status` 属性也会带上，Cypher 一查就出来。

如果之后又重装了（label 重新出现），sync 脚本会把 `status` 字段清掉，恢复 active。

### 时间戳策略

- `createdAt`：git first-commit（实体的"出生日期"）
- `updatedAt`：每次 sync 改 yaml 时刷新
- `meta.updatedAt`：同上，meta 段冗余一份，方便图数据库侧统一查询

## 实战效果

```bash
# dry-run 先看 diff
$ python3 scripts/sync_startup_items.py --dry-run
============================================================
扫描 23 个，yaml 已有 24 个
  + added:      0
  ~ updated:    1
      ~ startup-li-dingtalk: enabled
  ↺ restored:   1
      ↺ startup-sa-com.sogou.SogouServices
  × removed:    1
      × startup-li-fakeitem
  = unchanged:  21
============================================================
```

四类变化（added/updated/restored/removed）一目了然。

## 关键命令速查

```bash
# 看会做什么
python3 scripts/sync_startup_items.py --dry-run

# 应用到 yaml
python3 scripts/sync_startup_items.py

# 应用 + 推 Aura
python3 scripts/sync_startup_items.py --sync-aura
```

## 总结

建模"会变的实体"时，分清两套事实来源：

- **结构**（实体存在 / 配置）→ YAML，git 追溯
- **状态**（runtime 探测结果）→ 定期镜像到 YAML，承认是快照

CMDB 不需要实时，承认延迟反而让模型自洽。Sync 脚本是两者之间的桥，做软删 + diff 而不是直接覆盖。
