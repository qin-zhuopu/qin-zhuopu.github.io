---
layout: post
title: "Chrome 把 CDP 的门关了一半，但给 AI Agent 留了扇侧门"
date: 2026-09-19 06:40 +0800
categories: [AI, Agent]
tags: [chrome, cdp, mcp, playwright, browser-automation, 踩坑]
---

## 引子：一条走了十年的命令突然不好使了

要让 AI Agent 操作浏览器，第一反应几乎都是这句：

```bash
google-chrome --remote-debugging-port=9222
```

然后 Puppeteer / Playwright 连上去就完事。这条路走了十年很稳，**直到 Chrome 136 把它折掉一半**：

- 对**默认 profile**，`--remote-debugging-port` 会被**直接忽略**。想用 CDP 必须换一个全新的 `--user-data-dir` —— 于是登录态、Cookie、已装扩展全部归零。
- 即使换了目录，**外部 CDP 客户端连入时浏览器会弹「允许调试此浏览器？」**。人坐在电脑前可以点，跑在服务器上的 agent 点不了。

一个不能带登录态、还要人点确认框的浏览器，对自动化来说价值大打折扣。SSO 系统尤其致命：要么每次重登，要么放弃。

Chrome 留了一扇侧门：**扩展的 `chrome.debugger` API**。它是一等一的 CDP 通道，权限由扩展安装时的授权授予 —— 不需要启动参数、不弹外部连接框、能在你正在用的 profile 上工作。代价是地址栏那条「正在调试此浏览器」横幅，以及你把已登录浏览器的实际控制权交了出去。

围绕这扇侧门，最近一年多长出了一个不小的开源品类。这篇文章记录我在自己服务器上把它真正跑通的全过程 —— 包括**官方文档里没有、只能从打包后的 JS 里逆向出来的握手协议**。

## 一、这个品类里有什么

| 项目 | ★ | 许可 | 活跃度 | 定位 |
|---|---|---|---|---|
| `microsoft/playwright-mcp` `--extension` | 37k | Apache-2.0 | 官方、活跃 | **官方扩展模式**，连已开标签页 |
| `remorses/playwriter` | 3.9k | MIT | 活跃（三天前发版） | 扩展内跑 Playwright 片段，raw CDP 一等公民，能打真断点 |
| `hangwin/mcp-chrome` | 12.4k | MIT | 略放缓 | 扩展自身即 MCP server，20+ 工具含网络调试 |
| `Dexin-Huang/chrome-cdp-bridge` | 0 | — | — | 把扩展伪装成标准 `ws://…:9222`，现有 CDP 工具链零改动 |
| `browsermcp/mcp` | 7.1k | Apache-2.0 | **停更一年半** | 最早出圈，但别用了 |

架构分两类：**A 类**扩展本身就是 MCP server（扩展 ↔ native messaging host ↔ agent stdio），链路最短但工具定义各家自造；**B 类**扩展只当 CDP 中继、MCP 装在外面，可以白嫖 Playwright 的全部工具。

我选了 B 类的官方方案 `@playwright/mcp --extension`：工具面最全（26 个）、官方维护、和我已有的 Playwright 心智一致。

## 二、真正的难点不是装扩展，是那个「反向连接」

装扩展反而是最简单的（下节讲）。先说清运行时的形状，因为它和多数人的直觉相反：

```
Agent (MCP client)
  │  MCP: tools/call browser_navigate / browser_evaluate …
  ▼
@playwright/mcp --extension        HTTP :8931
  │  监听 ws://127.0.0.1:<随机端口>/extension/<uuid>
  │  然后 spawn("chrome", "chrome-extension://<id>/connect.html?mcpRelayUrl=…&token=…")
  ▼
Chrome
  │  预装的扩展打开 connect.html，校验 token
  ▼  反向 WebSocket 连回 MCP
扩展内 chrome.debugger             ← 真正执行 CDP 指令
```

**不是 agent 去连浏览器，而是 MCP 开一个 WebSocket 服务，然后想办法让浏览器里的扩展主动连出来。**

这个设计决定了后面所有坑的形状。我从 `playwright-core/lib/coreBundle.js` 读出的实际逻辑（关键词 `connect.html` / `mcpRelayUrl` / `_openConnectPageInBrowser`）：

```js
const url = new URL(`chrome-extension://${playwrightExtensionId}/connect.html`);
url.searchParams.set("mcpRelayUrl", `${this._wsHost}${this._extensionPath}`);
url.searchParams.set("client", JSON.stringify(client));
url.searchParams.set("protocolVersion", this._protocolVersion.toString());
if (this._token) url.searchParams.set("token", this._token);
// …
const args = [];
if (this._customUserDataDir) args.push(`--user-data-dir=${this._customUserDataDir}`);
if (this._profileDirectory)  args.push(`--profile-directory=${this._profileDirectory}`);
args.push(href);
spawn(executablePath, args, { windowsHide: true, detached: true, stdio: "ignore" });
```

看最后两行：**MCP 自己 spawn 一个浏览器进程去打开连接页**，而且不带你的 `--user-data-dir`（除非你显式传了）。扩展侧对应 `openRelayConnection(mcpRelayUrl)` → `new WebSocket(url)`。

## 三、五个坑

### 坑 0：网上教程教的 `--load-extension` 已经彻底失效

我一开始按经典教程做：解包扩展 → `--load-extension=/path/to/ext`。结果 Preferences 里干干净净，扩展根本没注册。有头模式、无头模式、加不加那个传说中的 `--disable-features=DisableLoadExtensionCommandLineSwitch`，全试了 —— **都不行**。profile 级的 `Default/External Extensions/` 目录同样不再生效。

能用的预装路线实测有三条：

```bash
# ① 系统级 External Extensions + 本地 CRX（推荐，完全离线）
sudo mkdir -p /opt/google/chrome/extensions
echo '{"external_crx":"/path/to/ext.crx","external_version":"1.2.3"}' \
  | sudo tee /opt/google/chrome/extensions/<EXT_ID>.json

# ② 同目录改用商店更新地址（能自动更新，但首次启动需联网下载 20~30s）
echo '{"external_update_url":"https://clients2.google.com/service/update2/crx"}' \
  | sudo tee /opt/google/chrome/extensions/<EXT_ID>.json

# ③ 企业策略强装（用户删不掉）
# /etc/opt/chrome/policies/managed/preinstall.json
# { "ExtensionInstallForcelist": ["<EXT_ID>;https://clients2.google.com/service/update2/crx"] }
```

`Preferences` 里 `extensions.settings[<id>].location` 能告诉你扩展从哪来：1 商店 / 2 外部本地 crx / 4 解包 / 5 内置 / 6 外部 update_url / 7 策略强制 / 10 命令行。

顺带，免登录拉 CRX 的端点是：

```
https://clients2.google.com/service/update2/crx?response=redirect&os=linux&os_arch=x86_64
  &nacl_arch=x86-64&prod=chromecrx&prodchannel=&prodversion=152.0.7977.0
  &acceptformat=crx3&x=id%3D<EXT_ID>%26uc
```

如果服务器出不了网（内网机器很常见），就在能上网的机器下好、把 CRX 拷进去走路线 ①。**预装本身不需要网络**，这点能省掉很多麻烦 —— 我一开始挂着代理折腾商店路线，其实完全绕远了。

还有个隐蔽的：解包扩展里若残留 CRX 自带的 `_metadata/` 目录，Chrome 会直接拒载，且错误信息几乎看不到。走 CRX 路线不会碰到。

### 坑 1：`--extension` 自己启动的浏览器，和常驻 Chrome 抢 profile

因为我需要一个长期常驻的 Chrome（复用连接、保留状态），MCP 那次 `spawn` 就成了灾难：新进程发现目标 profile 已被占用，只弹「Chrome 已在运行中」错误页 —— 而连接 URL 恰好开在这个错误的 profile 里，**扩展永远连不回来**。

解法只花了几行：`--executable-path` 可以指向任意可执行文件，于是我写了个替身启动器。它不启动 Chrome，而是把收到的 URL 用 CDP 塞给**已经在跑**的那个实例：

```python
# pw-chrome-open —— 给 @playwright/mcp --extension 当 --executable-path 用
url = next((a for a in sys.argv[1:] if a.startswith("chrome-extension://")), None)
port = os.environ.get("CDP_PORT", "9395")
if url:
    opener.open(f"http://127.0.0.1:{port}/json/new?{urllib.parse.quote(url, safe='')}")
```

这里有个不确定点：`/json/new` 开的标签页是**后台**的，脚本会不会不执行？实测会 —— 反向 WS 正常建立（Playwright 源码里也写了 "The background page is ok"）。

如果你的场景就是「MCP 自己起浏览器」，不需要这套 —— 传对 `--user-data-dir`，它启动的就是带扩展的那个 profile。

### 坑 2：令牌每次随机，每次重连都要人手输入

连接页带 `token`。MCP 在你不指定时会生成随机值并打印到 stderr；扩展侧的令牌却是**持久化**的（`chrome.storage.local`）。两者对不上，扩展就打开 `authToken.html` 要求人工输入 —— 服务器上没有手。

而抓 stderr 这条路本身是死的：**只有 stdio 模式才打印带 token 的连接 URL，`--port` HTTP 模式只打印 `Listening on …`**。

好消息是扩展自己会漏：它的 `status.html` 明文打印着当前令牌，还贴心写好了环境变量名。

```python
# 用 CDP 打开扩展自己的 status.html, 读回它的持久令牌
page = open("chrome-extension://<EXT_ID>/status.html")   # 经 /json/new + WebSocket 执行 JS
token = re.search(r"PLAYWRIGHT_MCP_EXTENSION_TOKEN=(\S+)", body).group(1)
```

把这个值以**同名环境变量**喂回 MCP，两侧就永久对齐了。效果很直观：**MCP 进程崩了重启，首次调用 0 秒恢复，全程零人工。**

顺带一个安心发现：扩展会给它驱动的标签页打上以 client 名命名的 tab group，所以它不会悄悄劫持你正在看的页面。

### 坑 3：MCP 的 Host 头白名单

```
$ curl -X POST http://127.0.0.1:8931/mcp
HTTP/1.1 403 Forbidden
Access is only allowed at localhost:8931
```

必须写 `http://localhost:8931/mcp`。这是防 DNS-rebinding 的，合理，但报错信息不会告诉你「把 127.0.0.1 换成 localhost 就好」。

### 坑 4：MCP over HTTP 是有状态的，旧会话返回空响应

`initialize` 响应头里的 `mcp-session-id` 要带上下次请求。而 **MCP 进程重启后，旧 sid 返回的是一个空响应** —— 不报错、不提示，就是空。第一版客户端因此表现为「服务明明活着，调用返回 `{}`」，排查方向完全跑偏。

客户端必须自己识别「空响应 = 会话失效」并重新握手。判据我扩到三条：空 body、`error.code ∈ {-32001,-32601,-32602}`、`message` 含 "not found"。

### 附赠一个执行层的坑：ssh 里的 `pkill -f` 是自杀

```bash
ssh host 'pkill -f "user-data-dir=/path"; rm -rf /path; echo done'   # 第一行就自杀
```

`pkill -f` / `pgrep -f` 的模式会匹配到**这条远程命令自身**（它的命令行里就有那个字符串），远端 shell 在第一行被自己杀掉，**后面所有清理静默不执行**，而你只看到「命令没有输出」。我在同一台机器上踩了三次，其中一次直接导致 Chrome 被误杀。

解法是用字符类断开匹配，让它匹配不到自己：

```bash
for pid in $(pgrep -f "remote-debugging-por[t]=9395"); do kill "$pid"; done
```

更彻底的做法是把重启逻辑做成脚本内部的子命令，外层命令行根本不出现那段字面量。

## 四、跑通之后

最终形态（四个脚本都进了内部仓库）：

```bash
chrome-ext-bridge.sh start
#   [1/3] 预装扩展(离线 CRX)…
#   [2/3] 起常驻 Chrome (有头 :50, CDP 9395)…
#   [3/3] 扩展 token: xxxxxxxx…  起 MCP(:8931)

chrome-ext-bridge.sh call tools/list
#   tools(26): browser_navigate, browser_click, browser_evaluate, browser_snapshot, …

chrome-ext-bridge.sh call tools/call '{"name":"browser_navigate","arguments":{"url":"https://example.com"}}'
#   ### Ran Playwright code ```js await page.goto('https://example.com'); ```
```

挂给 agent 就一行配置：

```json
{ "mcpServers": { "playwright-ext": { "url": "http://localhost:8931/mcp" } } }
```

值得单列的成果：**内网站点可访问**。走代理旁路（`*.jereh.cn;*.jereh-pe.cn;10.*;…`）之后，需要 SSO 的 `ide.jereh-pe.cn`、`oasis.jereh.cn` 都能正常打开并自动跳认证中心 —— 这正是这条通道相对「全新 user-data-dir + 裸 CDP」的全部意义。顺带踩到一个小坑：内网域名不止一个后缀，少了 `jereh-pe.cn` 就会出现「网页打不开 ERR_PROXY_CONNECTION_FAILED」，而本机 curl 直连明明是通的。

顺便说一个我原本以为能成、结果没成的事：**搬 Cookie**。我以为拷 `Cookies` 文件就能把登录态带过去，但它是 os_crypt AES-GCM 加密的，`Local State` 里没有 `encrypted_key`（说明走系统钥匙串），而且实测**不是** `--use-mock-keychain` 那个 `peanuts/saltysalt` 公开空密钥（10 个 cookie 全部解密失败）。可行的替代是**整个 profile 目录复制**（rsync 228MB 秒级，复制体启动后访问内网确实没被踢到登录页）—— 或者干脆，既然系统级预装对所有 profile 生效，直接在业务 profile 上用扩展通道就好。

## 五、几点判断

1. **`--load-extension` 系教程已经集体过时。** 判据只看 Preferences 里的 `extensions.settings`；`chrome://extensions` 是受保护页，CDP 打不开，别指望用它验收。
2. **注册 ≠ 激活。** 要看 `/json/list` 里有没有 `chrome-extension://<ID>/…` 的 **service worker**，才说明扩展的 MV3 worker 真活着。
3. **MV3 service worker 会被回收**，长任务必须保活。这类小项目（扩展 + 反向 WS）最容易死在掉线上，所以选型时「仓库是否还在动」比 star 数重要得多 —— 那个 7k 星的 browsermcp 就是反面教材。
4. **权限即全部。** 扩展能读所有标签页 URL/标题、在任意页面执行 JS；`browser_evaluate` / `browser_run_code_unsafe` 就是浏览器内 RCE。这条通道不要接给不可信的 agent，relay 和 MCP 都只绑 127.0.0.1，别转发到公网。
5. 系统级预装是**全局**的：写进去之后所有 user-data-dir 下次启动都会带上这个扩展。用完记得 `remove`。

---

如果你的场景是「Windows/Mac 桌面上那个带着内网 SSO 登录态的日常 profile」，这条路线值得认真投入 —— 它几乎是唯一既不用交出主 profile、又能保住登录态的做法。如果只是要在服务器上要一个干净的自动化浏览器，裸 CDP 继续用就行，不必折腾。
