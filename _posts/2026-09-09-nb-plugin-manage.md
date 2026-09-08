---
layout: post
title: "nb CLI 管理插件：nb plugin 与 nb api pm 的两套视角"
date: 2026-09-09 11:00:00 +0800
categories: [NocoBase]
tags: [nocobase, cli, nb, plugin]
---

NocoBase 的一切能力都挂在插件上，所以"看清楚实例里装了哪些插件、哪些启用着"是排障和二次开发的第一步。`nb` CLI 提供了两条路：`nb plugin` 系列偏人读摘要，`nb api pm` 系列直通服务端插件管理器（plugin manager），拿的是完整元数据。这篇记录两者差异和用法。

## 命令用途

NocoBase 里"插件"不只是功能开关：数据源、认证、工作流引擎、文件管理、AI，全都是插件。所以插件清单是理解一个陌生实例的第一张地图。相关命令分两组：

- `nb plugin list`：列出插件清单（displayName / packageName / enabled / description），适合人快速浏览。
- `nb api pm list`：返回每个插件的完整元数据，含 `packageJson`、`isCompatible`、`depsCompatible` 等，适合脚本和深度诊断。
- `nb api pm get --filter-by-tk <name>`：单个插件的元数据（`--filter-by-tk` 的值是插件名，如 `acl`）。
- `nb api pm enable / disable --filter-by-tk <name>`：启停插件。
- `nb api pm add / update / remove`：队列式安装、更新、移除插件。
- `nb api pm list-enabled` / `list-enabled-v2`：按 `dist/`（服务端）与 `client/`（前端）入口过滤已启用插件。

## 语法与常用参数

```bash
# 人读摘要
nb plugin list

# 完整元数据（配合 jq 过滤更实用）
nb api pm list | jq '.data[] | {name, enabled, isCompatible}'

# 单插件详情
nb api pm get --filter-by-tk acl

# 启停（改动运行时，慎重）
nb api pm disable --filter-by-tk <plugin-name>
nb api pm enable  --filter-by-tk <plugin-name>
```

## 实测效果

在一个 130+ 插件、全部启用的远程实例上：

```bash
$ nb plugin list
# 输出为插件 JSON 摘要数组，每项形如：
# { "displayName": "ACL", "packageName": "@nocobase/plugin-acl",
#   "enabled": true, "description": "..." }
```

```bash
$ nb api pm list
# 每项除上述字段外还有：
# packageJson: { version, dependencies, ... }
# isCompatible: true, depsCompatible: true
```

`list-enabled` / `list-enabled-v2` 的区别是入口过滤：一个面向服务端 `dist` 入口，一个面向前端 `client` 入口，排查"插件启用了但页面没渲染"时对比两边输出很有用。

两套命令的定位对比：

| 命令 | 输出粒度 | 适用场景 |
|------|---------|---------|
| `nb plugin list` | 摘要（名称/启用/描述） | 肉眼浏览、grep 快查 |
| `nb api pm list` | 完整元数据（含 packageJson、兼容性） | 脚本处理、深度诊断 |
| `nb api pm get --filter-by-tk` | 单插件完整元数据 | 定点查看某个插件 |
| `nb api pm list-enabled[-v2]` | 按 dist/client 入口过滤 | 排查前后端启用不一致 |

## 踩坑点

- `--filter-by-tk` 的值是**插件短名**（`acl`），不是包名（`@nocobase/plugin-acl`），传包名查不到。
- `nb plugin list` 输出的是摘要，想拿版本号、依赖兼容性必须走 `nb api pm list`。
- 130+ 插件的实例 `pm list` 输出非常大（每个插件都带完整 `packageJson`），直接看终端会刷屏，务必接 `jq` 过滤。
- `enable / disable / add / update / remove` 是真实改动运行时的操作：在共享的远程 demo 实例上不建议乱动，禁用核心插件（如 `acl`）可能直接把应用搞挂，操作前先做备份或修订点。
- `add / update / remove` 是**队列式**操作：命令返回不代表装完了，要去插件列表或应用日志里确认队列执行结果。

## 什么时候用

举两个典型脚本：

```bash
# 找出所有未启用的插件
nb plugin list | jq '.[] | select(.enabled == false) | .packageName'

# 确认某插件的版本与兼容性（升级前体检）
nb api pm get --filter-by-tk workflow | jq '.data | {version: .packageJson.version, isCompatible, depsCompatible}'
```

- 想快速确认"某插件装没装、开没开"：`nb plugin list` + grep 即可。
- 排查版本兼容、依赖缺失、升级前后差异：`nb api pm list`，看 `isCompatible` / `depsCompatible`。
- 自建实例上做插件生命周期管理（装、更、删）：`nb api pm add/update/remove`，并在操作前后各留一个备份（见 backup 系列）。
