---
layout: post
title: "在 macOS Big Sur 上给 RTL8188GU USB 网卡装驱动：一次完整的折腾记录"
date: 2026-07-31 08:00:00 +0800
categories: macOS
series: big-sur-series
---

最近翻出一颗旧的 USB 无线网卡想接到老 Mac 上用，结果一路踩坑到天黑。把全过程写下来，免得下次再踩。

> 适合读者：手上有一台跑 macOS 11 Big Sur 的 Intel Mac，有一颗 Realtek 芯片的 USB Wi-Fi 网卡，不想花钱买新的，愿意折腾。

## 0. 设备和环境

**Mac 信息**：

```
ProductName:    macOS
ProductVersion: 11.7.10
BuildVersion:   20G1427
架构:           x86_64 (Intel)
```

**USB 网卡信息**（插上后 `system_profiler SPUSBDataType` 看到的）：

```
802.11n WLAN Adapter:
    Product ID: 0xb711
    Vendor ID:  0x0bda  (Realtek Semiconductor Corp.)
    Version:    2.00
    Serial Number: 00E04CB82101
    Speed:      Up to 480 Mb/s
    Manufacturer: Realtek
```

设备贴纸写的是 "150Mbps Wireless N Nano USB Adapter"，实际芯片 Realtek **RTL8188GU**（Realtek 内部归到 `RtWlanU` 驱动包里和 RTL8710BU 共用 personality）。

## 1. 第一次插入：先变成光盘，再变成网卡

这颗网卡插上去的**第一秒**，并不是网卡，而是一个虚拟光驱：

```
DISK:
    Product ID: 0x1a2b       ← 注意这个 PID
    Vendor ID:  0x0bda
    Media:
      USB Disk autorun:
        Capacity: 154.1 MB
        Partition Map Type: Unknown
```

PID `0x1a2b` 是 Realtek 的"模式切换占位符"——设备先以**虚拟光驱**形态出现，里面是 Windows 的驱动安装包（autorun 光盘镜像）。在 Windows 上由驱动自动切换到网卡模式；在 macOS 上没有自动切换工具，但**这颗网卡能自己切换**——插上几秒后 PID 自动变成 `0xb711`，变身为 `802.11n WLAN Adapter`。

如果你的设备不会自动切换，停在 `0x1a2b`：
- 装一个 `usb_modeswitch`（`brew install usb_modeswitch`），手动发切换命令
- 或者去 Windows 上用 Realtek 自家工具禁用 autorun 模式

## 2. macOS Big Sur 没有自带驱动

切换到 `0xb711` 后，设备是网卡了，但 macOS 没有 RTL8188GU 的驱动。`networksetup -listallhardwareports` 里看不到新接口。

Realtek 官方多年前就停止维护 macOS 驱动了。**社区主流方案**是 [chris1111](https://github.com/chris1111) 维护的两个项目（Hackintosh 社区，基于 Realtek 最后一次发布的官方 macOS kext 重打包）：

- `Wireless-USB-OC-Big-Sur-Adapter`（OpenCore 变体，走 EFI 引导器）
- `WirelessAdapterCloverBigSur`（Clover 变体，同上）

但这两个项目其实有**两种不同的发布格式**，对应不同的 zip 包，**只有一个能用**：

| 文件名 | 是否含 kext | 适用场景 |
|---|---|---|
| `Wireless.USB.OC.Big.Sur.Adapter-V16.zip` | ❌ 只装 LaunchDaemon 和 EFI 引导器脚本 | 需要走 OpenCore 引导，复杂 |
| `Wireless.USB.Big.Sur.Adapter-V17.zip`    | ✅ 含真正的 `RtWlanU.kext` | **普通 Intel Mac 用这个** |

**避坑**：V16 里我打开看了，全部子包都是 LaunchDaemon / 状态栏 app / EFI 脚本，**根本没有 kext 文件**。装了也没用。**直接用 V17**。

## 3. 验证 PID 是否被驱动支持（关键步骤）

下载 V17 之前先做一件事：**验证你的 PID 是否在 kext 支持列表里**。chris1111 的 kext 是 Realtek 老驱动的重打包，PID 表是固定的——如果你的 PID 不在表里，装了也加载不上。

V17 内置的 `RtWlanU.kext/Contents/Info.plist` 在 `IOKitPersonalities` 下有 **172 个 personality 条目**，每个对应一组 VID/PID。先解压 V17，然后跑下面 Python 脚本验证：

```python
# check_pid.py
import plistlib, sys

plist_path = "RtWlanU.kext/Contents/Info.plist"
target_pid = 0xb711   # 改成你的 PID
target_vid = 0x0bda   # 改成你的 VID

with open(plist_path, "rb") as f:
    p = plistlib.load(f)

matches = []
def walk(obj, path=""):
    if isinstance(obj, dict):
        if obj.get("idProduct") == target_pid and obj.get("idVendor") == target_vid:
            matches.append(path)
        for k, v in obj.items():
            walk(v, f"{path}/{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            walk(v, f"{path}[{i}]")

walk(p)
print(f"PID 0x{target_pid:04x} / VID 0x{target_vid:04x} 命中 {len(matches)} 处:")
for m in matches:
    print(f"  {m}")
```

**我的结果**：

```
PID 0xb711 / VID 0x0bda 命中 1 处:
  /IOKitPersonalities/RTL8188GU_RTL8710BU
```

完美命中——驱动**原生支持**这个 PID，不需要改 Info.plist。

如果**没命中**：要么换网卡，要么手动编辑 kext Info.plist 在 `IOKitPersonalities` 下加一个 personality，再重新签名 + 重建 kext cache，复杂度高很多。

## 4. 检查 SIP 状态（决定要不要进恢复模式）

Big Sur 默认是开启 SIP（System Integrity Protection）的，未签名 kext 加载不了。先看现状：

```zsh
csrutil status
```

我的输出是：

```
System Integrity Protection status: unknown (Custom Configuration).

Configuration:
    Apple Internal: disabled
    Kext Signing: disabled             ← 关键
    Filesystem Protections: disabled   ← 关键
    Debugging Restrictions: enabled
    DTrace Restrictions: enabled
    NVRAM Protections: enabled
    BaseSystem Verification: enabled
```

**Kext Signing 和 Filesystem Protections 都是 disabled**——这是因为这台机器以前折腾过别的，已经预先关好了。所以我**不需要**进恢复模式。

**如果你的 SIP 是默认 enabled**，需要：
1. 关机 → 开机时按住 `Cmd+R` 进入恢复模式
2. 顶部菜单 → 实用工具 → 终端
3. 跑 `csrutil disable`
4. 重启

## 5. 安装步骤

### 5.1 下载 V17

从 [chris1111 的 GitHub release](https://github.com/chris1111/WirelessAdapterCloverBigSur/releases) 下载 `Wireless.USB.Big.Sur.Adapter-V17.zip`（国内访问 GitHub 慢的话挂代理 `localhost:8080`）。

### 5.2 解压并找到真正的 pkg

zip 解压后，真正的安装包藏在 app bundle 里：

```
Wireless USB Big Sur Adapter-V17/
└── Wireless USB Big Sur Adapter.app/
    └── Contents/Resources/.Files/
        └── Wireless USB Big Sur Adapter.pkg
```

注意是隐藏目录 `.Files`，Finder 里按 `Cmd+Shift+.` 才能看到。

把它复制到桌面方便引用：

```zsh
cp "Wireless USB Big Sur Adapter-V17/Wireless USB Big Sur Adapter.app/Contents/Resources/.Files/Wireless USB Big Sur Adapter.pkg" \
   ~/Downloads/WirelessUSBAdapter-V17.pkg
```

### 5.3 安装 pkg

```zsh
sudo installer -pkg ~/Downloads/WirelessUSBAdapter-V17.pkg -target /
```

预期输出：

```
installer: Package name is Wireless USB Big Sur Adapter-V17
installer: Installing at base path /
installer: The install was successful.
```

装完后会在以下位置出现文件：

```
/Library/Extensions/RtWlanU.kext                ← 主驱动
/Library/Extensions/RtWlanU1827.kext            ← 1827 系列驱动
/Library/LaunchDaemons/com.109Driver.*.plist    ← 开机守护进程
/Library/LaunchAgents/com.109Driver.*.plist     ← 登录项
/Library/Application Support/WLAN/              ← Realtek 工具
/Applications/Wireless USB Big Sur Adapter.app  ← 状态栏 app
```

### 5.4 重建 kext 缓存

```zsh
sudo kextcache -i /
```

预期输出：

```
Executing: /usr/bin/kmutil install --volume-root / --check-rebuild
rebuilding local auxiliary collection
kmutil done
```

### 5.5 在系统设置里批准加载（Big Sur 必经步骤）

Big Sur 引入了 **User-Approved Kernel Extensions** 机制。装上 kext 不算完，系统会让你手动批准：

1. 打开 **系统偏好设置 → 安全性与隐私 → 通用**
2. 应该看到一条提示：
   > "System software from developer 'REALTEK SEMICONDUCTOR CORP' was blocked from loading."
3. 点 **Allow**，输入密码

**看不到提示？** 常见原因：
- 提示延迟出现，等几分钟
- 拔插一次 USB 网卡触发
- 已经批准过但没重启

### 5.6 重启

**必须重启**。Big Sur 的 User-Approved kext 批准后，需要重启才会把 kext 加入 auxiliary kext collection 在启动时加载。**软件层面无法绕过这个重启**。

我试过不重启直接 `sudo kextload /Library/Extensions/RtWlanU.kext`，报错：

```
Error Domain=KMErrorDomain Code=27
"Extension with identifiers com.realtek.driver.RtWlanU1827,com.realtek.driver.RtWlanU
not approved to load. Please approve using System Preferences."
```

——批准了但没生效，老老实实重启。

## 6. 重启后验证

```zsh
# 1. kext 是否加载
kextstat | grep -i realtek
```

应该看到一行：

```
129    0 0xffffff7f9cd28000 0x2a2000 0x2a2000 com.realtek.driver.RtWlanU (1830.32.b27) DB501FB3-...
```

```zsh
# 2. 是否出现新网络接口
networksetup -listallhardwareports
```

应该多出来：

```
Hardware Port: 802.11n WLAN Adapter
Device: en5
Ethernet Address: 90:de:80:b8:64:05
```

```zsh
# 3. 接口状态
ifconfig en5
```

`status: active` 表示无线层面已经关联 AP。

## 7. 关联 Wi-Fi

第三方 Wi-Fi 接口在 macOS 上**不能用**标准的 `networksetup -getairportnetwork en5`（会报 "en5 is not a Wi-Fi interface"）。关联 AP 的几种方式：

### 方式一：用 Realtek 自带的状态栏 app

V17 包装了 `/Applications/Wireless USB Big Sur Adapter.app`，启动它，菜单栏会多一个 Wi-Fi 图标，点它选 SSID、输密码。

### 方式二：用 airport 命令行查关联状态

```zsh
/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport -I
```

成功关联会看到：

```
     agrCtlRSSI: -45              ← 信号强度（越接近 0 越强，-45 已经很好）
          state: running
        op mode: station
     lastTxRate: 145              ← 当前发射速率 Mbps
        maxRate: 144
          BSSID: 30:fc:68:8b:e0:ee
           SSID: w                ← 关联到的 AP 名
        channel: 6                ← 2.4GHz 信道
      802.11 auth: open
        link auth: wpa2-psk
```

### 方式三：系统偏好设置 → 网络

在左侧列表里找到 "802.11n WLAN Adapter"，"Configure IPv4" 选 **Using DHCP**，点 Apply。如果显示 "Not Connected"，等几秒自动 DHCP 续约；不行就点 "Renew DHCP Lease"。

## 8. 最终成果

```zsh
ifconfig en5
```

```
en5: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
    options=400<CHANNEL_IO>
    ether 90:de:80:b8:64:05
    inet6 fe80::4ee:c167:c01d:d73d%en5 prefixlen 64 secured scopeid 0xa
    inet 192.168.1.123 netmask 0xffffff00 broadcast 192.168.1.255
    media: autoselect
    status: active
```

| 项目 | 值 |
|---|---|
| 接口 | `en5`（802.11n WLAN Adapter） |
| MAC | `90:de:80:b8:64:05` |
| IP | `192.168.1.123`（DHCP） |
| 子网掩码 | `255.255.255.0` |
| 网关 | `192.168.1.1` |
| 关联 SSID | `w` |
| 信道 | 6（2.4GHz） |
| 信号 RSSI | -45 dBm（很好） |
| 速率 | 145 Mbps |
| 加密 | WPA2-PSK |

**连通性测试**：

```zsh
ping -c 2 192.168.1.1     # 网关 3 ms
ping -c 2 8.8.8.8         # 公网 224 ms
ping -c 1 www.baidu.com   # DNS 解析正常 32 ms
```

**默认路由走 en5**（优先级高于内置 Wi-Fi）：

```zsh
netstat -rn | grep ^default
```

```
default            192.168.1.1        UGScg          en5     ← USB 网卡优先
default            192.168.0.1        UGScIg         en0     ← 内置 Wi-Fi 备用
```

## 9. 坑点总结

复盘一下这次折腾踩的坑：

### 9.1 V16 和 V17 的区别

V16 是 OpenCore 变体，**不含 kext**，只装 EFI 引导脚本。如果你不打算给 Mac 加 OpenCore 引导器，**V16 装了等于没装**。**用 V17**——它把 kext 直接装到 `/Library/Extensions`，是普通驱动安装方式。

### 9.2 PID 必须先验证

很多 Realtek USB Wi-Fi 网卡的 PID **不在** chris1111 kext 的支持列表里。装之前先用第 3 节的 Python 脚本验证 PID 命中。不命中要手动改 Info.plist 加 personality，麻烦很多。

### 9.3 首次插入显示成 DISK 是正常的

PID `0x1a2b` 是 Realtek 模式切换占位符，等几秒自动切换到真实 PID。本设备能自动切换，省了一步。

### 9.4 User-Approved 必须重启

Big Sur 的 User-Approved kext 机制硬性要求：批准后**必须重启**。`kextload` 命令无法绕过——会一直报 `not approved to load`。

### 9.5 Apple Silicon 不支持

两个 chris1111 项目都明确写 **"Does not work on M1/M2/M3/M4"**。kext 是 Intel x86_64 内核扩展，Apple Silicon 用的是 Apple Kernel Cache 机制，无法加载。**只有 Intel Mac 能用**。

### 9.6 macOS 12+ 兼容性未确认

本文只在 **macOS 11.7.10 Big Sur** 上验证通过。Monterey / Ventura / Sonoma 上 kext 加载机制更严格（要求 notarization），Realtek 老 kext 大概率用不了。如果你在更新版本上试成功了，欢迎评论告诉我。

### 9.7 System Preferences 找不到批准提示

如果 Security & Privacy → General 下没有"系统软件被阻止"提示：
- 等几分钟（提示有时延迟）
- 拔插一次网卡触发
- 已经批准过的话直接看 `kextstat | grep -i realtek`

### 9.8 顺手记录：在这台机器上装 gh CLI 也踩坑

写这篇文章的过程中想用 GitHub CLI 查博客仓库，发现：

- **新版 `gh` 2.96.0 不能在 Big Sur 上跑**：调用 `_SecTrustCopyCertificateChain` 系统函数（macOS 12+ 才有），dyld 加载时报 `Symbol not found`
- **`brew install gh` 也失败**：依赖新版 Go，Go 要求 macOS 12+
- **解决**：从 [GitHub Release](https://github.com/cli/cli/releases) 直接下载 **`gh 2.39.2`**（2023 年 11 月发布的最后一个支持 Big Sur 的版本），二进制解压放到 `~/bin/gh` 就能用

```zsh
curl -L -o gh.zip "https://github.com/cli/cli/releases/download/v2.39.2/gh_2.39.2_macOS_amd64.zip"
unzip gh.zip
cp gh_2.39.2_macOS_amd64/bin/gh ~/bin/gh
```

## 10. 如果不折腾的替代方案

老实说，为了一个 150 Mbps 单频 2.4GHz USB 网卡，在一台正常工作的 Mac 上动用未签名 kext + 关 SIP + 重启，**投入产出比不高**。如果不是必要（比如内置网卡坏了、需要单独的物理网络接口），更推荐：

- 买一颗**明确标注 macOS 兼容**的 USB Wi-Fi，比如 Panda Wireless PAU06、Edimax EW-7811Un（虽老但有官方驱动）
- 或者直接用内置 AirPort——大部分场景内置网卡性能都比这种 USB 单频网卡强

但如果就是想折腾，或者手头只有这颗网卡，希望这篇文章能帮到你。

---

**全文验证环境**：

| 项 | 值 |
|---|---|
| 机器 | MacBook Pro (Intel) |
| 系统 | macOS 11.7.10 Big Sur (Build 20G1427) |
| 架构 | x86_64 |
| SIP | Custom Configuration（Kext Signing disabled） |
| 网卡芯片 | Realtek RTL8188GU |
| USB VID/PID | `0bda:b711` |
| 驱动来源 | `Wireless.USB.Big.Sur.Adapter-V17.zip` |
| kext 版本 | RtWlanU 1830.32.b27 / RtWlanU1827 1827.4.b36 |
