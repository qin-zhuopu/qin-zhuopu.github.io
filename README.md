# qin-zhuopu.github.io

我的个人博客，基于 GitHub Pages + Jekyll（Minima 主题）。

线上地址：https://qin-zhuopu.github.io

## 写新文章

在 `_posts/` 下新建文件，命名格式 `YYYY-MM-DD-标题.md`，开头加 front matter：

```yaml
---
layout: post
title: "标题"
date: 2026-07-12 09:00:00 +0800
categories: 随笔
---
```

然后：

```bash
git add .
git commit -m "新文章：标题"
git push
```

几分钟后 GitHub Pages 会自动编译发布。
