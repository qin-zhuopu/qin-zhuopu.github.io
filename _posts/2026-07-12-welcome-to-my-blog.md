---
layout: post
title: "欢迎来到我的博客"
date: 2026-07-12 09:00:00 +0800
categories: 随笔
---

这里是用来记录折腾过程的地方。主要写几类东西：

- **Home Assistant**：智能家居集成、设备接入、asyncio 踩坑
- **macOS**：老系统（Big Sur）上的驱动、内核扩展、工具链折腾
- **工具**：命令行工具、抓包、Git 之类
- **随笔**：偶尔的想法和笔记

每篇文章都是一次完整的踩坑+解决过程，希望能帮到同样在折腾的人。

## 分类索引

### Home Assistant · 海尔空调接入系列

把海尔空调接入 HA 的完整折腾过程。从抓 token、读源码到加 HTTP polling，踩过的 asyncio 坑、命名不一致问题、Recorder 与日志的差异，都拆成独立文章写清楚了。

- [把海尔空调接入 Home Assistant：抓 token、读源码、加轮询的完整折腾记录](/2026/07/31/haier-ac-home-assistant-integration/) — 系列总览
- [海尔智家云的两套 token，以及为什么手机抓不到 refresh_token](/2026/07/31/haier-oauth-token-explained/)
- [给 Home Assistant 集成加定时任务踩的三个 asyncio 坑](/2026/07/31/home-assistant-asyncio-pitfalls/)
- [Home Assistant 的两个存储：数据库只记变化，日志每次都记](/2026/07/31/home-assistant-recorder-vs-log/)
- [Home Assistant 实体的「数据库行数」≠「事件次数」](/2026/07/31/home-assistant-websocket-push-analysis/)
- [同一个设备两套名字：海尔 WS 实体名 vs Polled 实体名不一致](/2026/07/31/haier-entity-name-mismatch/)
- [Home Assistant 在 macOS 上 CPU 100%：三次抓栈定位到 c-ares](/2026/07/31/home-assistant-cpu-100-triage/)

### macOS · Big Sur 折腾系列

在 macOS 11 Big Sur 上折腾 USB 网卡驱动和内核扩展的故事。Big Sur 之后引入的 User-Approved Kext 让老驱动安装流程彻底变了。

- [在 macOS Big Sur 上给 RTL8188GU USB 网卡装驱动](/2026/07/31/macbook-big-sur-usb-wifi-rtl8188gu/)
- [macOS Big Sur 的 User-Approved Kernel Extensions](/2026/07/31/big-sur-user-approved-kext/)

### 工具

命令行工具的安装和使用笔记。

- [在 macOS Big Sur 上装 gh CLI](/2026/07/31/gh-cli-on-big-sur/)

### 随笔

- 欢迎来到我的博客（本文，2026-07-12）

## 关于评论和反馈

如果某篇文章帮到了你，或者你发现哪里写错了，欢迎在对应的 GitHub commit 下开 issue 讨论。文章源码都在 [博客仓库](https://github.com/qin-zhuopu/qin-zhuopu.github.io) 里。
