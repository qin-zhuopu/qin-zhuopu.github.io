---
layout: post
title: "海尔智家云的两套 token，以及为什么手机抓不到 refresh_token"
date: 2026-07-31 11:30:00 +0800
categories: Home-Assistant
series: haier-series
---

把海尔空调接入 Home Assistant 时绕不开一个坑：**`refresh_token` 抓不到**。

社区里几乎每个新手都会撞这个坑，banto6/haier 的 issue 区常年有人问。这篇把它彻底写清楚——

- 海尔的认证体系分两层
- 为什么手机端抓不到 `refresh_token`
- 怎么绕过去（用 `access_token` 直填）

## TL;DR

| 项 | `access_token` | `refresh_token` |
|---|---|---|
| 用途 | 所有 API 请求的 Bearer | 用来换新的 access_token |
| 有效期 | 几小时到几天 | 几十天 |
| 抓包可见性 | **HTTP header 明文，抓得到** | 走 mmtls 加密，**手机端抓不到** |
| HA 集成是否必需 | 是（间接） | banto6/haier 默认要求 |

绕过方案：改源码让 banto6/haier 接受 `access_token` 直填，不要 `refresh_token`。

## 一、海尔的两套 token

海尔云的认证基于 OAuth 2.0，但有自己的小改动。

### access_token

- 所有 API 请求必须带的 Bearer token
- 放在 HTTP header 里：`accesstoken: <token>`（全小写，注意不是 `accessToken`）
- 海尔 API 用它识别用户身份
- 有效期短：几小时到几天不等
- **过期后必须刷新**，否则集成失效

### refresh_token

- 只用来调一个接口：`oauthserver/applet/v3/login/onekey`
- 这个接口接收 `refresh_token`，返回新的 `access_token`（和新的 `refresh_token`）
- 有效期长：几十天
- banto6/haier 的标准登录就靠它——只要 refresh_token 不过期，集成能一直自动刷新

## 二、为什么 access_token 能抓到

`access_token` 是普通 HTTP header 字段，明文传输（HTTPS 加密在传输层，但代理装了根证书就能看明文）。

抓包步骤：

1. 手机装海尔智家 App（**原生 App，不是微信小程序**）
2. 电脑跑抓包工具（whistle / Reqable / Charles）
3. 手机走电脑代理，装根证书到手机系统
4. 打开 App 用一下（进主页、点空调）
5. 在抓包工具里搜 `uws.haier.net` 的请求
6. 看 header 里的 `accesstoken` 字段 → **这就是 access_token**

> HTTP header 大小写不敏感。banto6 代码里写 `accessToken`，抓包看到的是 `accesstoken`，**是同一个东西**。

顺便抓到 `client_id`（在请求 URL 或 body 里）。海尔智家 App 的是：

```
8E8FB3A7-1281-4632-8DDF-D87DD147ED5C
```

它代表 App 来源。海尔有不同的 App 来源（App、微信小程序、支付宝小程序等），不同来源走不同的 API 路径和签名规则。**建议用原生 App 的 `client_id`**。

## 三、为什么 refresh_token 抓不到

`refresh_token` 的故事完全不同。

### 海尔的不同登录入口

海尔智家在多个平台有入口：

- 海尔智家 App（原生 App）→ 用原生 App 自己的 OAuth 流程，token 走标准 HTTPS
- 微信小程序"海尔智家官方"→ 走微信生态 + 海尔的 mmtls
- 支付宝小程序 → 走支付宝生态

**banto6/haier 用的是微信小程序的 OAuth 接口**：

```
POST https://zj.haier.net/api-gw/oauthserver/applet/v3/login/onekey
```

这个接口的请求体里有 `refreshToken` 字段——这就是我们要的东西。

### mmtls 是什么

mmtls 是微信自己搞的传输层加密协议，**在 HTTPS 之上再加一层加密**。微信小程序里所有 `wx.request` 调用都走 mmtls。

抓包工具看到的是：

- HTTPS 握手正常完成
- 应用层数据是一坨二进制（mmtls 加密后的密文）
- **完全看不到原始请求体**

banto6/haier 之所以推荐用 PC 微信抓包，是因为：

- PC 微信老版本不强制 mmtls
- 或者 PC 微信的 mmtls 实现有漏洞
- 总之 PC 微信抓包能看到明文

但**手机微信不行**。现在新版 PC 微信也开始强制 mmtls，越来越难抓。

### 为什么原生 App 的 token 不能用作 refresh_token

有人会问：原生 App 不就有 `refresh_token` 吗？为什么不用原生 App 的流程？

答：**海尔的原生 App 用的 OAuth 路径和小程序不同**。

- 原生 App：`/api-gw/oauthserver/oauth/token`（标准 OAuth 2.0）
- 小程序：`/api-gw/oauthserver/applet/v3/login/onekey`（海尔自己的设计）

banto6/haier 实现的是**小程序的接口**，所以原生 App 抓到的 `refresh_token` 走不通 banto6 的代码。

## 四、绕过方案：access_token 直填

既然 `access_token` 能抓到，集成又能正常用 `access_token` 调所有 API，**为什么非要 `refresh_token`？**

`refresh_token` 的唯一作用是：access_token 过期后**自动刷新**。如果没有 `refresh_token`：

- access_token 有效期内一切正常
- 一旦过期，集成挂掉
- 必须手动重抓 access_token

对个人玩家来说，**每隔几天重抓一次也不算大事**。比拿不到 `refresh_token` 强多了。

### 改 banto6/haier 源码

`config_flow.py` 里原来强制要求 `refresh_token`：

```python
# 改成 access_token 和 refresh_token 二选一
ACCESS_TOKEN = 'access_token'

refresh_token = user_input.get(REFRESH_TOKEN, '').strip()
access_token = user_input.get(ACCESS_TOKEN, '').strip()

if refresh_token:
    # 原来的流程:用 refresh_token 换 access_token
    token_info = await client.refresh_token(refresh_token)
    token = token_info.token
    new_refresh_token = token_info.refresh_token
    expires_at = int(time.time()) + token_info.expires_in
elif access_token:
    # 直填模式:直接用 access_token
    token = access_token
    new_refresh_token = ''
    expires_at = 0
else:
    raise HaierClientException('必须填写 refresh_token 或 access_token 其中之一')

# schema 里 refresh_token 改 Optional,新增 access_token Optional
vol.Optional(REFRESH_TOKEN): str,
vol.Optional(ACCESS_TOKEN): str,
```

`__init__.py` 的 `token_updater` 也要改，否则集成每次启动都会尝试 refresh，然后挂掉：

```python
if not cfg.refresh_token:
    if token_valid:
        _LOGGER.warning("没有配置 refresh_token，跳过自动刷新。access_token 过期后需要手动重新抓取。")
        return False
    raise HaierClientException('access_token 已失效且未配置 refresh_token，无法自动刷新')
```

这套改动推到了我的 fork：[`qin-zhuopu/haier@85f2fb2`](https://github.com/qin-zhuopu/haier/commit/85f2fb283a439f7694efedfbba28b8d6fd7254b2)。

## 五、什么时候还是要 refresh_token

虽然 access_token 直填能用，但有几个场景必须回到 refresh_token：

| 场景 | 是否必须 refresh_token |
|---|---|
| 个人偶尔玩玩 | 否 |
| 长期部署（几个月） | **强烈建议有**，否则每月重抓很烦 |
| 给非技术用户用 | **必须有**，否则他们不会抓 |
| 想给 banto6/haier 提 PR | 建议有，主仓库的哲学是 refresh-token-based |

### 怎么真正拿到 refresh_token

唯一靠谱的方法（截至 2026 年）：

1. 找一台 Windows 或 macOS 电脑
2. 装 **PC 版微信**（不是手机版）
3. 装抓包工具（推荐 [Reqable](https://reqable.com/)，比 whistle 友好）
4. PC 微信里打开"海尔智家官方"小程序并登录
5. 在 Reqable 里搜 `zj.haier.net/api-gw/oauthserver/applet/v3/login/onekey`
6. 看请求体，里面有 `clientId` 和 `refreshToken`

填到 banto6/haier 的配置里，永久可用。

> PC 微信版本越老越容易抓。新版开始强制 mmtls 后会变难。

## 六、海尔 API 的签名

顺便提一下，海尔 API 还有一层签名验证。每个请求要算 `sha256(url_path + body + appId + appKey + timestamp)` 放到 header 里。这部分 banto6/haier 已经实现好了，不需要自己写。

如果只是想用集成，跳过这一节。如果想深入逆向海尔云，从这里开始挖。

## 参考

- [banto6/haier 主仓库](https://github.com/banto6/haier)
- [我的 fork（含 access_token 直填改动）](https://github.com/qin-zhuopu/haier/commit/85f2fb283a439f7694efedfbba28b8d6fd7254b2)
- [Reqable 抓包工具](https://reqable.com/)
- [whistle 抓包工具](https://wproxy.org/whistle/)
- 微信 mmtls 协议分析（搜 "wechat mmtls" 能找到一些研究文章）
