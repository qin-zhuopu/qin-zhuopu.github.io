---
layout: post
title: "nb api flow-surfaces：NocoBase Modern UI 页面组装的底层 API"
date: 2026-09-09 17:00:00 +0800
categories: [NocoBase]
tags: [nocobase, cli, nb-api, flow-surfaces, ui]
---

用 NocoBase 2 的界面拖页面时，背后到底发生了什么？答案是 flow-surfaces——Modern UI 的页面/区块/动作组装层。`nb api flow-surfaces` 把这层直接暴露到了命令行，于是"建页面、加表格、配弹窗"这些原本只能拖拽的事，全部变成了可脚本化的 API 调用。这篇记录它的能力地图、几个核心命令的用法，以及"什么时候绕过 UI 直接用它"。

## 命令用途

```bash
nb api flow-surfaces --help
```

能力可以归成六类：

```text
读      get                 读单个页面/标签页/弹窗的结构化回读
        describe-surface    更细的结构读回
        catalog             能力目录：可用区块、动作、配置项元数据
写(整页) apply-blueprint      一次提交整页蓝图 JSON，后端负责编译装配
写(局部) add-block / add-field / add-action / addRecordAction / compose
        configure / update-settings / set-layout
        move-* / remove-*
菜单/页  create-menu / update-menu / create-page / destroy-page
标签页   add-tab / update-tab / move-tab / remove-tab（弹窗内标签页同理 add-popup-tab）
联动/事件 get-reaction-meta + set-field-value-rules / set-field-linkage-rules ...
        get-event-flow-meta + add-event-flow / set-event-flow(s) / remove-event-flow
模板     list-templates      列出可复用的区块/弹窗模板
```

## 语法与常用参数

通用形态是"目标 + 类型 + 业务对象"：

```bash
# 目标是 {uid: string}，复杂对象推荐用 --body-file 传 JSON
nb api flow-surfaces add-action -e <env> -j \
  --target '{"uid": "<容器/区块 uid>"}' \
  --type '<动作类型>' \
  --settings '<高频设置>'

# 记录级动作（表格行上的按钮）用另一个入口
nb api flow-surfaces addRecordAction --target '{"uid": "<表格 uid>"}' ...

# 局部微调高频设置：页/标签标题、表格 pageSize、字段点击打开、动作确认弹窗等
nb api flow-surfaces configure -e <env> -j --body '<changes 对象>'

# 整页创建：一份蓝图 JSON 进，页面+菜单+区块+动作一次落地
nb api flow-surfaces apply-blueprint --body-file <page-blueprint>.json -e <env> -j
```

弹窗模板是这组 API 里最有意思的部分：

```bash
# 先看有哪些可复用模板
nb api flow-surfaces list-templates -e <env> -j

# 动作上直接挂弹窗复用语义
#   popup.template  : 显式指定模板，mode 取 reference（引用，跟随更新）或 copy（复制一份）
#   popup.tryTemplate: true 时后端自动挑兼容模板（优先同关联，退而求非关联模板）
#   popup.saveAsTemplate: { name, description }，把本地弹窗内容顺手存成新模板
nb api flow-surfaces add-action -e <env> -j \
  --target '{"uid": "<表格 uid>"}' --type '<动作类型>' \
  --popup '{"template": {"uid": "<模板uid>", "mode": "reference"}, "title": "详情"}'
```

## 实测效果

- `catalog` / `get-reaction-meta` / `get-event-flow-meta` 这组"元数据读"很关键：它告诉你**当前容器里哪些动作/区块是可见可建的**，直接 `add` 一个目录里没有的东西会被拒。
- `apply-blueprint` 是官方给 agent/脚本准备的正门：提交的蓝图 JSON 会经后端"编译器"归一化，硬校验失败时返回聚合的 `errors[]`（一次列出所有问题，而不是改一个错一个）。
- 局部命令有明确的分工：`add-action` 只管非记录动作（表格上的"新增/删除"、表单提交、筛选重置、动作面板按钮），**行内按钮必须走 `addRecordAction`**；直接 add 不接受裸 `props` / `decoratorProps` / `stepParams` / `flowRegistry`，要改配置就用 `settings` 或 `configure.changes`。
- 模板复用语义由后端兜底：`tryTemplate=true` 命中模板就直接复用，未命中则回退到本地 `popup.blocks` 内容，所以本地内容仍然值得写一份作为兜底。

## 踩坑点

1. **动作入口选错是最常见的报错来源**。表格行按钮用 `add-action` 会被拒；反过来把记录动作塞进 `addRecordActions` 批量命令也会被逐条拒。判断标准就一条：按钮是否需要"当前行"作为上下文。
2. **不要给业务对象再包一层信封**。`--body-file` 里放的应该是裸的业务 JSON，别再裹 `cliBody` 之类的壳；校验失败的 `errors[]` 多半也在提示形状不对。
3. **`popup.template` 与本地内容的关系**：一旦显式给了 `popup.template`，本地 `popup.mode/blocks/layout` 会被接受但忽略，`popup.title` 仍然生效；`saveAsTemplate` 不能与 `template` 同用，但可以与 `tryTemplate=true` 共存（命中复用、未命中保存）。
4. **局部写之前先读**。做"事件流/联动规则"整体替换（`set-event-flows`）时，要用 live 读回的完整结构，自己拼一个部分结构会把别的规则覆盖掉。
5. **审批类动作键是单例的**：同一个审批表单/流程表单里审批动作 key 不可重复，写入成功后后端会同步调整关联工作流节点的运行时配置——这条副作用要知道。
6. **权限与门户前置**：flow-surfaces 写入的目标页面挂在某个 Portal/布局下，目标不可达时先解决环境与角色问题，而不是换命令重试。

## 什么时候用

- **批量建页/复制结构**：十几个结构相似的数据维护页，写一份蓝图模板循环 `apply-blueprint`，比拖几十分钟快且一致。
- **可评审的 UI 变更**：蓝图 JSON 存进 git，改动可 diff、可回滚——UI 拖拽给不了这个。
- **模板化弹窗治理**：`list-templates` + `popup.template`（reference 模式）让二十个页面的"详情弹窗"改一处全局生效。
- **什么时候仍然用 UI**：单页、一次性的小调整，或需要边看边调的视觉微调，直接拖拽更高效；flow-surfaces 的价值在**规模化与可重复**，不在单次便利。

## 参考

- 本地帮助：`nb api flow-surfaces --help`，以及各子命令的 `--help`（`add-action` 的长描述几乎是这份 API 的设计说明书）
- 相关前篇：`nb api resource`（数据侧 CRUD）、`nb api acl`（角色对菜单/页面的可见性）
