---
layout: post
title: "把海尔空调接入 Home Assistant：抓 token、读源码、加轮询的完整折腾记录"
date: 2026-07-31 08:15:00 +0800
categories: Home-Assistant
series: haier-series
---

最近想把家里的海尔空调接入 Home Assistant（下面简称 HA），主要不是为了远程控制——海尔智家 App 已经能做——而是为了**长期记录室温、湿度，未来配合自动化做"室温超过 28 度自动开空调"**。

官方海尔集成只支持国际版账号，国内版要走社区项目 `banto6/haier`。一路从抓 token、读源码、改源码加轮询踩过来，记下来给同样折腾的人。

> 适合读者：会基本的命令行操作，愿意读 Python 代码，对 HA 集成开发有兴趣的人。

> 本文是「海尔空调接入 HA」系列的概览。深入的话题另写了几篇独立文章，链接见文末。

## TL;DR

- 海尔智家国内云用 OAuth + WebSocket 推送，标准登录需要 `refresh_token`
- 手机端抓不到 `refresh_token`（微信小程序走 mmtls 加密），只能抓到短期的 `access_token`
- 改 `banto6/haier` 源码让 `access_token` 直接登录，能用，但 token 过期要重抓
- WebSocket 是事件驱动的，**空调关机时云端完全不推数据**，只发心跳
- 改源码加一个 60 秒主动轮询（HTTP polling），关机也能拿到室温
- 中间踩了三个 Python asyncio 的坑（协程没 await、跨线程调用、调度器 API 误用），全部解决

## 一、为什么是 banto6/haier

HA 官方应用商店里搜 "Haier" 出来的官方集成只支持国际版（`tuya` 或者海尔海外账号）。国内版海尔智家 App 用的云是 `zj.haier.net` / `uws.haier.net` / `account-api.haier.net`，协议是私有的。

社区里用得最多的是 [banto6/haier](https://github.com/banto6/haier)，一千多 star，反向工程了海尔的 OAuth、WebSocket、HTTP API。我直接用它。

## 二、海尔认证体系：两套 token

海尔云的认证分两层：

| token 类型 | 来源 | 有效期 | 用途 |
|---|---|---|---|
| `access_token` | 登录接口返回 | 几小时到几天 | 所有 API 请求的 Bearer token |
| `refresh_token` | 登录接口返回 | 几十天 | 用来换新的 `access_token` |

**banto6/haier 的标准登录流程**：

1. 用户在配置页面填 `client_id`（App 来源标识）和 `refresh_token`
2. 集成调 `oauthserver/applet/v3/login/onekey` 用 `refresh_token` 换 `access_token`
3. 拿到 `access_token` 之后所有 API 请求都用它

问题：**`refresh_token` 怎么拿？**

## 三、抓包踩坑：微信小程序的 mmtls 加密

官方推荐的方法是用 whistle 或 Charles 抓微信小程序的包：

1. 手机装微信，打开"海尔智家官方"小程序
2. 电脑跑 whistle，手机走电脑代理
3. 装 whistle 的根证书到手机
4. 在小程序里登录，抓 `zj.haier.net/api-gw/oauthserver/applet/v3/login/onekey` 请求
5. 请求体里的 `refreshToken` 就是

听起来简单，实际：

- **手机端微信抓不到**：现在微信小程序走 `mmtls` 协议，请求体在传输层加密，whistle 看到的是一坨密文
- **必须用 PC 版微信**：Windows 或 macOS 上的 PC 微信抓包才能看到明文
- **建议用 Reqable 替代 whistle**：UI 友好，免费

我手上只有手机，PC 微信懒得装。**所以决定绕过 `refresh_token`，直接用 `access_token`。**

## 四、抓 access_token（这个能抓到）

虽然 `refresh_token` 走加密通道看不到，但 **`access_token` 是放在 HTTP header 里的明文**，所有 API 请求都会带。所以：

1. 手机装海尔智家 App（不是微信小程序！是原生 App）
2. 电脑跑 whistle / Reqable，手机走代理
3. 装根证书
4. 打开 App 用一下（进主页、点空调）
5. 在抓包工具里搜 `uws.haier.net` 的请求
6. **看请求 header 里的 `accesstoken` 字段**（全小写）——这就是 `access_token`

> ⚠️ 注意：HTTP header 大小写不敏感，banto6 代码里写的是 `accessToken`，抓包看到的是 `accesstoken`，是同一个东西。

还可以顺便抓到 `client_id`（在请求 URL 或 body 里），它代表 App 来源。海尔智家 App 的是 `8E8FB3A7-1281-4632-8DDF-D87DD147ED5C`，小程序版的是另一个值。建议用 App 版的，因为后续所有 API 都跟着这个来源走。

## 五、改 banto6/haier 源码：支持 access_token 直填

banto6/haier 原版的 `config_flow.py` 强制要求 `refresh_token`，没有就报错。改一下让它接受 `access_token`：

```python
# config_flow.py
ACCESS_TOKEN = 'access_token'

refresh_token = user_input.get(REFRESH_TOKEN, '').strip()
access_token = user_input.get(ACCESS_TOKEN, '').strip()

if refresh_token:
    # 走原来的 refresh 流程
    token_info = await client.refresh_token(refresh_token)
    token = token_info.token
    new_refresh_token = token_info.refresh_token
    expires_at = int(time.time()) + token_info.expires_in
elif access_token:
    # 直接用 access_token，不刷新
    token = access_token
    new_refresh_token = ''
    expires_at = 0
else:
    raise HaierClientException('必须填写 refresh_token 或 access_token 其中之一')

# schema 里 refresh_token 改 Optional，新增 access_token Optional
vol.Optional(REFRESH_TOKEN): str,
vol.Optional(ACCESS_TOKEN): str,
```

`__init__.py` 里的 `token_updater` 也要改，否则集成启动时尝试 refresh 会直接挂：

```python
if not cfg.refresh_token:
    if token_valid:
        _LOGGER.warning("没有配置 refresh_token，跳过自动刷新。")
        return False
    raise HaierClientException('access_token 已失效且未配置 refresh_token，无法自动刷新')
```

这套改完，集成可以正常加载，空调也能控制了。改动已经推到我的 fork：[`qin-zhuopu/haier@85f2fb2`](https://github.com/qin-zhuopu/haier/commit/85f2fb283a439f7694efedfbba28b8d6fd7254b2)。

## 六、新问题：关机时拿不到室温

集成装上之后能控制空调，但**空调关机时，HA 里看不到室温变化**。

读了 banto6/haier 的代码发现：

- 集成 `should_poll = False`，纯 WebSocket 推送
- 空调开机状态变化时，云端通过 WS 推送一次全量快照（一台空调约 33 个 attribute）
- **空调关机时，云端只发心跳保活，完全不推数据**

实测：空调关机状态下，HA 跑了 30 分钟，WS 收到 30 条消息，**全部是 HeartBeatAck（心跳响应），0 条真实数据**。

这正是我接入 HA 的初衷（监测室温）失效的场景。所以加 HTTP polling。

## 七、加 60 秒 HTTP polling

海尔云有个 HTTP API `uws.haier.net/shadow/v1/devdigitalmodels`，可以拉取设备的全量 attribute（和 WS 推送的是同一份数据格式），**关机也能拉到**。

设计思路是让每个 attribute 平台（number、sensor）注册**两个实体**：

- **WS 版**：原名 `xxx`，只监听 `EVENT_DEVICE_DATA_CHANGED`（WS 推送）
- **Polled 版**：`xxx_polled`，名字带 `(Polled)`，只监听 `EVENT_DEVICE_DATA_POLLED`（60 秒轮询）

这样在 HA 历史曲线里就能看到两条线，分别来自 WS 和轮询。

### 核心代码

新增事件 `core/event.py`：

```python
EVENT_DEVICE_DATA_POLLED = 'device_data_polled'
```

新增实体基类 `entity.py`：

```python
from homeassistant.helpers.entity import DeviceInfo, Entity, EntityCategory

class HaierPolledEntity(HaierAbstractEntity):
    """仅监听定时 polling 数据的实体。"""
    def __init__(self, device, attribute):
        super().__init__(device, attribute)
        self._attr_unique_id = self._attr_unique_id + '_polled'
        self._attr_name = (self._attr_name or '') + ' (Polled)'
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_icon = 'mdi:cloud-refresh'

    async def async_added_to_hass(self) -> None:
        # 只监听网关断开 + polling 事件
        def gateway_disconnected_callback(event):
            if event.data.get('deviceId') != self._device.id: return
            self._attr_available = False
            self.schedule_update_ha_state()
        self.async_on_remove(
            listen_event(self.hass, EVENT_GATEWAY_DISCONNECTED, gateway_disconnected_callback))

        def polled_callback(event):
            if event.data['deviceId'] != self._device.id: return
            self._attr_available = True
            self._attributes_data = event.data['attributes']
            self._update_value()
            self.schedule_update_ha_state()
        self.async_on_remove(
            listen_event(self.hass, EVENT_DEVICE_DATA_POLLED, polled_callback))
```

注册定时任务 `__init__.py`：

```python
from datetime import timedelta
from homeassistant.helpers.event import async_track_time_interval

# async_setup_entry 末尾
cancel_polling = async_track_time_interval(
    hass,
    _make_polling_callback(hass, client, devices),
    timedelta(seconds=60),
)
hass.data[DOMAIN]['cancel_polling'] = cancel_polling
```

## 八、踩了三个 asyncio 的坑

polling 的回调函数看起来就一个，我前后改了三个版本才跑通。每个版本都是一个不同的坑，记下来。

### 坑 1：协程从未被 await

第一版：

```python
def _make_polling_callback(hass, client, devices):
    async def _callback(now) -> None:
        await _polling_tick(hass, client, devices)
    return _callback
```

日志报：

```
RuntimeWarning: coroutine '_polling_tick' was never awaited
```

**原因**：`async_track_time_interval` 的回调签名接受**同步函数**。在 HA 较新版本里，它**不会 await** 传入的协程。async 函数被调用时返回一个 coroutine 对象，如果没人 await，就直接被 GC 掉。

**教训**：HA 调度器（`track_time_interval` / `track_state_change` 等）的回调签名要看清楚是 sync 还是 async。不要假设"反正 HA 是异步框架就会 await 我的回调"。

### 坑 2：跨线程调用 async API

第二版：

```python
def _make_polling_callback(hass, client, devices):
    def _callback(now) -> None:
        hass.async_create_task(_polling_tick(hass, client, devices))
    return _callback
```

日志报：

```
RuntimeError: Detected that custom integration 'haier' calls
hass.async_create_task from a thread other than the event loop
```

**原因**：`async_track_time_interval` 的回调**在 worker 线程里执行**，而 `hass.async_create_task` 是事件循环 API，**不能跨线程调用**。

**教训**：跨线程往事件循环里塞任务，必须用 `asyncio.run_coroutine_threadsafe(coro, loop)`。这是 Python 标准库的 API，HA 不会替你封装。

### 坑 3（终极修复）：用线程安全的调度 API

```python
def _make_polling_callback(hass: HomeAssistant, client, devices):
    """track_time_interval 在 worker 线程里触发回调,必须用线程安全的调度方式。"""
    loop = asyncio.get_event_loop()
    def _callback(now) -> None:
        asyncio.run_coroutine_threadsafe(_polling_tick(hass, client, devices), loop)
    return _callback

async def _polling_tick(hass: HomeAssistant, client, devices) -> None:
    from .core.event import fire_event, EVENT_DEVICE_DATA_POLLED
    for device in devices:
        try:
            values = await client.get_device_snapshot_data(device.id)
        except Exception as err:
            _LOGGER.warning('polling device %s failed: %s', device.id, err)
            continue
        # 注意:输出完整 attrs JSON,便于排查"没拉到 vs 没写库"
        _LOGGER.debug('polling device %s got %d attrs: %s', device.id, len(values), values)
        fire_event(hass, EVENT_DEVICE_DATA_POLLED, {
            'deviceId': device.id,
            'attributes': values,
        })
```

跑起来日志里每 60 秒一条：

```
05:31:59 polling device DC330D80F406 got 32 attrs: {'specialMode': '0', ..., 'indoorTemperature': '26.00', ...}
```

完美。

## 九、一个值得记的经验：日志要输出完整数据

第一版 polling 日志写的是：

```python
_LOGGER.debug('polling device %s got %d attrs', device.id, len(values))
```

只输出"拉到几个属性"，**不输出值**。

后来发现一个尴尬的事：polling 跑了 19 次，数据库只写了 1 行。一通排查才知道，**HA Recorder 只在状态变化时写库**——空调关机时室温稳定 26.0°C 不变，所以即使每分钟拉一次，数据库也不增加新行。

这本身是 HA 的设计（节省存储），但带来一个问题：**怎么区分"没拉到"和"拉到了但没变化"？**

答案：让日志把完整 attrs 也打出来：

```python
_LOGGER.debug('polling device %s got %d attrs: %s', device.id, len(values), values)
```

这样排查时直接看日志里的 `indoorTemperature` 字段就能判断：

- 日志里**有**完整 attrs，`indoorTemperature` 没变 → 拉到了，数据库不写是正常的
- 日志里**有**完整 attrs，`indoorTemperature` 变了但数据库没记 → 实体没收到事件，bug
- 日志里**没有**这条 → polling 没跑，代码或网络问题

这个教训以后写任何 polling 都用得上：**日志一定要打完整 payload，否则查问题时只能瞎猜**。

## 十、最终效果

接入的设备：

| 设备 | 型号 | Polled 实体数 |
|---|---|---|
| 北卧室空调 | KFR-35G/SAA21AU1 | 8 个（室温、目标温度、湿度、风速、模式、摆风等） |
| 客厅/2P 空调 | KFR-50G/HDA22AU1 | 6 个 |
| 净水机 | HRO800SVM3-U1 | 6 个（TDS、滤芯寿命、纯水量等） |

总计 18 个 Polled 实体，每 60 秒拉一次，关机也照样记录。

后续可以做的事：

- 配置 HA 自动化：室温超过阈值自动开空调
- 接入 InfluxDB + Grafana 做长期可视化（SQLite 一年后会变慢）
- 给 `select` / `binary_sensor` 平台也加 Polled 版
- 找一台 PC 微信拿到真正的 `refresh_token`，切回标准模式

## 十一、参考资料

- [banto6/haier 主仓库](https://github.com/banto6/haier)
- [我的 fork（含本次改动）](https://github.com/qin-zhuopu/haier/commit/85f2fb283a439f7694efedfbba28b8d6fd7254b2)
- [Home Assistant 开发文档](https://developers.home-assistant.io/)
- [whistle 抓包工具](https://wproxy.org/whistle/)
- [Reqable（推荐替代 whistle）](https://reqable.com/)

## 系列文章

本文是总览，下面几个深入话题单独写了：

- [海尔智家云的两套 token，以及为什么手机抓不到 refresh_token](/2026/07/31/haier-oauth-token-explained/) — 认证体系深挖
- [给 Home Assistant 集成加定时任务踩的三个 asyncio 坑](/2026/07/31/home-assistant-asyncio-pitfalls/) — 三个坑的完整分析
- [Home Assistant 的两个存储：数据库只记变化，日志每次都记](/2026/07/31/home-assistant-recorder-vs-log/) — 排查"polling 没生效"的方法
- [Home Assistant 实体的「数据库行数」≠「事件次数」](/2026/07/31/home-assistant-websocket-push-analysis/) — WS 推送频率分析
- [同一个设备两套名字：海尔 WS 实体名 vs Polled 实体名不一致](/2026/07/31/haier-entity-name-mismatch/) — 实体命名踩坑

---

折腾这个东西前后花了三天。最大收获不是接入本身，而是把 HA 的实体生命周期、asyncio 的跨线程模型、海尔云的协议结构都串起来理解了一遍。家里有海尔设备又想折腾的，欢迎交流。
