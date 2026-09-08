---
layout: post
title: "nb CLI 的本地自建专属命令：app / db / source / proxy"
date: 2026-09-09 15:00:00 +0800
categories: [NocoBase]
tags: [nocobase, cli, nb, self-hosted, pm2]
---

`nb` CLI 有一组命令只在**本地自建环境**下有意义：管理应用进程、内置数据库容器、本地源码和反向代理配置。如果你像笔者一样主要用 connect-remote 模式连远程实例，这组命令会全部用不上——但自建部署时它们就是日常。这篇把它们的用途和边界讲清楚。

## 命令用途

- `nb app start / stop / restart / logs / upgrade`：管理本地 NocoBase 应用进程与升级。
- `nb db check / ps / start / stop / logs`：管理 CLI 内置的数据库容器。
- `nb source download / dev / build / test / publish`：本地源码项目的下载、开发、构建、测试、发布。
- `nb proxy nginx / caddy`：为 CLI 管理的 app 生成 Nginx / Caddy 反向代理配置。

## 语法与常用参数

```bash
# 应用生命周期（本地 npm/git 部署用 pm2，Docker 部署用 docker）
nb app start
nb app stop
nb app restart
nb app logs          # 跟踪服务端日志
nb app upgrade       # 升级 NocoBase 版本

# 内置数据库容器
nb db check          # 检查数据库可用性
nb db start / stop / ps / logs

# 源码
nb source download   # 拉取 NocoBase 源码（scaffold 插件的前提）
nb source dev / build / test / publish

# 反向代理
nb proxy nginx       # 生成 nginx 配置
nb proxy caddy       # 生成 caddy 配置
```

## 实测效果

在 connect-remote 模式的环境上，这组命令不适用——帮助文本里已经写明它们的适用对象是"CLI 安装并管理的本地 app"。切换到自建 env（`nb init --setup-mode install-new` 或 `manage-local`）后：

- `nb app start` 会根据部署形态选择进程管理器：npm/git 方式走 **pm2**，Docker 方式走 **docker**；
- `nb db` 系列对应的是 `init` 时选择内置数据库而起的容器；
- `nb proxy nginx` 生成的配置里已含正确的 upstream 端口，贴进 `/etc/nginx/...` 即可。

一个典型的自建部署链路：

```bash
nb init --setup-mode install-new -e local --ui   # 引导式安装，可含内置 DB
nb db start                                       # 起数据库容器
nb app start                                      # 起 NocoBase（pm2 / docker）
nb app logs                                       # 看启动日志确认就绪
nb proxy caddy                                    # 生成反代配置对外暴露
```

远程模式下的等价操作则完全不同：重启远端要靠 `nb api app restart`（异步），清缓存靠 `nb api app clear-cache`，看版本用 `nb api app get-info`。

两种模式的命令对照：

| 需求 | 本地自建 | connect-remote |
|------|---------|----------------|
| 重启应用 | `nb app restart` | `nb api app restart` |
| 看日志 | `nb app logs` | 拿不到（只能看远端控制台） |
| 清缓存 | `nb app clear-cache` | `nb api app clear-cache` |
| 数据库 | `nb db ps/start/...` | 外部库，CLI 不管 |
| 版本信息 | `nb app ...` | `nb api app get-info` |

## 踩坑点

- **connect-remote 下不要期待这些命令能作用到远端**。它们管理的对象是本机进程/容器，远程实例的进程你根本碰不到；远端操作请走 `nb api app ...`。
- `nb app upgrade` 会改动本地 NocoBase 版本，升级前先 `nb backup create` + `nb revision create` 留退路。
- `nb db` 只管 **CLI 内置**的数据库容器；如果你自建时连的是外部 Postgres（远程 env 的 `databaseStatus` 就是 external），`nb db ps` 看不到它，要用 `nb env info` 确认数据库归属。
- `nb source download` 拉源码是 `nb scaffold plugin` 能跑起来的前提，缺源码时会报 `spawn nocobase-v1 ENOENT`。

## 什么时候用

- 自己在服务器或本机装了一套 NocoBase（install-new / manage-local）：app、db、proxy 三件套就是你的 systemd + 运维面板。
- 想做插件开发：`nb source download` → `nb scaffold plugin` → `nb source dev/build/test` 的完整链路。
- 只是远程管理一个 demo/托管实例：忽略本篇全部命令，直接用 `nb api` 系列。
