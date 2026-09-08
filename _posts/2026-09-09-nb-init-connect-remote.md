---
layout: post
title: "nb init 连接远程实例：connect-remote 全流程与两个报错坑"
date: 2026-09-09 11:00:00 +0800
categories: [NocoBase]
tags: [nocobase, cli, nb, init]
---

上一篇画了 nb CLI 的命令地图，这篇从第一步讲起：用 `nb init --setup-mode connect-remote` 把 CLI 连到一个已经部署好的远程实例上。命令本身很短，但我第一次跑就在两个地方卡住了——一个报错文案自相矛盾，一个是"超时"其实只是实例在睡觉。

## 命令用途

`nb init` 负责建立"环境"，它是后续所有 `nb api` / `nb plugin` / `nb backup` 命令的前提。三种 setup-mode 对应三种场景：

| setup-mode | 场景 |
|-----------|------|
| `connect-remote` | 只连接已有远程实例，本地不装任何东西 |
| `install-new` | 在本机全新部署一套（npm 源码或 Docker） |
| `manage-local` | 接管一个已经在本地跑着的实例 |

没有实例、只想试 API 的，选 `connect-remote`，这也是今天的主角。

## 语法与常用参数

```bash
nb init -y -e demo --setup-mode connect-remote \
  -u https://<your-instance>.demo.nocobase.com/api \
  -a basic \
  --username <管理员账号> \
  --password <密码>
```

- `-e <name>`：环境名，之后 `nb env use <name>` 切换用
- `-u <url>`：实例地址，**必须带 `/api` 路径**
- `-a basic`：认证方式，basic 即账号密码
- `-y`：非交互，跳过所有确认提示——写脚本必备；不带的话每一步都会停下来问你
- `--ui`：交互式引导（更适合本地安装场景）

## 实测效果

```bash
$ nb init -y -e demo --setup-mode connect-remote \
    -u https://<your-instance>.demo.nocobase.com/api \
    -a basic --username <管理员账号> --password <密码>

Syncing agent skills...
Environment "demo" created.

$ nb env current
demo
```

注意输出里的 `Syncing agent skills`——init 会顺手把一套 `nocobase-*` 的 AI 技能同步到 `~/.nocobase`，给 Claude Code 这类工具用。这个动作不需要你干预，细节在系列的 skills 篇里讲。

连上之后即可直接调 API：

```bash
$ nb api app get-info
{"version":"2.4.0-alpha.4","database":{"dialect":"postgres"},"lang":"en-US",...}
```

## 踩坑一：`--api` 前缀报错，两套工具规则相反

第一次跑我传的是裸域名：

```bash
nb init ... -u https://<your-instance>.demo.nocobase.com
# 报错：URL 必须包含 /api 前缀
```

按提示补上 `/api` 就过了。但几天后我用 DSL 那套工具链时，它的配置 `NB_URL` 反而**不能**带 `/api`——那个工具会自己拼 `/api`，带了就变成 `/api/api/...`。

结论记这一条：**`nb init` 的 `-u` 必须带 `/api`；DSL 工具链的 `NB_URL` 必须不带**。两边规则相反，各自记住，别想当然地统一。

## 踩坑二：demo 实例"超时"，其实是冷启动

第二个坑更迷惑。init 之后第一次请求卡住一分多钟没响应，看起来像超时挂了：

```bash
$ nb api app get-info
# 卡住 >60s，无输出
```

用 `curl -v` 诊断，输出很关键：

```bash
$ curl -v https://<your-instance>.demo.nocobase.com/api/app:getInfo
* Connected to <your-instance>.demo.nocobase.com ... port 443
* TLS 1.3 connection using TLS_AES_128_GCM_SHA256
* Server certificate: OK
> GET /api/app:getInfo HTTP/2
# 然后长时间等待...
```

注意：**TCP 已连接、TLS 已握手、证书校验通过**——网络链路完全没问题，请求发出去了，只是服务端迟迟不回。这不是超时故障，是 demo/休眠实例在冷启动：容器从停机状态拉起、加载插件需要时间。

处理方式就是等。实测首次请求 60 秒以上是正常的，唤醒后同一命令秒回：

```bash
$ time nb api app get-info
# 唤醒后 <1s
```

判别口诀：`curl -v` 里如果卡在 `Connected` 之前，是网络/DNS 问题；如果 TLS 已通、卡在等响应头，是服务端慢（冷启动或后端阻塞），换个思路等或者去查服务端日志，别在本地网络层瞎折腾。

## 其它注意点

- `-y` 很好用，但意味着密码写在命令行里。共享机器上建议改用交互式，或者让 CLI 从自己的配置存储里取（init 过一次后，后续操作不再需要传密码）。
- init 成功后用 `nb env status` 做一次健康检查确认连接质量，比单次 `api` 调用更适合写进脚本前置检查。

## 什么时候用 connect-remote

- 只拿到一个线上/测试实例的地址和账号，想在命令行、脚本或 AI 工具里操作它。
- 不想在本地装 NocoBase 源码（那要好几个 G 和一堆依赖）。
- 反之，要本地开发插件、跑测试，就得走 `install-new` / `manage-local`，`scaffold`、`app`、`db` 那些本地命令才会可用。

## 系列其它篇目

- [nb CLI 总览](/2026/09/09/nb-cli-overview/)
- [nb env 环境管理](/2026/09/09/nb-env-manage/)
- [nb config / self / session](/2026/09/09/nb-config-self-session/)
- [nb skills 技能同步](/2026/09/09/nb-skills-sync/)
