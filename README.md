# qin-zhuopu.github.io

我的个人博客，基于 GitHub Pages + Jekyll（Minima 主题）。

线上地址：https://qin-zhuopu.github.io

## Claude Code 技能

本仓库同时托管一个自定义 Claude Code 技能 `blog-pitfall`，用于将对话中的技术踩坑经验**自动脱敏**后发布到博客。详见：

- **Skill 源码**：[`skills/blog-pitfall/SKILL.md`](skills/blog-pitfall/SKILL.md)
- **安装使用说明**：[Claude Code blog-pitfall 技能安装使用指南](https://qin-zhuopu.github.io/2026/08/01/claude-code-blog-pitfall-skill/)（博客文章）

触发词：`记下来`、`写到博客`、`踩坑记录`、`blog this`、`record this pitfall` 等。

## 首次克隆后的配置

本仓库用「仓库内 hooks」做推送前检查。clone 后需手动激活 hooks：

```bash
./scripts/setup-hooks.sh
```

或直接：

```bash
git config core.hooksPath .githooks
```

> **注意**：`.githooks` 目录随仓库同步，但 `core.hooksPath` 配置不会自动生效（Git 安全机制），所以 clone 后必须手动执行上面的命令一次。

### 提交前检查（pre-commit）

 TODO：[可选] 格式化 front matter、lint markdown

### 推送前检查（pre-push）

推送前自动跑死链脚本，只检查**站内链接**（不依赖外网）：

```bash
python scripts/check_links.py --no-net
```

如果检测到死链，推送会被阻止。修复后重试，或紧急情况下加 `--no-verify` 跳过：

```bash
git push --no-verify   # 不推荐，除非你知道自己在做什么
```

## 写新文章

在 `_posts/` 下新建文件，命名格式 `YYYY-MM-DD-标题.md`，开头加 front matter：

```yaml
---
layout: post
title: "标题"
date: 2026-07-12 09:00:00 +0800
categories: 随笔
---
```

然后：

```bash
git add .
git commit -m "新文章：标题"
git push
```

几分钟后 GitHub Pages 会自动编译发布。
