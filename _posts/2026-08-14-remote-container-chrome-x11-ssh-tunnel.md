---
layout: post
title: "免安装 X Server + SSH 隧道：把远程容器里的 Chrome 窗口显示到 Windows 桌面"
date: 2026-08-14 09:35:00 +0800
categories: [技术笔记]
tags: [xserver, vcxsrv, ssh-tunnel, docker, chrome, cdp]
---

需求很简单：远程 Docker 容器里跑 Chrome，想在本地 Windows 桌面看到它的窗口，还要能用 CDP 远程控制它。听起来是标准的 X11 转发，但一路踩了免安装、端口、字体三个坑。本文完整记录，命令可直接复用。

## 问题现象

目标链路：

```
[远程容器里的 Chrome GUI]  →  SSH 隧道  →  [本地 Windows X Server]  →  显示到桌面
```

分解成四个子问题：

1. Windows 上要有一个 X Server 接收窗口——但不想「安装」软件（无管理员权限）
2. 容器和本地之间隔着网络/NAT，X Server 端口要能被容器访问
3. 容器里没有 Chrome，要装进去
4. 最终窗口出来了，但**汉字全是方块（tofu）**

## 环境信息

- OS: Windows 11 + Git Bash (MINGW64)，本地用 WSL2 里的 Docker 容器模拟「远程生产容器」
- 容器镜像：`ubuntu:24.04` + node + python（一个精简的开发镜像）
- X Server：VcXsrv 21.1.16.1
- Chrome：Google Chrome 151（Linux 版）

## 排查过程

### 坑一：X Server 要「免安装」运行

VcXsrv 官方（GitHub / SourceForge）**只发布安装器 `.exe`，从来没有 zip 便携包**。查了源码 `marchaesen/vcxsrv`，它是 X.Org 的 Windows 移植，编译产物就是一组普通的 `EXE + DLL + 字体`，**本身不依赖「安装」这个动作**（不是驱动、不是服务）。官方打包成 NSIS 安装器只是为了方便分发。

自己编译？`HOW_TO_BUILD.txt` 要求 VS2022 + Cygwin + Perl + NSIS，官方说「give it a couple hours」——完全不值得。

真正的解法：**用 NSIS 安装器自带的静默解压参数**，把文件抖出来即可，不写注册表、不装服务、不碰 `Program Files`：

```bash
# 从国内镜像下载安装器（GitHub 官方大文件在国内易超时）
curl -sS -L -o vcxsrv-installer.exe \
  "https://<github-mirror>/https://github.com/marchaesen/vcxsrv/releases/download/21.1.16.1/vcxsrv-64.21.1.16.1.installer.noadmin.exe"

# NSIS 静默解压到指定目录（关键：cmd.exe + 绝对路径，绕开 MSYS 路径转换）
MSYS_NO_PATHCONV=1 cmd.exe /c "C:\tools\dl\vcxsrv-installer.exe /S /D=C:\tools\vcxsrv"
```

> 注意：直接用 7-Zip 解这个 NSIS 安装器会报 `Cannot open the file as archive`（即便完整版 7za 也不行），必须用 NSIS 自身的 `/S /D=`。且 `/D=` 必须是绝对路径、放在参数最后。

解压后直接启动，纯绿色：

```bash
MSYS_NO_PATHCONV=1 cmd.exe /c start "" "C:\tools\vcxsrv\vcxsrv.exe" \
  :0 -multiwindow -clipboard -ac -wgl
# 验证监听 6000（= display :0 的端口）
netstat -ano | grep ":6000" | grep LISTENING
```

X11 的 display number 对应端口：`:0` → 6000，`:1` → 6001。记住这条，后面有大坑。

### 坑二：X Server 端口怎么进容器——反向隧道

本地防火墙默认拦截外部（容器/WSL）到 Windows 6000 端口的入站连接。与其去改防火墙（`-ac` 裸奔 + 放行有安全风险），不如用 **SSH 反向隧道**，全程走 loopback：

```bash
# 从本地发起，-R 让容器侧监听 6000，转发回本地的 6000（=本地 X Server）
ssh -o StrictHostKeyChecking=no -N \
  -R 6000:localhost:6000 \
  -p 20022 root@127.0.0.1
```

`-R remotePort:host:hostPort` 的语义：在 **SSH 服务端（容器）** 监听 `remotePort`，把连接转发回 **SSH 客户端（本地）** 的 `host:hostPort`。这样容器内连 `localhost:6000` 就等于连到了本地的 X Server。

验证隧道通不通，可以在容器内做一次 X11 协议握手（不依赖任何 X 客户端）：

```python
import socket
# X11 连接初始化：字节序 'l' + 协议版本 11.0 + padding，共 12 字节
handshake = b"l\x00\x00\x0b\x00\x00\x00\x00\x00\x00\x00\x00"
s = socket.create_connection(("127.0.0.1", 6000), timeout=5)
s.sendall(handshake)
resp = s.recv(64)
# resp[0]==0x00 表示 X Server 接受连接；resp[2:4] 小端 = 协议主版本(11)
print("OK" if resp and resp[0] == 0 else "FAIL", resp[:8].hex())
```

### 坑三：容器里装 Chrome

精简镜像没有 Chrome，且 Ubuntu 24.04 源里的 `chromium` 是 snap 包，容器里没有 snapd 装不了。直接用 Google 官方 `.deb`。

在国内环境，我的做法是本地下载好 `.deb`，传到内网对象存储，容器再从内网高速拉取（比容器直连 Google 快得多）：

```bash
# 依赖要注意 Ubuntu 24.04 的 t64 迁移：包名变了！
#   libasound2 → libasound2t64
#   libcups2   → libcups2t64
apt-get install -y --no-install-recommends \
  fonts-liberation libasound2t64 libatk-bridge2.0-0 libatk1.0-0 libatspi2.0-0 \
  libcairo2 libcups2t64 libdbus-1-3 libgbm1 libglib2.0-0 libgtk-3-0 \
  libnspr4 libnss3 libpango-1.0-0 libvulkan1 libxcomposite1 libxdamage1 \
  libxfixes3 libxkbcommon0 libxrandr2 wget xdg-utils

# 再装 chrome 本体
apt-get install -y /tmp/google-chrome-stable_current_amd64.deb
```

启动 Chrome 连回本地 X Server——**这里是本文最大的坑**：

```bash
# ❌ 错误：DISPLAY=localhost:6000 会被解析成 display number 6000 → 端口 6000+6000=12000
#    结果报 "Missing X server or $DISPLAY"
# ✅ 正确：DISPLAY=localhost:0 → display 0 → 端口 6000（我们隧道监听的就是 6000）
export DISPLAY=localhost:0
nohup /opt/google/chrome/chrome \
  --no-sandbox --disable-dev-shm-usage --disable-gpu \
  --dbus-stub --ozone-platform=x11 \
  --window-size=1280,800 https://www.baidu.com &
```

窗口出来了，在本地用 VcXsrv 自带的 `xwininfo` 确认（注意用 `127.0.0.1:0` 而非 `:0`，Git Bash 里后者常解析失败）：

```bash
cd /c/tools/vcxsrv && DISPLAY=127.0.0.1:0 ./xwininfo.exe -root -tree
# 输出含： 0x200004 ("google-chrome") 1280x800  → 成功
```

### 坑四：汉字显示成方块

窗口出来了，但页面上的汉字全是方块（tofu）。第一反应是编码问题，于是开 CDP 抓页面文本验证——这又用到一条隧道，**方向相反的本地转发**：

```bash
# -L 本地转发：本地 9222 → 容器 127.0.0.1:9222（Chrome 的 CDP 端口）
ssh -N -L 9222:127.0.0.1:9222 -p 20022 root@127.0.0.1 &

# Chrome 启动时加 --remote-debugging-port=9222 --user-data-dir=/tmp/xxx
# 本地就能访问 CDP 了
curl -s http://127.0.0.1:9222/json/version   # → Chrome/151.x
curl -s http://127.0.0.1:9222/json           # → tab 列表（含 webSocketDebuggerUrl）
```

用 CDP 的 `Runtime.evaluate` 抓 `document.title` 和 `innerText`，发现**文本完全正常**（`百度一下，你就知道`）。这就锁定了根因：

> `innerText` 是 DOM 文本节点，和字体无关，所以数据没问题。方块是**渲染层**问题——精简容器里**根本没有中文字体**（`fc-list :lang=zh` 为空），Chrome 找不到 CJK 字形，只能画方块。

装中文字体，然后**重启 Chrome**（字体在进程启动时加载，运行中的 Chrome 不会感知新装字体——这一步最容易漏）：

```bash
# 微软雅黑是专有字体，Linux 包管理没有；开源的 Noto CJK / 思源黑体足够
apt-get install -y fonts-noto-cjk
fc-cache -f
fc-list :lang=zh | wc -l    # 确认 > 0（装完约 30 个中文字体）

# 关键：重启 Chrome，新字体才生效
```

重启后汉字正常显示。

### 坑五：能看中文，但打不出中文

窗口里汉字正常了，但想在输入框里打中文——Windows 本地输入法对这个窗口完全无效，Ctrl+Space 也切不出拼音。

这是 X11 转发的本质决定的：**X11 只转发原始按键（keysym）**，中文「拼音→汉字」的组字过程是**应用侧**输入法框架（XIM / fcitx / ibus）的事。Windows 输入法组好的中文不会被塞进 X11 转发的窗口。所以**输入法必须装在应用所在的地方，也就是容器里**。

装 fcitx5 + RIME（中州韵）+ 雾凇拼音词库。选 RIME 是因为：搜狗官方 Linux 版仍是 `sogoupinyin_4.2.1.145`（多年冻结、fcitx4 架构、与 fcitx5 冲突），豆包没有 Linux 版，百度 Linux 版也是老架构。**RIME + 雾凇拼音（rime-ice）是唯一现代、原生支持 fcitx5、体验对标搜狗的方案**。

```bash
# 输入法框架 + RIME 引擎
apt-get install -y --no-install-recommends \
  fcitx5 fcitx5-rime dbus-x11 im-config git

# 关键坑一：GTK/Qt 桥接模块。Chrome 是 GTK 应用，GTK_IM_MODULE=fcitx
# 需要对应的 immodule（im-fcitx5.so）才生效，否则环境变量形同虚设
apt-get install -y fcitx5-frontend-gtk3 fcitx5-frontend-gtk4 fcitx5-frontend-qt5
ls /usr/lib/*/gtk-3.0/*/immodules/im-fcitx5.so   # 确认桥接文件存在

# 雾凇拼音词库（66M）克隆到 RIME 用户目录
git clone --depth 1 https://github.com/iDvel/rime-ice.git \
  /root/.local/share/fcitx5/rime
```

配置分三层，缺一层都不对：

```bash
# 1) RIME 默认方案设为雾凇（default.custom.yaml）
cat > /root/.local/share/fcitx5/rime/default.custom.yaml <<'YAML'
patch:
  schema_list:
    - schema: rime_ice
YAML

# 2) fcitx5 profile 默认输入法设为 rime（DefaultIM=rime）

# 3) 环境变量 + 启动
export DISPLAY=localhost:0
export GTK_IM_MODULE=fcitx QT_IM_MODULE=fcitx XMODIFIERS=@im=fcitx
export XDG_RUNTIME_DIR=/tmp/runtime-root         # 缺这个 fcitx5 报 "XDG_RUNTIME_DIR is invalid"
mkdir -p $XDG_RUNTIME_DIR && chmod 700 $XDG_RUNTIME_DIR
eval $(dbus-launch --sh-syntax)                  # fcitx5 依赖 dbus session
fcitx5 -d --replace ; sleep 3                     # 先起 fcitx5，首次部署编译词库（约 58M，需十几秒）
/opt/google/chrome/chrome ... &                   # 后起 Chrome（继承 IM 环境变量）
```

### 坑六：一启动默认还是英文

配好后能打中文了，但每次进来默认是英文，要按一次 Ctrl+Space 才切中文。想「一启动就是中文」，需要**同时**满足两层开关，缺一个都不行：

```bash
# fcitx5 层：全局 config 设 ActiveByDefault（否则默认走键盘布局=英文）
cat > /root/.config/fcitx5/config <<'CONF'
[Behavior]
ActiveByDefault=True
ShareInputState=All
CONF
```

```yaml
# RIME 层：rime_ice.custom.yaml 给 ascii_mode 加 reset: 0（否则 RIME 内部默认西文）
# 把 rime_ice.schema.yaml 的 switches 段照抄过来，只在 ascii_mode 项加 reset: 0
patch:
  switches:
    - name: ascii_mode
      states: [ 中, Ａ ]
      reset: 0
    # ... 其余 switch 项照抄
```

`ActiveByDefault` 管 fcitx5 是否激活输入法，`ascii_mode: reset: 0` 管 RIME 内部中/西文——两个是不同层的开关，只改一个都还是英文。改完重启 fcitx5 + Chrome 才生效。

在输入框里直接敲拼音就是中文，候选词窗口也经同一个 X server 显示到 Windows 桌面。

## 根因分析

坑其实分布在几个不同层面：

1. **「免安装」≠「必须有便携版下载」**：编译型 X Server 的产物天生免安装，安装器只是分发外壳，用 `/S /D=` 解压即可。
2. **DISPLAY 的数字是 display number 不是端口**：`localhost:0` 才是端口 6000。这个错误的症状（`Missing X server`）极具误导性，让人以为是隧道不通，实际隧道好好的。
3. **文本正常不代表显示正常**：`innerText` 正确只能证明数据链路 OK，字形渲染依赖容器内的字体文件。
4. **显示和输入是两件事**：字体解决「看得到中文」，输入法解决「打得出中文」。二者都在**容器侧**（应用侧），与 Windows 本地环境无关——这是 X11 网络透明性的直接结果。
5. **环境变量要有对应的 immodule 才生效**：`GTK_IM_MODULE=fcitx` 只是声明，真正干活的是 `fcitx5-frontend-gtk3` 提供的 `im-fcitx5.so`。

## 完整链路

```
[容器 Chrome, DISPLAY=localhost:0, GTK_IM_MODULE=fcitx]
   ├── X11 →  ssh -R 6000:localhost:6000  → [本地 VcXsrv:0] → 桌面窗口
   ├── CDP ←  ssh -L 9222:127.0.0.1:9222  ← [本地 curl/websocket]
   ├── 中文显示 ← fonts-noto-cjk（容器内字体）
   └── 中文输入 ← fcitx5 + im-fcitx5.so（容器内输入法，候选词也经 X server 显示）
```

## 关键命令速查

```bash
# 1. VcXsrv 免安装（NSIS 静默解压）
MSYS_NO_PATHCONV=1 cmd.exe /c "installer.exe /S /D=C:\tools\vcxsrv"
MSYS_NO_PATHCONV=1 cmd.exe /c start "" "C:\tools\vcxsrv\vcxsrv.exe" :0 -multiwindow -clipboard -ac -wgl

# 2. 反向隧道：把本地 X Server:6000 送进容器
ssh -N -R 6000:localhost:6000 -p 20022 root@127.0.0.1 &

# 3. 容器内跑 Chrome（DISPLAY 用 :0 不是 :6000！）
export DISPLAY=localhost:0
/opt/google/chrome/chrome --no-sandbox --disable-gpu --ozone-platform=x11 https://example.com &

# 4. 本地转发访问 CDP
ssh -N -L 9222:127.0.0.1:9222 -p 20022 root@127.0.0.1 &
curl -s http://127.0.0.1:9222/json

# 5. 修方块：装中文字体后重启 Chrome
apt-get install -y fonts-noto-cjk && fc-cache -f
```

## 参考

- VcXsrv 源码与构建说明：`github.com/marchaesen/vcxsrv`
- X11 DISPLAY 端口规则：display N → TCP 端口 6000 + N
- SSH 隧道：`-R` 反向（远端监听转发回本地）、`-L` 本地（本地监听转发到远端）
