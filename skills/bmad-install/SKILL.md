---
name: bmad-install
description: >
  在当前项目中安装、重装或更新 BMAD Method AI 开发框架（core + bmm + loop + tea + bmb）。
  触发词："安装 bmad" "重装 bmad" "setup bmad" "bmad update" "bmad init"
  "bmad 初始化" "更新 bmad" "bmad 模块" "bmad 技能" "bmad loop" "bmad builder"
  "bmad 怎么装" "装一下 bmad" "bmad 坏了重装" "bmad 迁移" "bmad 升级"。
  在项目目录中实现 BMAD 自动化开发循环的初始化与验证。
---

# BMAD Method 安装技能

在当前项目目录中安装、重装或更新 BMAD Method AI 开发方法论框架，含 Core、BMM、Loop、Test Architect、Builder 全部模块。

## 特点

- **一键安装**：一条命令安装全部模块（避免 `--action update` 陷阱）
- **移除检测**：检测到已安装时询问是覆盖重装还是跳过
- **代理自动配置**：读取系统环境变量中的代理，自动注入安装命令
- **Skip 污染检测**：自动扫描 CSV 文件是否被 `TSD-Header` 污染，发现即触发完整重装
- **bmad-loop 初始化**：安装完成后自动运行 `bmad-loop init` 注册 hooks，通过验证

## 个人配置

BMAD 安装行为存于用户主目录，与项目无关：

```
~/.config/bmad/install.yaml      # 创建后不再询问
```

**首次调用**若文件不存在，询问并创建：
- `proxy_env` — 代理 URL（例：`http://your-proxy:port`，空则不设代理。若项目根有 `.env.local` 里的 `HTTP_PROXY`，可读它，避免硬编码）
- `tools` — 目标工具（默认 `claude-code`，可选 `codex`、`copilot`）
- `modules` — 模块列表（默认 `core,bmm,bmad-loop,tea,bmb`）
- `bmad_loop_branch_mode` — 分支隔离模式（`none` 或 `worktree`，默认 `none`）

## 工作流程

### 1. 读取/创建配置

检查 `~/.config/bmad/install.yaml` 是否存在。不存在时：

1. 询问 `proxy_env`（可选，默认空）
2. 询问 `tools`（默认 `claude-code`）
3. 询问 `modules`（默认 `core,bmm,bmad-loop,tea,bmb`）
4. 询问 `bmad_loop_branch_mode`（默认 `none`）
5. 写入 YAML，后续不再询问

读取后导出相应环境变量。

### 2. 检查现有安装

检查以下目录/文件是否存在：

```bash
if [ -d "_bmad" ] || [ -d ".claude/skills" ] || [ -d ".bmad-loop" ]; then
  # 已安装，询问用户：
  echo "检测到现有 BMAD 安装。"
  echo "1) 覆盖重装（删除全部后全新安装）"
  echo "2) 增量更新（只更新 skills 和模块配置，保留 _bmad-output/ 产物）"
  echo "3) 跳过"
fi
```

### 3. 污染检测（CSV 完整性检查）

运行以下扫描，若发现 `TSD-Header` 则自动建议重装：

```bash
if fgrep -rl TSD-Header _bmad/ .claude/skills/ 2>/dev/null | head -1; then
  echo "警告：检测到 CSV/脚本文件被加密/污染（TSD-Header），建议完整重装。"
fi
```

### 4. 执行安装

**预处理**：

```bash
# 备份产物
if [ -d "_bmad-output" ]; then
  cp -r _bmad-output _bmad-output.$(date +%s).bak
fi

# 删除旧安装（仅重装模式）
rm -rf _bmad .claude/skills .kiro/skills .bmad-loop _bmad-output .claude/settings.json
```

**基础安装**：

```bash
npx bmad-method install -y \
  --modules "$modules" \
  --tools "$tools" \
  -d --directory . --output-folder _bmad-output
```

**代理配置**（如有）：

```bash
export http_proxy="$proxy_env"
export https_proxy="$proxy_env"
export HTTP_PROXY="$proxy_env"
export HTTPS_PROXY="$proxy_env"
```

**安装结果预期**：
- 5 个模块全部安装
- 64 skills 写入 `.claude/skills/`
- `_bmad/` 配置目录生成
- `_bmad-output/` 产物目录生成

### 5. 可选：Kiro 技能镜像

如果项目同时用 Kiro IDE，询问是否镜像 skills：

```bash
mkdir -p .kiro && cp -r .claude/skills .kiro/skills
```

### 6. bmad-loop 编排器初始化

如果 modules 包含 `bmad-loop`，自动执行：

1. **检查系统依赖**：
   - `uv`：Python 包管理器（未安装则提示 `curl -LsSf https://astral.sh/uv/install.sh | sh`）
   - `tmux`：终端复用器（未安装则提示 `sudo apt-get install -y tmux`）
   - `gh`：GitHub CLI（未安装则提示）

2. **初始化**：
   ```bash
   bmad-loop init --project "$(pwd)" --cli claude
   ```

3. **清理工作区**：
   - 检查 `.gitignore` 是否包含 `.log-claude/`、`.bmad-loop/runs/`、`.bmad-loop/cache/`、`.bmad-loop/policy.toml`
   - 若未包含，追加并提交

4. **验证**：
   ```bash
   bmad-loop validate --project "$(pwd)"
   ```
   验证项包括：
   - BMAD config OK
   - policy OK（gates、adapter）
   - sprint-status OK
   - git worktree clean
   - tmux available
   - bmad-loop hooks registered for claude
   - upstream skills present

### 7. .gitignore 补全

确保 `.gitignore` 包含以下内容（若缺失则追加并提交）：

```
# BMAD 个人配置
_bmad/config.user.toml
_bmad/custom/config.user.toml

# bmad-loop 运行数据
.bmad-loop/runs/
.bmad-loop/cache/
.bmad-loop/policy.toml

# logs
.log-claude/
```

### 8. git commit

如果工作区有变更，询问用户后提交：

```bash
git add -A
git commit -m "chore(bmad): <安装/重装/更新 BMAD Method 框架>"
```

## 约束

- 不自动 push，提交后询问
- 重装前**必须**备份 `_bmad-output/` 目录（避免丢失历史产物）
- `--modules` 必须一次性声明全部模块，**禁止**分两步用 `--action update` 补充
- `bmad-loop init` 后提示用户手动运行一次 `claude` 命令接受 workspace trust
- 遇到 `TSD-Header` 污染的 CSV，强制建议完整重装而非增量更新

## 关键教训

1. **安装器行为是 replace 不是 add**：`--modules core,bmm` 后再 `--action update --modules bmad-loop,tea,bmb` 会导致 BMM 被删除。必须一次性写全。

2. **代理必须手动 export**：`bmad-method install` 不读取系统代理，超时 133 秒后失败。

3. **git worktree clean 是 bmad-loop validate 的先决条件**：未提交的改动会导致验证失败，需要提前 commit。

4. **.log-claude/ 必须加入 .gitignore**：否则 bmad-loop validate 的 "git worktree clean" 会失败。
