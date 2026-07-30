---
layout: post
title: "GitHub CLI 在 macOS Big Sur 上装不了？装个旧版本就行"
date: 2026-07-31 07:30:00 +0800
categories: 工具
---

写上一篇文章的时候需要用 GitHub CLI（`gh` 命令）查自己的仓库列表，结果发现新版 gh 装不了。把解决过程记一下，省得下次再踩。

## 现象

环境：macOS 11.7.10 Big Sur，Intel。

### 尝试 1：`brew install gh` 失败

```
==> Installing gh dependency: go
go: This formula does not run on macOS versions older than Monterey.
Error: An unsatisfied requirement failed this build.
```

`brew install gh` 会先装 `go` 作为构建依赖，而**新版 Go 1.21+ 要求 macOS 12 Monterey 或更高**——Big Sur 直接被卡死。

### 尝试 2：从 GitHub Release 下载二进制

```
$ curl -L -o gh.zip https://github.com/cli/cli/releases/download/v2.96.0/gh_2.96.0_macOS_amd64.zip
$ unzip gh.zip
$ ./gh_2.96.0_macOS_amd64/bin/gh --version

dyld: Symbol not found: _SecTrustCopyCertificateChain
  Referenced from: /path/to/gh (which was built for Mac OS X 12.0)
  Expected in: /System/Library/Frameworks/Security.framework/Versions/A/Security
```

二进制能下载、能解压，但**跑不起来**。dyld 报符号找不到——`_SecTrustCopyCertificateChain` 这个函数是 macOS 12 Monterey 才引入的（Security framework），Big Sur 的 Security framework 里没这个符号。

错误信息写得很明白：

```
(which was built for Mac OS X 12.0)
```

也就是说 **`gh 2.96.0` 编译时最低部署目标是 macOS 12**，编译出来的二进制用了 Monterey+ 才有的系统调用，根本不可能在 Big Sur 上跑。

## 原因：Go 1.21+ 放弃了 Big Sur 支持

gh CLI 是用 Go 写的。**Go 1.21 起把最低支持的 macOS 版本提到了 12 Monterey**（[Go 1.21 release notes](https://go.dev/doc/go1.21)）：

> Go 1.21 is the last release that is supported on macOS 10.15 Catalina and 11 Big Sur. Go 1.22 will require macOS 10.15 or later.

——实际效果是 Go 1.21 编译出来的程序在 Big Sur 上能跑（`_SecTrustCopyCertificateChain` 是 Go 1.21 引入的新调用），但 Big Sur 的 Security framework 还没有这个符号。

Go 团队的解释：他们用了 macOS 12 才有的 Security API 来改 TLS 实现，所以编译产物不能在 Big Sur 跑。

而 `brew install gh` 的 `gh.rb` formula 直接拉最新版 Go 作为依赖，于是 Big Sur 用户既装不上 Go，也装不上 gh。

## 解决：找一个还在 Big Sur 上能跑的 gh 版本

GitHub CLI 在 2.40 之后开始用需要 macOS 12 的 Go 版本编译。**最后能在 Big Sur 上稳定跑的版本是 `gh 2.39.x`**（2023 年 11 月发布）。

### 下载安装步骤

```zsh
# 走代理（如果直连慢）
export https_proxy=http://localhost:8080

# 下载 gh 2.39.2 macOS amd64
curl -L -o /tmp/gh.zip \
  https://github.com/cli/cli/releases/download/v2.39.2/gh_2.39.2_macOS_amd64.zip

# 解压
cd /tmp && rm -rf gh-extract && unzip gh.zip -d gh-extract

# 验证能跑
/tmp/gh-extract/gh_2.39.2_macOS_amd64/bin/gh --version
```

应该看到：

```
gh version 2.39.2 (2023-11-27)
https://github.com/cli/cli/releases/tag/v2.39.2
```

如果能跑，复制到 PATH 里：

```zsh
mkdir -p ~/bin
cp /tmp/gh-extract/gh_2.39.2_macOS_amd64/bin/gh ~/bin/gh
chmod +x ~/bin/gh
rm -rf /tmp/gh.zip /tmp/gh-extract
```

确保 `~/bin` 在 PATH 里：

```zsh
echo 'export PATH="$HOME/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

验证：

```zsh
which gh
gh --version
```

## 登录

```zsh
gh auth login
```

按提示选择：

1. **What account do you want to log into?** → `GitHub.com`
2. **What is your preferred protocol for Git operations on this host?** → `HTTPS`（如果你有 SSH key 配好了也可以选 SSH）
3. **Authenticate Git with your GitHub credentials?** → `Y`
4. **How would you like to authenticate GitHub CLI?**
   - `Login with a web browser`：会显示一个一次性 code，按回车打开浏览器授权（最方便）
   - `Paste an authentication token`：去 https://github.com/settings/tokens 创建一个 Personal Access Token，复制粘贴

授权成功后，验证：

```zsh
gh auth status
```

输出：

```
github.com
  ✓ Logged in to github.com as YOUR_USERNAME (keyring)
  ✓ Git operations for github.com configured to use https protocol.
  ✓ Token: ghp_************************************
  ✓ Token scopes: ...
```

## 常用命令

```zsh
# 列出自己的仓库
gh repo list --limit 50

# 列出某个用户的仓库
gh repo list USERNAME --limit 100

# 看仓库信息（含 README）
gh repo view OWNER/REPO

# Clone 自己的仓库
gh repo clone REPO_NAME

# 创建新仓库
gh repo create REPO_NAME --public --source=. --push

# 看 PR 列表
gh pr list

# 看 Issue 列表
gh issue list

# 创建 PR
gh pr create --title "标题" --body "描述"
```

## 为什么不用最新版

`gh 2.39.2` 是 2023 年 11 月的版本，距离现在一年半。如果你需要新版本的功能（比如某个 2.50+ 才加的命令），那 Big Sur 上确实没救——除非升级 macOS。

但 `gh` 的核心功能（`auth` / `repo` / `pr` / `issue` / `api`）在 2.39 已经稳定很久了，对于查仓库、clone、提 PR 这种日常用法，2.39 完全够用。

## 思考：为什么有些工具越来越难在老系统上用

这种"最新版要求最新系统"的情况在 macOS 生态里很常见：

1. **Apple 鼓励开发者把最低部署目标设为新版本**——能用新 API、不用写兼容代码
2. **上游语言/工具链放弃老系统**——Go 1.21+ 抛弃 Big Sur，Node.js 也类似
3. **包管理器跟着上游走**——Homebrew 直接拉最新 Go，Big Sur 用户被卡

如果你坚持用老 macOS（这台机器卡在 Big Sur 不升级是有原因的：性能、稳定性、某个软件兼容性等），就会越来越频繁地撞到这种"最新版要求新系统"的墙。**对策**：

- 找最后一个支持老系统的版本（像本文这样）
- 找替代品（比如用 `git` + GitHub 网页代替 `gh`）
- 用 Docker 跑老版本（成本高）

我个人经验：常用工具（git、curl、jq、python3）大部分都有兼容老系统的发布版；问题主要集中在用 Go / Rust / Node.js 写的新工具上。装之前先去 release 页面看 binary 的最低系统要求，能省很多事。

## 总结

- `brew install gh` 在 Big Sur 上失败，是因为依赖的 Go 1.21+ 要求 macOS 12+
- 直接下载 gh 最新版二进制也不行，因为 dyld 找不到 `_SecTrustCopyCertificateChain` 符号（macOS 12+ 才有）
- **解决方案**：从 GitHub Release 下载 **`gh 2.39.2`**，二进制能直接在 Big Sur 上跑

```zsh
curl -L -o /tmp/gh.zip \
  https://github.com/cli/cli/releases/download/v2.39.2/gh_2.39.2_macOS_amd64.zip
unzip /tmp/gh.zip -d /tmp/gh-extract
mkdir -p ~/bin
cp /tmp/gh-extract/gh_2.39.2_macOS_amd64/bin/gh ~/bin/gh
echo 'export PATH="$HOME/bin:$PATH"' >> ~/.zshrc
```

如果以后 2.39 也不能跑了，可以去 [release 页面](https://github.com/cli/cli/releases) 翻更早的版本。`gh` 的核心 API 调用通过 GraphQL / REST，老版本对新 GitHub 功能支持不全但日常操作都 OK。
