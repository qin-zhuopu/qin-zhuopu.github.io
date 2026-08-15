---
layout: post
title: "给不明身份的 STM32 板子找回出厂固件源码：Keil CMSIS-Pack 挖掘记"
date: 2026-08-16 00:05:00 +0800
categories: [技术踩坑]
tags: [STM32, Keil, CMSIS-Pack, USB, 固件分析]
---

淘宝买的一块 STM32 板子，到手时跑着陌生固件，想知道这固件哪来的、有没有源码。这篇记录从 USB 取证定位固件身份，到在 Keil 官方 CMSIS-Pack 里挖出同款 demo 源码的完整过程。

## 问题现象

- 一块不明身份的 STM32 板子，插上电脑枚举出一个 8 KB 的仿真磁盘（FAT12）
- 磁盘里只有一个 2007 年的 ReadMe.txt，自述是某个评估板的 USB 存储演示固件
- 想找这份演示固件的源码，官方渠道似乎早已停发

## 环境信息

- OS: macOS 11（Intel）
- 工具: curl / unzip / gh (GitHub CLI)
- 板卡: STM32F103 系列（Blue Pill 形态，跑着 Keil 评估板 demo）

## 排查过程

### 第一步：从固件自曝的身份入手

USB 设备字符串显示它是 Keil 出品的存储演示（VID `0xC251` 是 Keil/ARM 的厂商号），仿真磁盘里的 ReadMe 直接写明对应的评估板型号和芯片。

线索有了，但这是 2007 年的固件——那个年代 Keil 的板级例程随 MDK4 安装包发布，如今官方主推 MDK5 + CMSIS-Pack 体系，老安装包已经不提供了。

### 第二步：GitHub 找镜像，失败

用 GitHub CLI 搜代码（按 demo 的特征文件名、路径关键词）：

```bash
gh api "search/code?q=MCBSTM32+usb+in:path&per_page=15" \
  --jq '.items[] | .repository.full_name + "  " + .path'
```

结果只有零散的无关工程（LPC 板的同类例程、别的评估板例程），**原版 demo 没有完整镜像**。

### 第三步：转向 CMSIS-Pack 体系，成功

Keil MDK5 时代，器件支持包（DFP）是公开下载的，而且 `.pack` 文件本质就是 zip。关键发现：**新版 F1 器件包里仍保留着同系列评估板的板级例程**，包括同技术栈（Keil RL-USB + RTX）的 USB Device 例程。

获取流程：

```bash
# 1. 拉包索引，找到目标包的最新版本号
curl -sL https://www.keil.com/pack/index.pidx -o index.pidx
grep -o '<pdsc url="[^"]*" vendor="Keil" name="STM32F1xx_DFP" version="[^"]*"' index.pidx
# → version="2.4.1"

# 2. 下载（.pack = zip，约 50 MB）
curl -sL https://www.keil.com/pack/Keil.STM32F1xx_DFP.2.4.1.pack -o f1.pack

# 3. 直接解压浏览
unzip -q f1.pack -d f1pack
find f1pack/Boards -maxdepth 3 -type d
```

解压后果然在 `Boards/Keil/<评估板>/Middleware/USB/Device/` 下找到三份 USB 设备例程，应用层源码齐全：

- **MassStorage** —— 和板上跑的 demo 同类（`MassStorage.c` + `USBD_User_MSC_0.c`）
- **VirtualCOM** —— USB 虚拟串口
- **HID** —— 键盘鼠标类设备

### 第四步：备一条完全开源的路

Keil 例程是 MDK 工程（Windows 向）。作为补充，ST 官方的 USB-FS-Device 库在 GitHub 有多个镜像，完全开源、可用 GCC 编译，且例程更全——其中 **Device_Firmware_Upgrade (DFU)** 例程尤其有价值（见下文）。

```bash
git clone --depth 1 https://github.com/<mirror>/STM32_USB-FS-Device_Lib.git
```

## 根因分析

老一代评估板例程的命运：**随 IDE 安装包分发 → IDE 换代 → 安装包停发**，但例程本身被吸收进了 CMSIS-Pack 体系继续存在，只是换了位置（`Boards/` 目录进 DFP）。找不到的原因不是没了，而是入口变了。

另外注意：DFP 里的例程只有应用层源码，USB 协议栈本体在单独的 **MDK-Middleware** 包里——想完整编译仍需 Keil 环境；想彻底开源就用 ST 自己的库。

## 最终方案

| 需求 | 方案 |
|---|---|
| 看 demo 原理 / 同款例程 | 解压 Keil DFP pack，看 `Boards/Keil/*/Middleware/USB/Device/` |
| 脱离 Keil / 开源编译 | ST 官方 USB-FS-Device 库（GitHub 镜像）+ arm-none-eabi-gcc |
| 以后免烧录器升级 | 先想办法烧一次 ST 库的 **DFU 例程**，之后纯 USB 口升级固件 |

### 附带一个网络坑

keil.com 国内直连不稳定：`curl` 返回 302 或空文件，但不算失败（退出码 0），容易误判。用 `-w "HTTP:%{http_code} SIZE:%{size_download}\n"` 确认真实状态，必要时走代理。

## 关键命令速查

```bash
# 从未知 USB 设备取证身份
system_profiler SPUSBDataType | grep -B2 -A8 -i "product"
diskutil list                       # 有没有挂出仿真磁盘
cat /Volumes/<卷名>/ReadMe.txt      # 磁盘里的说明文件往往自曝身份

# CMSIS-Pack 挖掘
curl -sL https://www.keil.com/pack/index.pidx -o idx.pidx   # 包索引
unzip -q xxx.pack -d dir                                     # pack 就是 zip

# GitHub 代码搜索（需 gh auth）
gh api "search/code?q=<特征文件名或路径>&per_page=10" --jq '.items[].path'
```

## 方法论小结

识别不明固件板卡的三板斧：

1. **USB 字符串取证**：产品名/厂商/VID-PID 直接暴露固件出身
2. **仿真磁盘内容**：demo 固件挂出的盘里常有 ReadMe 自述
3. **官方 pack 考古**：`.pack` 是公开 zip，`Boards/` 目录是板级例程的活化石
