---
layout: post
title: "pychrome 做 CDP 端到端测试：data-testid 单 tab 模式踩坑"
date: 2026-08-09 17:20:00 +0800
categories: [技术笔记]
tags: [e2e, cdp, pychrome, 测试, chrome]
---

给一个本地 web 页面写端到端测试，不想拉 Playwright/Selenium 这种重型工具。Python 的 `pychrome` 直接驱动 Chrome DevTools Protocol（CDP），10 个用例 / 30 个断言跑通。但要踩几个坑：GenericAttr 不是字符串、localStorage 在 `about:blank` 拒访、多个 tab 共享一个 tab 的状态切换。

## 问题现象

最初每个测试都开新 tab，跑完后关掉。结果：

1. 第一次跑：`argument of type 'GenericAttr' is not iterable`——pychrome 的 `tab.url` 不是普通字符串
2. 改完跑：`SecurityError: Failed to read the 'localStorage' property from 'Window'`——新 tab 还停在 `about:blank` 时不能访问 localStorage
3. 改完跑：测试之间互相污染（旧 tab 残留 LocalStorage）

## 环境信息

- macOS（大版本不限）
- Chrome 开了 CDP 端口：`~/scripts/cdp/launch_chrome.sh 9222`
- Python 3.10+，`pychrome`（`pip install pychrome`）

## 排查过程

### 坑 1：`tab.url` 是 GenericAttr

```python
for t in browser.list_tab():
    if "localhost:8765" in t.url:  # 抛异常：GenericAttr not iterable
        ...
```

pychrome 把每个属性包成 `GenericAttr` 对象，不能直接 `in`。

**修复**：先转字符串。

```python
url = str(t.url or "")
if "localhost:8765" in url:
    ...
```

### 坑 2：localStorage 访问被拒

新开的 tab 初始 URL 是 `about:blank`，文档还没到合法 origin，访问 `localStorage` 抛 `SecurityError`。

```python
def setup(browser):
    tab = browser.new_tab()
    tab.clear_storage()  # 错！还没导航就访问 localStorage
    tab.navigate(URL)
```

**修复**：先 navigate 再访问 storage。

```python
def setup(browser):
    tab = find_or_open_tab(browser)
    tab.navigate(URL)         # 先到合法页面
    tab.clear_storage()       # 再清
```

### 坑 3：多 tab 互相干扰

每个测试开新 tab 跑完关掉，但 Chrome 进程的总体状态（other tabs 的 LocalStorage、Cookie）会乱。而且多 tab 慢。

**修复**：所有测试共享一个 tab，每个测试前清 LocalStorage + 重新 navigate。

```python
SHARED_TAB = None

def setup(browser):
    global SHARED_TAB
    if SHARED_TAB is None:
        SHARED_TAB = find_or_open_tab(browser)
    tab = SHARED_TAB
    tab.navigate(URL)         # 等到 ready
    tab.clear_storage()       # 清旧状态
    tab.navigate(URL)         # 重新进，从干净状态开始
    return tab
```

## 根因分析

CDP 测试和 Selenium 类工具的根本差异：CDP 操作的是**浏览器内部状态机**，不是模拟用户点击鼠标。所以：

- 浏览器的 origin 模型 / 安全策略，CDP 也得遵守
- `pychrome` 这种轻封装不替你做类型转换，属性都是 GenericAttr
- 多 tab 不是隔离的"虚拟机"，状态会互相影响

## 最终方案

### Tab 类的轻封装

```python
class Tab:
    def __init__(self, tab):
        self.t = tab

    def eval(self, expression, await_promise=False):
        r = self.t.Runtime.evaluate(
            expression=expression,
            awaitPromise=await_promise,
            returnByValue=True,
        )
        if r.get("exceptionDetails"):
            raise RuntimeError(r["exceptionDetails"])
        return r.get("result", {}).get("value")

    def click_testid(self, testid, nth=0):
        sel = f"[data-testid='{testid}']"
        ok = self.eval(f"""(() => {{
          const els = document.querySelectorAll({json.dumps(sel)});
          const el = els[{nth}];
          if (el) {{ el.click(); return true; }}
          return false;
        }})()""")
        if not ok:
            raise RuntimeError(f"{testid}#{nth} not found")

    def text(self, testid):
        return self.eval(f"""document.querySelector(
          `[data-testid='${testid}']`
        )?.textContent || ''""")

    def storage_get_json(self, key):
        raw = self.eval(f"localStorage.getItem({json.dumps(key)})")
        return json.loads(raw) if raw else None
```

### 所有 DOM 访问走 data-testid

页面里所有要操作的元素都加 `data-testid`：

```html
<button data-testid="load-neighbors-btn">查邻居</button>
<div data-testid="type-card" data-type="Device">...</div>
<div data-testid="inst-row" data-id="mac">...</div>
```

测试里**绝不**用样式选择器（`.my-btn`）或位置选择器（`div > ul > li:nth(3)`），因为样式会变、结构会重构，但 `data-testid` 不会变。

### 单 tab 复用

```python
def find_or_open_tab(browser):
    for t in browser.list_tab():
        url = str(t.url or "")
        if t.type == "page" and "localhost:8765" in url:
            t.start()
            t.Page.enable()
            t.Runtime.enable()
            return Tab(t)
    # 没有就开
    t = browser.new_tab()
    t.start()
    t.Page.enable()
    t.Runtime.enable()
    return Tab(t)
```

## 关键命令速查

```bash
# 启 Chrome 带 CDP
~/scripts/cdp/launch_chrome.sh 9222

# Python 里看 tabs
import pychrome
browser = pychrome.Browser(url="http://127.0.0.1:9222")
print(browser.list_tab())

# 跑全部用例
python3 e2e_test.py

# 跳过依赖外网的用例
python3 e2e_test.py --no-aura

# 只跑名字含 'load' 的
python3 e2e_test.py --filter load
```

## 几个易忘的细节

| 细节 | 备注 |
|---|---|
| `t.url` 必须 `str()` | pychrome 的 GenericAttr 不能直接 `in` |
| 新 tab 先 navigate 再访问 DOM | `about:blank` 上 localStorage 抛 SecurityError |
| 同 tab 测试前 clear_storage | 否则前一个测试的缓存污染下一个 |
| `Runtime.evaluate` 必须 `returnByValue=True` | 否则拿到的是远程对象引用 |
| 用 json.dumps 拼 selector | 避免引号注入，也避免字符串拼接错 |

## 总结

CDP 测试适合给本地工具页面写"我自己的 e2e"——快、轻、不依赖云服务。核心三件套：

1. `data-testid` 标记每个要操作的 DOM
2. 单 tab 复用，setup 里 navigate + clear
3. pychrome 的属性记得 `str()`
