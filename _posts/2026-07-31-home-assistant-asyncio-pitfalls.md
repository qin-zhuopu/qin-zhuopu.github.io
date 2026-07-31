---
layout: post
title: "给 Home Assistant 集成加定时任务踩的三个 asyncio 坑"
date: 2026-07-31 08:25:00 +0800
categories: Home-Assistant
series: haier-series
---

上一篇写了怎么把海尔空调接入 HA，里面提到加 60 秒轮询踩了三个 asyncio 坑。这篇单独把它写出来——因为这三个坑太典型了，**任何给 HA 写定时回调的集成都可能撞上**。

先给结论：

| 坑 | 表象 | 真因 |
|---|---|---|
| 1 | `coroutine was never awaited` | 调度器回调签名要求 sync 函数，传 async 进去协程被 GC |
| 2 | `calls hass.async_create_task from a thread` | 调度器在 worker 线程触发回调，事件循环 API 不能跨线程用 |
| 3 | （终极方案）`run_coroutine_threadsafe` | 用 Python 标准库的跨线程调度 API |

下面分别写清楚每个坑的现象、原因和正确写法。

## 任务背景

我想做的事很简单：**每 60 秒拉一次海尔云端 API，把结果 fire 给所有 polled 实体**。

HA 提供了官方的定时器 helper：

```python
from homeassistant.helpers.event import async_track_time_interval
from datetime import timedelta

cancel = async_track_time_interval(
    hass,
    callback_fn,
    timedelta(seconds=60),
)
```

`callback_fn` 每次触发会收到一个 `now` 参数。看起来很普通，三个坑都藏在"callback_fn 应该长什么样"这个问题上。

## 坑 1：协程从未被 await

### 写法

```python
def _make_polling_callback(hass, client, devices):
    async def _callback(now) -> None:
        await _polling_tick(hass, client, devices)
    return _callback

cancel_polling = async_track_time_interval(
    hass,
    _make_polling_callback(hass, client, devices),
    timedelta(seconds=60),
)
```

### 现象

集成加载，没报错，但 60 秒之后什么都没发生。`_polling_tick` 里 fire 的事件没出现，polled 实体永远不更新。

数据库只有几条记录，时间戳和 WS 重连事件完全重合——polling 实际从未执行过。

### 日志证据

```
RuntimeWarning: coroutine '_polling_tick' was never awaited
```

警告里还打印了源码位置：

```
_polling_tick(hass, client, devices),
'haier-polling-tick',
```

### 原因

`async_track_time_interval` 的回调签名接受一个**同步函数**。在 HA 较新版本里，它**不会 await** 传入的协程。

async 函数被调用时，Python 返回一个 coroutine 对象。如果没人 await 这个对象，就直接被 GC 掉，产生这个 RuntimeWarning。整个 `_polling_tick` 的代码一行都不会执行。

### 错误推断

我一开始以为"HA 是异步框架，传 async 回调就会自动 await"。错。**调度器是否 await 取决于它的实现**，要看 HA 官方文档对每个 helper 的签名要求。

### 教训

写任何 callback 之前先看文档/helper 的源码：

```python
# 在 homeassistant/helpers/event.py 里看 async_track_time_interval
# 签名一般类似:
def async_track_time_interval(hass, action, interval, *, cancel_on_shutdown=False):
    """action: Callable[[datetime], None]"""
```

`action` 类型是 `Callable`，不是 `Coroutine`。这就决定了它**不会 await 你的 async 函数**。

## 坑 2：跨线程调用 async API

### 写法（坑 1 之后）

既然 async 回调不被 await，那就包一层同步函数，内部用 `hass.async_create_task` 把协程塞到事件循环里：

```python
def _make_polling_callback(hass, client, devices):
    def _callback(now) -> None:
        hass.async_create_task(_polling_tick(hass, client, devices))
    return _callback
```

### 现象

日志报线程安全错误，polling 仍不执行。

### 日志证据

```
RuntimeError: Detected that custom integration 'haier' calls
hass.async_create_task from a thread other than the event loop,
which may cause Home Assistant to crash or data to corrupt.
```

HA 还贴心地指出：

```
For more information, see
https://developers.home-assistant.io/docs/asyncio_thread_safety/#hassasync_create_task
at custom_components/haier/__init__.py, line 64
```

### 原因

`async_track_time_interval` 的回调**在 worker 线程里执行**（HA 用线程池跑定时任务）。

而 `hass.async_create_task` 是事件循环 API，**只能在事件循环所在的线程调用**。跨线程调用会破坏事件循环内部状态（任务队列、协程调度链等），HA 检测到这种情况会主动报 RuntimeError。

### 教训

跨线程往事件循环里塞任务，必须用 `asyncio.run_coroutine_threadsafe(coro, loop)`。这是 Python 标准库的 API，**HA 不会替你封装**。

## 坑 3（终极方案）：用线程安全的调度 API

### 最终写法

```python
import asyncio

def _make_polling_callback(hass, client, devices):
    """track_time_interval 在 worker 线程里触发回调,必须用线程安全的调度方式。"""
    loop = asyncio.get_event_loop()
    def _callback(now) -> None:
        asyncio.run_coroutine_threadsafe(
            _polling_tick(hass, client, devices), loop
        )
    return _callback
```

### 关键点

- `asyncio.get_event_loop()` 在 `async_setup_entry` 里调用，能拿到事件循环（因为 `async_setup_entry` 本身就在事件循环里跑）
- 闭包把 `loop` 固定下来，回调触发时复用
- `asyncio.run_coroutine_threadsafe(coro, loop)` 是线程安全的 API，内部用 `loop.call_soon_threadsafe` 把任务塞回去

### 验证

重启 HA 之后日志：

```
05:00:33 polling device 24E8CE5D89EF got 16 attrs: {...}
05:00:33 polling device DC330D80F406 got 32 attrs: {...}
05:00:33 polling device DC330DEC1560 got 25 attrs: {...}
05:01:33 polling device 24E8CE5D89EF got 16 attrs: {...}
...
```

每 60 秒一次，3 台设备各拉一次，间隔精准。19 次 tick 共拉了 57 个数据包。

## 总结：通用模式

以后给 HA 写任何"在 worker 线程里触发、但要在事件循环里执行协程"的回调，**都用下面这个模式**：

```python
import asyncio
from homeassistant.helpers.event import async_track_time_interval

async def async_setup_entry(hass, entry):
    loop = asyncio.get_event_loop()  # 在事件循环里拿

    def sync_callback(now):
        # 在 worker 线程里被调用,线程安全地塞协程回事件循环
        asyncio.run_coroutine_threadsafe(actual_async_work(hass), loop)

    cancel = async_track_time_interval(hass, sync_callback, timedelta(seconds=60))
```

记住这个模式，**永远不会再撞上面三个坑**。

## 什么时候用 `hass.async_create_task`，什么时候用 `run_coroutine_threadsafe`

| 场景 | 用哪个 |
|---|---|
| 在事件循环线程里（比如 `async def` 函数内部）创建任务 | `hass.async_create_task(coro)` |
| 在 worker 线程里（比如 track_time_interval 回调、监听器回调）创建任务 | `asyncio.run_coroutine_threadsafe(coro, loop)` |
| 不确定是不是在事件循环里 | `hass.add_job(coro)`（HA 自己判断，安全但稍慢） |

## 参考资料

- [HA 官方文档：Asyncio Thread Safety](https://developers.home-assistant.io/docs/asyncio_thread_safety/)
- [Python 文档：asyncio.run_coroutine_threadsafe](https://docs.python.org/3/library/asyncio-task.html#asyncio.run_coroutine_threadsafe)
- HA 源码：`homeassistant/helpers/event.py` 看 `async_track_time_interval` 实现
