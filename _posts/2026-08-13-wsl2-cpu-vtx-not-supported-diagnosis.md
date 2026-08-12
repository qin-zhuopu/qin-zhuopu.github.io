---
layout: post
title: "WSL2 转换失败？别折腾软件配置了，先查 CPU 是否真的支持 VT-x"
date: 2026-08-13 21:30:00 +0800
categories: [技术踩坑]
tags: [WSL2, Hyper-V, 嵌套虚拟化, VDI, Windows]
---

把 WSL1 的发行版转成 WSL2，反复报"请启用虚拟机平台 Windows 功能，并确保在 BIOS 中启用虚拟化"。照着提示把功能开了又开、重启了又重启都不管用——最后发现根因是这台机器的 CPU 压根不支持硬件虚拟化指令集（VT-x）。这篇记录一条从报错套话一路挖到硬件层的排查链。

## 问题现象

在一台 Windows 机器上，想把已有的 WSL1 发行版转成 WSL2：

```powershell
wsl --set-version Ubuntu 2
```

每次都返回退出码 `-1`，输出（中文环境）：

```
正在进行转换，这可能需要几分钟时间...
请启用 WSL 2 所需的虚拟机平台功能，并确保在 BIOS 中启用虚拟化。
有关信息，请访问 https://aka.ms/wsl2
```

同样地，用 `wsl --import` 重新装一个 WSL2 发行版也失败，报错几乎一样。最坑的是这段话是**固定套话**，没有任何文件、路径、错误码级别的具体信息，难以判断到底卡在哪一层。

## 环境信息

- OS: Windows 10 Enterprise LTSC 2021 (build 19044)
- 机型: 一台 VDI 虚拟桌面（Hypervisor 平台侧虚拟化）
- WSL: 内核 5.10.16，默认版本 2

## 排查过程

错误文本指向两个方向：① 虚拟机平台功能没开；② BIOS 虚拟化没开。逐项核实。

### 1. 先确认功能真的开了

用管理员 DISM 查所有相关功能（中文系统下注意"状态"字段是中文，别用英文 `State` 去匹配）：

```powershell
# 查单个功能
dism.exe /online /get-featureinfo /featurename:VirtualMachinePlatform
# 列出所有 Hyper-V/WSL 相关功能
dism.exe /online /get-features /format:table | findstr /R "Hyper-V VirtualMachine HypervisorPlatform Windows-Subsystem"
```

或用 PowerShell：

```powershell
'VirtualMachinePlatform','Microsoft-Windows-Subsystem-Linux','Microsoft-Hyper-V-Hypervisor' |
  ForEach-Object { (Get-WindowsOptionalFeature -Online -FeatureName $_) | Select FeatureName, State }
```

结果：`VirtualMachinePlatform`、`Microsoft-Windows-Subsystem-Linux`、`Microsoft-Hyper-V-*`、`HypervisorPlatform` **全部 = 已启用 / Enabled**。功能没问题。

> 注意：`Get-WindowsOptionalFeature` 查询状态本身就需要管理员权限（会报"该参数需要提升权限"）。可以把它写进 `.ps1`，用 `Start-Process -Verb RunAs` 提权执行，结果写到临时文件再读回。

### 2. 确认是否需要重启

启用功能后不重启，内核组件不会真正加载。检查挂起重启：

```powershell
# 注册表方式查 pending reboot
Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager' -Name PendingFileRenameOperations
# CBS / Windows Update 挂起
Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending'
```

存在 `PendingFileRenameOperations` 就说明改过系统、需要重启。重启一次后再试——如果还失败，说明不是 pending reboot 的问题。

### 3. 查事件日志里的"真实"错误（关键）

`wsl` 自己不吐具体错误，但 Hyper-V 的主机计算服务 HCS 会在事件日志里留下带错误码的记录。这一步是**整个排查的转折点**：

```powershell
# 先触发一次失败，让新错误进日志，再查最近 3 分钟的事件
$stamp = (Get-Date).AddMinutes(-3)
Get-WinEvent -FilterHashtable @{
    LogName = 'Microsoft-Windows-Hyper-V-Compute-Admin'
    StartTime = $stamp
} | ForEach-Object { "[$($_.TimeCreated)] ID=$($_.Id): " + (($_.Message -split "`r?`n")[0]) }
```

输出（每次 `wsl --set-version` 失败都会触发一条）：

```
[...] ID=11008: 操作失败: 未安装 Hyper-V，因此无法启动系统 {...} 。
```

**事件 ID `11008`**，来源 `Microsoft-Windows-Hyper-V-Compute-Admin`。这条比 `wsl` 那句套话精确得多——它在说 HCS 试图为 WSL2 启动一个工具型虚拟机时，发现 Hyper-V 没真正就绪。功能显示 Enabled 但 HCS 说没装，典型的"内核组件没加载"。

### 4. 检查 hypervisor 是否真的在跑

```powershell
# bcdedit 看 hypervisor 启动策略（需管理员）
bcdedit /enum '{current}' | Select-String 'hypervisorlaunchtype'
# systeminfo 看虚拟化
systeminfo | Select-String 'Hyper-V'
```

正常情况下 `hypervisorlaunchtype` 应为 `Auto`，`systeminfo` 应显示虚拟化已启用 / 已检测到虚拟机监控程序。

到这一步，如果功能全开、重启过、hypervisor 也 launch=Auto，但 11008 依旧——**几乎可以断定问题出在 CPU 硬件虚拟化能力上**。

### 5. 最终判别：查 CPU 的 VT-x 支持位（决定性）

```powershell
Get-CimInstance Win32_Processor | Select-Object Name,
    VirtualizationFirmwareEnabled,
    VMMonitorModeExtensions,
    SecondLevelAddressTranslationExtensions
```

注意三个字段的区别，**别只看第一个**：

| 字段 | 含义 |
|------|------|
| `VirtualizationFirmwareEnabled` | 仅表示 **BIOS 里有这个开关且开着**，不代表 CPU 真支持 |
| `VMMonitorModeExtensions` | **CPU 是否真的支持 VT-x 指令集**（这才是关键） |
| `SecondLevelAddressTranslationExtensions` | 是否支持 SLAT（EPT/NPT），WSL2/Hyper-V 也需要 |

本例输出：

```
Name                                    : Intel(R) Core(TM)2 Duo CPU T7700 @ 2.40GHz
VirtualizationFirmwareEnabled           : True
VMMonitorModeExtensions                 : False   ← 真相
SecondLevelAddressTranslationExtensions : False
```

`VirtualizationFirmwareEnabled=True` 就是最大的烟雾弹——它让你以为"BIOS 虚拟化已开"。但 `VMMonitorModeExtensions=False` 才说了实话：**这颗 CPU（Core 2 Duo T7700，2007 年的型号）物理上不支持 Intel VT-x**，没有硬件虚拟化指令集，WSL2/Hyper-V 根本无从启动。

## 根因分析

这台机器是一台 **VDI 虚拟桌面**（`Win32_ComputerSystem` 的 `Manufacturer` / `Model` 暴露了底层 Hypervisor 平台），它的虚拟 CPU 被分配/模拟成了一个**不支持 VT-x 的老型号**。

WSL2 依赖 Hyper-V，Hyper-V 依赖 CPU 的**硬件虚拟化（VT-x + SLAT）**。当虚拟机平台没有开启**嵌套虚拟化（nested virtualization）**——即没有把宿主机的 VT-x 能力暴露给虚拟机内部的 Hyper-V 使用时，虚拟机里的 `VMMonitorModeExtensions` 就是 `False`，于是：

- 所有 Windows 功能都显示 Enabled
- `hypervisorlaunchtype = Auto`
- 但 hypervisor 实际起不来，HCS 报 11008
- `wsl --set-version` / `wsl --import` 全部失败

软件层面无论怎么改都绕不过去。

## 最终方案

这是 VDI / 虚拟化平台侧的配置问题，**用户自己无法解决**，需要联系平台管理员：

1. 在底层 Hypervisor 平台（本例是公司 VDI 平台）为该虚拟机**开启嵌套虚拟化**，或
2. 换一个 CPU 型号支持 VT-x 的 vCPU 配置

开好后，之前做的所有软件层准备就自动生效（功能已就绪），直接 `wsl --import` 一条命令就能装好 WSL2 发行版。

## 几个排坑要点

- **`wsl` 的报错是套话**，别在上面死磕，第一时间去看事件日志 `Microsoft-Windows-Hyper-V-Compute-Admin` 的 ID 11008。
- **`VirtualizationFirmwareEnabled` 不等于 CPU 支持虚拟化**，它只反映 BIOS 开关。真正的判别是 `VMMonitorModeExtensions` 和 `SecondLevelAddressTranslationExtensions`。
- **`systeminfo` 说"已检测到虚拟机监控程序"也可能是烟雾弹**，以 `Win32_Processor` 的扩展位为准。
- 在 VDI / 云桌面 / 嵌套虚拟机环境里装 WSL2，先确认宿主有没有暴露 VT-x，否则白折腾。
- 顺带：`wsl --set-version` 转换需要**临时磁盘空间**（大约等于发行版大小），C 盘满了（`ENOSPC`）也会让转换 / 安装莫名失败，记得先查 `df` / 盘符剩余空间。

## 关键命令速查

```powershell
# 1. 查 Windows 可选功能状态（需管理员）
dism.exe /online /get-features /format:table | findstr /R "Hyper-V VirtualMachine HypervisorPlatform Windows-Subsystem"

# 2. 查挂起重启
(Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager' -Name PendingFileRenameOperations -ErrorAction SilentlyContinue).Count

# 3. 查 HCS 真实错误（事件 ID 11008 = Hyper-V 未就绪）
Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-Hyper-V-Compute-Admin'; StartTime=(Get-Date).AddMinutes(-5)} |
  ForEach-Object { "ID=$($_.Id): " + (($_.Message -split "`r?`n")[0]) }

# 4. 决定性判别：CPU 是否真支持 VT-x
Get-CimInstance Win32_Processor | Select-Object Name, VirtualizationFirmwareEnabled, VMMonitorModeExtensions, SecondLevelAddressTranslationExtensions

# 5. 是否虚拟机 / 什么平台
Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer, Model

# 6. WSL1 转换、或直接 import 装到非系统盘
wsl --set-version Ubuntu 2
wsl --import Ubuntu D:\WSL\Ubuntu D:\path\to\rootfs.tar.gz --version 2
```

## 参考

- [WSL 2 installation — Microsoft Learn](https://aka.ms/wsl2-install)
- [Win32_Processor — VirtualizationFirmwareEnabled vs VMMonitorModeExtensions](https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-processor)
- [Nested Virtualization — Hyper-V](https://learn.microsoft.com/en-us/virtualization/hyper-v-on-windows/user-guide/nested-virtualization)
