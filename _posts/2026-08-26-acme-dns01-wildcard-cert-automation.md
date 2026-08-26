---
layout: post
title: "用 acme-client 自动签发 Let's Encrypt 通配符证书踩坑记"
date: 2026-08-26 16:00:00 +0800
categories: [技术踩坑]
tags: [lets-encrypt, acme, dns-01, nodejs, tls]
---

想给 `*.example.com` 这样的通配符域名自动签发免费 TLS 证书，Let's Encrypt 的 DNS-01 challenge 是唯一可行路径。原理很简单——在 `_acme-challenge.<域名>` 下放一条 TXT 记录证明你控制该域名，Let's Encrypt 验证通过就签发证书。但用 Node 的 `acme-client` 库内建这套流程时，踩了三个报错极具误导性的坑。这篇记录一下。

## 问题现象

目标是写一个命令行工具，一条命令全自动完成：调用 ACME 协议 → 算出 challenge 值 → 通过 DNS 服务商 API 写 TXT 记录 → 等生效 → 通知验证 → 拉取证书落盘。用的是 `acme-client` 5.4.0。

跑起来后连续撞了三堵墙，每堵墙的报错都指向错误的方向：

1. `Attempting to read ACME directory returned error 503`
2. `Incorrect TXT record "xxx" found at _acme-challenge.gb10.example.com`
3. `Authorization not found in DNS TXT record: _acme-challenge.gb10.example.com`

## 环境信息

- OS: Windows 11 (Git Bash) / 同样适用 Linux、macOS
- Node.js: v22
- 库: `acme-client` 5.4.0
- 网络: 需经 HTTP 代理访问外网（企业环境常见）

## 排查过程

### 坑一：503 —— 不是 Let's Encrypt 挂了，是 axios 代理实现有缺陷

第一个报错是读取 ACME directory 返回 503。第一反应是 Let's Encrypt 服务波动，于是直接用 curl 走同一个代理测：

```bash
export https_proxy=http://代理地址:端口
curl -s -o /dev/null -w "%{http_code}\n" \
  https://acme-staging-v02.api.letsencrypt.org/directory
# 200
```

curl 走代理 200，说明代理和 Let's Encrypt 都没问题。那 503 从哪来？`acme-client` 底层用 axios，我一开始用 axios 的原生 proxy 配置透传代理：

```javascript
const p = new URL(proxyUrl);
acme.axios.defaults.proxy = {
  protocol: "http",
  host: p.hostname,
  port: parseInt(p.port, 10),
};
```

单独把这段拎出来测：

```javascript
const acme = require("acme-client");
acme.axios.defaults.proxy = { protocol: "http", host: "...", port: ... };
acme.axios.get("https://acme-staging-v02.api.letsencrypt.org/directory")
  .then(r => console.log("OK", r.status))
  .catch(e => console.log("ERR", e.response && e.response.status));
// ERR 503
```

复现了。**根因**：axios 内置的 proxy 配置对 HTTPS 目标的 CONNECT 隧道支持有缺陷，代理返回了 503。解决办法是禁用 axios 自带 proxy，改用 `https-proxy-agent` 走标准 CONNECT 隧道：

```javascript
const { HttpsProxyAgent } = require("https-proxy-agent");
const agent = new HttpsProxyAgent(proxyUrl);
acme.axios.defaults.proxy = false;      // 关键：关掉 axios 原生 proxy
acme.axios.defaults.httpsAgent = agent;
acme.axios.defaults.httpAgent = agent;
```

### 坑二：Incorrect TXT record —— 旧值没清干净

代理修好后，DNS-01 流程能跑到验证阶段了，但报 `Incorrect TXT record` ——而且那个"错误的值"是我上一次失败运行时写进去的旧 challenge 值。

问题出在我写 TXT 记录的 upsert 逻辑上。我最初的实现是"读出现有值，把新值 append 进去"：

```javascript
const merged = [...existingValues, newValue];  // 错误：追加
await api("PUT", txtPath, merged.map(v => ({ data: v, ttl })));
```

ACME 每一轮 challenge 都会生成一个全新的 token 值。如果 append，DNS 里就会残留上一轮的旧值。Let's Encrypt 校验时逐条比对，命中旧值就报 `Incorrect TXT record`。

**根因**：challenge 是一次性的，同一个 `_acme-challenge` 记录名下只应该保留当前这一个值。改成 PUT 覆盖为唯一值：

```javascript
// 只保留当前值，清掉任何残留
await api("PUT", txtPath, [{ data: newValue, ttl }]);
```

### 坑三：Authorization not found —— 库在用本机 DNS 缓存自检

覆盖逻辑改对后，又冒出 `Authorization not found in DNS TXT record`。诡异的是，我自己用 Google 的 DoH（`https://dns.google/resolve`）查这条 TXT，明明已经能查到新值了。

翻 `acme-client` 源码，发现它在通知 Let's Encrypt 验证**之前**，会先做一次内部 DNS 自检（`verify.js`），而且用的是 **Node 本机的 DNS resolver**：

```javascript
// node_modules/acme-client/src/verify.js
const txtRecords = await resolver.resolveTxt(recordName);
if (!recordValues.includes(keyAuthorization)) {
  throw new Error(`Authorization not found in DNS TXT record: ${recordName}`);
}
```

本机 resolver 用的是企业内网 DNS，TXT 记录的 TTL 是 600 秒，缓存里还是旧值（或空）。所以本机自检失败，但公网早已生效。

**根因**：`acme-client` 的内部自检用本机 resolver，会命中缓存导致误报。而 Let's Encrypt 自己验证时是直接查域名的**权威 NS**，绕过一切缓存。所以这个本机自检纯属多余，直接跳过：

```javascript
await client.auto({
  csr,
  email,
  termsOfServiceAgreed: true,
  challengePriority: ["dns-01"],
  skipChallengeVerification: true,   // 跳过本机自检
  challengeCreateFn: async (authz, challenge, keyAuth) => {
    await upsertTxtRecord(...);       // 写 TXT（覆盖）
    await waitForTxt(...);            // 用公网 DoH 确认传播
  },
  challengeRemoveFn: async () => {},  // 按需可保留 TXT 不删
});
```

自己用一个走公网的 DoH 查询来确认传播，比本机 resolver 靠谱得多：

```javascript
// 用 https://dns.google/resolve?name=<fqdn>&type=TXT 轮询
// 直到 Answer 里出现期望的 challenge 值
```

三个坑全填平后，staging 和生产环境都一次签发成功，通配符证书落盘。

## 根因分析

三个报错的共同特点是**指向的方向都是错的**：

| 报错 | 看起来像 | 实际原因 |
|------|---------|---------|
| `503` | Let's Encrypt 服务波动 | axios 原生 proxy 的 HTTPS CONNECT 缺陷 |
| `Incorrect TXT record` | DNS 没生效 / 传播延迟 | upsert 追加导致旧值残留 |
| `Authorization not found` | TXT 写失败 | 库用本机 resolver 命中缓存 |

排查时最有用的动作是**用 curl / DoH 从旁路验证**——它把"代理和上游到底通不通"和"客户端库自己的行为"这两件事分开了，一下就定位到问题在库这边而非网络。

## 最终方案

一条命令签发通配符证书的核心流程：

1. `acme-client` 生成账户密钥 + 订单 + CSR
2. `challengeCreateFn` 里：算出 keyAuthorization → PUT 覆盖 `_acme-challenge.<域名>` 的 TXT → 用公网 DoH 轮询确认传播
3. `skipChallengeVerification: true` 跳过本机自检
4. Let's Encrypt 直查权威 NS 完成校验，返回证书
5. 落盘 `privkey.pem` / `fullchain.pem` / `cert.pem`

## 关键命令速查

```bash
# 从旁路验证代理到 Let's Encrypt 通不通（排除库自身行为的干扰）
export https_proxy=http://代理地址:端口
curl -s -o /dev/null -w "%{http_code}\n" \
  https://acme-staging-v02.api.letsencrypt.org/directory

# 用公网 DoH 查 TXT 是否已传播（绕过本机 DNS 缓存）
curl -s "https://dns.google/resolve?name=_acme-challenge.你的域名&type=TXT" \
  -H "Accept: application/dns-json"
```

```javascript
// acme-client 三个必备配置
const { HttpsProxyAgent } = require("https-proxy-agent");
const agent = new HttpsProxyAgent(proxyUrl);
acme.axios.defaults.proxy = false;              // 1. 关掉 axios 原生 proxy
acme.axios.defaults.httpsAgent = agent;
await client.auto({
  skipChallengeVerification: true,              // 2. 跳过本机 DNS 自检
  // ...
});
// 3. TXT upsert 用 PUT 覆盖为唯一值，不要 append
```

**经验总结**：
- 先用 staging 环境（`acme-staging-v02`）验证，跑通了再打生产，避免踩生产的限流（每域名每周 50 张证书）。
- 通配符证书**必须**走 DNS-01，HTTP-01 不支持通配符。
- DNS-01 的验证是查权威 NS 的，任何本地/企业 DNS 缓存都不影响 Let's Encrypt，但会影响你自己写的"确认传播"逻辑——所以确认传播要走公网 DoH。

## 参考

- [Let's Encrypt Challenge Types](https://letsencrypt.org/docs/challenge-types/)
- [acme-client (npm)](https://www.npmjs.com/package/acme-client)
- [RFC 8555 - ACME](https://datatracker.ietf.org/doc/html/rfc8555)
