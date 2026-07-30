---
layout: page
title: 分类
permalink: /categories/
---

按分类浏览所有文章。

## Home-Assistant

海尔空调接入 Home Assistant 的完整折腾过程。

{% assign ha_posts = site.posts | where: "categories", "Home-Assistant" | sort: "date" | reverse %}
{% for post in ha_posts %}
- [{{ post.title }}]({{ post.url }}) — {{ post.date | date: "%Y-%m-%d" }}
{% endfor %}

## macOS

老系统上的驱动和工具链折腾。

{% assign mac_posts = site.posts | where: "categories", "macOS" | sort: "date" | reverse %}
{% for post in mac_posts %}
- [{{ post.title }}]({{ post.url }}) — {{ post.date | date: "%Y-%m-%d" }}
{% endfor %}

## 工具

命令行工具的使用笔记。

{% assign tool_posts = site.posts | where: "categories", "工具" | sort: "date" | reverse %}
{% for post in tool_posts %}
- [{{ post.title }}]({{ post.url }}) — {{ post.date | date: "%Y-%m-%d" }}
{% endfor %}

## 随笔

{% assign essay_posts = site.posts | where: "categories", "随笔" | sort: "date" | reverse %}
{% for post in essay_posts %}
- [{{ post.title }}]({{ post.url }}) — {{ post.date | date: "%Y-%m-%d" }}
{% endfor %}
