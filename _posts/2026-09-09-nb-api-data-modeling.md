---
layout: post
title: "nb api data-modeling：命令行里完成建集合到删集合的完整生命周期"
date: 2026-09-09 12:30:00 +0800
categories: [NocoBase]
tags: [nocobase, cli, nb-api, data-modeling]
---

NocoBase 的数据建模平时都在 UI 里拖拽完成，但自动化场景下（初始化环境、脚本化验证、批量建表）用 `nb api data-modeling` 更顺手。这篇按「建集合 → 加字段 → 写记录 → 查 → 删集合」的完整生命周期走一遍实测。

## 命令用途

`nb api data-modeling` 下有四个子主题：

- `collections`：集合的 apply（创建/更新）/ get / list / destroy
- `fields`：单字段的 upsert
- `data-sources`：数据源管理（`list-enabled` 等）
- `db-views`：数据库视图

## 语法与常用参数

```bash
# 列出所有业务集合
nb api data-modeling collections list

# 创建集合（fields 传 JSON 数组）
nb api data-modeling collections apply \
  --name blog_demo_notes \
  --title "博客演示笔记" \
  --fields '[
    {"name":"title","interface":"input","title":"标题"},
    {"name":"priority","interface":"select","title":"优先级",
     "options":[{"label":"高","value":"high"},{"label":"低","value":"low"}]}
  ]'

# 查看单个集合
nb api data-modeling collections get --filter-by-tk blog_demo_notes

# 单独加字段
nb api data-modeling fields apply --collection <集合名> \
  --values '{"name":"status","interface":"select"}'

# 看启用了哪些数据源
nb api data-modeling data-sources list-enabled

# 删除集合
nb api data-modeling collections destroy --filter-by-tk blog_demo_notes
```

## 实测效果

`collections list` 在实例上返回了 20 个业务集合（`scm_*`、`crm_*`、`it_*`、`desk_*` 等，都来自各个 Portal 项目）。新建集合的响应里能看到 NocoBase 自动补齐的系统字段：

```json
{
  "key": "k3xqz8vbn2la",
  "name": "blog_demo_notes",
  "title": "博客演示笔记",
  "fields": [
    { "name": "id", "interface": "id", "type": "bigInt" },
    { "name": "title", "interface": "input", "type": "string" },
    { "name": "priority", "interface": "select", "type": "string" },
    { "name": "createdAt", "interface": "createdAt", "type": "date" },
    { "name": "updatedAt", "interface": "updatedAt", "type": "date" },
    { "name": "createdById", "type": "bigInt" },
    { "name": "updatedById", "type": "bigInt" }
  ]
}
```

删集合的返回同样是删除条数：

```bash
$ nb api data-modeling collections destroy --filter-by-tk blog_demo_notes
{"data": 1}
```

`db-views list` 在没建过视图的实例上返回 `[]`，属正常现象。

## 踩坑点

**1. `collections get` 返回的 fields 是空的。** 这是最反直觉的一点——get 拿到的集合元数据里 fields 列表为空。不是没建上字段，而是 get 这个入口不带字段元数据。想看真实字段结构，看 `apply` 的响应，或从 `collections list` 里取。

**2. 集合 key 是随机 uid。** apply 返回的 `key` 是 `k3xqz8vbn2la` 这样的随机串，不是你传的 `name`。后续 `--filter-by-tk` 用 `name` 即可，别把 key 和 name 搞混。

**3. 系统字段是自动生成的。** `id`（雪花 ID）、`createdAt`、`updatedAt`、`createdById`、`updatedById` 都会自动加上，`--fields` 里不用写。

**4. destroy 是真删。** 集合连带数据一起没了，测试集合命名时加个 `demo_` / `tmp_` 前缀方便事后辨认。

## 什么时候用

- 脚本化初始化一套演示/测试环境（建集合 → 造数据 → 展示 → 清理）
- 多环境之间同步一套简单的数据模型定义
- 配合 `nb api resource`（见上一篇）做端到端验证

一次完整的建模周期在远程实例上几秒钟就跑完，比在 UI 里逐个点字段快得多——但正式环境的模型变更还是建议走 UI 或版本化的 DSL 流程，留下可追溯的记录。
