---
layout: post
title: "vanilla JS 用 History API 做三级路由：pushState 入栈、popstate 回退"
date: 2026-08-09 17:10:00 +0800
categories: [技术笔记]
tags: [javascript, history-api, 前端路由, vanilla-js]
---

写一个"类型列表 → 类型详情 → 实体详情"的三级页面，不用任何框架。最初每页都是直接 `render()` 一次，**点浏览器后退键没反应**——历史栈根本没记录。后来用 HTML5 History API 走通：点击 `pushState` 入栈，后退触发 `popstate` 重新渲染。整个路由代码不到 30 行。

## 问题现象

- 点击类型卡片进入详情页：URL 变了但 history 没动
- 浏览器后退键不响应（或退回上一个完全不同的网站）
- 直接粘贴 URL 进来，刷新页面，渲染不对

## 环境信息

- 纯 vanilla JS（无 React/Vue/Router）
- 单页应用，hash 路由（`#type-detail/Device` 这种）

## 排查过程

**最初版本**（不工作）：

```js
function go(page, params) {
  route = { page, ...params };
  location.hash = `#${page}/${params.type || ''}${params.id || ''}`;
  render();
}
```

URL 倒是变了，但 history.length 不增长——因为改 hash 不一定入栈（取决于浏览器策略）。后退键不响应。

**第二版**：直接 `history.pushState`

```js
function go(page, params) {
  const hash = '#' + page + ...;
  history.pushState({ page, ...params }, '', hash);
  route = parseHash();
  render();
}
```

点击入栈了，但**后退键还是没反应**。

为什么？因为 pushState 只是塞历史栈，浏览器后退触发的是 `popstate` 事件——你没监听，路由就不会同步。

## 根因分析

History API 的两条独立路径必须配对：

| 用户动作 | 浏览器做的事 | 你要做的事 |
|---|---|---|
| 点击链接 | 什么都不做 | `pushState` + 渲染 |
| 浏览器后退/前进 | 触发 `popstate` | 读 `event.state` 或 `location.hash`，渲染 |

漏掉任意一边都会出现"URL 变了但页面没变"或"后退键没反应"。

## 最终方案

```js
// 全局路由状态
let route = { page: 'types' };

// 跳页：pushState 入栈 + 渲染
function go(page, params) {
  const newRoute = { page, ...params };
  const hash = '#' + page
    + (params.type ? '/' + params.type : '')
    + (params.id ? '/' + params.id : '');
  history.pushState(newRoute, '', hash);
  route = newRoute;
  render();
}

// 后退：用 history.back()，不要直接改 hash
function back() {
  history.back();  // 触发 popstate
}

// 监听 popstate：URL 变了（后退/前进/手改 hash），同步 route + 渲染
window.addEventListener('popstate', (e) => {
  route = parseHash();
  render();
});

// hash → route
function parseHash() {
  const h = location.hash.replace(/^#/, '');
  const parts = h.split('/');
  // 兼容 'inst' 和 'inst-detail' 两种写法
  const page = parts[0].replace('-detail', '');
  const out = { page: page || 'types' };
  if (parts[1]) out.type = decodeURIComponent(parts[1]);
  if (parts[2]) out.id = decodeURIComponent(parts[2]);
  return out;
}

// 入口：把当前 URL 同步成 route（兼容刷新和深链）
history.replaceState(route, '', location.hash || '#types');
```

## 几个坑

### 坑 1：`back()` 不要直接改 hash

```js
function back() {
  location.hash = '#types';  // 错！这会再 push 一次历史
}
```

正确做法是 `history.back()`，让浏览器自己走栈，自然触发 popstate。

### 坑 2：刷新页面后第一个 pushState 会让 length 多 1

页面一加载就有 `history.length`（包含其他网站的记录）。直接比较 length 没意义——做 e2e 测试时应该比较"点击前后差 1"。

### 坑 3：深链直进详情页

用户直接粘 `http://app/#inst-detail/mac` 进来，IIFE 必须先 `parseHash` 再渲染。我用了：

```js
(async function(){
  route = parseHash();
  history.replaceState(route, '', location.hash);  // 把当前 state 塞进去
  await ensureData();
  render();
})();
```

`replaceState`（不是 pushState）覆盖当前的 state，不入栈。

## 关键命令速查

```js
// 跳页（点击）
history.pushState({page:'inst-detail', id:'x'}, '', '#inst-detail/x');

// 后退
history.back();

// 看栈长度
history.length;

// 监听后退
window.addEventListener('popstate', e => { ... });

// 初始化（不动栈，只更新当前 state）
history.replaceState(route, '', location.hash);
```

## 总结

vanilla JS 自己实现路由，三条线必须接好：

1. 点击 → `pushState` + 渲染
2. 后退 → 监听 `popstate` + 渲染
3. 初始化 → `parseHash` + `replaceState`

接好后 30 行代码就够。不需要 React Router，也不需要 next.js。
