---
layout: post
title: "Claude Code bmad-install 技能：一键自动化安装 BMAD Method"
date: 2026-08-01 08:00:00 +0800
categories: [ai, workflow]
tags: [claude-code, bmad, automation, ai-agents]
---

BMAD Method 是 AI-Native 的开发框架，有 5 个模块（Core、BMM、Loop、Test Architect、Builder）共 64 个 skills。手动安装过程繁琐：先装基础模块、再装扩展模块（容易踩坑）、然后初始化 bmad-loop 编排器、验证 preflight。我刚整理了一个 Claude Code 技能，把这些全部自动化——说"安装 bmad"就一键搞定。

## 功能

- **一键全装**：一条命令装齐 5 个模块，避开 `--action update` 陷阱
- **CSV 污染检测**：自动扫描 `TSD-Header` 加密标记，发现即触发完整重装
- **产物备份**：重装前自动备份 `_bmad-output/` 历史产物
- **代理自动注入**：读取系统 proxy 环境变量，自动 export 到安装命令
- **bmad-loop 贯通**：安装完成后自动 init hooks、补全 .gitignore、运行验证

## 安装

### 1. 复制技能到 Claude Code 技能目录

```bash
mkdir -p ~/.claude/skills/bmad-install
cp skills/bmad-install/SKILL.md ~/.claude/skills/bmad-install-install/
```

> 技能文件在博客仓库的 [`skills/bmad-install/SKILL.md`](https://github.com/qin-zhuopu/qin-zhuopu.github.io/blob/main/skills/bmad-install/SKILL.md)。

### 2. 首次使用：配置安装行为

在任意项目的 Claude 对话中说出触发词：

> "帮我安装 bmad"

首次调用时，skill 会询问以下信息并保存到 `~/.config/bmad/install.yaml`：

| 配置项 | 示例值 | 说明 |
|--------|--------|------|
| `proxy_env` | `http://172.24.0.5:3128` | 代理 URL（无代理留空） |
| `tools` | `claude-code` | 目标工具（claude-code / codex / copilot） |
| `modules` | `core,bmm,bmad-loop,tea,bmb` | 模块列表 |
| `bmad_loop_branch_mode` | `none` | 分支隔离（none / worktree） |

后续所有项目共用，不再询问。

## 使用方法

### 触发词

- 安装场景："安装 bmad" "bmad init" "setup bmad" "bmad 怎么装" "装一下 bmad"
- 重装场景："重装 bmad" "bmad 坏了" "bmad 升级" "更新 bmad"
- 迁移场景："迁移 bmad" "从另一个 bmad 导入"

### 工作流程

触发后 Claude 自动执行：

1. **读取配置**：从 `~/.config/bmad/install.yaml` 加载代理、工具、模块列表
2. **检测现有安装**：发现已有 `_bmad/` / `.claude/skills/` 时询问：覆盖重装 / 增量更新 / 跳过
3. **CSV 污染扫描**：`fgrep -rl TSD-Header` 扫描全部 CSV，发现污染即建议完整重装
4. **备份产物**：`cp -r _bmad-output _bmad-output.<timestamp>.bak`
5. **删除旧安装**：`rm -rf _bmad .claude/skills .bmad-loop _bmad-output ...`
6. **运行安装**：`npx bmad-method install --modules core,bmm,bmad-loop,tea,bmb ...`
7. **Kiro 镜像**（可选）：询问是否同步到 `.kiro/skills/`
8. **bmad-loop init**：注册 hooks、生成 policy.toml
9. **补全 .gitignore**：追加 `.log-claude/`、`.bmad-loop/*`、`_bmad/config.user.toml`
10. **验证**：`bmad-loop validate --project "$(pwd)"`，检查全部 8 项
11. **git commit**：`chore(bmad): 安装/重装 BMAD Method 框架`

### --action update 陷阱

BMAD 安装器的行为是 **replace** 不是 **add**。如果你分两步：

```bash
# 第一步：只装 core + bmm
echo "." | npx bmad-method install -y --modules core,bmm ...

# 第二步：想补充 loop + tea + bmb
echo "." | npx bmad-method install -y --action update --modules bmad-loop,tea,bmb ...
```

第二步会**删除** BMM 模块和对应的 skills！结果是只剩 31 个 skills，缺失 `bmad-dev-auto`、`bmad-sprint-planning` 等核心技能。

**正确做法**（本 skill 自动执行）：

```bash
echo "." | npx bmad-method install -y \
  --modules core,bmm,bmad-loop,tea,bmb \
  --tools claude-code -d \
  --directory . --output-folder _bmad-output
```

一次性声明全部模块。

### TSD-Header CSV 污染

如果之前安装中断或被外部工具污染，CSV 文件会变成加密二进制格式，头部含 `TSD-Header` 标记。这会导致 skill manifest 解析失败、bmad-loop 无法正常工作。

本 skill 自动检测：

```bash
fgrep -rl TSD-Header _bmad/ .claude/skills/ 2>/dev/null
```

一旦发现，强制建议**完整重装**而非增量更新。我们在之前的工作中因此完整重装过一次。

### preflight 验证全绿

`bmad-loop validate` 检查 8 项：

| 检查项 | 常见失败原因 | 修复 |
|--------|-------------|------|
| BMAD config OK | 模块配置缺失 | 重装 |
| policy OK | 未 init | `bmad-loop init` |
| sprint-status OK | 无故事 | 正常（0 stories） |
| git worktree clean | 未提交文件 | `git add && git commit` |
| tmux available | 未安装 | `sudo apt-get install -y tmux` |
| claude found | 未安装 Claude Code | `npm install -g @anthropic-ai/claude-code` |
| hooks registered | 未 init | `bmad-loop init --project $(pwd) --cli claude` |
| upstream skills present | bmm 被删除 | 重装（--modules 写全） |

本 skill 在第 9 步补全 `.gitignore` 来解决 "git worktree clean" 问题。

## 安装产物

成功安装后项目目录结构：

```
project-root/
├── .claude/
│   ├── skills/              # 64 skills
│   └── settings.json        # hooks 注册（bmad-loop init 生成）
├── .kiro/skills/            # Kiro IDE 镜像（可选）
├── .bmad-loop/
│   ├── bmad_loop_hook.py    # 编排器脚本
│   ├── policy.toml          # 编排策略（gitignored）
│   ├── runs/                # 运行记录（gitignored）
│   └── cache/               # 缓存（gitignored）
├── _bmad/
│   ├── config.toml          # 模块配置
│   ├── core/                # Core 模块
│   ├── bmm/                 # BMM 模块
│   ├── bmad-loop/           # Loop 模块
│   ├── bmb/                 # Builder 模块
│   ├── tea/                 # Test Architect 模块
│   └── _config/
│       ├── bmad-help.csv
│       ├── files-manifest.csv
│       └── skill-manifest.csv
├── _bmad-output/
│   ├── planning-artifacts/
│   ├── implementation-artifacts/
│   └── test-artifacts/
└── .gitignore               # 已追加 BMAD 相关条目
```

## 参考

- [bmad Skill 源码](https://github.com/qin-zhuopu/qin-zhuopu.github.io/blob/main/skills/bmad-install/SKILL.md)
- [BMAD Method GitHub](https://github.com/bmad-code-org/BMAD-METHOD/)
- [BMAD Loop Repository](https://github.com/bmad-code-org/bmad-loop)
- [Claude Code 技能文档](https://docs.anthropic.com/en/docs/claude-code/skills)
