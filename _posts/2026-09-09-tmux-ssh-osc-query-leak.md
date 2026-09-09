---
layout: post
title: "tmux attach 后命令行出现 11;rgb:... 乱码：一次从玄学到 GitHub issue 的排查"
date: 2026-09-09 09:30:00 +0800
categories: 技术踩坑
tags: [tmux, ssh, terminal, zsh, Windows]
---

在 Windows 上的终端软件里通过 SSH 连到 Linux 服务器，跑 `tmux new -A -s xxx` 时，屏幕上总会先冒出一串乱码，甚至污染命令行。这篇记录完整的排查过程——包括几次"修好了其实没修好"的弯路。

## 问题现象

在 Windows 终端 → SSH → 服务器 zsh 的链路里，每次跑 `tmux new -A -s xxx`，会出现类似这样的输出：

```
^[]11;rgb:0c0c/0c0c/0c0c^[\%
➜  ~ 11;rgb:0c0c/0c0c/0c0c
```

仔细看其实是**五段终端应答**全部漏了出来：

| 乱码片段 | 实际身份 |
|----------|----------|
| `?61;4;6;7;14;...c` | DA1 应答（终端属性） |
| `>0;10;1c` | DA2 应答 |
| `10;rgb:cccc/cccc/cccc` | OSC 10 应答（前景色） |
| `11;rgb:0c0c/0c0c/0c0c` | OSC 11 应答（背景色） |

它们是应答，不是查询——也就是说，**远端有什么程序问了终端问题，但没人认领答案**，答案就被内核回显上屏、并被 shell 当成键盘输入塞进命令行。

## 环境信息

- 服务器：Ubuntu 24.04 (arm64)，tmux 3.4
- 客户端：Windows 上的终端模拟器，SSH 连接
- Shell：zsh + oh-my-zsh

## 排查过程（含弯路）

### 弯路 1：怀疑 zsh 主题/插件在查背景色

OSC 11（查询背景色）常见于 p10k 之类的主题。翻了 `.zshrc`：主题只是 robbyrussell，`plugins=(git)`——排除。

### 弯路 2：怀疑 tmux 配置，验证后无效

给 `.tmux.conf` 加上 `default-terminal` 和 `terminal-features` 显式声明终端能力，实测**查询照样发**。后来在 issue 里确认这是普遍结论：这些探测在 `tty_start_tty()` 里是无条件的，配置挡不住。

### 本地 pty 仿真：复现不出

写了个 Python pty 脚本模拟"迟应答的终端"，让终端在收到 `ESC]11;?` 查询后延迟 0 / 0.4s / 1.2s / 3s 才应答——**tmux 全都正确消费了**，`new -A` 一步创建也一样。这说明本机 tmux 处理正常应答没有问题，泄漏需要"应答迟到到 tmux 已经放弃等待"这个特殊时序，而那个时序只存在于 SSH 链路上。

仿真过程中还踩了两个坑，值得记下来：

1. **无 ZLE 的 shell 处于 canonical 模式**，没有换行符结尾的应答字节会压在行缓冲里，`read -t 0` 根本读不到。仿真排水逻辑必须先 `stty raw`，否则会误判方案"无效"。
2. zsh 的 `zle-line-init` 是钩子型 widget，**没有**对应的 `.line-init` 内置 widget 可调用。直接 `zle -N zle-line-init xxx` 然后在 widget 里 `zle .line-init` 会报 `No such widget: .line-init`，正确做法是用 `add-zle-hook-widget`。

### 期间做的兜底（缓解命令行污染）

虽然没找到根因，这些兜底确实把"乱码进命令行"治住了一部分，最终也保留了下来：

```zsh
# tmux 运行窗口关回显 → 应答到达时不上屏；返回后立刻排空 tty 残留字节
tmux() {
  command stty -echo 2>/dev/null
  command tmux "$@"
  command stty echo 2>/dev/null
  local junk
  while read -t 0 -k junk 2>/dev/null; do :; done
}
# 每次出 prompt、ZLE 读键前排空滞留应答
_jc_drain_tty() {
  local junk
  while read -t 0 -k junk 2>/dev/null; do :; done
}
autoload -Uz add-zle-hook-widget
add-zle-hook-widget line-init _jc_drain_tty
```

## 根因分析

靠提示词里那句"开代理去 GitHub 搜搜"才走上正路。拿乱码原文去搜，直接命中两个 issue：

- **tmux#4846**《OSC 10/11 and DA query responses leak as visible text when attaching over SSH》——症状一字不差，连 DA1 应答的 `?61;4;6;7;14;21;22;23;24;28;32;42;52c` 都相同
- **tmux#5540**——WezTerm on Windows + SSH + tmux 3.4/3.5 的同症状报告

机制：tmux attach 时在 `tty_start_tty()` 无条件发 5 个探测（DA1/DA2/XTVERSION/OSC10/OSC11）。本地跑 tmux 时应答瞬时回来、被完整消费；但 SSH 链路上应答有网络延迟，**一旦迟到超过 tmux 的探测窗口，tmux 就不再认领**，应答原样漏给 shell——被内核回显上屏（那行 `^[]11;...` 残影），并被读进命令行（`➜ ~ 11;rgb:...`）。

受影响版本：3.4、3.5a（已被确认）。issue 作者还验证了 `terminal-features`、`allow-passthrough` 等**所有配置手段都无效**。tmux 作者 nicm 的回复是：3.5 已是两年前的版本，改动很大，建议用 **3.7c** 或 master 验证。

## 最终方案

**升级服务器 tmux 到 3.7c**（Ubuntu 24.04 的 apt 只有 3.4，源码编译）：

```bash
# 依赖（apt 索引过期会 404，先 update）
sudo apt-get update
sudo apt-get install -y libevent-dev ncurses-dev pkg-config bison

# 编译安装到 /usr/local（PATH 优先命中，不动系统的 3.4）
cd /tmp && curl -sLO \
  https://github.com/tmux/tmux/releases/download/3.7c/tmux-3.7c.tar.gz
tar xzf tmux-3.7c.tar.gz && cd tmux-3.7c
./configure --prefix=/usr/local && make -j"$(nproc)" && sudo make install
hash -r && tmux -V   # → tmux 3.7c
```

回退：`sudo rm /usr/local/bin/tmux` 即回到系统的 3.4。

升级后实测乱码消失；上面的 zsh 兜底继续保留作纵深防御。

## 经验小结

1. **本地复现不出来的问题，及时把乱码原文拿去全网搜**。终端转义序列的"指纹"（如 `?61;4;6;7;14;...c`）辨识度极高，直接搜原文比猜机制快得多——这次绕了一大圈，一条 issue 搜索就终结战斗。
2. 终端链路问题排查顺序建议：先看是谁在发查询（`.zshrc`/插件），再验证配置能否关掉，再用 pty 仿真隔离变量，最后带着**逐字符的症状原文**搜 issue。
3. tmux 在 attach 时会无条件向终端发 5 个能力探测，SSH 高延迟链路 + 应答慢的终端组合就是踩雷条件。

## 参考

- [tmux#4846: OSC 10/11 and DA query responses leak as visible text when attaching over SSH](https://github.com/tmux/tmux/issues/4846)
- [tmux#5540: Terminal DA/OSC responses leak into active pane when attaching over SSH from Windows terminals](https://github.com/tmux/tmux/issues/5540)
