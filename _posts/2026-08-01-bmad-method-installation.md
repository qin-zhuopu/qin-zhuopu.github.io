---
layout: post
title: "BMAD Method 安装记录"
date: 2026-08-01 06:00:00 +0800
categories: [ai, workflow]
tags: [bmad, claude, automation, ai-agents]
---

BMAD（**B**uild **M**ore, **A**rchitect **D**reams）是一个开源的 AI-Native 开发方法论框架，通过模块化 skills 系统扩展 AI assistant 的能力。本文记录在 Linux 开发环境（WSL2）下完整安装 BMAD Core + 扩展模块的过程。

## 环境信息

- **OS**: Linux 6.6.87.2-microsoft-standard-WSL2
- **Shell**: zsh
- **Node.js**: 通过 npx 运行 bmad-method
- **网络**: 需代理访问 GitHub

## 网络代理配置

当前环境访问外部网络需通过代理：

```bash
export http_proxy=http://172.24.0.5:3128
export https_proxy=http://172.24.0.5:3128
export HTTP_PROXY=http://172.24.0.5:3128
export HTTPS_PROXY=http://172.24.0.5:3128
```

> **踩坑**: 首次安装时因未配置代理，连 GitHub 超时卡死 133 秒后失败。`bmad-method install` 不自动读取系统代理，必须在执行前手动 export。

## 安装步骤

### 1. 基础安装（Core + BMM）

```bash
# 交互式安装会卡死在 Installation directory 提示（--yes 未覆盖此 prompt）
# 解决方法：管道输入目录 + -y 自动确认
echo "." | npx bmad-method install -y \
  --tools claude-code \
  -d --directory . --output-folder _bmad-output
```

**安装结果**:
- ✅ BMad Core Module (v6.10.0)
- ✅ BMad Method (v6.10.0)
- ✅ 46 skills → `.claude/skills/`

### 2. 扩展模块安装

用 `--action update` 补充安装 Loop、Test Architect、Builder。注意模块代码：

| 模块 | 正确代码 | 错误代码 |
|------|---------|---------|
| BMAD Loop | `bmad-loop` | `bml` ❌ |
| Test Architect | `tea` | `bmt` ❌ |
| Builder | `bmb` | — |

```bash
export http_proxy=http://172.24.0.5:3128
export https_proxy=http://172.24.0.5:3128
echo "." | npx bmad-method install -y \
  --action update \
  --modules bmad-loop,tea,bmb \
  --tools claude-code -d \
  --directory . --output-folder _bmad-output
```

**安装结果**:
- ✅ BMAD Loop Skills (v0.9.0)
- ✅ Test Architect (v1.19.1)
- ✅ BMad Builder (v2.1.0)

### 3. BMAD Loop Orchestrator 初始化

Loop 需要独立的 Python orchestrator 工具驱动循环，从 Git 安装：

```bash
# 安装 uv（BMAD 推荐的 Python 包管理器）
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

# 安装 bmad-loop 编排器（含 TUI 依赖）
uv tool install "bmad-loop[tui] @ git+https://github.com/bmad-code-org/bmad-loop.git"

# 项目初始化（注册 hooks + 安装 bundled skills + 生成 policy）
bmad-loop init --project "/home/dev/repos/jc" --cli claude

# 升级时刷新 bundled skills
bmad-loop init --project "/home/dev/repos/jc" --cli claude --force-skills

# Preflight 验证
bmad-loop validate --project "/home/dev/repos/jc"
```

**preflight 修复过程**:

| 问题 | 原因 | 修复 |
|------|------|------|
| `tmux unavailable` | tmux 未安装 | `sudo apt-get install -y tmux` |
| `git worktree not clean` | 有未提交改动 | `git add ... && git commit` |
| `bmad-dev-auto not found` | bmm 模块重装前缺失 | `--action update --modules bmm` 重装补全 |

### 4. 安装产物结构

```
/home/dev/repos/jc/
├── .bmad-loop/
│   ├── bmad_loop_hook.py      # claude hooks
│   └── policy.toml            # 编排策略 (per-epic, claude adapter)
├── .claude/skills/            # 46 skills ✓
│   ├── bmad-dev-auto          # dev primitive (bmm)
│   ├── bmad-loop-resolve      # loop escalation
│   ├── bmad-loop-sweep        # deferred-work triage
│   ├── bmad-agent-builder     # builder
│   ├── bmad-testarch-*        # test architect (8 skills)
│   └── ... (core + bmm skills)
├── _bmad/
│   ├── config.toml            # 模块配置
│   ├── config.user.toml       # 用户个人设置
│   ├── core/                  # core module config
│   ├── bmm/                   # bmm module config
│   ├── bmad-loop/             # loop module config
│   ├── bmb/                   # builder module config
│   ├── tea/                   # test architect config
│   └── _config/bmad-help.csv  # skills 目录
└── _bmad-output/              # 产物输出目录
    ├── planning-artifacts/
    └── implementation-artifacts/
```

## 可用 Skills 一览

| 模块 | 数量 | 代表 Skills |
|------|------|------------|
| **Core** | 12 | `bmad-forge-idea`, `bmad-spec`, `bmad-brainstorming`, `bmad-help` |
| **BMM** | 23 | `bmad-dev-auto`, `bmad-sprint-planning`, `bmad-code-review`, `bmad-create-story` |
| **Loop** | 3 | `bmad-loop-setup`, `bmad-loop-resolve`, `bmad-loop-sweep` |
| **Builder** | 5 | `bmad-agent-builder`, `bmad-module-builder`, `bmad-workflow-builder` |
| **Test Architect** | 8 | `bmad-tea`, `bmad-testarch-test-design`, `bmad-testarch-automate` |
| **合计** | **46** | |

## 关键命令速查

```bash
# 启动 BMAD 开发循环
bmad-loop run

# TUI 监控面板
bmad-loop tui

# 状态验证
bmad-loop validate --project "/home/dev/repos/jc"

# 安装/升级 bmad-loop orchestrator
uv tool upgrade bmad-loop --reinstall

# 升级全部模块 config + skills
/bmad-loop-setup upgrade
```

## 参考

- [BMAD Method GitHub](https://github.com/bmad-code-org/BMAD-METHOD/)
- [uv 文档](https://docs.astral.sh/uv/)
- [BMAD Loop Repository](https://github.com/bmad-code-org/bmad-loop)
