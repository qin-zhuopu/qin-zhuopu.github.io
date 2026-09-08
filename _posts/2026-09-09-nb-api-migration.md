---
layout: post
title: "NocoBase 数据迁移全流程：nb api migration 从建规则到执行"
date: 2026-09-09 16:00:00 +0800
categories: [NocoBase]
tags: [nocobase, cli, nb-api, migration, publish]
---

写 nb CLI 系列时发现最容易和别的东西混的是 `nb api migration`：它和 `nb api backup` 长得像，干的事却不同。**backup 是"整个应用快照"（结构+数据+配置），migration 是"按规则挑一批数据搬家"**——典型场景是把测试环境造好的业务数据发布到生产，或把某个数据源的记录集从一个实例挪到另一个。这一篇把它的完整流程走一遍。

## 命令用途

```bash
nb api migration --help
```

三块能力：

```text
主命令   list / get / create / download / check / execute / remove
rules    rules list / rules get / rules create   # 定义"搬什么"
logs     logs list / logs get / logs download    # 执行日志与排障
```

流程上的心智模型是三层：

1. **规则（rule）**：描述"迁移哪些集合、哪些记录、用户/系统数据怎么取舍"。
2. **迁移包（migration file）**：按规则在源环境生成的一个可下载文件。
3. **执行（execute）**：把包上传到目标环境校验后导入。

## 语法与常用参数

### 第一步：建迁移规则

```bash
# 列出已有规则
nb api migration rules list -e <env> -j

# 创建规则：user/system 两类策略描述用户数据与系统数据的取舍
nb api migration rules create -e <env> -j \
  --name 'publish-crm-data' \
  --description 'CRM 业务数据发布' \
  --user-defined-rule '<用户数据选择策略>' \
  --system-defined-rule '<系统数据选择策略>'
```

`rules create` 的四个字段都是字符串 flag；具体策略内容的写法以实例版本为准，最稳的路径是先 `rules list` 看一条现存规则的原文，照着改。

### 第二步：源环境生成迁移包

```bash
# 按规则生成迁移包，--rule-id 必填，返回里带包名（name）
nb api migration create --rule-id <ruleId> --title 'publish-<源>-to-<目标>' \
  -e <源环境> -j

# 列出/查看迁移包状态
nb api migration list -e <源环境> -j
nb api migration get --name <迁移包名> -e <源环境> -j

# 下载到本地
nb api migration download --name <迁移包名> --output ./<本地文件> -e <源环境>
```

### 第三步：目标环境先检查、再执行

```bash
# 上传前预检：不落库，先看冲突与兼容性
nb api migration check --file ./<本地文件> -e <目标环境> -j

# 确认无误后真正执行
nb api migration execute --file ./<本地文件> -e <目标环境> -j

# execute 的可选参数
#   --skip-backup            跳过执行前自动备份（不建议轻易加）
#   --env-texts '<JSON>'     目标环境的文本/密钥替换项，secret 项会被加密处理

# 失败排障：日志三件套
nb api migration logs list -e <目标环境> -j
nb api migration logs get --name <日志名> -e <目标环境> -j
nb api migration logs download --name <日志名> --output ./<日志文件> -e <目标环境>

# 清理源环境里的迁移包
nb api migration remove --name <迁移包名> -e <源环境> -j
```

全局参数里 `-e <env>` 指定环境、`-j` 输出原始 JSON、`-y` 跨环境操作时的确认开关——迁移天然是跨环境操作，这三个会频繁用到。

## 实测效果

在一台 NocoBase 2.4.x 远程实例上实测：

- `migration list` 在未创建过包时返回空列表，正常。
- `create` 需要已存在的 `ruleId`，也就是说**没有规则就没有迁移包**，规则是这个流程的入口。
- 整个设计是"离线文件"模式：`create` 在服务端生成、`download` 落到本地、`execute` 在目标端重新上传——源和目标甚至不需要互相可达，一个文件包就够了，这与 backup 的"原地快照/恢复"是两种拓扑。
- `check` 是纯读操作（不产生副作用），所以"先 check 后 execute"应该形成肌肉记忆。

## 踩坑点

1. **migration ≠ backup**。backup 恢复是整应用回滚（会覆盖结构），migration 是数据集导入。发布业务数据用 migration，整机备份/回滚用 backup，别用反了。
2. **执行顺序不能倒**：必须 `create → download → check → execute`。跳过 `check` 直接 execute，遇到集合不匹配、ID 冲突时会在半途失败，回滚成本远高于先预检。
3. **`--skip-backup` 是高危开关**。execute 前目标环境默认会做一次备份，正是失败回退的保命符；除非目标空间紧张，否则别加。
4. **规则内容版本敏感**。`user-defined-rule` / `system-defined-rule` 的结构随版本演进，跨版本迁移时先在目标版本上试建一条等价规则确认语法。
5. **迁移包与日志都占服务端空间**。发布完成、日志确认无误后，用 `remove` 清掉源环境的包，`logs download` 留档后也可清理。
6. **跨环境执行会触发确认**：目标环境与当前 env 不一致时 CLI 会要求确认，脚本化时用 `-y` 显式放行——但要确保 `-e` 写对了，`-y` 会跳过这最后一道防线。

## 什么时候用

- **测试→生产的数据发布**：测试环境造好的业务数据（客户、报价单、流程配置引用的记录）按规则搬到生产。
- **实例间的数据合并/搬迁**：老实例退役前把若干集合的记录挪进新实例。
- **定期同步集**：规则固定后，`create + download + check + execute` 四条命令就是一条可脚本化的发布流水线。
- 如果目的只是"整机备份/整机恢复"，直接用 `nb api backup`，不要用 migration 硬凑。

## 参考

- 本地帮助：`nb api migration --help`、`nb api migration rules --help`、`nb api migration logs --help`
- 相关前篇：`nb api backup`（整机备份与恢复）
