# CLAUDE.md

本仓库是 Jekyll + GitHub Pages（Minima 主题）个人博客。日常命令见 `README.md`。

## 网络：访问 GitHub / 被墙站点走代理

本机直连 `github.com` 等域名会超时。访问 GitHub（git push、API、抓 commit SHA、跑
`scripts/check_links.py` 查外链等）时，请走代理，地址为 `172.24.0.5:3128`（HTTP 代理）。

- git：`git -c http.proxy=172.24.0.5:3128 push`，或先 `git config --global http.proxy 172.24.0.5:3128`
- curl：`curl --proxy 172.24.0.5:3128 ...`
- 死链检查脚本：`python scripts/check_links.py --proxy 172.24.0.5:3128`

## 死链检查

`scripts/check_links.py` 校验站内链接（按 `_config.yml` 的 permalink
`/:year/:month/:day/:title/` 反查 `_posts/`）和外链。常用：

```bash
python scripts/check_links.py --no-net                          # 只查站内，秒出
python scripts/check_links.py --proxy 172.24.0.5:3128            # 含外链，走代理
python scripts/check_links.py --skip-host github.com             # 跳过指定域名
```

注意：代理地址 `172.24.0.5:3128` 是 HTTP 代理端口，不是网页，不要当成链接校验。
脚本默认会跳过 `localhost` / `127.0.0.1`；脚本对私有 IP 段的外链目前不会自动跳过，
跑全量检查时若把代理地址写成 `http://172.24.0.5:3128` 会被误报为 HTTP 400，
所以上面统一用不带 `http://` 前缀的写法。

