#!/bin/sh
# 一键配置 Git hooks
# 用法：./scripts/setup-hooks.sh

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "🔧 配置 Git hooks..."

cd "$REPO_ROOT" || exit 1

if [ ! -d ".githooks" ]; then
    echo "❌ .githooks 目录不存在"
    exit 1
fi

git config core.hooksPath .githooks

echo "✅ hooks 已配置：$(git config core.hooksPath)"
echo "   当前 hooks："
for f in .githooks/*; do
    [ -f "$f" ] && echo "     - $(basename "$f")"
done
