---
layout: post
title: "nb api resource：NocoBase 任意集合的通用 CRUD 命令行"
date: 2026-09-09 12:00:00 +0800
categories: [NocoBase]
tags: [nocobase, cli, nb-api, crud]
---

用 `nb` CLI 管理远程 NocoBase 实例时，最高频的一类需求就是「对某个集合做增删改查」。`nb api resource` 就是这把万能钥匙——不需要写一行 HTTP 请求，直接对任意业务集合执行 list / get / create / update / destroy / query。这篇把它的语法、实测输出和几个容易卡住的点记下来。

## 命令用途

```bash
nb api resource <action> --resource <集合名> [选项]
```

六个子动作：

| 动作 | 用途 |
|------|------|
| `list` | 分页列出记录 |
| `get` | 按 ID 取单条 |
| `create` | 新建记录 |
| `update` | 按 ID 更新 |
| `destroy` | 按 ID 删除 |
| `query` | 带过滤条件的查询（更接近 REST 风格） |

前提是已经 `nb init` 连好了远程实例（`--setup-mode connect-remote`）。

## 语法与常用参数

```bash
# 列出（分页）
nb api resource list --resource <集合名> --page 1 --page-size 20

# 新建：注意是 --values，不是 --body
nb api resource create --resource <集合名> \
  --values '{"title":"第一篇笔记","priority":"high"}'

# 更新
nb api resource update --resource <集合名> \
  --filter-by-tk <记录ID> --values '{"priority":"low"}'

# 删除
nb api resource destroy --resource <集合名> --filter-by-tk <记录ID>

# 指定外部数据源
nb api resource list --resource <集合名> --data-source <数据源key>
```

## 实测效果

新建一条记录：

```bash
$ nb api resource create --resource blog_demo_notes \
    --values '{"title":"hello","priority":"high"}'
{
  "data": {
    "id": 385624802918400,
    "title": "hello",
    "priority": "high",
    "createdAt": "2026-09-09T04:12:33.114Z",
    "updatedAt": "2026-09-09T04:12:33.114Z",
    "createdById": 1
  }
}
```

list 的返回结构带分页元信息：

```json
{
  "data": [ ... ],
  "meta": { "count": 20, "page": 1, "pageSize": 20, "totalPage": 3 }
}
```

删除的返回很「朴素」，只有删除条数：

```bash
$ nb api resource destroy --resource blog_demo_notes --filter-by-tk 385624802918400
{"data": 1}
```

关联资源也能直接操作，比如拿某篇文章下的评论：

```bash
nb api resource list --resource posts.comments --source-id <postId>
```

## 踩坑点

**1. `--values` 不是 `--body`。** 我第一反应是照 REST 习惯传 `--body`，CLI 直接报 Nonexistent flag。body 类参数在这里统一叫 `--values`，值为一段 JSON 字符串。

**2. 记录 ID 是雪花整数。** 返回的 `id` 是 `385624802918400` 这种长数字，不是从 1 开始的自增。写脚本时别假设 ID 规律，从 create/list 的响应里取。

**3. `--filter` 的 JSON 会被拒。** 我试过 `--filter '{"enabled":true}'`，报 `Invalid value`。这里接受的是 query 风格（如 `filter[enabled]=true`）而不是一段独立 JSON，过滤条件复杂时更建议直接用 `query` 动作。

**4. update 成功返回的 `data` 可能是数组**（按主键更新的不同路径），脚本里取值前先判断类型。

## 什么时候用

- 临时查数据、造测试数据、清测试记录——比开浏览器点界面快得多
- 写 shell 脚本做数据初始化 / 批量修补
- CI 里做冒烟验证：建一条 → 查得到 → 删掉

只是要小心：这是直接打生产 API 的命令，`destroy` 之前最好先 `get` 确认一下 ID 对不对。
