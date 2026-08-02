---
layout: post
title: "Qwen LoRA 微调资源调研 + 国内镜像下载被墙资源实战"
date: 2026-08-03 10:00:00 +0800
categories: [llm, finetuning]
tags: [qwen, lora, llama-factory, unsloth, huggingface, hf-mirror, modelscope, qlora, sft]
---

调研 Qwen 系列模型的 LoRA 微调生态时，需要从 HuggingFace 下载 GB 级数据集。本文整理了完整的资源清单（含可复现项目）和一套在墙内环境下稳定下载大文件的实战方案。

## 问题现象

在 macOS 上调研千问（Qwen）模型 LoRA 微调方案，需要做三件事：

1. 找到靠谱的微调框架、数据集、评测基准
2. 从 HuggingFace 下载 GB 级数据集
3. 验证找到的项目真的"可复现"——既有训练集，又有测试集和评测分数

期间遇到三个具体障碍：

- **HuggingFace 在墙内访问不了**，必须走代理
- **代理下大文件经常失败**：HF LFS 在 ~80% 时报 `curl: (18) HTTP/2 stream 1 was reset`，且**不支持断点续传**（`-C -` 返回 200 覆盖而不是 206 续传）
- **GitHub clone 下来的 ceval/clue 仓库只有 4 KB 的 LFS 指针**，实际 parquet 文件没拉到

## 环境信息

- OS: macOS (Darwin 20.6.0)
- Shell: zsh (oh-my-zsh)
- 工具: curl、git（无 git-lfs、无 wget）
- 代理: 本地 HTTP 代理 `localhost:8080`（CLAUDE.md 中约定）

## 排查过程

### 第 1 步：用 localhost 代理下 HF 大文件——失败

按惯例用代理直接下：

```bash
curl -x http://localhost:8080 -L -o file.jsonl \
  "https://huggingface.co/datasets/X/Y/resolve/main/file.jsonl"
```

**结果**：3 个 GB 级文件（firefly 1.1 GB、Belle 1.8 GB、medical 1.3 GB）**全部在 ~80% 时报 `HTTP/2 stream reset`**。

### 第 2 步：改 HTTP/1.1 + 断点续传——还是失败

```bash
curl --http1.1 -C - -o file.jsonl "<url>"
```

**结果**：HF LFS 服务器**不支持 Range 请求**——服务器返回 `200 OK`（不是 `206 Partial Content`），curl 把整个文件从头覆盖下载。最后还是被代理 stream reset 截断。

### 第 3 步：换国内镜像源——成功

发现两个国内可用镜像：

**hf-mirror.com**（HuggingFace 官方授权镜像）：

```bash
# 把 huggingface.co 换成 hf-mirror.com，绕过代理直连
curl -sL --noproxy '*' \
  "https://hf-mirror.com/datasets/X/Y/resolve/main/file.jsonl" \
  -o file.jsonl
```

实测速度 **4.7 MB/s**（比代理走 HF 美国节点快 3 倍），且**支持 HTTP 206 Range 续传**——即使中途断了也能恢复。

**ModelScope 魔搭社区**（阿里）：

```bash
curl -sL --noproxy '*' \
  "https://www.modelscope.cn/api/v1/datasets/AI-ModelScope/firefly-train-1.1M/repo?Revision=master&FilePath=firefly-train-1.1M.jsonl"
```

直链会 302 重定向到 `cdn-lfs-cn-1.modelscope.cn`（国内 CDN），速度 **3.5 MB/s**。

### 第 4 步：处理 LFS 指针问题

之前 `git clone` 下来的 ceval/clue 评测集，parquet 文件只有 4 KB——是 LFS 指针文本，内容是：

```
version https://git-lfs.github.com/spec/v1
oid sha256:37e61cdf5bf63420fe45dfe5a30a306cdd165a485f7dda38b6b4c617ca757eab
size 120915
```

**根因**：系统没装 git-lfs，clone 时不会自动拉 LFS 文件。

**解决方案**：绕开 git-lfs，直接通过 hf-mirror 的 `/resolve/<branch>/<file>` 路径批量 HTTP 下载真实 parquet：

```bash
# 拿到所有 parquet 文件名（HF API 通过 mirror 访问）
curl -s --noproxy '*' \
  "https://hf-mirror.com/api/datasets/ceval/ceval-exam" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); [print(s['rfilename']) for s in d['siblings'] if s['rfilename'].endswith('.parquet')]"

# 并行下载
while IFS= read -r fp; do
  curl -sL --noproxy '*' -o "$fp" \
    "https://hf-mirror.com/datasets/ceval/ceval-exam/resolve/main/$fp" &
  # 控制并发 8
  while [ $(jobs -r | wc -l) -ge 8 ]; do sleep 0.2; done
done < files.txt
wait
```

156 个 ceval parquet + 35 个 clue parquet，全部完整下载。

## 根因分析

1. **HTTP/2 stream reset 是代理本身的稳定性问题**——HTTP/2 多路复用在某些代理实现下，长连接被服务器/中间设备主动 reset。改 HTTP/1.1 治标不治本。

2. **HF LFS 服务器不支持 Range**：HF 用了 XetHub 的 xet-cdn 做内容分发，签名 URL 设计上不支持部分请求。这意味着**用代理下大文件基本上一次失败就重头再来**。

3. **国内镜像（hf-mirror）的真正价值**：
   - 不是绕过墙（HF 官方在墙内访问不了）
   - 是绕过 LFS 签名机制，**直接代理到能 Range 的存储**
   - 不走 HTTP 代理 = 不受 stream reset 影响

4. **shell 全局代理陷阱**：oh-my-zsh 的 `shell-proxy` 插件可能在 `~/.zshrc` 中预置了全局 `https_proxy`。每个新的 bash session 都会继承这个变量。在用国内镜像时**必须显式 `unset` 或加 `--noproxy '*'`**。

## 最终方案：被墙资源下载优先级

按以下顺序处理，命中率高且稳定：

### 1. 优先找国内源/镜像

| 资源类型 | 国内镜像 |
|---|---|
| HuggingFace 数据集/模型 | `hf-mirror.com` 替换 `huggingface.co` |
| 中文模型权重/数据集 | [ModelScope 魔搭](https://www.modelscope.cn) |
| Python 包 | `pip install -i https://pypi.tuna.tsinghua.edu.cn/simple <pkg>` |
| Docker 镜像 | 阿里云、网易等国内 registry |

### 2. 实在找不到国内源才走代理

- 大文件必加 `--http1.1` 减小 stream reset 概率
- HF LFS 不支持续传，**只能赌一次性能下完**

### 3. GitHub 源码（小仓库）直接走代理

- **不要用 Gitee 镜像**——理由：保真实性、防投毒、避免镜像过期
- GitHub 仓库通常很小（几十 MB 内），代理足够稳定

## Qwen LoRA 微调资源完整清单

### 微调框架

| 框架 | Stars | 特点 |
|---|---|---|
| **hiyouga/LLaMA-Factory** | 73k+ | yaml 配置驱动，文档最全，内置 MMLU/C-Eval/CMMLU 评测 |
| **unslothai/unsloth** | 69k+ | LoRA 加速器，2-5x 训练速度、省 70% 显存，Mac 可跑 |
| **yangjianxin1/Firefly** | 6.6k | 中文 SFT 工具，支持 Qwen2.5，公开 C-Eval 评分 |
| **shibing624/MedicalGPT** | - | 医疗领域全流程（SFT+DPO+RLHF）|

### 数据集（按是否带 train/val/test 三分分类）

**带完整三分的（直接可用）**：

| 数据集 | 大小 | 用途 |
|---|---|---|
| `shibing624/medical` | 1.4 GB | 医疗 SFT，原生 train/val/test |
| `ceval/ceval-exam` | 4 MB | 52 学科评测基准，dev/val/test |
| `clue/clue` | 90 MB | 中文 NLU 多任务评测 |

**只有训练集的（需自己切分）**：

| 数据集 | 大小 | 说明 |
|---|---|---|
| `YeungNLP/firefly-train-1.1M` | 1.1 GB | 165 万条中文指令，Firefly 项目用 |
| `BelleGroup/train_2M_CN` | 1.8 GB | Belle 2M 中文指令 |
| `m-a-p/COIG-CQIA` | 142 MB | 高质量中文指令集 |
| `silk-road/alpaca-data-gpt4-chinese` | 75 MB | GPT4 蒸馏的中文 Alpaca |

### 可复现的端到端项目（重点推荐）

**官方 + 内置评测（最稳）**：

1. **LLaMA-Factory `tests/e2e/` 和 `tests/eval/`** — 官方 CI 自动化测试，每次 release 都跑
2. **Unsloth 官方 Notebooks** — `docs.unsloth.ai/get-started/unsloth-notebooks`，每个 notebook 自带数据+训练+评测
3. **LLaMA-Factory `examples/train_lora/qwen3_lora_sft.yaml`** — 标准 LoRA SFT 配置

**社区 Reproducible 项目**：

| 项目 | 关键特性 |
|---|---|
| `tu-rt/post-training` | Qwen2.5 QLoRA + C-Eval + hold-out 评测 |
| `ArupKantiDas/qwen3-4b-resume-screener-qlora-code` | 诚实的 base-vs-adapter 对比 |
| `aump-JUNJUN/math-cot-pipeline` | 数学 CoT + 双轨评测 |
| `Lawson-Darrow/Text-to-SQL-Finetune` | Qwen2.5-Coder + execution-accuracy |
| `Nikhilsh10/MediTune` | Mistral-7B 医疗 QLoRA 端到端 |

## 关键命令速查

```bash
# 0. 用国内镜像前先 unset 全局代理（防止 shell-proxy 插件干扰）
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy

# 1. hf-mirror 下载（推荐，绕过墙且支持断点续传）
curl -sL --noproxy '*' -C - \
  -o file.jsonl \
  "https://hf-mirror.com/datasets/<ns>/<name>/resolve/main/<file>"

# 2. ModelScope CDN 下载（备选）
curl -sL --noproxy '*' \
  "https://www.modelscope.cn/api/v1/datasets/<ns>/<name>/repo?Revision=master&FilePath=<file>" \
  -o file

# 3. 代理下 GitHub 源码（小仓库直接走代理，保真实性）
git -c http.proxy=http://localhost:8080 clone --depth=1 https://github.com/<owner>/<repo>.git

# 4. 验证大文件完整性（避免代理截断）
stat -f "%z" file.jsonl           # 字节数
tail -c 100 file.jsonl            # 末尾应为正常字符，不是 UTF-8 中间字节
tail -1 file.jsonl | python3 -c "import json,sys; json.loads(sys.stdin.read()); print('OK')"

# 5. 并行批量下载 parquet
while IFS= read -r fp; do
  curl -sL --noproxy '*' -o "$fp" \
    "https://hf-mirror.com/datasets/<ns>/<name>/resolve/main/$fp" &
  while [ $(jobs -r | wc -l) -ge 8 ]; do sleep 0.2; done
done < files.txt
wait
```

## 总结

- **墙内下载 HF 大文件首选 `hf-mirror.com` + 绕过代理直连**，速度 4.7 MB/s 且支持续传，比走代理稳定 3 倍
- **GitHub 源码继续走代理**，小仓库代理足够稳，且保真实性
- **社区数据集只给 train 是常态**，标准做法是：外部指令数据训练 + 自己切 1-2% 验证 + 学术基准（C-Eval/CMMLU/CLUE）做最终评测
- **可复现项目验证清单**：README 是否提到 train/val/test 切分、是否给评测脚本、是否公开 base-vs-adapter 分数对比

## 参考

- [LLaMA-Factory](https://github.com/hiyouga/LLaMA-Factory)
- [Unsloth](https://github.com/unslothai/unsloth)
- [hf-mirror.com](https://hf-mirror.com)
- [ModelScope 魔搭社区](https://www.modelscope.cn)
- [C-Eval 评测基准](https://cevalbenchmark.com)
- [Firefly 中文大模型训练工具](https://github.com/yangjianxin1/Firefly)
