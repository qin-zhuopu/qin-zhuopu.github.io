---
layout: post
title: "nb skills：给 AI 装一套 NocoBase 技能，20 个 nocobase-* 各管什么"
date: 2026-09-09 14:00:00 +0800
categories: [NocoBase]
tags: [nocobase, cli, nb, skills, ai]
---

用 Claude Code 这类 AI 工具操作 NocoBase 时，光有 `nb` 命令不够——AI 得知道这套命令怎么组合、有哪些约定、踩过哪些坑。`nb skills` 就是干这个的：把一套官方维护的 `nocobase-*` 技能同步到本地，供 AI 工具加载。这篇讲它怎么用，以及 20 个技能分别管什么。

## 命令用途

```bash
nb skills check     # 查看同步状态与版本
nb skills install   # 安装/同步技能
nb skills update    # 升级到最新
nb skills remove    # 移除
```

## 实测效果

```bash
$ nb skills check
Skills home      ~/.nocobase
Installed        yes
Managed by nb    yes
Version          2.0.58
Skills           20 (nocobase-*)
```

四个关键信息：技能家目录在 `~/.nocobase`、已安装、由 nb 托管（意味着能被 `nb skills update/remove` 统一管理，不是你手动拷贝的散文件）、版本 2.0.58。

还有一个隐藏入口：**`nb init` 时会自动同步**。连远程实例那次，输出里就有一行 `Syncing agent skills...`——不需要你额外跑 `nb skills install`。所以典型情况下这组命令你只会用到 `check` 和 `update`。

## 语法要点

- `check` 是无副作用的，可以随手跑
- `update` 升级技能包内容；**升级 CLI（`nb self` 那边）不会自动升级技能**，两套版本独立，要分别更
- `remove` 之后想恢复，再跑 `install`（或重跑 `nb init`）即可

## 20 个技能的用途分组

技能名都带 `nocobase-` 前缀，按职责大致分五组：

**入口与分发**
- `nocobase-portal-manage`：UI 相关请求的总入口/分发器，先确定用哪个 Portal 再往下走
- `nocobase-ui-builder`：页面、区块、字段、动作、布局的搭建（接在 portal-manage 之后）
- `nocobase-ai-builder`：源码型 AI Portal 的开发
- `nocobase-prototype-repro`：照着 HTML 原型/参考图还原页面

**数据与模型**
- `nocobase-data-modeling`：集合、字段、关系、视图
- `nocobase-data-analysis`：查数、分组统计、跨数据源分析

**运维与治理**
- `nocobase-env-manage`：初始化、进程生命周期、CLI/技能维护
- `nocobase-plugin-manage`：插件启停与巡检
- `nocobase-acl-manage`：角色、权限策略、Portal 访问
- `nocobase-publish-manage`：备份恢复与迁移发布
- `nocobase-revision`：把里程碑存成可回滚修订（对应 `nb revision`）
- `nocobase-file-manager`：文件存储引擎与文件集合
- `nocobase-notification-manage`：站内信、邮件 SMTP、工作流通知
- `nocobase-workflow-manage`：工作流的查、建、改、排障

**AI 能力**
- `nocobase-ai-manager`：LLM provider、模型、密钥配置
- `nocobase-ai-employee`：AI 员工的创建与维护
- `nocobase-ai-knowledge-base-manager`：知识库与向量库

**开发与工具**
- `nocobase-plugin-development`：插件开发全流程（脚手架、服务端、客户端、i18n）
- `nocobase-dsl-reconciler`：YAML/DSL 导出导入路径（opt-in）
- `nocobase-utils`：过滤条件语法、表达式求值等通用参考

不需要背这个表——技能的 description 写得很详细，AI 会按任务自动触发。但知道分组有个实际好处：**排障时能判断该让 AI 用哪个技能**，比如权限问题指到 acl-manage 而不是让它瞎试 API。

## 踩坑点

1. **版本错位**：CLI 2.x 配技能 2.0.x，两套版本号不同步。行为对不上技能文档时，先 `nb skills check` 看版本，再 `nb skills update`。
2. **手动改文件会被覆盖**：`Managed by nb yes` 说明目录是托管的，直接改 `~/.nocobase` 下的技能内容，下次 update 就没了。想定制，应该复制一份出去改，别原地改。
3. **技能只是"说明书"**：它告诉 AI 怎么做，实际执行还是靠 `nb api` 等命令——所以技能、CLI、实例三者版本要大体匹配，太老的技能描述新实例的 API 会对不上。
4. **init 只同步一次**：init 之后官方更新了技能，不会自动跟上，要手动 `nb skills update`。

## 什么时候用

- 第一次用 AI 工具接 NocoBase：`nb init` 之后跑一次 `nb skills check` 确认装好了。
- 定期维护：升级 CLI 后顺手 `nb skills update`。
- 换机器 / 换 AI 工具：`~/.nocobase` 目录可以整体带走，或在 mejor机重新 `install`。

## 系列其它篇目

- [nb CLI 总览](/2026/09/09/nb-cli-overview/)
- [nb init 连接远程实例](/2026/09/09/nb-init-connect-remote/)
- [nb env 环境管理](/2026/09/09/nb-env-manage/)
- [nb config / self / session](/2026/09/09/nb-config-self-session/)
