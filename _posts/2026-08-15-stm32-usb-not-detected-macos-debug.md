---
layout: post
title: "STM32 开发板插上电脑没反应？macOS 下 USB 排查实录"
date: 2026-08-15 23:16:45 +0800
categories: [技术踩坑]
tags: [STM32, macOS, USB, pyocd, 嵌入式]
---

一块 STM32 板子插上 Mac，既没有串口也没有任何反应。这篇记录从零开始的排查过程，以及最后发现"它其实不是调试器，是板子自己在装磁盘"的反转。

## 问题现象

- STM32 开发板通过 USB 插到 macOS，`/dev/cu.*` 下没有任何新串口
- 系统报告里也看不到新 USB 设备
- 板上电源灯正常点亮

## 环境信息

- OS: macOS 11（Intel）
- Shell: zsh
- 板卡: STM32F103 系列评估板（一开始身份未知）
- 工具: system_profiler / ioreg / diskutil / pyocd

## 排查过程

### 第一步：分清"缺驱动"和"没枚举"

macOS 下查看 USB 设备树：

```bash
system_profiler SPUSBDataType
ls /dev/cu.* /dev/tty.*
```

这里有个关键区分：

| 现象 | 结论 |
|---|---|
| USB 树里**能看到设备**，但没有 `/dev/cu.*` 串口 | 缺串口驱动（CH340/CP210x 之类），设备本身是好的 |
| USB 树里**根本没有**设备 | USB 枚举都没完成：线的问题、接口接触不良、或设备固件没开 USB |

我的情况是 USB 树里只有摄像头、键盘、蓝牙这些内置设备——连枚举都没有，所以直接排除了驱动问题。

### 第二步：电源灯亮 ≠ 数据通

板上电源灯亮，只证明 USB 的 5V（VBUS）供电通了，**不能证明 D+/D- 数据线是通的**。大量 Micro-USB 线是纯充电线，内部根本没有数据线芯，表现就是：灯亮、电脑毫无反应。

**换了一根确认能传数据的线之后，设备出现了。**

### 第三步：识别出的设备居然不是调试器

换线后 USB 树里多出一个设备：

```
Product ID: 0x1c03
Vendor ID: 0xc251 (Keil Software)
Manufacturer: Keil Software
```

VID `0xC251` 是 Keil（ARM）的厂商号。装好 pyocd 后 `pyocd list` 却报 "No available debug probes are connected"——因为它根本不是调试器，而是**板子本身**：板上跑着 Keil 出厂示例固件，把 USB 枚举成了一个 Mass Storage 存储设备。

### 第四步：从仿真磁盘里挖出板卡身份

这个设备在系统里挂出了一个 8 KB 的 FAT12 小磁盘：

```bash
diskutil list
# /dev/disk3 (external, physical):
#   0:  STM32x_USB  *8.2 KB  disk3

ls /Volumes/STM32x_USB/
# ReadMe.txt
```

ReadMe.txt 的内容直接揭晓了板卡身份：

```
This is a USB Memory Device demonstration for
the Keil MCBSTM32 Board with ST STM32F103RBT6.
```

一块 Keil MCBSTM32 评估板，主控 STM32F103RBT6。注意这个磁盘是固件仿真的，**别往里写东西**。

## 根因分析

两个叠加的认知盲区：

1. **物理层**：USB 线是纯充电线，数据线芯缺失，设备连枚举都无法完成。电源灯亮极具迷惑性。
2. **协议层**：STM32 的 USB 口不是"自带的串口"。只有固件里实现了 USB CDC（虚拟串口）、HID 或 Mass Storage 之类的能力，插上电脑才会有设备出现。这块板跑的出厂 demo 恰好实现的是 MSD，所以它伪装成了一个 8 KB 磁盘——既不是串口，也不是调试器。

## 最终方案

- 换用支持数据传输的 USB 线（问题一解决）
- 板卡身份通过仿真磁盘里的 ReadMe.txt 确认
- 想烧录自己的固件：F103 的 ROM 引导程序只支持 UART ISP（BOOT0 拉高 + USART1），**没有 USB DFU**；调试烧录需要 ST-Link + SWD
- 想要 USB 虚拟串口：得先烧一个实现了 CDC 的固件

### 附：pyocd 安装的两个坑

macOS 上装 pyocd 连摔两跤，顺手记录：

1. `pip3 install pyocd` 被 PEP 668 拒绝（系统 Python 禁止直接装包）→ 用 venv：

```bash
python3 -m venv ~/venvs/pyocd
~/venvs/pyocd/bin/pip install pyocd -i https://pypi.tuna.tsinghua.edu.cn/simple
```

2. `brew install pyocd` 卡在自动更新拉 formula 索引（网络被墙，formula API 拉不下来）→ 跳过自动更新 + 国内 bottle 镜像：

```bash
export HOMEBREW_NO_AUTO_UPDATE=1
export HOMEBREW_BOTTLE_DOMAIN=https://mirrors.ustc.edu.cn/homebrew-bottles
```

（不过镜像索引没就绪时 brew 可能仍找不到公式，venv 方案更省事。）

## 关键命令速查

```bash
# USB 设备树（设备在不在，一眼判定）
system_profiler SPUSBDataType

# 串口节点（有设备无串口 = 缺驱动）
ls /dev/cu.* /dev/tty.*

# 更详细的 USB 属性（描述符级别）
ioreg -p IOUSB -l -w 0

# 看板子有没有挂出仿真磁盘
diskutil list

# 装好 pyocd 后扫描调试探针
pyocd list
```

## 排查判定树

```
插上没反应
├─ USB 树里没有设备？
│   ├─ 电源灯亮 → 大概率纯充电线，换线
│   └─ 电源灯不亮 → 线/接口/供电问题
├─ USB 树里有设备但没串口？
│   ├─ VID 1a86/10c4/silabs 等 → 装串口驱动
│   └─ STM32 直连 → 固件没实现 USB CDC，属正常
└─ 出现磁盘/HID 等奇怪设备？
    └─ 是固件枚举的功能设备（如出厂 demo），看它挂载出的内容找线索
```
