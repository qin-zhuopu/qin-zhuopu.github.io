# CLAUDE.md

本仓库是 Jekyll + GitHub Pages（Minima 主题）个人博客。日常命令见 `README.md`。

## 网络：访问 GitHub / 被墙站点走代理

本机直连 `github.com` 等域名会超时。访问 GitHub（git push、API、抓 commit SHA、跑
`scripts/check_links.py` 查外链等）时，请走代理。

**代理地址从项目根的 `.env.local` 读**（dotenv 风格，键为 `HTTP_PROXY`）。
该文件不进 git（已在 `.gitignore`）；模板见 `.env.local.example`。

读不到 `.env.local` 或 `HTTP_PROXY` 为空时，**问用户要代理地址，不要假设、不要硬编码**。

两种调用方式：

```bash
# 方式一：source 后直接用（同一 shell 多条命令时方便）
source .env.local
curl --proxy "$HTTP_PROXY" https://github.com
git -c http.proxy="$HTTP_PROXY" push

# 方式二：单次读取（不想改 shell 环境）
HTTP_PROXY=$(grep -E '^HTTP_PROXY=' .env.local | cut -d= -f2-)
curl --proxy "$HTTP_PROXY" ...
```

## 死链检查

`scripts/check_links.py` 校验站内链接（按 `_config.yml` 的 permalink
`/:year/:month/:day/:title/` 反查 `_posts/`）和外链。常用：

```bash
python scripts/check_links.py --no-net                          # 只查站内，秒出
python scripts/check_links.py --proxy "$HTTP_PROXY"             # 含外链，走代理（先 source .env.local）
python scripts/check_links.py --skip-host github.com            # 跳过指定域名
```

脚本本身不读 `.env.local`——代理地址来源是调用方的事，脚本只接受 `--proxy` 参数。
注意：从 `.env.local` 读到的值是 HTTP 代理端口，不是网页，不要当成链接校验。
脚本默认会跳过 `localhost` / `127.0.0.1`；脚本对私有 IP 段的外链目前不会自动跳过，
跑全量检查时若把代理地址写成 `http://...` 形式可能被误报为 HTTP 400，
所以传给 `--proxy` 时值里如果只含 `host:port`，按原样传即可。

## 博客与技能内容脱敏（总原则）

写进 `_posts/`（博客）或 `skills/`（技能）的内容，**只写方式方法，不写本机私有数据**。
博客要让任何开发者在任何机器上看懂、可复用；技能要能在不同环境之间无障碍迁移。

**禁止直接出现**：本机真实 IP（含内网/代理地址）、Token / 密钥、个人用户名、私有仓 URL、
公司内部域名、本机绝对路径、`.env.local` / `install.yaml` / `blog.yaml` 等**本地配置文件里的真实值**。

**应该写**：从哪里读这些值（如"代理地址从项目根 `.env.local` 的 `HTTP_PROXY` 读"），
以及读写流程；让读者照着在自己机器上配置，而不是看到你的具体值。

详细替换规则（IP → `192.0.2.x` 测试段、token → `[REDACTED]` 等）见
`skills/blog/SKILL.md` 第 3 节"脱敏"。该规则同样适用于技能文件本身和所有 `_posts/` 文章，
不限是否触发 blog 技能。

