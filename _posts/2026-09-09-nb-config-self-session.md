---
layout: post
title: "nb config / self / session：CLI 配置、版本检查与日志目录对应关系"
date: 2026-09-09 13:00:00 +0800
categories: [NocoBase]
tags: [nocobase, cli, nb, config]
---

这三个命令是最不起眼、但排障时最常翻出来的一组：`config` 管 CLI 自身的配置项，`self` 管 CLI 自己的版本，`session` 管"这次操作属于哪一次会话"。平时感觉不到它们，等 CLI 行为奇怪、想报 issue、想翻日志的时候，全靠它们。

## 命令用途

| 命令 | 用途 |
|------|------|
| `nb config list / get / set` | 读写 CLI 自身配置（如提示语言 locale） |
| `nb self check` | 当前版本、最新版本、更新通道、安装方式 |
| `nb session id` | 输出当前会话的 UUID |

注意它们管的都是 **CLI 本身**，不是 NocoBase 实例——实例的系统设置要走 `nb api system-settings`。

## nb config

```bash
$ nb config list
No CLI config values are set.

$ nb config get locale
zh-CN

$ nb config set locale zh-CN
```

刚装完 `config list` 是空的，因为大多数配置有默认值、只有显式改过的才会落盘。`locale` 控制的是 **CLI 的提示语言**（报错文案、交互提示），不是实例的界面语言——两者互不影响，实例侧的语言在 `nb api system-settings` 和用户设置里。

## nb self

```bash
$ nb self check
Current version   2.2.8
Latest version    2.2.8
Channel           latest
Install method    npm-global
Update available  no
```

五个字段各有用处：

- `Current / Latest`：一眼看出是不是落后了
- `Channel`：更新通道（latest / beta 之类），切通道后升级行为会变
- `Install method`：**排障最关键**。npm-global、npm-local 等不同安装方式决定了升级命令和配置目录位置。报 issue 时贴上它，维护者能立刻复现你的环境
- `Update available`：直接判断要不要升

CLI 版本和技能版本是两回事：`nb self check` 看 CLI，`nb skills check` 看同步下来的技能包版本（本例里技能是 2.0.58，CLI 是 2.2.8，两者独立演进）。升级 CLI 之后记得单独跑 `nb skills update`，否则技能还是旧的。

## nb session 与日志目录

```bash
$ nb session id
3f2a1c9e-8b4d-4f6a-9c1e-2d7b5a8e0f31
```

这个 UUID 不是摆设——**它就是日志目录的名字**：

```bash
$ ls ~/.nocobase/logs/2026-09-09/
3f2a1c9e-8b4d-4f6a-9c1e-2d7b5a8e0f31/
```

目录结构是 `~/.nocobase/logs/<日期>/<session-id>/`。实际用法是：跑一条会留下痕迹的操作（比如 `nb backup create`、一次 `nb api` 失败），先记下 `nb session id`，失败后直接去对应目录里翻详细日志，而不是在一堆日志里按时间猜。

给 AI 工具用的时候这个对应关系尤其有用：让 agent 输出 session id，你就能立刻定位它这次操作留下的全部日志。

## 实测小结与踩坑点

1. `config list` 为空 ≠ 没有配置，只是没有覆盖默认值。想确认某个具体项，用 `config get <key>`。
2. `self check` 需要联网查最新版本；离线机器上 Latest 字段可能拿不到，不要因此误判安装坏了。
3. `session id` 每次 CLI 交互可能不同——先跑 `nb session id` 记下来，再去执行要排障的命令，顺序反了就找不到目录了。
4. 日志在用户主目录下（`~/.nocobase`），不在项目目录里，全局搜项目时容易漏。

## 什么时候用

- CLI 行为怪异 / 想提 issue：`self check` 贴环境信息 + `session id` 对应的日志一起给。
- 写脚本：`self check` 里的 `Update available` 可以做版本漂移提醒。
- 多人协作或 agent 自动化：用 session id 把"哪次操作"和"哪份日志"对上。

## 系列其它篇目

- [nb CLI 总览](/2026/09/09/nb-cli-overview/)
- [nb init 连接远程实例](/2026/09/09/nb-init-connect-remote/)
- [nb env 环境管理](/2026/09/09/nb-env-manage/)
- [nb skills 技能同步](/2026/09/09/nb-skills-sync/)
