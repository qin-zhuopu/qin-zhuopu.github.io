---
layout: post
title: "把 macOS 开机启动项扫进 CMDB：launchd + 登录项 + 脱敏"
date: 2026-08-09 17:30:00 +0800
categories: [技术笔记]
tags: [macos, launchd, cmdb, python, plist]
---

把 macOS 的开机启动项建成 CMDB 实体（StartupItem）。一次扫描覆盖 4 个来源（用户 LaunchAgent / 系统 LaunchAgent / 系统 LaunchDaemon / 系统设置登录项），自动识别厂商，把绝对路径里的用户名换成占位符。一次跑完生成 23 个实体 + 27 条边。

## 问题现象

想看本机都有哪些东西"开机自启"。手工查：

- `~/Library/LaunchAgents/*.plist`
- `/Library/LaunchAgents/*.plist`
- `/Library/LaunchDaemons/*.plist`
- 系统设置 → 通用 → 登录项

四个地方分散，每次翻都费劲。而且 Apple 自带的几百个 `com.apple.*` 是噪音，得过滤掉。

## 环境信息

- macOS（任意版本， Ventura 之后登录项位置有变但 API 兼容）
- Python 3 标准库 `plistlib` + `subprocess`
- `osascript` 跑 AppleScript 拿 GUI 登录项

## 排查过程

### 来源 1-3：plist 文件

```python
import plistlib
from pathlib import Path

def scan_plist(plist_path: Path, domain: str):
    with plist_path.open("rb") as f:
        data = plistlib.load(f)
    label = data.get("Label") or plist_path.stem
    args = data.get("ProgramArguments") or []
    program = args[0] if args else data.get("Program", "")
    return {
        "label": label,
        "domain": domain,
        "plistPath": str(plist_path),
        "program": program,
        "programArgs": args,
        "runAtLoad": bool(data.get("RunAtLoad", False)),
        "keepAlive": bool(data.get("KeepAlive", False))
                    if not isinstance(data.get("KeepAlive"), dict)
                    else True,
        "startInterval": data.get("StartInterval"),
    }
```

### 来源 4：登录项（GUI）

```python
def scan_login_items():
    out = subprocess.run(
        ["osascript", "-e",
         'tell application "System Events" to get the name of every login item'],
        capture_output=True, text=True, timeout=5,
    ).stdout.strip()
    items = []
    for name in out.split(", "):
        name = name.strip()
        if not name:
            continue
        items.append({"label": name, "domain": "login_item", ...})
    return items
```

### 过滤 Apple 自带

```python
if plist.name.startswith("com.apple."):
    continue  # 跳过系统自带
```

### 厂商识别

按 label 前缀正则匹配：

```python
VENDOR_PATTERNS = [
    (r"^com\.google\.",          ("vendor", "Google")),
    (r"^homebrew\.mxcl\.",       ("homebrew", "Homebrew")),
    (r"^org\.virtualbox\.",      ("vendor", "Oracle")),
    (r"^com\.oray\.",            ("vendor", "Oray")),
    (r"^com\.youqu\.todesk",     ("vendor", "ToDesk")),
    # ...
]

def guess_vendor(label):
    for pat, result in VENDOR_PATTERNS:
        if re.search(pat, label):
            return result
    return ("unknown", "")
```

## 根因分析：实体 id 的坑

`label` 里有非 ASCII 字符（"钉钉"）和特殊字符（homebrew 的 `postgresql@15`），直接做 id 会出问题：

- 中文 → 不可读 URL
- `@15` → Cypher 标识符不接受 `@`

**slugify 时维护一张映射表**：

```python
LOGIN_ITEM_SLUG = {
    "钉钉": "dingtalk",
    "StatusBarApp": "status-bar-app",
}

def slugify(s: str) -> str:
    if s in LOGIN_ITEM_SLUG:
        return LOGIN_ITEM_SLUG[s]
    return re.sub(r"[^a-zA-Z0-9._-]", "-", s)
```

加 domain 前缀做最终 id：`startup-{ua|sa|sd|li}-{slug}`。例：

- `com.zhuopu.mihomo` (user agent) → `startup-ua-com.zhuopu.mihomo`
- `钉钉` (login item) → `startup-li-dingtalk`
- `homebrew.mxcl.postgresql@15` → `startup-ua-homebrew.mxcl.postgresql-15`

## 脱敏

**核心原则**：进 git 的文件不能含 `/Users/<真实用户名>/...`。

```python
USER_HOME = str(Path.home())

def redact_path(path: str) -> str:
    if path.startswith(USER_HOME):
        return "<user-home>" + path[len(USER_HOME):]
    return path
```

应用后：

```
program: /Users/alice/bin/mihomo
↓
program: <user-home>/bin/mihomo
```

ontology 里这些占位符在 `properties.yaml#redactionPlaceholders` 都登记了，方便后续人看。

## 状态字段

除了配置层（plist）的字段，还要记录运行时状态：

```python
def is_loaded(label: str) -> bool:
    """launchctl list 看 label 是否加载了。"""
    out = subprocess.run(["launchctl", "list"], capture_output=True, text=True).stdout
    return any(line.split("\t")[-1].strip() == label for line in out.splitlines())

def is_disabled(plist_path: Path, domain: str) -> bool:
    """先看 plist 的 Disabled 键，再看 launchctl print-disabled。"""
    with plist_path.open("rb") as f:
        data = plistlib.load(f)
    if data.get("Disabled") is True:
        return True
    # 进一步看 launchctl
    if domain == "user_agent":
        target = f"gui/{os.getuid()}/{plist_path.stem}"
    elif domain == "system_agent":
        target = f"gui/501/{plist_path.stem}"
    else:
        target = f"system/{plist_path.stem}"
    out = subprocess.run(
        ["launchctl", "print-disabled", target],
        capture_output=True, text=True, timeout=3,
    ).stdout
    return '"disabled" => true' in out
```

## 关系边

每个 StartupItem 至少有一条 `definedIn` 边指向当前主机：

```yaml
edges:
  - relationType: definedIn
    from: startup-ua-com.zhuopu.mihomo
    to: mac-macos
  - relationType: launches        # 已知映射
    from: startup-ua-com.zhuopu.mihomo
    to: mihomo
  - relationType: configuredBy
    from: startup-ua-com.zhuopu.mihomo
    to: proxy-mihomo-plist
```

`launches` 边需要一张手工维护的映射表（label → Service/Software id），因为脚本没办法从 plist 自动判断它启动的是不是已建模的实体。

## 关键命令速查

```bash
# 扫描 + 写 yaml
python3 scripts/scan_startup_items.py

# dry-run 只看
python3 scripts/scan_startup_items.py --dry-run

# 看所有 launchd 单元
launchctl list

# 看 GUI 域禁用情况
launchctl print-disabled "gui/$(id -u)/com.foo"

# 看登录项
osascript -e 'tell application "System Events" to get the name of every login item'
```

## 最终实体样例

```yaml
# entities/startup-items/startup-ua-com.zhuopu.mihomo.yaml
createdAt: '2026-08-09'
updatedAt: '2026-08-09'
__schemaVersion: 1
id: startup-ua-com.zhuopu.mihomo
type: StartupItem
label: com.zhuopu.mihomo
domain: user_agent
managedBy: self
loaded: true
enabled: true
vendor: zhuopu
plistPath: <user-home>/Library/LaunchAgents/com.zhuopu.mihomo.plist
program: <user-home>/bin/mihomo
programArgs:
  - <user-home>/bin/mihomo
  - -d
  - <user-home>/.config/mihomo
runAtLoad: true
keepAlive: true
meta:
  source: probe
  createdAt: '2026-08-09'
  updatedAt: '2026-08-09'
  tags: [macos, launchd]
```

## 总结

四个来源 + 一张 slug 映射表 + 路径脱敏 = 一次扫描把 macOS 启动项全收进 CMDB。Apple 自带 `com.apple.*` 过滤掉之后只剩 20 多个真正关心的项。
