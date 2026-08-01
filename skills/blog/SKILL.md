---
name: blog
description: >
  将当前会话中发现的技术踩坑、调试经验或安装备忘，脱敏后发布到博客。
  触发词："记下来" "写成博客" "发到博客" "这个坑" "经验教训" "踩坑记录"
  "脱敏后发布" "值得记录" "写篇博客" "blog this" "record this"
  "值得发博客" "把刚才的记录下来" "刚才的坑记下来" "写成文章" "记一下"。
  遇到环境配置错误、版本冲突、奇怪的行为、工具使用技巧时也触发。
---

# 博客记录技能

将对话中的技术经验转化为脱敏的博客文章，发布到用户的 Jekyll/Hexo 博客。

## 个人配置

博客配置存于用户主目录，与任何项目无关：

```
~/.config/blog/blog.yaml      # 创建后不再询问
```

**首次调用**若文件不存在，询问并创建：
- `repo` — GitHub 仓库 `owner/name`（例：`myname/myname.github.io`）
- `local_dir` — 本地克隆绝对路径（例：`~/workspace/myname.github.io`）
- `branch` — 目标分支（默认 `main`）
- `posts_dir` — 文章目录，默认 `_posts`（Hexo 用 `source/_posts`）
- `frontmatter_date_format` — 日期格式，默认 `"YYYY-MM-DD HH:MM:SS +0800"`

保存后后续直接读取。

## 工作流程

### 1. 读取/创建配置

检查 `~/.config/blog/blog.yaml` 是否存在。不存在时：

1. 询问 `repo`（owner/name 格式）
2. 询问 `local_dir`（绝对路径，支持 `~` 展开）
3. 询问 `branch`（默认 `main`）
4. 询问 `posts_dir`（默认 `_posts`）
5. 写入 YAML，后续不再询问

### 2. 分析当前对话

阅读当前会话，提取：
- **问题现象**：报错、异常行为、超时、不预期的结果
- **环境背景**：什么工具/框架/命令触发的（泛化描述）
- **排查过程**：尝试了哪些方法，哪些有效哪些无效
- **根因**：为什么会发生
- **解决/规避方案**：最终怎么解决的
- **通用命令**：可复用的命令或配置片段

若当前对话内容不足以支撑一篇完整文章，向用户简要概括已提取的要点，询问是否有补充细节。

### 3. 脱敏

**必须**执行以下替换：

| 类型 | 示例 | 替换为 |
|------|------|--------|
| **项目名** | `my-company-service`、`internal-dashboard` | `my-project` 或 `一个典型的 Node.js 项目` |
| **组织/公司名** | `Acme Corp`、`BigCo` | 删除或泛化 |
| **具体绝对路径** | `/home/alice/repo/...`、`/Users/bob/workspace/...` | `project-root/` 或 `~/workspace/` |
| **个人用户名** | `alice`、`bob_qin` | `我` 或删除 |
| **IP 地址** | `192.168.0.5`、`172.24.0.5` | `127.0.0.1`、`192.0.2.x`（RFC 5737 测试网）或泛化 `代理服务器` |
| **Token / 密钥** | `ghp_xxx`、`sk-xxx` | `[REDACTED]` |
| **内部域名** | `litellm.internal.example.com` | `my-llm-gateway.example.com` 或 `内部网关` |
| **私有仓库 URL** | `github.com/my-org/secret-repo` | `github.com/owner/private-repo` |
| **具体叙事ID** | `JIRA-578`、`TICKET-42` | `#578`、`issue-N` |
| **公司员工名** | 同事真实姓名 | 角色名或删除 |

**脱敏原则**：
- 保留技术本质和可复现步骤
- 替换后不影响读者理解和复用
- 不确定是否敏感的内容，默认泛化或删除

### 4. 生成文章

文件名：`YYYY-MM-DD-<slug>.md`

**标题规则**：
- 用技术现象命名，**不含项目名和组织名**
- 例：
  - ❌ `BMAD 在 codepilot-web 的安装记录`
  - ✅ `BMAD Method 安装踩坑记录`
  - ❌ `公司内网代理导致 GitHub 超时`
  - ✅ `代理环境下 npm/npx 安装超时排查`

**文章模板**：

```markdown
---
layout: post
title: "标题"
date: YYYY-MM-DD HH:MM:SS +0800
categories: [技术笔记]
tags: [tag1, tag2, tag3]
---

简短引言（1-2 句）。

## 问题现象

## 环境信息

- OS: Linux (WSL2) / macOS / Windows
- Shell: zsh / bash
- 工具: 相关版本号（如需要）

## 排查过程

## 根因分析

## 最终方案

## 关键命令速查

```bash
# 可复用命令
```

## 参考

- [链接](URL)
```

### 5. 发布

1. 检查本地目录是否存在：
   ```bash
   if [ ! -d "$local_dir/.git" ]; then
     mkdir -p "$(dirname "$local_dir")"
     gh repo clone "$repo" "$local_dir"
   fi
   ```

2. 写入文章到 `$local_dir/$posts_dir/YYYY-MM-DD-<slug>.md`

3. `cd "$local_dir" && git add "$posts_dir/"`

4. 询问用户是否直接 push：
   - 若用户同意：`git commit -m "post: <标题摘要>" && git push origin "$branch"`
   - 若用户不同意：`git commit -m "post: <标题摘要>"`，提示手动 `git push`
   - 若用户想修改：打开文件供编辑

## 约束

- 不自动 push，提交后询问
- 文章必须让**任何开发者**看懂并可复用
- categories 固定 `[技术踩坑]`，tags 从技能/工具中提取 2-5 个
- 不引用超出通用范围的文件路径
