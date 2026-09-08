---
layout: post
title: "nb CLI 总览：一张命令地图玩转 NocoBase"
date: 2026-09-09 10:00:00 +0800
categories: [NocoBase]
tags: [nocobase, cli, nb, overview]
---

最近在用 NocoBase 2.x 做项目，`nb` 这个官方 CLI 几乎接管了我所有日常操作：连实例、看环境、管插件、备份数据、写 API。命令不少，第一次 `nb --help` 看下去容易迷路，这篇先把整张命令地图画出来，作为系列的索引篇——后面几篇会逐个展开高频子命令。

## nb 是什么，能干两件什么样的事

`nb` 的所有能力都围绕"环境（env）"展开，而环境分两类，这决定了哪些命令对你可用：

1. **远程环境（connect-remote）**：你只有一个已部署好的 NocoBase 实例的 URL 和账号，CLI 通过 HTTP API 操作它。比如公司的 SaaS 实例、demo 实例。
2. **本地环境（install-new / manage-local）**：实例跑在你自己机器上（npm 源码或 Docker），CLI 除了调 API，还能管进程、管数据库容器、管反向代理。

```bash
# 远程：只连接，不部署
nb init -y -e demo --setup-mode connect-remote \
  -u https://<your-instance>.demo.nocobase.com/api \
  -a basic --username <管理员账号> --password <密码>

# 本地：全新装一套（可带内置数据库容器）
nb init --setup-mode install-new --ui
```

**远程环境能用**的是所有走 API 的命令：`api`、`plugin`、`backup`、`revision`、`skills`、`session`、`config`、`self`、`env`。**本地环境专属**的是那些要碰进程和文件系统的：`app`、`db`、`proxy`、`source`、`scaffold`。在远程环境跑本地专属命令，要么报错要么直接不存在——这是第一个要建立的认知。

## 完整命令地图

### 连接与环境

| 命令 | 一句话用途 |
|------|-----------|
| `nb init` | 初始化/连接一个环境，三选一 setup-mode |
| `nb env current / list / info / status` | 看当前环境、列所有环境、看某环境详情、做健康检查 |
| `nb env add / use / update / remove / auth` | 增删改环境、切换、改认证信息 |

### 配置与自检

| 命令 | 一句话用途 |
|------|-----------|
| `nb config list / get / set` | CLI 自身的配置（如提示语言 locale） |
| `nb self check` | 检查 CLI 版本、安装方式、有没有新版本 |
| `nb session id` | 查当前会话 UUID，对应日志目录名 |
| `nb skills check/install/update/remove` | 管理给 AI agent 用的 nocobase-* 技能 |

### 业务操作（远程可用）

| 命令 | 一句话用途 |
|------|-----------|
| `nb api <topic> <action>` | 直调实例 REST API，topic 就是资源名（app/pm/acl/ai/kb/workflow/resource…） |
| `nb plugin list` | 快速看插件启用状态（轻量版 `api pm list`） |
| `nb backup create / restore / download / status` | 建备份并自动下载、恢复、迁移 |
| `nb revision create "描述"` | 把当前构建存成可回滚的修订点 |

### 本地/自建环境专属

| 命令 | 一句话用途 |
|------|-----------|
| `nb app start/stop/restart/logs/upgrade` | 管本地 NocoBase 进程（npm/git 走 pm2，Docker 走 docker） |
| `nb db check/ps/start/stop/logs` | 管内置数据库容器 |
| `nb proxy nginx/caddy` | 给 CLI 管的 app 生成反向代理配置 |
| `nb source download/dev/build/test/publish` | 本地源码项目的开发构建发布 |
| `nb scaffold plugin <name>` | 在本地源码树里脚手架一个插件 |

## nb api：最常用的子命令树

`nb api` 是日常重度区，topic 基本就是实例的 REST 资源，我按用途分组：

- **应用**：`app get-info / get-lang / get-plugins / clear-cache / restart` —— 实例版本、方言、运行时插件、清缓存
- **插件**：`pm list / get / list-enabled / add / update / remove / enable / disable` —— 插件全量元数据与生命周期，`--filter-by-tk` 指插件名
- **权限**：`acl roles ...`、`roles-resources-scopes`、`available-actions`、`data-sources`
- **数据建模**：`data-modeling collections / fields / data-sources / db-views` —— 建集合建字段最顺手的入口
- **业务数据**：`resource list/get/create/update/destroy/query`，支持 `posts.comments` 关联写法和 `--data-source` 外部源
- **工作流**：`workflow workflows / executions / flow-nodes / jobs`
- **AI**：`ai employees / llm-services / llm-providers`
- **知识库**：`kb list / create / run-hit-test / list-external-vector-store-providers`
- **备份迁移**：`backup list`、`migration list / check / create / execute`
- **其它**：`system-settings`、`authenticators`、`api-keys`、`file-manager`、`theme-editor`、`flow-surfaces`（Modern UI 页面组装）

```bash
# 三个高频例子
nb api app get-info
nb api pm get --filter-by-tk acl
nb api resource create --resource blog_notes --values '{"title":"hello"}'
```

## 实测效果

```bash
$ nb env current
demo

$ nb self check
Current version  2.2.8
Latest version   2.2.8
Channel          latest
Install method   npm-global
Update available no

$ nb api app get-info
{"database":{"dialect":"postgres"},"version":"2.4.0-alpha.4","lang":"en-US",...}

$ nb backup create
# 约 24~40s，服务端创建 + 自动下载
# backup_20260908_215255_9761.nbdata
```

## 踩坑点

1. **URL 的 `/api` 后缀**：`nb init` 要求 `-u` 的地址**必须**带 `/api` 前缀，否则直接报错；但 DSL 那套工具链相反，`NB_URL` 不能带 `/api`（它自己拼）。两套规则并存，混用必炸。
2. **`env list -j` 不存在**：`Nonexistent flag: -j`，不是所有命令都支持 JSON 输出，遇到先 `--help`。
3. **revision 只有 create**：没有 `revision list`，且描述是位置参数不是 `--description`。
4. **远程环境跑本地命令**：`nb scaffold plugin` 会报 `spawn nocobase-v1 ENOENT`，因为它需要本地源码树；`nb license status` 在远程 demo 环境也报不支持自动生成实例 ID。
5. **共享实例慎动**：`pm add/remove`、`app restart`、`restore` 这类破坏性/影响全局的命令，在多人共用的实例上别随手跑。

## 什么时候用 nb

- 只有一个远程实例、想用脚本/命令行而不是点 UI：用 `env` + `api` + `backup` + `revision`。
- 在自己机器上开发插件、调试本地实例：用 `init install-new` + `app` + `db` + `scaffold`。
- 配合 Claude Code 等 AI 工具做 NocoBase 开发：`nb skills` 同步的那套技能就是给它们看的。

## 系列后续篇目

- [nb init 连接远程实例](/2026/09/09/nb-init-connect-remote/)：connect-remote 全流程与冷启动超时诊断
- [nb env 环境管理](/2026/09/09/nb-env-manage/)：current/list/info/status 与多环境切换
- [nb config / self / session](/2026/09/09/nb-config-self-session/)：CLI 配置、版本检查、日志目录对应关系
- [nb skills 技能同步](/2026/09/09/nb-skills-sync/)：AI 技能的装、更、删与 20 个技能的用途分组
