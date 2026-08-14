---
layout: post
title: "GitHub Pages 从某次提交起构建全挂？先查被 Liquid 误读的代码块"
date: 2026-08-14 12:40:00 +0800
categories: [技术踩坑]
tags: [jekyll, github-pages, liquid, 博客, 排障]
---

Jekyll + GitHub Pages 有个很隐蔽的坑：首页和文章停在某个旧版本，新文章怎么推都不上线。不是代码没推上去，而是 **渲染 markdown 前会先用 Liquid 处理全文**，正文里一旦出现没被 raw 标签包裹的双花括号（`&#123;&#123;` `&#125;&#125;`），整次 Pages 构建会直接失败，之后所有新提交全部连带失败。

> 说明：本文为了讲解 raw 标签本身，所有提及标签的地方都做了处理——真实演示在下方代码块里用外层 raw 包裹，正文叙述里的字面量全部用 HTML 实体转义，避免文章自己再触发那个坑。

## 问题现象

- 博客首页最新只到上周某篇文章，这周连续推了十几篇新文章都不显示
- 本地仓库和远端 main 分支内容一致、完全没落后
- 每次 `git push` 都成功，但线上页面就是不变
- GitHub 会往关联邮箱发 "The page build failed" 的构建失败邮件

## 环境信息

- 平台: Jekyll + GitHub Pages（Minima 主题）
- 构建: GitHub 托管 Pages 自动构建
- 关键时刻: 某个"技术文批量提交"的 commit 是分水岭，之前构建正常、之后全挂

## 排查过程

第一反应是"是不是没 push"，于是逐层排除：

1. **对比本地与远端**：`git status` 干净，`git log origin/main..main` 为空，说明远端已经是新的。
2. **抓线上首页**：`curl https://<user>.github.io/`，看到首页文章列表确实停在旧时间点——但这也只说明"线上没更新"，没说明为什么。
3. **查 Pages 构建状态**（关键一步）。
4. **看构建历史**：发现某个 commit 之前全是 `built`，从它开始一连串 `errored`。

到这里基本锁定：**线上站点落后 = Pages 构建失败**，而不是内容问题。接下来找失败原因。

### 快速查 Pages 构建状态的命令

用 GitHub CLI（`gh`）一次拿到当前状态和最近构建记录，非常快：

```bash
# 当前构建状态（normal/building/errored）
gh api "repos/<owner>/<repo>/pages" --jq '.status'

# 最近几条构建历史 + 是否失败
gh api "repos/<owner>/<repo>/pages/builds" \
  --jq '.[] | {status, commit: .commit[0:7], error: (.error.message // "-")}'
```

输出样例（节选）：

```
{"status":"errored","commit":"a1b2c3d","error":"Page build failed."}
{"status":"built",  "commit":"9f8e7d6","error":"-"}
```

`status: errored` 加 `Page build failed` 就确认是构建问题。`git log` / `git diff` 都看不出构建失败，必须查构建 API。

## 根因分析

GitHub Pages 的构建管线是：**Liquid 渲染 → markdown 渲染 → 生成站点**。也就是说，Jekyll 在把 markdown 交给 kramdown 之前，会先让 Liquid 扫描每一个 `.md` 文件，把 `&#123;&#37;` … `&#37;&#125;`（标签）和 `&#123;&#123;` … `&#125;&#125;`（变量）当作模板语法处理。

问题就出在这里：技术博客的正文里，代码块很容易出现**看起来像模板、其实是业务代码**的字符，例如：

- JS / Python 代码里为了在 f-string 或模板字符串中转义花括号而写的 `&#123;&#123;` / `&#125;&#125;`，如 `(() => &#123;&#123; ... el.click(); return true; &#125;&#125;)`
- Cypher 等带参数语法里写的 `&#123;&#123;id: $id&#125;&#125;`、`&#123;&#123;id: $from&#125;&#125;`

这些字符只要出现在**没被 raw 包裹的代码块**里，Liquid 就会把 `&#123;&#123; el.click(); return true; &#125;&#125;` 或 `&#123;&#123;id: $id&#125;&#125;` 当成变量表达式去求值。解析一失败，**整次 Pages 构建直接报错中止**，而不是跳过。所以：

> 一篇坏文章 = 全站构建失败 = 之后所有推送都不上线。

这也是为什么"某一次提交是分水岭"：那批新增文章里只要有一篇带了这类字符，从它开始之后全部构建失败；GitHub 只会告诉你 `Page build failed`，不会告诉你具体是哪个文件哪一行。

## 最终方案

给含双花括号的代码块套上 raw 标签对，让 Liquid 跳过整块内容原样输出。raw 起始和结束标签放在 fenced code block 的 ` ``` ` 围栏**外面**：

{% raw %}
```python
### yaml_to_neo4j.py

session.run(f"""
    MERGE (n:{label_cypher} {{id: $id}})
    ON CREATE SET n.createdAt = $now
""", ...)
```
{% endraw %}

要点：

- raw 起始标签放在 fenced code block 的 ` ``` ` 围栏**外面**，不是里面；结束标签同理放在收尾 ` ``` ` 之后。
- 一对起始/结束标签包住整个含双花括号的代码块即可。
- **正文叙述里不要裸写这些字符**。如果文章本身要讲解这个坑（就像本文），把提及的 `&#123;&#123;` / `&#123;&#37;` 用 HTML 实体转义（`{` 写 `&#123;`、`%` 写 `&#37;`），否则讲解文字自己又会触发 Liquid——这是最容易反复踩的坑。
- 修完后 push，触发 Pages 重新构建，确认状态从 `errored` 变回 `built`，线上首页自然会带出所有积压的新文章。

### 排查顺序速查

1. 抓线上首页 → 确认内容确实落后
2. 对比 git 远端 → 确认代码没落后（排除 push 问题）
3. 用 `gh api` 查 pages 构建状态 → 若为 `errored`，说明是构建失败
4. 定位分水岭 commit → 谁引入第一处 `errored`
5. 在该 commit 新增文章的代码块里找会被 Liquid 误读的字符 → 用 raw 标签对包裹
6. 重新 push → 构建状态变 `built` → 首页更新

## 参考

- [GitHub Docs: About GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/about-github-pages)
- [Liquid: raw 标签文档](https://shopify.github.io/liquid/tags/raw/)
