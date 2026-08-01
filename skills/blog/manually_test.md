# blog 手动测试

## 测试目标
验证 skill 能否正确：
1. 分析对话内容提取踩坑要点
2. 正确脱敏（去掉项目名、路径、IP、token）
3. 生成符合 Jekyll 格式的文章
4. 输出到本地文件而非直接调 gh

## 测试方法

用以下 **Prompt** 触发 skill（复制粘贴到 Claude 对话）：

```
刚才 debug 的过程记下来发博客。
```

## 测试用的 Conversation 上下文

Claude 在处理下面的请求时，可以基于这段上下文来模拟分析。

```
用户: 我的项目报错了，帮忙看看
Claude: 什么报错？
用户: 我跑 npx bmad-method install 的时候超时了，连了 133 秒然后失败
Claude: 你的网络环境是怎样的？
用户: 我在公司内网，出口走 172.24.0.5:3128 代理
Claude: 试试先 export 代理再运行
用户: 可以了！加了代理就装上了
Claude: 具体命令？
用户: export http_proxy=http://172.24.0.5:3128 && npx bmad-method install -y ...
Claude: 用的是 --modules core,bmm,bmad-loop,tea,bmb
Claude: 我们这是 codepilot-web 项目，NestJS + Vite React
Claude: 装完后 bmad-loop validate 有个问题，_bmad/core/module-help.csv 这些文件被加密了，头有 TSD-Header
Claude: 所以要重装 bmad
Claude: 然后 bmad dev auto 整夜都在跑
```

## 预期输出

不调用 `gh` 克隆，而是把生成的文章写入 **当前工作目录下的 `output.md`**。

文章内容应包含：
- 标题类似 `npx 安装超时与代理配置踩坑`（不含 codepilot-web）
- 脱敏后的代理地址如 `192.0.2.x:3128`
- 不提及 BMAD 具体项目名
- 不提及个人用户名
- 保留 `echo "." | npx bmad-method install` 这类通用命令

## 通过标准

- [ ] 标题不含项目名和个人信息
- [ ] IP 地址被替换为占位符
- [ ] 路径被泛化（如 `project-root/`）
- [ ] 文章结构完整（问题/环境/过程/根因/方案/速查）
- [ ] 写入 `output.md` 而非直接 `gh clone`
- [ ] tags 正确提取（如 `proxy`, `npm`, `timeout`）
