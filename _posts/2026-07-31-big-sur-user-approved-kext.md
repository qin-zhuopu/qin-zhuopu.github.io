---
layout: post
title: "macOS Big Sur 的 User-Approved Kernel Extensions：装第三方 kext 必须经的流程"
date: 2026-07-31 07:00:00 +0800
categories: 折腾
---

上一篇写了在 Big Sur 上给 Realtek USB 网卡装驱动的过程，里面提到一个关键步骤——**User-Approved Kernel Extensions**（用户批准的内核扩展）。这篇把它单独拎出来写清楚，因为这个机制是 Big Sur 上装任何第三方 kext 都会撞上的。

## 背景：从 Catalina 到 Big Sur 的 kext 加载机制变化

**macOS 10.15 Catalina 及之前**：
- kext 文件放在 `/Library/Extensions/` 即可
- 系统启动时自动加载（需要重建 `kextcache`）
- 未签名 kext 只要 SIP 的 `Kext Signing` 设为 disabled 就能加载
- 没有用户交互层的"批准"步骤

**macOS 11 Big Sur 起**：
- 引入 **auxiliary kext collection**（辅助内核扩展集合）
- kext 必须先被用户在系统设置里**批准**，才能进入 auxKC
- **批准后必须重启**才生效
- 软件（`kextload` / `kextutil`）**无法绕过**这个重启

简单说：Big Sur 让 kext 加载这件事从"开发者的事"变成了"用户的事"。

## 完整流程（以未签名 kext 为例）

### 前置条件：SIP 的 Kext Signing 必须 disabled

先看现状：

```zsh
csrutil status
```

期望看到至少这两项 disabled：

```
Kext Signing: disabled
Filesystem Protections: disabled
```

如果 SIP 是默认 enabled 状态，**必须先在恢复模式关掉**：

1. 关机
2. 开机时按住 `Cmd+R`（Intel Mac），进入恢复模式
3. 顶部菜单栏 → 实用工具 → 终端
4. 跑 `csrutil disable`
5. 重启

> Apple Silicon Mac 进恢复模式的方式不同（开机长按电源键），且这套机制对 Apple Silicon 还有更严格的限制（kext 需要通过 recoveryOS 的特殊流程降级安全策略）。本文只覆盖 Intel Mac。

### 1. 把 kext 放到 `/Library/Extensions`

如果是通过 `.pkg` 安装包安装的，自动会放好：

```zsh
sudo installer -pkg YourDriver.pkg -target /
```

如果是手动下载的 `.kext` 文件：

```zsh
sudo cp -R YourDriver.kext /Library/Extensions/
sudo chown -R root:wheel /Library/Extensions/YourDriver.kext
```

### 2. 重建 kext 缓存

```zsh
sudo kextcache -i /
```

期望输出：

```
Executing: /usr/bin/kmutil install --volume-root / --check-rebuild
rebuilding local auxiliary collection
kmutil done
```

如果有 warning 或 error，会在这里显示。常见错误：
- kext 没有合法的 Info.plist
- kext 与已有 kext 冲突
- 缺依赖

### 3. 在系统设置里批准

打开 **系统偏好设置 → 安全性与隐私 → 通用**。

往下滚，应该看到一条横幅提示，类似：

> **System software from developer "YOUR_DEVELOPER_NAME" was blocked from loading.**
>
> [Allow...]

点 **Allow...**，输入管理员密码。

**找不到这个提示？** 排查路径：

- **提示延迟出现**：等几分钟，Big Sur 有时延迟
- **拔插一次硬件触发**：如果是设备驱动，重新插拔 USB 设备
- **看是否已经被批准过**：跑下面命令看 kext 是否已加载，加载了就说明批准过了

### 4. 重启

**这是最关键也最容易被忽略的一步**：批准后**必须重启**，kext 才会真正加载。

很多人误以为"点完 Allow 就生效"，结果发现 kext 没加载，反复重装重试。

不重启直接 `kextload` 会报错：

```
Error Domain=KMErrorDomain Code=27
"Extension with identifiers com.example.driver.XXX not approved to load.
Please approve using System Preferences."
```

这个错误**不**意味着没批准，而是批准了但还没生效——重启即可。

### 5. 重启后验证

```zsh
# 1. 看 kext 是否加载
kextstat | grep -i your_driver_name

# 2. 看 kext 文件是否还在
ls -la /Library/Extensions/ | grep -i your_driver

# 3. 如果是硬件驱动，看设备是否被识别
system_profiler SPUSBDataType | grep -A 5 "Your Device Name"
```

## 不重启时手动 kextload 的常见错误

如果你不想重启，尝试 `kextload` 强制加载，会遇到各种错误。**没有任何一个能绕过 User-Approved 机制**：

### 错误 1：not approved to load

```
Error Domain=KMErrorDomain Code=27
"Extension with identifiers com.realtek.driver.RtWlanU not approved to load."
```

**含义**：kext 进入了 auxKC，但用户还没批准。去系统设置批准 + 重启。

### 错误 2：not in prelinked kernel / not in auxKC

```
Kext rejected - kext not in prelinked kernel cache.
Kext rejected - kext not in auxiliary kext collection.
```

**含义**：kext 没被加入 auxKC。先跑 `sudo kextcache -i /` 重建缓存，然后重启。

### 错误 3：kext-dev-mode allowing invalid signature

```
KernelCache:
kxld[xxx]: kext is invalid signature
(may be ignored if kext-dev-mode is allowed)
```

**含义**：SIP 还在拦未签名 kext。`csrutil status` 看 `Kext Signing` 是否 disabled，没有的话进恢复模式关。

### 错误 4：code signature invalid

```
Code Failed To Load: Code Signature Invalid
```

**含义**：kext 的签名被改坏（比如手动编辑了 Info.plist 后没重新签名）。重装原版 kext，或者用 `codesign` 重签。

## `kextcache -i /` vs `kmutil`

Big Sur 上，老的 `kextcache` 命令实际是被 `kmutil` 包装的：

```zsh
$ sudo kextcache -i /
Executing: /usr/bin/kmutil install --volume-root / --check-rebuild
rebuilding local auxiliary collection
kmutil done
```

直接用 `kmutil` 也可以：

```zsh
# 重建 auxKC
sudo kmutil install --volume-root /

# 检查是否需要重建
sudo kmutil install --volume-root / --check-rebuild

# 加载单个 kext（不写入 auxKC，仅当前会话）
sudo kmutil load -p /Library/Extensions/YourDriver.kext
```

但 `kmutil load` 同样逃不过 User-Approved——批准过的才能用，没批准的会报和 `kextload` 一样的错误。

## 排查"批准窗口不出现"问题

最常见的一个坑：装完 kext 后去 System Preferences 找批准提示，**结果根本没有那条横幅**。原因排查：

### 原因 1：提示延迟出现

Big Sur 上这条提示有时延迟几分钟才出现。等几分钟再去看，或者退出 System Preferences 重新打开。

### 原因 2：需要触发事件

对于**硬件驱动**，系统可能等设备出现才生成批准请求。**插上设备**或**拔插一次**触发。

### 原因 3：已经批准过

如果之前装过同一 bundle ID 的 kext 并批准过，不会再次提示。直接 `kextstat` 看是否已加载。

### 原因 4：bundle ID 不在批准列表

可以用下面命令查看当前所有待批准/已批准的 kext：

```zsh
systemextensionsctl list                # 用于系统扩展（DriverKit，不是 kext）
system_profiler SPExtensionsDataType    # 列出所有已加载的 kext
pluginkit -mDAv                         # 列出所有插件
```

Big Sur 没有公开的"列出待批准 kext"命令，所以这条没好办法直接查。

### 原因 5：用 `spctl kext-consent` 查看

这是个隐藏命令，能看到当前待批准的 kext bundle ID：

```zsh
sudo spctl kext-consent list
```

输出类似：

```
EQHXZ8M8AV        com.realtek.driver.RtWlanU              REALTEK SEMICONDUCTOR CORP
EQHXZ8M8AV        com.realtek.driver.RtWlanU1827          REALTEK SEMICONDUCTOR CORP
```

`EQHXZ8M8AV` 是 Realtek 的 Developer ID。批准就等于把 developer ID + bundle ID 加入白名单。

**通过命令行批准**（不进 GUI）：

```zsh
sudo spctl kext-consent add EQHXZ8M8AV
```

但这只是加入白名单，**仍需重启**才生效。

## 备查：删除已批准的 kext

如果想撤销批准，把 kext 删掉 + 重建缓存即可：

```zsh
sudo rm -rf /Library/Extensions/YourDriver.kext
sudo kextcache -i /
sudo reboot
```

如果要彻底清除"已批准 developer ID"记忆：

```zsh
sudo spctl kext-consent reset
```

这条会清空所有已批准的 developer ID，下次装新 kext 都要重新批准。**慎用**——会影响所有第三方 kext，不只是你想删的那个。

## 总结

Big Sur 的 User-Approved Kernel Extensions 是 Apple 给 kext 加的最后一道用户层闸门。流程其实就 5 步：

1. 关 SIP 的 Kext Signing（恢复模式）
2. 装 kext 到 `/Library/Extensions/`
3. `sudo kextcache -i /` 重建缓存
4. System Preferences → Security & Privacy → General → Allow
5. **重启**

最容易踩的坑是第 4 步找不到批准提示（多半是延迟或没触发事件），以及第 5 步被忽略——`kextload` 的 `not approved to load` 报错**不**意味着没批准，而是批准了但没重启生效。

下一篇写写 gh CLI 在 Big Sur 上为什么装不了最新版，以及怎么找一个能跑的旧版本。
