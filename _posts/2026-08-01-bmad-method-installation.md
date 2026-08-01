---
layout: post
title: "BMAD Method 在 WSL2 安装记录"
date: 2026-08-01 06:00:00 +0800
categories: [ai, workflow]
tags: [bmad, claude, automation, ai-agents]
---

BMAD（**B**uild **M**ore, **A**rchitect **D**reams）是一个开源的 AI-Native 开发方法论框架，通过模块化 skills 系统扩展 AI assistant 的能力。本文是 Linux 开发环境（WSL2）下的完整安装实录，可作为同类环境的参考。

## 环境信息

- **OS**: Linux 6.6.87.2-microsoft-standard-WSL2
- **Shell**: zsh
- **Node.js**: 通过 npx 运行 bmad-method
- **网络**: 需代理访问 GitHub

## 网络代理配置

当前环境访问外部网络需通过代理。代理地址写在本机一个**不进 git** 的 dotenv 文件里（项目根的 `.env.local`，键名 `HTTP_PROXY`），这样换机器/换网络时只改本地文件、博客和脚本里永远不出现真实 IP：

```bash
# .env.local（自己创建，不进 git；模板见 .env.local.example）
HTTP_PROXY=http://192.0.2.10:3128     # 替换成你的真实代理地址

# 安装 bmad 前先 source 一下，让 npx 能拿到代理
source .env.local
export http_proxy="$HTTP_PROXY" https_proxy="$HTTP_PROXY" \
       HTTP_PROXY="$HTTP_PROXY" HTTPS_PROXY="$HTTP_PROXY"
```

> **踩坑**: 首次安装时因未配置代理，连 GitHub 超时卡死 133 秒后失败。`bmad-method install` 不自动读取系统代理，必须在执行前手动 export。
> **再次踩坑**: 早期版本的博客把代理 IP 直接写进文章里——换网络就失效，还泄露了内网地址。改为 `.env.local` 后这两个问题都解决了。

## 安装步骤

### 1. 安装 uv（Python 包管理器）

BMAD workflows 依赖 Python 脚本，通过 `uv` 运行：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
```

### 2. 一键安装全部模块（core + bmm + loop + tea + bmb）

```bash
echo "." | npx bmad-method install -y \
  --modules core,bmm,bmad-loop,tea,bmb \
  --tools claude-code \
  -d --directory . --output-folder _bmad-output
```

> **注意**: `--modules` 要一次性声明所有需要的模块。如果先装 `core+bmm` 再用 `--action update` 补充扩展模块，会导致 BMM 被意外清除——这是安装器行为，不是 "add" 语义而是 "replace" 语义。

| 模块 | 代码 | 作用 |
|------|------|------|
| Core | `core` | 需求锻造、PRD、规格、头脑风暴等基础技能 |
| BMM | `bmm` | Business Model Manager（开发全流程管理） |
| BMAD Loop | `bmad-loop` | 自动化开发循环、升级决策、待办清扫 |
| Test Architect | `tea` | 测试策略、自动化、ATDD、NFR |
| Builder | `bmb` | Agent/模块/工作流构建器 |

**安装结果**:
- ✅ BMad Core Module (v6.10.0)
- ✅ BMad Method (v6.10.0)
- ✅ BMAD Loop Skills (v0.9.0)
- ✅ Test Architect (v1.19.1)
- ✅ BMad Builder (v2.1.0)
- ✅ 64 skills → `.claude/skills/`

### 3. 初始化 bmad-loop 编排器

安装 BMAD Loop skills 不等于安装 `bmad-loop` Python 编排器。需要单独初始化：

```bash
# 安装 bmad-loop 编排器工具（含 TUI 依赖）
uv tool install "bmad-loop[tui] @ git+https://github.com/bmad-code-org/bmad-loop.git"

# 进入项目目录，初始化 hooks 和 policy
bmad-loop init --project "$(pwd)" --cli claude
```

初始化后项目根目录新增：

```
.bmad-loop/
├── bmad_loop_hook.py   # 编排器 hooks 脚本
└── policy.toml         # 编排策略（gitignored）
.claude/settings.json    # hooks 注册（SessionStart/Stop/SessionEnd/PreCompact）
```

### 4. Preflight 验证

```bash
bmad-loop validate --project "$(pwd)"
```

首次运行可能遇到这些问题：

| 问题 | 原因 | 修复 |
|------|------|------|
| `tmux unavailable` | tmux 未安装 | `sudo apt-get install -y tmux` |
| `git worktree not clean` | 有未提交改动或新增文件 | `git add ... && git commit`，或把日志目录加入 `.gitignore` |
| `bmad-dev-auto not found` | bmm 模块重装前缺失 | 重装 BMAD |
| `bmad-loop hooks not registered` | 未运行 `bmad-loop init` | `bmad-loop init --project "$(pwd)" --cli claude` |

## 安装产物结构

以一个典型 TypeScript/NestJS 项目为例：

```
project-root/
├── .claude/
│   ├── skills/              # 64 skills → Claude Code / 命令调用
│   │   ├── bmad-forge-idea      # core: 需求锻造
│   │   ├── bmad-dev-auto        # bmm: 开发自动化
│   │   ├── bmad-loop-resolve    # loop: 升级决策
│   │   ├── bmad-loop-sweep      # loop: 待办清扫
│   │   ├── bmad-agent-builder   # bmb: Agent 构建
│   │   ├── bmad-module-builder  # bmb: 模块构建
│   │   ├── bmad-workflow-builder # bmb: 工作流构建
│   │   ├── bmad-testarch-*      # tea: 测试架构 (8 skills)
│   │   └── bmad-agent-*         # agents: 7 个角色代理
│   └── settings.json        # hooks 注册（安装器生成）
├── .kiro/
│   └── skills/              # Kiro IDE 技能镜像（可选，与 .claude/skills 同源）
├── .bmad-loop/              # 编排器目录
│   ├── bmad_loop_hook.py
│   ├── policy.toml          # 编排策略
│   ├── runs/                # 运行记录（gitignored）
│   └── cache/               # 缓存（gitignored）
├── _bmad/                   # 模块配置
│   ├── config.toml          # 安装器管理（只读）
│   ├── config.user.toml     # 用户个人设置（gitignored）
│   ├── core/
│   ├── bmm/
│   ├── bmad-loop/
│   ├── bmb/
│   ├── tea/
│   ├── custom/              # 团队自定义配置
│   └── _config/
│       ├── bmad-help.csv    # skills 目录
│       ├── files-manifest.csv
│       └── skill-manifest.csv
└── _bmad-output/            # 产物输出目录
    ├── planning-artifacts/    # 规划产物
    ├── implementation-artifacts/  # 实现产物（epic-* 子目录）
    └── test-artifacts/        # 测试产物（tea 模块）
```

## Agents 配置

`config.toml` 中预定义了 7 个领域代理角色：

| 代理 | 名称 | 模块 | 角色 |
|------|------|------|------|
| 📊 Mary | `bmad-agent-analyst` | bmm | Business Analyst |
| 📚 Paige | `bmad-agent-tech-writer` | bmm | Technical Writer |
| 📋 John | `bmad-agent-pm` | bmm | Product Manager |
| 🎨 Sally | `bmad-agent-ux-designer` | bmm | UX Designer |
| 🏗️ Winston | `bmad-agent-architect` | bmm | System Architect |
| 💻 Amelia | `bmad-agent-dev` | bmm | Senior Software Engineer |
| 🧪 Murat | `bmad-tea` | tea | Test Architect |

## 可用 Skills 一览

| 模块 | 数量 | 代表 Skills |
|------|------|------------|
| **Core** | ~12 | `bmad-forge-idea`, `bmad-spec`, `bmad-brainstorming`, `bmad-help`, `bmad-prd` |
| **BMM** | ~25 | `bmad-dev-auto`, `bmad-sprint-planning`, `bmad-code-review`, `bmad-create-story`, `bmad-ux`, `bmad-retrospective` |
| **Loop** | 3 | `bmad-loop-setup`, `bmad-loop-resolve`, `bmad-loop-sweep` |
| **Builder** | 4 | `bmad-agent-builder`, `bmad-module-builder`, `bmad-workflow-builder`, `bmad-bmb-setup` |
| **Test Architect** | 8 | `bmad-tea`, `bmad-testarch-test-design`, `bmad-testarch-automate`, `bmad-testarch-atdd`, `bmad-testarch-ci` |
| **Agents** | 7 | `bmad-agent-analyst`, `bmad-agent-architect`, `bmad-agent-dev`, ... |
| **合计** | **64** | 见 `.claude/skills/` 完整列表 |

## 关键命令速查

```bash
# 安装/升级 BMAD 全部模块（一次性声明）
echo "." | npx bmad-method install -y \
  --modules core,bmm,bmad-loop,tea,bmb \
  --tools claude-code -d \
  --directory . --output-folder _bmad-output

# 启动 BMAD 自动化开发循环
bmad-loop run

# TUI 监控面板
bmad-loop tui

# 状态验证
bmad-loop validate --project "$(pwd)"

# 升级 bmad-loop orchestrator
uv tool upgrade bmad-loop --reinstall
```

## 参考

- [BMAD Method GitHub](https://github.com/bmad-code-org/BMAD-METHOD/)
- [uv 文档](https://docs.astral.sh/uv/)
- [BMAD Loop Repository](https://github.com/bmad-code-org/bmad-loop)
