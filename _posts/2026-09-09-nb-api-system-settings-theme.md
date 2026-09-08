---
layout: post
title: "NocoBase 全局设置与主题配置的命令行玩法：nb api system-settings + theme-editor"
date: 2026-09-09 13:00:00 +0800
categories: [NocoBase]
tags: [nocobase, cli, nb-api, system-settings, theme]
---

接着写 nb CLI 系列 exploratory 笔记。这一篇是两个"轻量但高频"的 API 组：`nb api system-settings`（站点标题、Logo、注册开关、语言列表这些全局设置）和 `nb api theme-editor`（主题配色与尺寸的保存/切换）。它们平时都在管理界面的系统设置页里点出来，但当你想用脚本初始化一套新环境、或者批量对齐多个实例的品牌配置时，命令行反而更省事。

## 命令用途

```bash
nb api system-settings    # 全局系统设置
nb api theme-editor       # 主题配置管理
```

两个组各自只有一个子 topic（名字重复一层），先看帮助就能摸清全部能力：

- `system-settings system-settings`：只有 `get` 和 `update` 两个动作，对应 `GET /systemSettings:get` 和 `POST /systemSettings:update`。
- `theme-editor theme-config`：`list / create / update / destroy`，完整的主题 CRUD。

连接远程实例的环境初始化不在本篇展开，假设已经通过 `nb init --setup-mode connect-remote -u https://<your-instance>.demo.nocobase.com/api ...` 建好了一个 env（下面统一用 `-e <env>` 引用）。

## 语法与常用参数

### 读取全局设置

```bash
# 读取当前全局设置（无任何必填参数）
nb api system-settings system-settings get -e <env> -j

# 更新全局设置：update 命令本身没有 body 字段 flag，
# 需要通过 --body / --body-file 传 JSON
nb api system-settings system-settings update -e <env> -j \
  --body '{"title": "My NocoBase", "allowSignUp": false}'
```

实测 `get` 返回里能看到的关键字段：

- `title`：站点标题
- `allowSignUp`：是否允许自助注册（布尔）
- `enabledLanguages`：启用的语言列表（如 `["zh-CN","en-US"]`）
- `logoId`：Logo 附件的文件记录 ID

### 主题配置

```bash
# 列出全部主题（内置主题 + 自建主题）
nb api theme-editor theme-config list -e <env> -j

# 新建主题：name 必填，token 是可选的主题变量对象
nb api theme-editor theme-config create -e <env> -j \
  --config '{"name": "brand-blue", "token": {"colorPrimary": "#1677ff"}}'

# 更新主题（--id 必填）
nb api theme-editor theme-config update --id <themeId> -e <env> -j \
  --config '{"token": {"borderRadius": 6}}'

# 删除主题
nb api theme-editor theme-config destroy --id <themeId> -e <env> -j
```

`create` / `update` 还带两个布尔开关：`--optional` 和 `--is-built-in`。`--is-built-in` 会把主题标记为内置，不要对已有内置主题乱用；`--optional` 对应"可选主题"（允许用户在界面里自行切换的那种）。

`--config` 的形状是 `{name: string, token?: object}`，`token` 里就是 Ant Design 风格的主题 token——主色、圆角、间距这类，和 UI 主题编辑器里改的是同一份数据。

## 实测效果

在一台 NocoBase 2.4.x 的远程实例上实测：

- `system-settings get` 一次拿到完整的全局设置 JSON，`-j` 后可以直接接 `jq` 提取单个字段，比如 `| jq -r '.data.title'`。
- `theme-config list` 返回内置主题加自建主题的列表，每条带 `id`、`name`、`config.token`、`optional` 等字段，足以判断某个 token 已被谁改过。
- `update` 全局设置后刷新前端即可生效，不需要重启应用；主题变更同样走的是配置表，无需清缓存。

配合 `jq` 可以做一个"品牌配置巡检"小脚本：

```bash
# 检查注册是否已关闭、标题是否符合预期
SETTINGS=$(nb api system-settings system-settings get -e <env> -j)
echo "$SETTINGS" | jq '{title: .data.title, allowSignUp: .data.allowSignUp}'
```

## 踩坑点

1. **子 topic 名字是重复的**。命令要写全 `nb api system-settings system-settings get`，第一层是插件组、第二层才是资源，容易少写一层然后报 Unknown command。卡住时先 `nb api system-settings --help` 看层级。
2. **`update` 没有 body 字段 flag**。不像 `migration create` 那样把每个字段拆成 `--xxx`，system-settings 的 update 只接受 `--body` / `--body-file` 传完整 JSON。别去找 `--title` 这种 flag，不存在。
3. **更新语义是按提交的字段 patch，但建议先 get 再合并**。想改 `title` 就只提交 `title`，不要把 `get` 拿到的整个对象原样发回去——里面混着 `logoId`、`enabledLanguages` 等，一旦你的读取结果过期，等于把别人的修改覆盖回去。
4. **主题的 `token` 是整对象替换**。`update --config '{"token": {...}}'` 时要带上希望保留的全部 token 键，只发一个键可能丢掉其它已定制的 token。稳妥做法是先 `list` 读出当前 `config.token`，改完再整体提交。
5. **`logoId` 指向文件记录**。要换 Logo 得先走文件上传拿到附件 ID，不是随手填个 URL。

## 什么时候用

- **多环境初始化**：新建一套测试/演示环境后，用两条命令把标题、语言、注册策略、品牌主题一次配齐。
- **配置巡检与对齐**：写个脚本拉取多个实例的 `system-settings get` 做 diff，确认"生产关闭注册、语言只有 zh-CN"这类安全基线。
- **主题版本化**：把 `--config` 的 JSON 存进 git，换环境时 `create` 一遍，主题不再靠截图复刻。
- 而日常的单点微调，UI 里点两下仍然更快——命令行的价值在**可重复**，不在单次。

## 参考

- 本地帮助：`nb api system-settings system-settings --help`、`nb api theme-editor theme-config --help`
- 相关前篇：`nb api resource` 通用 CRUD、`nb api app` 应用管理
