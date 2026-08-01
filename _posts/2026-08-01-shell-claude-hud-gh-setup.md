---
layout: post
title: "一次会话里的 Zsh 插件整理、Claude HUD 安装和 gh CLI 配置"
date: 2026-08-01 04:00:00 +0800
categories: 工具
---

今天聊一次干活时的整理过程：关掉一个用不惯的插件、优化一个在用的 git 克隆函数、给 Claude Code 装 HUD 状态栏，以及把 gh CLI 装好并登录。

---

## 1. 关掉 zsh-autosuggestions

之前装了 `zsh-autosuggestions`，就是那个在终端里显示灰色幽灵文字、提示你之前打过什么命令的插件。用了一阵发现太碍眼——打一半的时候它总在旁边 "嗡嗡"，分神。

做法是直接从 `plugins` 数组里剔除它：

```zsh
# 在 ~/.zshrc 里
plugins=(git zsh-syntax-highlighting)
# 剔掉了: zsh-autosuggestions
```

如果彻底不想再见到，连目录一起清：

```bash
rm -rf ~/.oh-my-zsh/custom/plugins/zsh-autosuggestions
```

`syntax-highlighting` 倒是留下来了——绿色有效、红色无效，这个很直观。

---

## 2. 优化 ghc 函数并写到 aliases.zsh

`ghc` 是我自己写的一个 git clone 快捷函数。之前版本有几个边角问题，这次一并修了：

### URL 里的用户名密码会被存到目录名里

比如 `https://user:pass@github.com/owner/repo.git`，如果不处理，`$HOME/repo` 底下会多出一层 `user:pass@github.com` 目录，敏感信息直接上盘。

加上 `sed -E 's|^[^@]*@||'` 把 `@` 前面的东西删掉：

```bash
local repo_path
repo_path=$(echo "$url" \
    | sed -E 's|^[^:]+://||' \
    | sed -E 's|^git@||' \
    | sed -E 's|^[^@]*@||' \
    | sed 's|:|_|g' \
    | sed 's|\.git$||')
```

### 端口冒号污染路径

处理后的 URL 里如果还有 `:`（比如 `github.com:8443`），在 Linux 文件名里不合法。统一换成 `_`：

```bash
sed 's|:|_|g'
```

这样 `github.com_8443/owner/repo` 就是干净的路径了。

### 目标已存在但不区分文件和目录

如果一个文件碰巧叫 repo 的名字，原先代码用 `-d` 只判断目录，现在先用 `-e` 判断存在，再用 `-f` 细分：

```bash
if [ -e "$target_dir" ]; then
    if [ -f "$target_dir" ]; then
        echo "Error: $target_dir is a file, not a directory"
        return 1
    fi
    # 是目录就 cd 进去
    cd "$target_dir" || return
    return 0
fi
```

### ~/.cache 目录可能不存在

函数会在浅克隆后后台执行 `git fetch --unshallow`，日志写到 `~/.cache/ghc-unshallow.log`。如果系统没有 `~/.cache`，后台进程（已 disown）写日志失败你还不知道。

在 fork 之前加一行 `mkdir -p "$HOME/.cache"` 兜底。

### 最终落盘位置

没有直接塞进 `~/.zshrc`，而是写到 Oh My Zsh 自动加载的路径：

```
~/.oh-my-zsh/custom/aliases.zsh
```

好处是以后所有自定义函数和别名都归这里管，`~/.zshrc` 保持干净。

---

## 3. 安装 Claude HUD 插件

Claude HUD 是 Claude Code 的一个状态栏插件，会在输入框下方显示当前 context 用量、活跃工具、运行中的 agent 和 todo 进度。

安装分三步：

```bash
# 添加 marketplace
claude plugin marketplace add jarrodwatts/claude-hud

# 安装插件
claude plugin install claude-hud

# 在对话里执行
/reload-plugins
```

装完后还要运行 `/claude-hud:setup` 来配置 `~/.claude/settings.json` 里的 `statusLine`。这个 setup 比较长，核心逻辑是：

1. 找到插件实际安装路径（在 `~/.claude/plugins/cache/` 下的某个版本目录）
2. 检测本机 runtime——优先 bun，没有就 fallback 到 node
3. 组装一条命令，导出 `COLUMNS` 让 HUD 知道终端宽度，然后动态定位最新版本并执行
4. 写入 `settings.json`
5. 做备份（`settings.json.bak.时间戳`）
6. 可选配置额外显示项（tools activity、agents、todos 等）

写入的 `settings.json` 关键段类似：

```json
{
  "statusLine": {
    "type": "command",
    "command": "bash -c '... exec \"/path/to/node\" \"${plugin_dir}dist/index.js\"'"
  }
}
```

下次打开 Claude Code 或在对话里交互一次，底部就会出现 HUD 了。

---

## 4. 安装 gh CLI 并用 PAT 登录

`gh` 是 GitHub 官方命令行工具，今天第一次在这台机器上装。

Ubuntu 直接 apt：

```bash
sudo apt-get install gh -y
```

装完后验证：

```bash
gh --version
# gh version 2.45.0
```

登录。这台环境没有浏览器，走 Personal Access Token（PAT）。代理地址我从项目根 `.env.local` 的 `HTTP_PROXY` 读（不写死，换网络只改那个文件）：

```bash
source .env.local
export https_proxy="$HTTP_PROXY"
echo "ghp_xxxxx" | gh auth login --with-token
```

验证登录：

```bash
gh auth status
# ✓ Logged in to github.com account qin-zhuopu
```

Token scope 很全（`repo`, `workflow`, `gist`, `copilot` 等），足够日常推代码和管理 issue 了。代理也配好了，后续 `git push` 走代理不会超时。

---

## 小结

| 动作 | 文件/位置 | 备注 |
|---|---|---|
| 移除 autosuggestions | `~/.zshrc` plugins 数组 | 简单直接 |
| 优化 ghc 函数 | `~/.oh-my-zsh/custom/aliases.zsh` | 处理 URL 敏感信息、端口、文件冲突、.cache 兜底 |
| 安装 Claude HUD | `~/.claude/settings.json` | marketplace 安装 + setup 生成 statusLine 命令 |
| 安装并登录 gh | `~/.config/gh/hosts.yml` | apt 一步装完，PAT 登录 |

都是小修小补，但整理完后顺手多了。下次打开终端或 Claude Code，体验应该更干净。
