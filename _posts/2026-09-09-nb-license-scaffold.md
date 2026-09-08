---
layout: post
title: "nb license 与 nb scaffold plugin：两条在远程实例上跑不通的命令"
date: 2026-09-09 14:00:00 +0800
categories: [NocoBase]
tags: [nocobase, cli, nb, license, scaffold]
---

`nb` CLI 的大部分子命令在 connect-remote 模式下都能直接作用于远程实例，但有两个例外：`nb license`（生成实例 ID 激活许可）和 `nb scaffold plugin`（脚手架插件）。它们都依赖"本地环境"——一个是本地实例的机器标识，一个是本地 NocoBase 源码树。这篇记录两条命令的报错、原因和正确打开方式。

## 命令用途

- `nb license status` / `nb license id`：查看许可状态、生成实例 ID，用于商业许可激活。
- `nb scaffold plugin <pkg>`：按官方模板生成插件骨架（collections、server/client 目录、`package.json` 等）；另有 `nb scaffold migration` 生成迁移文件。

## 语法与常用参数

```bash
# 许可
nb license status
nb license id

# 插件脚手架（包名可带 scope）
nb scaffold plugin @my-scope/my-plugin
nb scaffold migration <name>
```

两条命令的前提条件不同，先对照自己的环境：

| 命令 | 需要的环境 | connect-remote 下 |
|------|-----------|------------------|
| `nb license` | 本地/自建实例（实例 ID 派生自机器） | 报不支持 |
| `nb scaffold plugin` | 本地 NocoBase 源码树 | 报 ENOENT |

## 实测效果

在连接远程 demo 实例（connect-remote 模式）的环境上：

```bash
$ nb license status
# <env> does not support automatic instance ID generation

$ nb license id
# 同样的报错：不支持自动生成实例 ID
$ nb scaffold plugin @scope/demo
# spawn nocobase-v1 ENOENT
```

两条命令的失败方式都很"干净"——不产生半成品文件，也不影响实例本身，所以在远程实例上试一下确认环境不满足是无害的。

## 踩坑点

- **license 报错的根因是环境类型**：实例 ID 通常派生自本地安装的机器特征。connect-remote 模式下 CLI 只是远端的客户端，拿不到（也不该生成）远端机器的实例 ID。要在**自建/本地 env**（`--setup-mode install-new` 或 `manage-local` 装出来的实例）上执行才能成功。
- **scaffold 报 `spawn nocobase-v1 ENOENT` 不是 nb 装坏了**：脚手架靠调用本地 NocoBase 源码树里的生成器（`nocobase-v1` 可执行文件），当前环境只有 npm 全局的 CLI、没有源码树，`spawn` 自然找不到这个命令。官方文档也明确要求 scaffold "require a source tree"。
- 也就是说，这两个报错都说明"命令没问题，环境不满足"，不需要反复重装 CLI。

## 问题现象

两个命令的报错表面完全无关，实际是同一个原因的两面：它们依赖的能力在远端实例上根本不存在。

## 什么时候用 / 怎么用

排查思路小结：看到 `does not support automatic instance ID generation` 或 `spawn nocobase-v1 ENOENT`，先问自己"这个命令操作的对象在哪"——对象在远端实例或根本不在本机，就说明该切环境了，而不是 CLI 坏了。

```bash
# 切到本地自建 env 再执行这两类命令
nb env use local      # 指向 install-new/manage-local 装出的本地实例
nb license id
nb scaffold plugin @my-scope/my-plugin
```

环境管理本身（`nb env add/use/list` 等）见同系列 env 管理一篇；源码下载与插件开发链路见本地自建命令一篇。

**经验总结**：`nb` CLI 的命令按"作用对象"分了两类——作用于远端实例的（走 HTTP API，connect-remote 可用）和作用于本机安装的（进程、容器、源码、机器标识）。分不清时就看命令名：`nb api *` 一定是前者，其余的先确认本机有没有对应对象。

本文测试环境为 connect-remote 模式连接的远程 NocoBase 2 实例，CLI 版本 2.x；不同版本的子命令集合可能有出入。

- 需要激活商业许可：先在自建机器上用 `nb init --setup-mode install-new` 装一个本地实例，再在同一个 env 下执行 `nb license id` 拿实例 ID。
- 需要开发插件：先 `nb source download` 拉一份 NocoBase 源码（或在克隆出的源码仓库里），保证 `nocobase-v1` 在 PATH 中可见，再执行 `nb scaffold plugin`；生成的骨架配合本地 `nb app` / `nb db` 命令做联调。
- 纯远程实例的日常管理（查数据、配 ACL、备份）不受影响，这两条命令跳过即可。
