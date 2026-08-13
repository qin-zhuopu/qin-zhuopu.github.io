---
layout: post
title: "ESP8266 MicroPython 跑 HTTP 服务踩坑：30KB RAM 下的 ENOMEM 生存指南"
date: 2026-08-13 23:17:00 +0800
categories: [技术踩坑]
tags: [esp8266, micropython, embedded, ch340, mpremote]
---

把一块吃灰的 ESP8266 开发板翻出来想做个 WiFi 联网的小玩具。本以为是烧固件 + 几行 Python 就完事的活，结果一路踩到 MicroPython 在 ESP8266 上跑 HTTP 服务时的内存墙——所有"标准模板"代码都会因为 `ENOMEM` 启动不了 socket。最终方案是延迟 import + 手写 JSON 拼接，把 RAM 占用压到能用的程度。

## 问题现象

硬件：经典 ESP8266EX 开发板，4MB flash，CH340 USB 转串口。

刷上 MicroPython v1.28.0，boot.py 里连好 WiFi，然后写了段"教科书式"的 main.py：

- import network / socket / json / urequests / ntptime / time / machine
- 定义几个 handler 函数
- 拼一个 INDEX_HTML 大字符串
- 主循环里非阻塞 accept + 心跳 + WiFi 自愈

启动后 `ping` 能通（说明 boot.py 把 WiFi 连上了），但浏览器访问 `http://设备IP/` 完全无响应。

## 环境信息

- 板子：ESP8266EX，4MB flash，CH340 桥接
- 固件：MicroPython v1.28.0 (ESP8266_GENERIC)
- 主机：macOS 11.7.10 Intel
- 工具：esptool 5.3.1 / mpremote 1.28.0

## 排查过程

### 第一步：CH340 不识别

板子插上电脑后蓝灯闪两下就停，`system_profiler SPUSBDataType` 看不到任何新设备，`/dev/cu.*` 也没串口。换了"确定能传数据"的线还是一样。

深挖 `system_profiler` 输出，**实际上 USB 树里能看到**：

```
USB Serial:
  Product ID: 0x7523
  Vendor ID:  0x1a86
  Speed:      Up to 12 Mb/s
```

`0x1a86` 是沁恒（WCH）的 vendor ID，对应 CH340/CH343 系列 USB 转串口芯片。系统枚举成功了，但 macOS Big Sur **默认不带 CH340 的串口驱动 kext**，所以 `/dev/cu.*` 没出现。

解决：

```bash
brew install --cask wch-ch34x-usb-serial-driver
# 重启,首次允许 WCH 内核扩展
```

但实际测试发现，**有时根本不用装驱动**——某些 CH340 板子会被 macOS 内置的 `AppleUSBACM` 驱动接管，直接出现 `/dev/cu.usbserial-XXXX`。装驱动更稳妥就是了。

### 第二步：固件烧录（顺利）

```bash
# 备份原始 flash
esptool --port /dev/cu.usbserial-XXXX read_flash 0x0 0x400000 flash_backup.bin

# 擦除 + 烧 MicroPython
esptool --port /dev/cu.usbserial-XXXX erase_flash
esptool --port /dev/cu.usbserial-XXXX --baud 460800 \
  write_flash --flash_size detect --flash_mode dio 0x0 \
  ESP8266_GENERIC-20260406-v1.28.0.bin
```

注意 4MB flash 备份约 6 分钟（87 kbit/s），不要急着重启中断。

### 第三步：用 mpremote 而不是手动串口操作

最初我写了个 Python 脚本用 pyserial 模拟 Ctrl-C、Ctrl-D、行行送进 friendly REPL，结果在 MicroPython 的 friendly REPL 多行语句和续行符 `...` 上乱成一锅粥。

**正解是装 `mpremote`（官方工具）**：

```bash
pip install mpremote

# 交互 REPL
mpremote connect /dev/cu.usbserial-XXXX repl

# 跑一段代码
mpremote connect /dev/cu.usbserial-XXXX exec 'import sys; print(sys.version)'

# 上传文件
mpremote connect /dev/cu.usbserial-XXXX cp 本地文件.py :远端文件.py

# 读设备文件
mpremote connect /dev/cu.usbserial-XXXX cat :main.py
```

`mpremote` 处理了所有 raw REPL 协议，比手撸串口稳定 100 倍。

### 第四步：HTTP 服务的 ENOMEM

这才是真正卡了很久的坑。

第一次写好的 main.py 启动后 ping 通但 HTTP 不响应。中断进 REPL 重新 `import main`，看到：

```
[20642] ntp ok
Traceback (most recent call last):
  File "main.py", line 171, in main
  File "main.py", line 129, in start_server
OSError: [Errno 12] ENOMEM
```

`ENOMEM` 在 `start_server()` 的 `socket.bind()` / `listen()` 时抛出。看下当时内存：

```python
>>> import gc
>>> gc.mem_free()
35936
```

**36 KB 可用内存，对 ESP8266 上的 MicroPython 是常态**，但开 socket + 维持 HTTP 处理缓冲不够。

#### 原因分析

main.py 启动时模块加载顺序：

1. `import network` — 几乎不占内存
2. `import socket` — 占一些
3. `import json` — 占很多（JSON 解析器）
4. `import urequests` — 占很多（依赖 ssl、http 模块）
5. `import ntptime` — 中等
6. INDEX_HTML 大字符串常量 — 字符串常量在 RAM 里

ESP8266 的 MicroPython 总共约 40-50 KB 可用 RAM，全部 import 完后剩余就只有 5-10 KB，开 socket listen 时直接 ENOMEM。

### 第五步：极简化重构

最终能跑起来的 main.py 做了这些优化：

**1. 延迟 import（lazy import）**

把 `urequests`、`ntptime`、`json` 全部从顶层去掉，只在用到时局部 import，用完 `del` 释放：

```python
def do_heartbeat():
    import urequests
    r = urequests.get("http://example.com", timeout=5)
    r.close()
    del urequests
    gc.collect()
```

这样空闲时这些大模块不在 RAM 里。

**2. 关闭内核调试输出**

boot.py 开头加：

```python
import esp
esp.osdebug(None)
```

能省一些被内核打印占用的缓冲。

**3. 手写 JSON 拼接，不用 `json.dumps`**

`json.dumps` 一次性构造大字符串，对内存峰值冲击大。改用手写拼接：

```python
def status_text():
    hb = "{}ms".format(LAST_HB[0][2]) if LAST_HB[0] else "none"
    return '{"uptime":"' + uptime() + '","free_mem":' + str(gc.mem_free()) \
         + ',"wifi":"' + wifi_info() + '"}'
```

字段越少越好——浏览器侧拿到基本字段就够，需要详细日志可以让前端再请求一个 `/log`。

**4. 日志缓冲限长**

```python
LOG_BUF = []
def log(m):
    LOG_BUF.append(m)
    if len(LOG_BUF) > 30:  # 上限 30 条,字符串短
        LOG_BUF.pop(0)
```

不要存 dict/tuple，直接存短字符串。

**5. INDEX_HTML 用 bytes 字面量**

```python
INDEX_HTML = b"<!doctype html>..."
```

bytes 比 str 省一半空间（不用 UTF-8 解码）。

**6. HTTP 分块发送**

不要 `body = resp_header + body` 拼大缓冲，分多次 send：

```python
conn.send(b"HTTP/1.0 200 OK\r\nContent-Type: ")
conn.send(ctype)
conn.send(b"\r\nContent-Length: ")
conn.send(str(len(body)).encode())
conn.send(b"\r\nConnection: close\r\n\r\n")
conn.send(body)
```

**7. socket 设非阻塞 + 不预留 backlog**

```python
s.listen(2)         # backlog=2 而不是 5
s.setblocking(False)
```

主循环里：

```python
try:
    conn, _ = SRV[0].accept()
except OSError:
    return  # 没连接,正常
```

## 根因总结

ESP8266 是 2014 年的芯片，RAM 极其有限：

- 总 RAM：约 80 KB
- MicroPython 解释器自身：约 40 KB
- **用户代码可用：约 30-40 KB**

任何在 PC/树莓派上觉得"理所当然"的标准库（json、requests）在 ESP8266 上都是奢侈品。MicroPython 文档里其实有提到这点，但只有真撞上 ENOMEM 才会刻骨铭心。

## 最终方案

完整可运行的 main.py 模板（核心思路）：

```python
import network, time, machine, socket, gc
from machine import Pin

STA_SSID = "your_ssid"
STA_PASS = "your_password"

LED = Pin(2, Pin.OUT, value=1)
LOG_BUF = []
HB_COUNT = [0]
LAST_HB = [None]
START_MS = time.ticks_ms()
SRV = [None]  # 用 list 包一下,函数内可改

def log(m):
    LOG_BUF.append(m)
    if len(LOG_BUF) > 30:
        LOG_BUF.pop(0)

def uptime():
    s = (time.ticks_ms() - START_MS) // 1000
    return "{}h{}m{}s".format(s//3600, (s%3600)//60, s%60)

def wifi_ok():
    return network.WLAN(network.STA_IF).isconnected()

def wifi_reconnect():
    sta = network.WLAN(network.STA_IF)
    if not sta.active(): sta.active(True)
    sta.connect(STA_SSID, STA_PASS)
    for _ in range(12):
        if sta.isconnected(): return True
        time.sleep(0.5)
    return False

def do_heartbeat():
    # 延迟 import
    import urequests
    try:
        t0 = time.ticks_ms()
        r = urequests.get("http://example.com", timeout=5)
        LAST_HB[0] = (time.ticks_ms(), r.status_code, time.ticks_ms() - t0)
        HB_COUNT[0] += 1
        r.close()
    except: pass
    del urequests
    gc.collect()

def status_text():
    hb = "{}ms".format(LAST_HB[0][2]) if LAST_HB[0] else "none"
    return '{"uptime":"' + uptime() + '","free_mem":' + str(gc.mem_free()) \
         + ',"hb_count":' + str(HB_COUNT[0]) + ',"last_hb":"' + hb + '"}'

INDEX_HTML = b"<!doctype html>... 你的 HTML/JS ..."

def handle(path):
    if path in ("/", "/index.html"): return INDEX_HTML, b"text/html"
    if path == "/status": return status_text().encode(), b"application/json"
    if path == "/led/on": LED.value(1); return b'{"ok":1}', b"application/json"
    if path == "/led/off": LED.value(0); return b'{"ok":1}', b"application/json"
    return b"404", b"text/plain"

def start_server():
    addr = socket.getaddrinfo("0.0.0.0", 80)[0][-1]
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(addr); s.listen(2); s.setblocking(False)
    SRV[0] = s

def serve_once():
    if SRV[0] is None: return
    try: conn, _ = SRV[0].accept()
    except OSError: return  # 没连接
    try:
        conn.settimeout(1.5)
        req = conn.recv(512)
        path = req.split(b" ", 2)[1].decode("ascii", "replace") if req and b" " in req else "/"
        body, ctype = handle(path)
        conn.send(b"HTTP/1.0 200 OK\r\nContent-Type: ")
        conn.send(ctype)
        conn.send(b"\r\nContent-Length: " + str(len(body)).encode())
        conn.send(b"\r\nConnection: close\r\n\r\n")
        conn.send(body)
    finally:
        conn.close()

def main():
    gc.collect()
    start_server()
    last_hb = time.ticks_ms()
    last_wifi = time.ticks_ms()
    last_blink = 0
    while True:
        try:
            now = time.ticks_ms()
            if time.ticks_diff(now, last_hb) > 60_000:
                do_heartbeat(); last_hb = now
            if time.ticks_diff(now, last_wifi) > 30_000:
                if not wifi_ok(): wifi_reconnect()
                last_wifi = now
            serve_once()
            if time.ticks_diff(now, last_blink) > 1000:
                LED.value(0); time.sleep_ms(20); LED.value(1)
                last_blink = now
            time.sleep_ms(50)
        except:
            time.sleep(1)

main()
```

跑起来后内存稳定在 27-30 KB，60 秒一次心跳，浏览器每 3 秒拉一次 `/status`，运行几天没掉过线。

## 关键命令速查

```bash
# 1. 备份原始 flash(防止丢东西)
esptool --port /dev/cu.usbserial-XXXX read_flash 0x0 0x400000 flash_backup.bin

# 2. 擦 + 烧 MicroPython
esptool --port /dev/cu.usbserial-XXXX erase_flash
esptool --port /dev/cu.usbserial-XXXX --baud 460800 \
  write_flash --flash_size detect --flash_mode dio 0x0 ESP8266_GENERIC-XXX.bin

# 3. mpremote 操作
mpremote connect /dev/cu.usbserial-XXXX exec 'import sys; print(sys.version)'
mpremote connect /dev/cu.usbserial-XXXX cp main.py :main.py
mpremote connect /dev/cu.usbserial-XXXX cp boot.py :boot.py
mpremote connect /dev/cu.usbserial-XXXX ls
mpremote connect /dev/cu.usbserial-XXXX cat :main.py
mpremote connect /dev/cu.usbserial-XXXX reset

# 4. 在 REPL 里查看可用内存(关键诊断)
mpremote connect /dev/cu.usbserial-XXXX exec 'import gc; print(gc.mem_free())'

# 5. CH340 驱动
brew install --cask wch-ch34x-usb-serial-driver
```

## 参考

- [MicroPython on ESP8266](https://docs.micropython.org/en/latest/esp8266/quickref.html)
- [ESP8266 内存使用讨论](https://github.com/micropython/micropython/issues?q=ENOMEM+esp8266)
- [mpremote 文档](https://docs.micropython.org/en/latest/reference/mpremote.html)
