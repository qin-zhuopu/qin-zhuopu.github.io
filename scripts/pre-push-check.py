#!/usr/bin/env python3
"""
pre-push 检查脚本（零依赖，不需要 PyYAML）
覆盖：
  - YAML front matter 必填字段
  - 日期一致性（文件名日期 vs front matter 日期）
  - URL 冲突（重复 slug）
  - 中文标点错误
"""

import re, sys
from pathlib import Path

REQUIRED_FIELDS = {"layout", "title", "date", "categories"}
POST_FILE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-(.+)\.md$")
DATE_FM_RE = re.compile(r"^date:\s*(\d{4}-\d{2}-\d{2})", re.MULTILINE)


def parse_simple_yaml(text):
    """轻量 YAML 解析：只处理 key: value 单层映射，不依赖 pyyaml"""
    data = {}
    for line in text.splitlines():
        stripped = line.rstrip()
        if not stripped or stripped.startswith("#"):
            continue
        m = re.match(r"^(\w[\w_]*):\s*(.*?)$", stripped)
        if m:
            k, v = m.group(1).strip(), m.group(2).strip()
            # 去掉引号
            if (v.startswith('"') and v.endswith('"')) or \
               (v.startswith("'") and v.endswith("'")):
                v = v[1:-1]
            # 列表：categories: [x, y]
            if v.startswith("[") and v.endswith("]"):
                v = [x.strip().strip("\"'") for x in v[1:-1].split(",") if x.strip()]
            data[k] = v
    return data


def main():
    posts_dir = Path("_posts")
    if not posts_dir.exists():
        print("  ⚠️  _posts 目录不存在")
        return 0

    yaml_errors = []
    date_errors = []
    slug_keys = {}

    for f in sorted(posts_dir.glob("*.md")):
        text = f.read_text(encoding="utf-8")
        fname = f.name

        # ── YAML ──
        if not text.startswith("---"):
            yaml_errors.append(f"  {fname}: 缺少 front matter（必须以 --- 开头）")
            continue
        parts = text.split("---", 2)
        if len(parts) < 3:
            yaml_errors.append(f"  {fname}: front matter 未闭合（缺少第二个 ---）")
            continue
        try:
            fm = parse_simple_yaml(parts[1])
        except Exception as e:
            yaml_errors.append(f"  {fname}: front matter 解析失败 - {e}")
            continue

        missing = REQUIRED_FIELDS - set(fm.keys())
        if missing:
            yaml_errors.append(f"  {fname}: 缺少必填字段 {missing}")
            continue

        title = str(fm.get("title", ""))
        if any(c in title for c in "“”‘’"):
            yaml_errors.append(f"  {fname}: title 含有中文引号，应替换为英文 \"...\" 或单引号 \"...\"")

        cats = fm.get("categories")
        cats_str = str(cats) if not isinstance(cats, list) else ", ".join(str(c) for c in cats)
        if "：" in cats_str:
            yaml_errors.append(f"  {fname}: categories 含有中文冒号，应使用英文 \":\" 或列表格式 [x, y]")

        date_raw = str(fm.get("date", ""))
        if not re.match(r"^\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}:\d{2}\s+[+-]\d{4})?$", date_raw):
            yaml_errors.append(f"  {fname}: date 格式异常 \"{date_raw}\"，应为 YYYY-MM-DD HH:MM:SS +/-HHMM")

        # ── 日期一致性 ──
        m = POST_FILE_RE.match(fname)
        if not m:
            yaml_errors.append(f"  {fname}: 文件名格式应为 YYYY-MM-DD-slug.md")
            continue
        file_date = "%s-%s-%s" % m.group(1, 2, 3)
        fm_date_match = DATE_FM_RE.search(parts[1])
        if not fm_date_match:
            date_errors.append(f"  {fname}: front matter 中未找到 date 字段")
            continue
        fm_date = fm_date_match.group(1)
        if file_date != fm_date:
            date_errors.append(f"  {fname}: 文件名日期 {file_date} ≠ front matter 日期 {fm_date}")

        # ── URL 冲突 ──
        slug = m.group(4)
        key = (m.group(1), m.group(2), m.group(3), slug)
        if key in slug_keys:
            date_errors.append(f"  {fname}: URL 冲突——与 {slug_keys[key]} 生成相同 permalink /{key[0]}/{key[1]}/{key[2]}/{key[3]}/")
        slug_keys[key] = fname

    total_errors = 0

    if yaml_errors:
        print("❌ YAML front matter 问题：")
        for e in yaml_errors:
            print(e)
        total_errors += len(yaml_errors)
    else:
        print("✅ YAML front matter 正确")

    if date_errors:
        print("")
        print("❌ 日期一致性 / URL 冲突问题：")
        for e in date_errors:
            print(e)
        total_errors += len(date_errors)
    else:
        print("✅ 所有文章日期一致，无 URL 冲突")

    return 1 if total_errors else 0


if __name__ == "__main__":
    sys.exit(main())
