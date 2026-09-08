---
layout: post
title: "nb api file-manager storages 与 map map-configuration：存储后端和地图提供方的命令行配置"
date: 2026-09-09 15:00:00 +0800
categories: [NocoBase]
tags: [nocobase, cli, nb-api, file-manager, map]
---

这篇记两个"配置型" API 组：`nb api file-manager storages`（附件存哪：本地磁盘、S3、OSS/COS 这类对象存储）和 `nb api map map-configuration`（地图块用哪家提供方：高德、Google Maps 等）。两个的共同点是：界面里都是一两个设置表单，但里面藏着密钥与鉴权配置，命令行操作时有几个必须小心的脱敏与覆盖问题。

## 命令用途

```bash
nb api file-manager storages      # 存储引擎与文件存储设置
nb api map map-configuration      # 地图提供方配置
```

`storages` 的动作相当完整：

```text
list             列出已配置的存储引擎
get              单个存储引擎详情
get-basic-info   只返回上传安全字段（不含凭据）
check            解析"这次上传会用哪个存储"，并校验文件集合是否可上传
create / update / destroy   存储引擎 CRUD
```

`map-configuration` 是最简的一组，只有 `get` 和 `set`。

## 语法与常用参数

### 存储引擎

```bash
# 列出存储引擎（注意：低权限调用可能拿不到 options 里的密钥）
nb api file-manager storages list -e <env> -j

# 只读上传安全字段，不暴露凭据——做巡检用这个
nb api file-manager storages get-basic-info -e <env> -j
nb api file-manager storages get-basic-info --filter-by-tk <id或name> -e <env> -j

# 上传前的自检：显式存储 > 文件集合配置的存储 > 默认存储，并报告集合是否可上传
nb api file-manager storages check --file-collection-name <集合名> -e <env> -j

# 创建存储引擎：--type 决定 options 结构
nb api file-manager storages create -e <env> -j \
  --title '对象存储' --name 'oss_main' --type 's3' \
  --options '{"region": "...", "bucket": "...", "accessKeyId": "{{env.S3_AK}}", "accessKeySecret": "{{env.S3_SK}}"}' \
  --default --paranoid

# 更新：先读后写，嵌套对象整体提交
nb api file-manager storages update --filter-by-tk <id或name> -e <env> -j \
  --options '<完整的 options 对象>'
```

常用 flag：

- `--path` / `--param-base-url` / `--rename-mode`：文件存放路径、外链 base URL、重名处理策略
- `--default`：设为默认存储
- `--paranoid`：软删除（删除记录保留文件）
- `--rules` / `--settings`：上传规则（大小/类型限制等）与界面设置
- `--filter-by-tk` 同时接受主键 ID 或系统名 `name`

### 地图配置

```bash
# 读取当前地图提供方配置
nb api map map-configuration get -e <env> -j

# 设置：type 为提供方类型，access-key / security-js-code 为其鉴权材料
nb api map map-configuration set -e <env> -j \
  --type '<provider 类型>' \
  --access-key '<你的 key>' \
  --security-js-code '<前端安全密钥>'
```

## 实测效果

- `storages list` 能看到内置的 local 存储和所有自建引擎；`get-basic-info` 则刻意只回传上传所需的安全字段，**不回传密钥**，做配置巡检和文档化输出都用它，避免密钥进终端记录。
- `storages check` 很好用：不用真的传一个文件，就能确认某个附件集合解析到的存储、集合是否存在、是否允许上传——排障时省一轮"上传试试"。
- `destroy` 有保护：内置默认 local 引擎删不掉；正被文件集合引用的存储也删不掉，得先解绑。
- `map-configuration set` 成功后，新建的地图块即使用新提供方；`get` 返回当前提供方类型与 key（**注意输出里可能含 key**，别截图外发）。

## 踩坑点

1. **密钥不要进命令行明文**。`create/update` 的 `--options` 里会写 `SecretId/SecretKey/SecretAccessKey` 之类，直接内联 JSON 会留在 shell history 和 nb 的诊断日志里。做法：把值放进环境变量或 JSON 文件（如 `--body-file <json>`），文件权限收好，命令里只留占位符。
2. **嵌套对象是整体替换**。更新 `options` / `rules` / `settings` 时，只提交一个键可能把其余键清掉——官方帮助里明确要求"先读当前记录，提交完整对象"。
3. **options 的键名大小写敏感**。不同厂商的参数命名不同（比如腾讯 COS 用 `Region/SecretId/SecretKey/Bucket`），照抄别家示例会静默配置失败，创建后一定回读校验。
4. **`list` 的输出可能含明文密钥**（取决于权限），日志和截图注意脱敏；能用 `get-basic-info` 就别用 `get`。
5. **删除存储前先清点**：引用它的附件集合要先迁移或解绑，否则 `destroy` 会拒绝——这是保护而不是 bug。
6. 地图 `security-js-code` 是给前端用的安全密钥，会随页面下发到浏览器，别指望它能保密；计费与配额防护要靠提供方后台的域名白名单。

## 什么时候用

- **新环境初始化**：建环境后一条 `storages create` 把 S3/OSS 存储配好并 `--default`，再一条 `map-configuration set` 把地图 key 配上，全程可脚本化。
- **上传排障**：`storages check` 快速定位"是存储配错还是集合不可上传"。
- **配置巡检**：定期 `get-basic-info` 拉所有存储的安全字段做 diff，确认默认存储、软删除策略没被误改。
- 单次换个 key、改个路径，UI 更快；命令行的价值在**可重复与可审计**。

## 参考

- 本地帮助：`nb api file-manager storages --help`、`nb api map map-configuration --help`
- 相关前篇：`nb api resource` 通用 CRUD（storages 本质也是一个集合，可以用 `nb api resource --resource storages` 操作）、`nb api system-settings` 全局设置
