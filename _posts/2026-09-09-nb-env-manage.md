---
layout: post
title: "nb env 环境管理：current/list/info/status 实测与多环境切换"
date: 2026-09-09 12:00:00 +0800
categories: [NocoBase]
tags: [nocobase, cli, nb, env]
---

nb CLI 的所有命令都作用在"当前环境"上，所以 `nb env` 这组命令是整个 CLI 的方向盘。这篇把四个只读子命令的实测输出贴出来，再讲多环境怎么切换。

## 命令用途

`nb env` 管理的是 CLI 侧的环境注册表——每个环境记录实例地址、认证方式、运行时形态。子命令分两类：

- **只读查看**：`current`、`list`、`info`、`status`
- **增删改**：`add`、`use`、`update`、`remove`、`auth`

前一篇讲过环境可以用 `nb init -e <name>` 创建，`env add` 是等价的另一条路。

## 语法与常用参数

```bash
nb env current          # 当前环境名
nb env list             # 所有环境表格
nb env info [name]      # 某环境详情（默认当前）
nb env status [name]    # 健康检查
nb env use <name>       # 切换
nb env remove <name>    # 删除
```

一个要先泼的冷水：**`list` 不支持 `-j`**。我习惯性想拿 JSON 做脚本解析，直接被打回：

```bash
$ nb env list -j
error: Nonexistent flag: -j
```

想在脚本里用环境数据，老老实实解析表格文本，或者用 `env info` 的分组输出。

## 实测效果

```bash
$ nb env current
demo

$ nb env list
Name  Kind    API Base URL                                    Auth    Runtime
demo  remote  https://<your-instance>.demo.nocobase.com/api   basic   http

$ nb env info
Env
  Name              demo
  Kind              remote

App
  appStatus         http

DB
  databaseStatus    external

API
  apiBase           https://<your-instance>.demo.nocobase.com/api
  authMode          basic
```

`env info` 分成 Env / App / DB / API 四组。远程环境有两个特征值很说明问题：`appStatus=http`（应用只以 HTTP 服务形态存在，本地没有进程可管）和 `databaseStatus=external`（数据库在远端，`nb db` 那组命令不可用）。这两个值可以直接当作"这是不是远程环境"的判据。

```bash
$ nb env status
ok
```

`status` 输出极简，就一个 `ok`（不健康时会给出原因），适合放在脚本开头当哨兵：

```bash
nb env status >/dev/null 2>&1 || { echo "env not reachable"; exit 1; }
```

## 多环境切换实践

典型的多环境布局：一个远程测试实例 + 一个本地开发实例。

```bash
$ nb init -y -e demo --setup-mode connect-remote -u https://<your-instance>.demo.nocobase.com/api ...
$ nb init -y -e local --setup-mode install-new

$ nb env list
Name   Kind    API Base URL                                    Auth    Runtime
demo   remote  https://<your-instance>.demo.nocobase.com/api   basic   http
local  local   http://127.0.0.1:13000/api                      basic   pm2

$ nb env use local
$ nb env current
local
```

切换是全局的、立即生效——之后所有 `nb api`、`nb backup` 都打到新环境上。这点要特别小心：**没有 `--env` 参数的按命令覆盖**（至少当前版本没有），执行破坏性命令前先 `nb env current` 确认一遍，是成本最低的防呆。

另外 `nb env auth <name>` 可以单独更新某环境的认证信息，实例改了密码后不用 remove 再 add。

## 踩坑点

1. `list` 不支持 `-j`（上文），也不要指望其它子命令都有 JSON 输出。
2. 远程环境的 `appStatus=http` / `databaseStatus=external` 意味着 `nb app start`、`nb db ps` 这类命令对它无意义，跑了会失败——这不是 bug，是环境形态决定的。
3. 环境名冲突：`init` 一个已存在的名字会走更新路径而不是报错，想重建先 `remove`。
4. `env remove` 只删 CLI 侧的注册记录，不会动远程实例本身——放心删，但也别指望它帮你清理实例。

## 什么时候用

- 日常开工第一件事：`nb env current` 确认自己在哪，再干活。
- 写自动化脚本：用 `nb env status` 做前置健康检查。
- 同时维护测试/生产/本地多套 NocoBase：`env use` 切换，配合破坏性命令前的 `env current` 二次确认。

## 系列其它篇目

- [nb CLI 总览](/2026/09/09/nb-cli-overview/)
- [nb init 连接远程实例](/2026/09/09/nb-init-connect-remote/)
- [nb config / self / session](/2026/09/09/nb-config-self-session/)
- [nb skills 技能同步](/2026/09/09/nb-skills-sync/)
