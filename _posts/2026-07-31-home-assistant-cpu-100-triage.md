---
layout: post
title: "Home Assistant 在 macOS 上 CPU 100%:三次抓栈定位到 c-ares"
date: 2026-07-31 12:30:00 +0800
categories: Home-Assistant
series: haier-series
---

把海尔空调接入 HA 之后,机器一直很吵。`top` 一看,HA 进程 **CPU 99%**,已经烧了 23 小时。

这篇文章记录我三次抓栈定位的过程。**根因不是第一眼看到的那个**——典型的"症状和病根离得很远"的案例。

## 现象

```
PID    COMMAND    %CPU #TH
5326   python3.14 99.1 35
```

HA 占满一个核,机器风扇响。日志正常,功能正常,但电费在烧。

## 第一轮:以为是蓝牙

打开日志看尾部,46MB 的 `home-assistant.log` 里全是同一个错误:

```
AttributeError: 'NSKVONotifying_CBCentralManager' object has no attribute
'retrieveAddressForPeripheral_'. Did you mean: 'retrieveConnectedPeripherals'?
```

计数:**68280 条**,每秒还在增长。

### 根因解析

- HA 启用了 `bluetooth` 集成,底层用 `bleak` 库做 BLE 扫描
- bleak 在 macOS 上调 `central_manager.retrieveAddressForPeripheral_(peripheral)`
- 这个 API 是 **macOS 12 Monterey 之后才加的**,我是 Big Sur(11.7.10),没有
- CoreBluetooth 每收到一个广播包就调一次回调 → 回调崩 → 异常处理 → CoreBluetooth 继续推下一个广播
- Big Sur 的 CoreBluetooth 一秒能推几百个广播包,Python 层疯狂 traceback + 写日志

### 验证

```sh
kill -STOP 5326   # 冻结
# CPU 立刻掉到 3%
```

✅ CPU 立降,确认蓝牙错误是 hot path 之一。

### 修复

把 `.storage/core.config_entries` 里 bluetooth entry 加 `"disabled_by": "user"`:

```python
import json
p = 'config/.storage/core.config_entries'
data = json.load(open(p))
for e in data['data']['entries']:
    if e['domain'] == 'bluetooth':
        e['disabled_by'] = 'user'
json.dump(data, open(p, 'w'), indent=2)
```

重启 HA。蓝牙错误归零(从每秒数十条降到 0)。

**但 CPU 还是 99%。**

## 第二轮:抓栈找 hot thread

错误消失了,CPU 没掉——说明根因不止一个。用 macOS 自带的 `sample` 抓栈:

```sh
sample <pid> 5 -mayDie
```

输出很长,关键是 **Call graph** 部分每个线程被采到的次数。

### 第一误判:主线程卡在 kevent

主线程 4257 次采样全部在:

```
select_kqueue_control_impl → kevent
```

第一反应:"事件循环在忙循环"。但其实 `select_kqueue_control_impl` 是 asyncio selector 用来**注册/修改 fd**的方法——采样到它,既可能是"被 kevent 阻塞"(正常),也可能是"kevent 不停返回又被重新注册"(异常)。光看样本数无法区分。

### 关键观察:有几个线程不在 idle

用 Python 解析 sample 输出,列出所有线程:

```python
import re
text = open('/tmp/sample.txt').read()
threads = re.split(r'\n(?=\s*\d+ Thread_\d)', text)
for t in threads:
    m = re.match(r'\s*(\d+)\s+(Thread_\d+[^\n]*)', t)
    if not m: continue
    has_kevent = 'select_kqueue_control_impl' in t
    has_psync = '__psynch_cvwait' in t
    if not has_kevent and not has_psync:
        print(m.group(1), m.group(2))
```

输出 3 个**既不在 kevent 也不在 psync_cvwait** 的线程——它们在烧 CPU。

### 真正的罪魁:c-ares

抓这 3 个线程的栈:

```
Thread_434750
  ares_event_thread (in _cares.abi3.so)
    ares_evsys_kqueue_wait (in _cares.abi3.so)
      kevent
```

`_cares.abi3.so` 是 **c-ares 异步 DNS 解析库**。它在 kqueue_wait + DNS 处理之间高速循环——说明有大量 DNS 查询被反复发起,或者 DNS 配置本身有问题导致 c-ares 不停重试。

### 第三轮:为什么 DNS 不通

查系统 DNS 配置:

```sh
scutil --dns
```

关键行:

```
resolver #2
  domain   : local
  options  : mdns
  reach    : 0x00000000 (Not Reachable)
```

`.local` 域名( mDNS)的解析路径标 **Not Reachable**。

HA 的 SSDP/UPnP 集成在后台做服务发现,会反复解析 `*.local` 域名 → c-ares 失败 → 立刻重试 → 烧 CPU。

## 修复:关掉所有被动发现的集成

`default_config:` 是 HA 的"打包配置",默认拉起一整套组件,包括:

- `bluetooth`(蓝牙扫描)
- `ssdp` / `upnp`(UPnP 服务发现)
- `zeroconf`(mDNS/Bonjour)
- `dhcp`(DHCP 设备发现)
- `discovery`(各种被动发现)

这些组件共同特点:**在后台持续监听/解析 `.local` 域名**——在 macOS Big Sur 上正是触发 c-ares 死循环的根源。

### 改 configuration.yaml

```yaml
# 删掉 default_config:,改成显式列表
frontend:
cloud:
history:
logbook:
config:
automation:
scene:
script:
mobile_app:
analytics:
backup:

homeassistant:
  name: Home
  # ... 省略
```

### 改 .storage/core.config_entries

把 ssdp/upnp/bluetooth 相关 entry 都设 `"disabled_by": "user"`(可逆,UI 里能再启用):

```python
import json, shutil
p = 'config/.storage/core.config_entries'
shutil.copy(p, p + '.bak')
data = json.load(open(p))
for e in data['data']['entries']:
    if e['domain'] in ('ssdp', 'upnp', 'bluetooth', 'zeroconf', 'dhcp', 'discovery'):
        e['disabled_by'] = 'user'
json.dump(data, open(p, 'w'), indent=2)
```

重启 HA。CPU **稳定 0%**,线程数从 35 降到正常范围。

## 复盘

### 教训 1:top 显示的"主线程"不一定是真凶

`top -pid` 在 macOS 上能看到进程级 CPU,但看不到线程级。`sample` 能看线程,但**所有线程的样本数都被采满**(因为它只统计"线程是否存在",不区分运行/睡眠)。

**正确做法**:

```sh
ps -M -p <pid> | sort -k3 -rn | head -10
```

`ps -M` 显示每个线程的 `STIME`(系统时间)。**STIME 高的线程才是真凶**。

### 教训 2:sample 输出靠"位置"识别 idle

- 烧 CPU 的线程:**最深栈不包含** `__psynch_cvwait` 或 `select_kqueue_control_impl`
- idle 的线程:最深栈在 `__psynch_cvwait`(等条件变量)或 `kevent`(等 IO)

写脚本过滤这俩关键字,剩下的就是嫌疑线程。

### 教训 3:macOS 上 HA 是个不太受待见的平台

- 蓝牙 API 要 Monterey+
- mDNS / `.local` 解析路径在某些 Big Sur 配置下不通
- 大部分 HA 用户在 Linux/Docker/HAOS 上跑,这些平台问题不会被频繁报

如果你必须用 macOS 跑 HA:

1. **不要用 `default_config:`**——显式列出需要的组件
2. 关掉所有 `*discovery*` 类集成
3. 系统级 DNS 配置好,或者用 dnsmasq 给 `.local` 提供兜底解析

## 验证命令汇总

```sh
# 1. 进程级 CPU
top -l 1 -pid $(cat .ha.pid) -stats pid,command,cpu,threads

# 2. 线程级(找烧 CPU 的)
ps -M -p $(cat .ha.pid) | sort -k3 -rn | head -10

# 3. 抓栈
sample $(cat .ha.pid) 3 -mayDie

# 4. 日志错误数
grep -c 'AttributeError' config/home-assistant.log
grep -c 'retrieveAddressForPeripheral' config/home-assistant.log

# 5. DNS 配置
scutil --dns | grep -A 3 'Not Reachable'
```

## 总结

| 轮次 | 怀疑 | 验证 | 真相 |
|---|---|---|---|
| 1 | 蓝牙 API 不兼容 | `kill -STOP` CPU 立降 | ✅ 部分根因,修了 CPU 还烧 |
| 2 | 主线程 kqueue 忙循环 | sample 抓栈 | ❌ 主线程在 kevent 是正常 idle |
| 3 | c-ares 烧 CPU | 找非 idle 线程,看 stack | ✅ SSDP/UPnP 触发 DNS 死循环 |

整个排查过程中,**最大的陷阱是看到 99% CPU 就立刻归因到"最显眼的错误"**(蓝牙 API 不兼容)。看似修了错误 CPU 就降了——但只降了一点,真正的 hot path 还在后台烧。

**先抓栈再下结论**,永远比看日志猜来得可靠。

## 参考

- [HA 文档:Default Configuration](https://www.home-assistant.io/integrations/default_config/)
- [HA 文档:Bluetooth](https://www.home-assistant.io/integrations/bluetooth/)
- [c-ares 文档](https://c-ares.org/)
- macOS `sample(1)` man page
- 之前写的 [HA 实体数据库行数 ≠ 事件次数](/2026/07/31/home-assistant-websocket-push-analysis/)
