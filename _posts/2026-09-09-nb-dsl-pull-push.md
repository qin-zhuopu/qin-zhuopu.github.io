---
layout: post
title: "NocoBase DSL 导出/导入实战：pull 全量 YAML、push 回写与 NB_URL 的反直觉坑"
date: 2026-09-09 16:00:00 +0800
categories: [NocoBase]
tags: [nocobase, cli, nb, dsl, yaml]
---

想在 git 里管理 NocoBase 应用的页面、菜单、工作流和模型？DSL 导出/导入是官方给出的路子：`pull` 把整个应用导出成一套 YAML 文件，改完后 `push` 回写实例。这套命令走的是工作区（workspace）目录 + 一个 `cli.ts` 入口，和 `nb` 其它命令有两个明显差异，其中一个坑和 `nb init` 的要求正好相反。

## 问题背景

NocoBase 的配置存在数据库里，UI 上点点改改不会留下可评审的记录。DSL 这套命令把应用配置序列化成 YAML 文件，从此页面、菜单、工作流都能像代码一样 diff、review、回滚。

## 命令用途

- `pull <workspace>`：从实例**全量导出** YAML 到工作区目录。
- `push <workspace>`：把工作区的 YAML **回写**到实例（push 前有 spec 校验器把关）。
- `export`：导出单个页面（比全量 pull 轻）。
- `export-acl` / `export-workflows`：单独导出权限、工作流。
- `diff`：比较工作区与实例的差异。
- `graph` / `verify-data`：依赖/引用图与数据校验。

## 语法与常用参数

这套命令不走 `nb` 的子命令，而是通过一个 `cli.ts` 入口（通常配合 `npx tsx` 执行），工作区（workspace）目录是它的操作单位：

```bash
# 从模板/仓库初始化出工作区后，全量拉取
npx tsx cli/cli.ts pull workspaces/<project>

# 修改 YAML 后回写
npx tsx cli/cli.ts push workspaces/<project>

# 辅助
npx tsx cli/cli.ts diff   workspaces/<project>
npx tsx cli/cli.ts graph  workspaces/<project>
npx tsx cli/cli.ts export <page> ...
```

## 实测效果

`pull` 之后的工作区结构大致是：

```text
workspaces/<project>/
├── routes.yaml          # 路由/菜单树
├── pages/               # 每个页面的区块配置
├── templates/           # 区块模板（实测导出 236 个）
├── workflows/           # 工作流定义
└── collections/         # 集合定义（该实例为 0，见下）
```

改完 YAML 再 `push`，实例上的路由、页面、工作流随之更新，回写生效。注意 collections 目录为空的原因：这个实例的集合定义挂在各 AI Portal 的源码里，DSL 导出走的是实例元数据，所以拉不到它们——这类模型改动要用 `nb api data-modeling` 那条路。

## 踩坑点

- **`NB_URL` 不能带 `/api`，与 `nb init` 正好相反**。`nb init` 要求 URL **必须包含** `/api` 前缀，否则直接报错；而 DSL 的 `cli.ts` 会自己拼 `/api`，你给的 `NB_URL` 带 `/api` 反而拼出 `/api/api/...` 导致请求 404。两套入口各自记清楚，最稳妥的做法是给 `cli.ts` 单独 export 一个不带 `/api` 的变量。
- push 前有 spec 校验器，YAML 结构不合规范会被拦下。改文件时保留字段层级、不要手写未知的键，先小改小 push 验证一遍。
- `pull` 是全量的（该实例 templates 就有 236 个文件），提交 git 前先看 diff，别把无关模板的漂移一起带进提交。
- collections 拉不到的情况见上——DSL 管页面/路由/工作流，数据模型多半要配合 `nb api data-modeling` 操作。
- 冷启动的远程实例首次请求可能超过 60 秒才响应（TCP/TLS 握手正常但无输出），pull 时别急着当成超时报错，等实例唤醒后即可恢复正常速度。
- YAML 里的中文文本保持 UTF-8；编辑器自动加的 BOM 或把缩进转成 tab 都会让校验器报格式错误。

## 推荐工作流

```bash
# 1. 从实例全量拉取
npx tsx cli/cli.ts pull workspaces/app
# 2. 提交一个基线，方便评审后续改动
git add workspaces/app && git commit -m "dsl: baseline"
# 3. 修改 YAML（新页面/菜单项/工作流）
npx tsx cli/cli.ts diff workspaces/app     # 确认改动面
# 4. 回写并验证
npx tsx cli/cli.ts push workspaces/app
```

## 什么时候用

- 想把应用配置纳入 git：代码评审、回滚、多环境迁移（pull → commit → push 到另一个实例）。
- 批量修改页面/菜单结构：手改 YAML 比 UI 上一格格点快得多，`diff` 和 `graph` 帮你确认改动影响面。
- 只是临时调一两个区块：用 `export` 单页导出即可，不必每次全量 `pull`。
