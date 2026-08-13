---
layout: post
title: "macOS 11 上 v2rayN 7.16 崩溃：绕开 GUI 用 sing-box 单独跑"
date: 2026-08-13 22:00:00 +0800
categories: [技术踩坑]
tags: [macos, v2rayn, sing-box, launchd, proxy]
---

老 Mac 上升不了 macOS 12，又想在 macOS 11 上用代理。本以为装个 v2rayN 就完事，结果一路踩坑：内核 dyld 加载失败、配置 panic、最后 GUI 直接渲染层崩溃。绕开 v2rayN，让 sing-box 单独跑，反而更稳更轻。

## 问题现象

在 macOS 11.7.10 (Intel x86_64) 上运行 v2rayN 7.16.1，按顺序出现三类报错：

**1. 内核启动失败（dyld）**

```
dyld: Symbol not found: _SecTrustCopyCertificateChain
  Referenced from: .../bin/xray/xray (which was built for Mac OS X 12.0)
  Expected in: /System/Library/Frameworks/Security.framework/Versions/A/Security
```

sing-box 二进制同样中招：

```
dyld: Symbol not found: _SecTrustCopyCertificateChain
  Referenced from: .../bin/sing_box/sing-box (which was built for Mac OS X 12.0)
```

**2. 换上兼容版 Xray 后配置 panic**

```
panic: runtime error: invalid memory address or nil pointer dereference
github.com/xtls/xray-core/infra/conf.FakeDNSPostProcessingStage.Process(...)
```

**3. 最终 GUI 直接崩**

```
Unhandled exception. System.InvalidOperationException:
  Avalonia.Native was not able to start the RenderTimer.
  Native error code is: -6661
```

## 环境信息

- OS: macOS 11.7.10 (Intel x86_64, Broadwell 集成显卡)
- v2rayN: 7.16.1
- Xray-core: 25.x（官方默认，dyld 拒绝）
- sing-box: 1.13.x（官方默认，dyld 拒绝）
- 节点协议: VLESS + Reality + XTLS-Vision

## 排查过程

### 第 1 步：识别 dyld Symbol not found

`_SecTrustCopyCertificateChain` 是 macOS 12.0 才加入 Security framework 的符号。任何用 macOS 12+ SDK 编译的二进制（包括 Xray-core 最新版、sing-box 最新版）在 macOS 11 上都会被 dyld 拒绝加载。

**判断一个二进制能不能跑的最快办法**：

```bash
otool -l /path/to/binary | grep -A4 "LC_BUILD_VERSION"
# 看 minos / sdk 字段，11.0 表示兼容 macOS 11
```

### 第 2 步：找兼容版内核

`Xray-macos-64.zip` 在 25.3.6 之前一直是 `minos 11.0 sdk 11.0`；之后官方改为 macOS 12 基线。

`sing-box` 在 1.8.x 系列同时发布 `darwin-amd64` 和 `darwin-amd64-legacy` 两个变体，**legacy 用 SDK 10.13 编译**，专门为老系统准备：

```bash
# sing-box 1.8.14 legacy
otool -l sing-box | grep -A4 LC_BUILD_VERSION
# minos 10.13  sdk 10.13   ← 兼容 macOS 11
./sing-box version
# sing-box version 1.8.14
```

### 第 3 步：换上去之后 Xray 仍 panic

v2rayN 7.16.1 给节点生成的 DNS 配置含 `predefined` 字段（Xray 25.x 新格式），所有能跑 macOS 11 的旧 Xray 都不认识，post-process 时 nil 解引用。

**Xray 这条路堵死**：要么二进制太新（dyld 拒绝），要么配置太新（旧 Xray panic）。

### 第 4 步：切到 sing-box 内核仍失败

`v2rayN/binConfigs/config.json` 还是 Xray 格式。即使把节点的 `CoreType` 改为 `sing_box` (24)，重启 v2rayN 后配置文件未重新生成，且 GUI 直接崩。

### 第 5 步：发现真正根因 — Avalonia 渲染层

直接命令行启动 v2rayN.app：

```bash
/Applications/v2rayN.app/Contents/MacOS/v2rayN
```

报错：

```
Avalonia.Native was not able to start the RenderTimer. Native error code is: -6661
```

错误码 `-6661` 是 `kCVReturnInvalidDisplay`，Avalonia 11 的 native 渲染层初始化失败。这是 v2rayN 7.16.x 在老 Intel Mac + macOS 11 上的已知问题，**改配置改不回来**。

## 根因分析

| 问题 | 根因 |
|---|---|
| dyld Symbol not found | 二进制用 macOS 12+ SDK 编译，依赖 macOS 12 才有的 Security framework 符号 |
| FakeDNSPostProcessingStage panic | v2rayN 新版生成的 DNS `predefined` 字段，旧 Xray 不识别，nil 解引用 |
| Avalonia -6661 | v2rayN 7.16 用的 Avalonia 11 native 渲染层在老 Intel Mac 集显上无法初始化 |

前两个还能靠换内核版本绕，第三个是 GUI 本身的渲染层 bug，**没救**。

## 最终方案：绕开 v2rayN GUI，sing-box 单独跑

v2rayN 只是个壳子，真正干活的是内核。直接用 sing-box 1.8.14 legacy + launchd 自启 + macOS 系统代理，跳过 GUI 整个崩溃链路。

### 目录规划

```
~/.local/bin/sing-box                  # 二进制
~/.config/sing-box/config.json         # 节点配置
~/Library/LaunchAgents/local.sing-box.plist
~/.local/var/log/sing-box.log          # 运行日志
~/.local/bin/sb-set-proxy.sh           # 开启系统代理
~/.local/bin/sb-clear-proxy.sh         # 关闭系统代理
```

### 节点配置（VLESS Reality 示例）

`~/.config/sing-box/config.json`：

```json
{
  "log": { "level": "info", "timestamp": true },
  "dns": {
    "servers": [
      { "tag": "local", "address": "223.5.5.5", "detour": "direct" },
      { "tag": "remote", "address": "https://1.1.1.1/dns-query", "detour": "proxy" }
    ],
    "rules": [{ "outbound": "any", "server": "local" }],
    "strategy": "prefer_ipv4"
  },
  "inbounds": [
    {
      "type": "mixed",
      "tag": "mixed-in",
      "listen": "127.0.0.1",
      "listen_port": 10808
    }
  ],
  "outbounds": [
    {
      "type": "vless",
      "tag": "proxy",
      "server": "your.vps.example.com",
      "server_port": 443,
      "uuid": "REPLACE-WITH-YOUR-UUID",
      "flow": "xtls-rprx-vision",
      "tls": {
        "enabled": true,
        "server_name": "your.sni.example.com",
        "utls": { "enabled": true, "fingerprint": "chrome" },
        "reality": {
          "enabled": true,
          "public_key": "REPLACE-WITH-YOUR-PUBLIC-KEY",
          "short_id": ""
        }
      }
    },
    { "type": "direct", "tag": "direct" },
    { "type": "block", "tag": "block" },
    { "type": "dns", "tag": "dns-out" }
  ],
  "route": {
    "rules": [
      { "protocol": "dns", "outbound": "dns-out" },
      { "ip_is_private": true, "outbound": "direct" }
    ],
    "final": "proxy"
  }
}
```

`mixed` inbound 同时支持 HTTP 和 SOCKS5，一个端口搞定。

### launchd 开机自启

`~/Library/LaunchAgents/local.sing-box.plist`：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>local.sing-box</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/YOU/.local/bin/sing-box</string>
    <string>run</string>
    <string>-c</string>
    <string>/Users/YOU/.config/sing-box/config.json</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/Users/YOU/.local/var/log/sing-box.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/YOU/.local/var/log/sing-box.err.log</string>
</dict>
</plist>
```

加载：

```bash
launchctl load ~/Library/LaunchAgents/local.sing-box.plist
launchctl list | grep sing-box
```

### 系统代理开关脚本

`sb-set-proxy.sh`：

```bash
#!/bin/bash
PORT=10808
networksetup -listallnetworkservices | grep -v '^*' | grep -v '^$' | while read -r svc; do
  networksetup -setwebproxy "$svc" 127.0.0.1 $PORT off 2>/dev/null
  networksetup -setsecurewebproxy "$svc" 127.0.0.1 $PORT off 2>/dev/null
  networksetup -setsocksfirewallproxy "$svc" 127.0.0.1 $PORT off 2>/dev/null
done
```

`sb-clear-proxy.sh`：

```bash
#!/bin/bash
networksetup -listallnetworkservices | grep -v '^*' | grep -v '^$' | while read -r svc; do
  networksetup -setwebproxystate "$svc" off 2>/dev/null
  networksetup -setsecurewebproxystate "$svc" off 2>/dev/null
  networksetup -setsocksfirewallproxystate "$svc" off 2>/dev/null
done
```

注意：对 Bluetooth PAN / Thunderbolt 桥等虚拟接口会报 `parameters were not valid`，可忽略。

### 终端命令走代理

macOS 系统代理对 GUI 应用（浏览器、Slack、VS Code）生效，但 curl/git/wget 默认不读。在 `~/.zshrc` 加：

```bash
export http_proxy=http://127.0.0.1:10808
export https_proxy=http://127.0.0.1:10808
```

## 关键命令速查

```bash
# 验证二进制能否在当前 macOS 跑
otool -l /path/to/bin | grep -A4 LC_BUILD_VERSION
# 看 minos / sdk 字段，11.0 = 兼容 macOS 11

# 启停 / 重启 sing-box 服务
launchctl kickstart -k gui/$(id -u)/local.sing-box
launchctl unload   ~/Library/LaunchAgents/local.sing-box.plist
launchctl load     ~/Library/LaunchAgents/local.sing-box.plist

# 查看运行状态
launchctl list | grep sing-box
lsof -nP -iTCP:10808 -sTCP:LISTEN

# 测试代理（HTTP / SOCKS5）
curl -x http://127.0.0.1:10808 -s https://ifconfig.me
curl --socks5 127.0.0.1:10808 -s https://ifconfig.me

# 查看 / 开关系统代理
scutil --proxy
~/.local/bin/sb-set-proxy.sh
~/.local/bin/sb-clear-proxy.sh

# 改节点后重启
$EDITOR ~/.config/sing-box/config.json
~/.local/bin/sing-box check -c ~/.config/sing-box/config.json
launchctl kickstart -k gui/$(id -u)/local.sing-box

# 看日志
tail -f ~/.local/var/log/sing-box.log
```

## 回滚到 v2rayN

如果以后升级到 macOS 12+，想换回 v2rayN：

```bash
# 1. 停 sing-box 服务 + 关系统代理
launchctl unload ~/Library/LaunchAgents/local.sing-box.plist
~/.local/bin/sb-clear-proxy.sh

# 2. 装 v2rayN（直接下 dmg 或 zip）
# https://github.com/2dust/v2rayN/releases

# 3. （可选）禁用 launchd 自启，但保留配置
# 删除 ~/Library/LaunchAgents/local.sing-box.plist 即可
```

## 参考

- [Xray-core releases](https://github.com/XTLS/Xray-core/releases)
- [sing-box releases](https://github.com/SagerNet/sing-box/releases)（找 `darwin-amd64-legacy` 变体）
- [v2rayN releases](https://github.com/2dust/v2rayN/releases)
- [Apple Technical Q&A QA1783](https://developer.apple.com/library/archive/qa/qa1783/_index.html) — 弱链接与 SDK 兼容
- [launchd man](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html)
