---
layout: post
title: "用 nb api 管 NocoBase 登录方式与 API 密钥：authenticators + api-keys"
date: 2026-09-09 14:00:00 +0800
categories: [NocoBase]
tags: [nocobase, cli, nb-api, authenticators, api-keys, auth]
---

NocoBase 的登录方式（账号密码、短信、各种 SSO 协议）和给外部程序用的 API 密钥，平时都藏在管理界面的认证与密钥设置页里。这一篇记 `nb api authenticators` 和 `nb api api-keys` 两个 API 组——前者管"人怎么登录"，后者管"程序怎么访问"。两者凑在一起，正好覆盖一套实例的认证面。

## 命令用途

```bash
nb api authenticators   # 用户认证管理：密码、短信、SSO 协议与可扩展 provider
nb api api-keys         # API 密钥管理：签发、列出、吊销
```

`authenticators` 的能力比想象中全，子命令一览：

```text
list          列出全部认证提供方（含未启用的）
public-list   只列已启用的（无需管理员权限的公开视角）
list-types    列出当前实例可用的认证类型
get           单个认证方详情
create        新增认证方
update        修改认证方
destroy       删除认证方
```

`api-keys` 则只有三个动作：`create`（签发）、`list`（列出）、`destroy-filter-by-tk`（吊销）。

## 语法与常用参数

### 认证提供方

```bash
# 当前实例支持哪些登录类型（basic / sms / CAS / LDAP / OIDC / SAML / dingtalk / wecom ... 装了插件才有）
nb api authenticators authenticators list-types -e <env> -j

# 列出已配置的登录方式
nb api authenticators authenticators list -e <env> -j

# 新增一个登录方式：--name 是标识，--auth-type 是类型，--options 是该类型的配置
nb api authenticators authenticators create -e <env> -j \
  --name '<登录方式标识>' --auth-type '<类型>' \
  --options '<该类型的配置 JSON>'

# 启用 / 停用、改配置
nb api authenticators authenticators update --filter-by-tk <id> -e <env> -j \
  --options '<完整配置 JSON>' --enabled

# 删除
nb api authenticators authenticators destroy --filter-by-tk <id> -e <env> -j
```

`update` 的参数面比较宽（`--title`、`--description`、`--enabled` 等都能直接传），但**类型相关的配置全部在 `--options` 里**，且是按类型定义结构的——OIDC 有 issuer/clientId，LDAP 有服务器地址与绑定账号，各不相同。

### API 密钥

```bash
# 签发密钥：可指定名称与有效期
nb api api-keys api-keys create -e <env> -j \
  --name 'ci-deploy' --expires-in '<有效期>'

# 列出现存密钥（只显示元信息，明文只在创建响应里出现一次）
nb api api-keys api-keys list -e <env> -j

# 吊销
nb api api-keys api-keys destroy-filter-by-tk <id> -e <env> -j
```

签发拿到的密钥，配合 nb CLI 的全局参数就能以密钥身份访问 API：

```bash
# -t/--token 是全局参数，所有 nb api 命令都支持，用密钥覆盖当前登录态
nb api app get-info -e <env> -t '<api-key>' -j
```

这就是 `api-keys` 的实际意义：给 CI、给别的脚本发一把钥匙，替代在脚本里存管理员账号密码。

## 实测效果

在一台 NocoBase 2.4.x 远程实例上：

- `list-types` 能看到当前已安装认证插件提供的全部类型，没装 SAML 插件就不会出现 SAML 选项——它是"可配什么"的权威来源，配置前先查它。
- `list` 与 `public-list` 的差别很实用：前者带 `enabled` 与完整配置，用于管理端审计；后者模拟登录页视角，能快速确认"用户实际能看到哪些登录入口"。
- `create` 密钥的响应里包含明文密钥，`list` 里只有名字、角色、过期时间等元数据——密钥只在签发那一刻可见，和主流 SaaS 的做法一致。
- 用 `-t <api-key>` 覆盖后调用 `nb api` 各命令均正常，等价于带着这把钥匙直接 curl NocoBase 的 HTTP API，因此同一把钥匙也能给非 nb 工具用。

## 踩坑点

1. **`--options` 要提交完整对象**。更新某个 SSO 登录方式时，只传想改的那一个键可能丢掉其余配置——先 `get` 读出当前 `options`，改完整体提交。
2. **改完 `enabled` 不一定立刻体现在登录页**。部分认证插件对登录页配置有缓存，页面没变化时优先用 `public-list` 确认服务端状态，再看前端缓存。
3. **密钥明文只出现一次**。`create` 的输出没接住就只剩吊销重建，务必当场落到密钥管理工具，不要进 shell history 和日志。
4. **`--expires-in` 是字符串**，传的是时长描述而非时间戳，具体接受格式以实例版本的帮助与响应为准；不确定就不传（默认长期有效），后续靠定期轮换兜底。
5. **删除认证方前确认还有别的登录入口**。把唯一启用的登录方式 `destroy` 掉，可能把自己锁在门外——动手前先 `public-list` 看一眼剩余入口。
6. 这组命令属于高危面，**远程共享实例上克制使用**；密钥签发/吊销最好有审计记录（谁、何时、为什么）。

## 什么时候用

- **给 CI/CD 发钥匙**：用 `api-keys create` 签发专用密钥 + `-t` 覆盖，脚本里不再出现管理员账号密码。
- **SSO 接入与巡检**：`list-types` 确认能力，`create`/`update` 配 OIDC/LDAP 等，`public-list` 验证用户可见的登录入口。
- **安全基线检查**：脚本比对 `list` 输出，发现长期未轮换的密钥、不应存在的登录方式就告警。
- 登录方式的**首次**配置仍然建议在 UI 里做一遍（有表单校验，字段含义更直观），跑通用命令行固化即可。

## 参考

- 本地帮助：`nb api authenticators authenticators --help`、`nb api api-keys api-keys --help`
- 相关前篇：`nb api acl` 角色权限、`nb api pm` 插件管理
