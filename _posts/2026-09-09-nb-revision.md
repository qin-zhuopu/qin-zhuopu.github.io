---
layout: post
title: "nb revision create：给 NocoBase 应用打一个可回滚的修订点"
date: 2026-09-09 13:00:00 +0800
categories: [NocoBase]
tags: [nocobase, cli, nb, revision]
---

`nb backup` 备的是数据，`nb revision` 存的是应用配置的一个"构建快照"——完成一个有意义的里程碑（比如搭完一组页面、配完一条工作流）之后打一个修订点，后面改砸了可以回到这里。命令极简，但参数形式有个容易踩的坑。

## 问题背景

用 `nb` 或 AI 技能对 NocoBase 做批量改动时，最怕的不是改不动，而是改完才发现不对、又说不清改了哪些地方。revision 就是为此准备的"存档点"。

## 命令用途

`nb revision create` 把当前应用状态保存为一个可回滚的修订（revision）。适合作为"安全点"：改动前打一个，改动验证通过后再打下一个，形成一条可回退的时间线。

它和 `nb backup` 的定位不同：revision 存的是应用配置/构建层面的状态，轻量、秒级完成；backup 是包含业务数据的完整 `.nbdata` 包，重但全。日常小改动打 revision，大动作前再补一个 backup。

## 语法与常用参数

```bash
nb revision create "<描述文字>"
```

关键点：**描述是位置参数**，直接跟在子命令后面，不是 `--description` 选项。描述文字记得加引号，避免中文或空格被 shell 拆散；不加引号时只有第一个词会被当成描述，后面的词会被当作多余参数。

没有其它必填参数，也不需要指定要保存哪些内容——它抓取的就是"此刻"的整个应用状态。

## 实测效果

```bash
$ nb revision create "完成客户管理页面与审批流配置"
# Revision created successfully
```

输出很克制，只有一行成功提示。修订点保存了当时的构建状态，需要时可用于回滚。

把它嵌进 AI/脚本化搭建的流程里尤其有用——批量改动不 backed by 手工点击，出错也不容易定位到哪一步：

```bash
nb revision create "before: 批量生成 scm 报表页"
# 跑一批 nb api flow-surfaces / DSL push 操作
nb revision create "after: scm 报表页完成"
```

## 语法与常用参数（错误示范）

```bash
# 错误：--description 不是有效选项
nb revision create --description "完成 CRM 一期"
# 正确：
nb revision create "完成 CRM 一期"
```

## 踩坑点

- 写成 `nb revision create --description "xxx"` 不会被接受——`DESCRIPTION` 是位置参数，选项形式会报参数错误或被忽略。
- 没有 `nb revision list`：想看已有修订，命令会报 command not found。当前版本的 `nb revision` 只有 `create` 这一个入口，所以**描述文字一定要写得能自己认出来**（日期 + 里程碑），它就是你唯一的索引。
- 修订点是应用配置层面的快照，不等同于数据备份。要保护业务数据，仍然用 `nb backup create`，两者互补。

## 什么时候用

一条经验法则：**描述里写得出里程碑，就值得打一个修订点**。反过来，如果你写不出这次改动完成了什么，说明改动还没到该提交的粒度，先把活干完再打点。

- 用 `nb` 或 AI 技能批量搭建页面/工作流之前：先打一个修订点，出问题可整体回退。
- 完成一个阶段性交付（"审批流配完了""报表页上线"）时：打修订点留档。
- 与 `nb backup create` 搭配构成双保险：修订保配置，备份保数据。
- 成本几乎为零（一条命令、秒级），所以可以放开手用——每完成一个可描述的里程碑就打一个，好过事后想不起改了什么。

## 小结

`nb revision create` 是一条几乎不值得写文档的命令——直到你第一次在没有安全点的情况下改砸了应用。养成"动手前先 create 一个、动手完再 create 一个"的习惯，描述写清 before/after 与里程碑，就用最低的成本换来一条可回退的时间线。配合 `nb backup` 覆盖数据层，基本可以放心地对实例做任何结构性改动。
