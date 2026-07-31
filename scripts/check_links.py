#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检查 Jekyll 博客里的死链接。

覆盖两类链接：
  1. 站内链接（markdown 里以 / 开头的 href，以及代码块里的相对路径）
     -> 根据 _config.yml 的 permalink 规则 /:year/:month/:day/:title/
        把 /YYYY/MM/DD/<slug>(.html|/) 反查回 _posts/ 里的源文件，本地即可判定。
  2. 外链（http(s)://）
     -> 发 HEAD 请求，失败时回退 GET；超时/4xx/5xx 视为死链并打印状态码。

用法：
  python scripts/check_links.py            # 默认检查仓库根目录
  python scripts/check_links.py --no-net   # 只检查站内链接，不发网络请求
  python scripts/check_links.py --root path/to/repo
  python scripts/check_links.py --proxy http://localhost:8080   # 走代理查外链

  也可以用环境变量：
    HTTP_PROXY / HTTPS_PROXY = http://localhost:8080
    LINK_CHECK_TIMEOUT = 单请求超时秒数（默认 15）

注意：
  - 跳过明显是「示例/占位」的 URL，如 localhost、127.0.0.1、example.com、
    代码里的 curl 示例参数等。这些不是文章里要真的点开的链接。
  - 站内链接用 .html 后缀而 permalink 是目录形式，GitHub Pages 两者都能访问，
    脚本会把它当作「可达」，但在 NOTE 里单独提示这种风格不一致。
"""

import argparse
import http.client
import os
import re
import socket
import ssl
import sys
import time
import urllib.parse
import urllib.request

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

DEFAULT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 扫描这些目录下的 .md 文件
SCAN_DIRS = ["", "_posts"]

# 站内 URL 中「明显是占位/示例」、不该当作真链接校验的 host/片段
PLACEHOLDER_HOSTS = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "example.com",
    "example.org",
    "example.net",
}

# 外链检查参数
HTTP_TIMEOUT = int(os.environ.get("LINK_CHECK_TIMEOUT", "15"))  # 单个请求超时（秒）
HTTP_RETRIES = 1         # 失败重试次数
RETRY_BACKOFF = 2        # 重试间隔（秒）
USER_AGENT = "Mozilla/5.0 (compatible; link-checker/1.0)"
PROXY = None             # 可由 --proxy 覆盖

# ---------------------------------------------------------------------------
# 链接抽取
# ---------------------------------------------------------------------------

# Markdown 链接 [text](url) —— 只抓不跨行的，正则里 url 不含空白和 )
MD_LINK_RE = re.compile(r"\[(?:[^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")

# 裸 http(s) URL（含代码块里出现的，也要顺带看看，但排除一些占位场景）
BARE_URL_RE = re.compile(r"https?://[^\s)\"'`<>]+", re.IGNORECASE)


def extract_links(text):
    """从一段 markdown 文本里抽出 (kind, url) 列表。kind ∈ {'md', 'bare'}."""
    found = []

    # 先抓 markdown 链接，并记下它们用过的 URL 区间，避免裸 URL 重复抓
    md_urls = set()
    for m in MD_LINK_RE.finditer(text):
        url = m.group(1).strip()
        if url:
            found.append(("md", url))
            md_urls.add(url)

    for m in BARE_URL_RE.finditer(text):
        url = m.group(0).rstrip(".,;:)]}\"'`")
        if url and url not in md_urls:
            found.append(("bare", url))

    return found


# ---------------------------------------------------------------------------
# 站内链接校验
# ---------------------------------------------------------------------------

# 文件名 YYYY-MM-DD-title.md -> (year, month, day, slug)
POST_FILE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-(.+)\.md$")

# 站内链接里的日期+slug：/YYYY/MM/DD/<slug>(.html|/)
# slug 里允许字母数字和连字符；遇到 .html 或结尾 / 截断
INTERNAL_PATH_RE = re.compile(r"^/(\d{4})/(\d{2})/(\d{2})/([A-Za-z0-9._\-]+?)(?:\.html|/)?$")


def build_post_index(posts_dir):
    """返回 dict: (year, month, day, slug) -> filepath"""
    index = {}
    if not os.path.isdir(posts_dir):
        return index
    for name in os.listdir(posts_dir):
        m = POST_FILE_RE.match(name)
        if not m:
            continue
        y, mo, d, slug = m.group(1), m.group(2), m.group(3), m.group(4)
        index[(y, mo, d, slug)] = os.path.join(posts_dir, name)
    return index


def check_internal(url, post_index, root):
    """
    返回 (ok: bool, detail: str)。
    对站内 /YYYY/MM/DD/<slug>(.html|/) 形式反查 _posts 源文件；
    其它站内路径（如 /about/、/categories/）按根目录下同名 md 判断。
    """
    parsed = urllib.parse.urlparse(url)
    path = parsed.path

    m = INTERNAL_PATH_RE.match(path)
    if m:
        key = (m.group(1), m.group(2), m.group(3), m.group(4))
        fp = post_index.get(key)
        if fp and os.path.isfile(fp):
            return True, "对应文章存在"
        return False, "找不到对应的 _posts 源文件"

    # 其它站内路径：试 /<name>/ 或 /<name>.html -> root/<name>.md
    cleaned = path.strip("/").rstrip("/")
    if cleaned.endswith(".html"):
        cleaned = cleaned[: -len(".html")]
    if not cleaned:
        return False, "空站内路径"
    candidate = os.path.join(root, cleaned + ".md")
    if os.path.isfile(candidate):
        return True, "对应页面存在"
    return False, "根目录下没有 %s.md" % cleaned


# ---------------------------------------------------------------------------
# 外链校验
# ---------------------------------------------------------------------------


def is_placeholder_external(url):
    """判断外链是不是「示例/占位/内网」链接，应跳过。"""
    try:
        host = urllib.parse.urlparse(url).hostname or ""
    except ValueError:
        return True
    host = host.lower()
    if host in PLACEHOLDER_HOSTS:
        return True
    # 内网 / 私有 IP 段（含本机代理端口），不是公网可校验的网页
    if (host.startswith("127.") or host.startswith("10.") or host.startswith("192.168.")
            or host.startswith("172.") or host.startswith("169.254.") or host.endswith(".local")):
        return True
    # 形如 <entity_id>、xxx 这种占位片段
    if "<" in url or ">" in url or "{" in url:
        return True
    return False


def fetch_status(url):
    """
    发请求拿 HTTP 状态码。返回 (status_or_None, error_str)。
    status 为 None 表示请求本身失败（DNS/超时/连接拒绝等）。
    """
    # 拆出 host/port 选对 scheme
    parsed = urllib.parse.urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        return None, "不支持的协议 %s" % scheme

    def do_request(method):
        req = urllib.request.Request(url, method=method, headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
        })
        # https 关掉证书强校验，避免老根证书环境误报
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        # 代理
        if PROXY:
            proxy_handler = urllib.request.ProxyHandler({
                "http": PROXY,
                "https": PROXY,
            })
            opener = urllib.request.build_opener(proxy_handler, urllib.request.HTTPSHandler(context=ctx))
        else:
            opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
        try:
            with opener.open(req, timeout=HTTP_TIMEOUT) as resp:
                return resp.status, None
        except urllib.error.HTTPError as e:
            # HEAD 不被支持时常见 405/501，回退到 GET
            return e.code, None
        except (urllib.error.URLError, socket.timeout, http.client.HTTPException,
                ConnectionError, ssl.SSLError, ValueError) as e:
            return None, "%s: %s" % (type(e).__name__, e)

    # 先 HEAD，再按需 GET
    status, err = do_request("HEAD")
    if status is None or status in (405, 403, 501, 404):
        status2, err2 = do_request("GET")
        if status2 is not None:
            return status2, None
        # GET 也失败：如果 HEAD 拿到了非 None 状态（如 403），保留它
        if status is not None:
            return status, None
        return None, err2 or err
    return status, err


def check_external(url):
    """返回 (ok: bool, detail: str)。带重试。"""
    last_err = None
    for attempt in range(HTTP_RETRIES + 1):
        status, err = fetch_status(url)
        if status is not None and 200 <= status < 400:
            return True, "HTTP %d" % status
        if status is not None:
            last_err = "HTTP %d" % status
        else:
            last_err = err or "请求失败"
        if attempt < HTTP_RETRIES:
            time.sleep(RETRY_BACKOFF)
    return False, last_err


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def iter_markdown_files(root):
    seen = set()
    for sub in SCAN_DIRS:
        d = os.path.join(root, sub) if sub else root
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if not name.endswith(".md"):
                continue
            fp = os.path.join(d, name)
            if fp in seen:
                continue
            # 跳过被 exclude 的文件（README 等）
            if name in ("README.md",):
                continue
            seen.add(fp)
            yield fp


def main():
    ap = argparse.ArgumentParser(description="检查 Jekyll 博客死链接")
    ap.add_argument("--root", default=DEFAULT_ROOT, help="仓库根目录")
    ap.add_argument("--no-net", action="store_true", help="不检查外链，只校验站内链接")
    ap.add_argument("--proxy", default=None,
                    help="外链请求走指定代理，如 http://localhost:8080")
    ap.add_argument("--skip-host", action="append", default=[],
                    help="跳过指定 host 的外链检查（可多次指定），"
                         "如 --skip-host github.com 适合直连被墙的环境")
    args = ap.parse_args()

    if args.proxy:
        global PROXY
        PROXY = args.proxy

    root = os.path.abspath(args.root)
    posts_dir = os.path.join(root, "_posts")
    post_index = build_post_index(posts_dir)

    print("=" * 70)
    print("链接检查  root=%s" % root)
    print("已索引 %d 篇 _posts 文章" % len(post_index))
    print("=" * 70)

    dead = []          # (file, line, url, kind, reason)  真正的坏链
    notes = []         # 风格/可疑但不一定是坏链的提示
    total_links = 0
    checked_external = 0
    skipped_external = 0

    for fp in iter_markdown_files(root):
        rel = os.path.relpath(fp, root)
        with open(fp, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # 行号映射：逐行抽链接，方便定位
        for lineno, line in enumerate(lines, start=1):
            for kind, url in extract_links(line):
                total_links += 1
                lower = url.lower()

                # --- 跳过 Jekyll 模板变量 / 邮箱 / 锚点 ---
                if url.startswith("{{") or url.startswith("{%"):
                    continue
                if url.startswith("mailto:"):
                    continue
                if url.startswith("#"):
                    continue

                # --- 站内绝对路径 ---
                if url.startswith("/"):
                    ok, detail = check_internal(url, post_index, root)
                    if not ok:
                        dead.append((rel, lineno, url, "internal", detail))
                    continue

                # --- 外链 ---
                if lower.startswith("http://") or lower.startswith("https://"):
                    if is_placeholder_external(url):
                        skipped_external += 1
                        continue
                    host = (urllib.parse.urlparse(url).hostname or "").lower()
                    if any(host == h or host.endswith("." + h) for h in args.skip_host):
                        skipped_external += 1
                        continue
                    if args.no_net:
                        continue
                    ok, detail = check_external(url)
                    checked_external += 1
                    if not ok:
                        dead.append((rel, lineno, url, "external", detail))
                    continue

                # --- 相对路径（仓库内文件引用）---
                if not url.startswith(("http", "/", "#", "mailto:")):
                    target = os.path.normpath(os.path.join(os.path.dirname(fp), url.split("#")[0]))
                    if target and not os.path.exists(target):
                        # 代码里常出现形如 ~/bin/gh、gh.zip 这种不是真链接的，宽松提示
                        notes.append((rel, lineno, url, "relative", "本地文件不存在（可能是代码示例，未必是链接）"))

    # --- 输出 ---
    print()
    print("链接总数：%d" % total_links)
    print("外链已检查：%d，跳过占位/示例：%d" % (checked_external, skipped_external))
    print()

    if notes:
        print("---- 提示（不一定是死链）----")
        for rel, lineno, url, kind, reason in notes:
            print("  [%s:%d] %s  (%s)" % (rel, lineno, url, reason))
        print()

    if dead:
        print("==== 发现 %d 个死链 ====" % len(dead))
        for rel, lineno, url, kind, reason in dead:
            print("  [%s:%d] (%s) %s  -> %s" % (rel, lineno, kind, url, reason))
        print()
        print("❌ 共 %d 个死链" % len(dead))
        sys.exit(1)
    else:
        print("✅ 没有发现死链")
        sys.exit(0)


if __name__ == "__main__":
    main()
