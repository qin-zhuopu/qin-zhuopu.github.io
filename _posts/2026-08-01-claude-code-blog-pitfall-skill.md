---
layout: post
title: "Claude Code blog-pitfall 技能：让 AI 自动帮你写踩坑博客"
date: 2026-08-01 07:00:00 +0800
categories: [ai, workflow]
tags: [claude-code, blog, automation, ai-agents]
---

日常开发中跟 Claude 对话排雷，解决完一个坑之后，常见的流程是：打开编辑器 → 整理思路 → 手动脱敏（去掉项目名、IP、路径）→ 写成 Markdown → `git commit && git push`。这套流程重复多了很烦，而且脱敏这一步经常漏掉什么。

这个技能把整个过程自动化：你只需在对话里说一声"记下来发博客"，Claude 就帮你分析对话内容、自动脱敏、生成文章、推到你的博客仓库。

## 功能

- **分析对话**：自动提取问题现象、排查过程、根因、解决方案
- **自动脱敏**：项目名、IP、路径、token、个人用户名等 7 类敏感信息自动替换
- **生成文章**：按 Jekyll/Hexo Markdown 格式输出，含 front matter
- **一键发布**：通过 `gh` CLI 克隆博客仓库、写入文章、提交

## 安装

### 1. 复制技能到 Claude Code 技能目录

```bash
# 创建技能目录
mkdir -p ~/.claude/skills/blog-pitfall

# 复制 SKILL.md（从博客仓库或本仓库克隆）
cp skills/blog-pitfall/SKILL.md ~/.claude/skills/blog-pitfall/
```

> 技能文件在博客仓库的 [`skills/blog-pitfall/SKILL.md`](https://github.com/qin-zhuopu/qin-zhuopu.github.io/blob/main/skills/blog-pitfall/SKILL.md)。

### 2. 安装 gh CLI（如未安装）

```bash
# Debian/Ubuntu
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
sudo chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
sudo apt update && sudo apt install gh

# 登录
gh auth login
```

### 3. 首次使用：配置博客仓库

在任意项目的 Claude 对话中，说出触发词：

> "这个坑记下来发博客"

首次调用时，技能会检测到缺少配置，询问以下信息：

| 配置项 | 示例值 | 说明 |
|--------|--------|------|
| `repo` | `myname/myname.github.io` | GitHub 仓库，owner/name 格式 |
| `local_dir` | `~/workspace/myname.github.io` | 本地克隆绝对路径 |
| `branch` | `main` | 目标分支 |
| `posts_dir` | `_posts` | 文章目录（Hexo 用 `source/_posts`）|

配置保存到 `~/.config/blog-pitfall/blog.yaml`，后续所有项目共用，不再询问。

## 使用方法

### 触发词

以下任意说法都能触发技能：

- "刚才的记下来发博客"
- "这个坑写出来"
- "脱敏后发布"
- "blog this pitfall"
- "record this"
- "值得记录"

### 工作流程

触发后 Claude 会自动执行：

1. **读取配置**：从 `~/.config/blog-pitfall/blog.yaml` 加载博客 repo 和路径
2. **分析对话**：提取问题现象、排查过程、根因、解决方案
3. **脱敏处理**：替换项目名、路径、IP、token 等敏感信息
4. **生成文章**：按 Jekyll Markdown 格式写入文件
5. **提交**：`git add && git commit`，然后**询问是否 push**

不会自动 push，给你确认和修改的机会。

### 示例

假设你跟 Claude 聊了半天，解决了一个代理导致 npm 安装超时的问题。最后你说：

> "刚才 debug 的过程记下来发博客。"

Claude 会生成类似这样的文章：

```markdown
---
layout: post
title: "代理环境下 npx 安装超时排查"
date: 2026-08-01 07:00:00 +0800
categories: [技术踩坑]
tags: [proxy, npm, npx, timeout]
---

运行 `npx bmad-method install` 时遇到 GitHub 连接超时，
挂起 133 秒后失败。排查后发现是代理未配置导致。

## 问题现象

...

## 关键命令速查

```bash
export http_proxy=http://192.0.2.x:3128
export https_proxy=http://192.0.2.x:3128
npx bmad-method install -y ...
```
```

**注意**：原始对话中的项目名 `codepilot-web`、IP `172.24.0.5`、个人用户名都已被替换。

## 脱敏规则

技能内置 7 类敏感信息的自动替换：

| 类型 | 示例 | 替换后 |
|------|------|--------|
| 项目名 | `my-company-service` | `my-project` |
| 绝对路径 | `/home/alice/repo/...` | `project-root/` |
| IP 地址 | `172.24.0.5` | `192.0.2.x`（RFC 5737 测试网段）|
| Token / 密钥 | `ghp_xxx` | `[REDACTED]` |
| 内部域名 | `litellm.internal.com` | `内部网关` 或占位符 |
| 个人用户名 | `alice`、`qin-zhuopu` | `我` |
| 公司名 | `Acme Corp` | 删除或泛化 |

**原则**：保留技术本质和可复用步骤，替换后不影响读者理解。

## 适用场景

- 环境配置踩坑（代理、DNS、SSL 证书）
- 工具使用技巧（命令参数、隐藏选项）
- 版本兼容性排雷（依赖冲突、API 变更）
- 安装过程备忘（特定环境下的安装步骤）
- 调试过程复盘（反复试错后找到的根因）

不适用：需要配图或大量代码示例的技术深度文章——这类内容更适合手动编辑。

## 参考

- [blog-pitfall Skill 源码](https://github.com/qin-zhuopu/qin-zhuopu.github.io/blob/main/skills/blog-pitfall/SKILL.md)
- [Claude Code 技能文档](https://docs.anthropic.com/en/docs/claude-code/skills)
- [Jekyll 文章格式](https://jekyllrb.com/docs/posts/)
