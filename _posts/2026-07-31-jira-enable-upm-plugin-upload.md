---
layout: post
title: "Jira 10 没有「上传插件」按钮？开启 UPM 文件上传的正确姿势"
date: 2026-07-31 08:20:00 +0800
categories: 工具
---

给 Docker 部署的 Jira 装一个 `.obr` 插件，打开「Manage apps」页面却发现**根本没有 Upload app 按钮**。查了一圈资料都说加个 JVM 参数就行，可参数明明加了，按钮还是不出现。这篇记录完整的排查过程——结论是：**参数加对了地方才算数**。

## 背景

- Jira 版本：10.3.2（Docker 镜像，基于 Tomcat + OpenJDK 17）
- 目标：通过 Web 后台上传本地 `.obr` / `.jar` 插件包安装
- 现象：`/plugins/servlet/upm` 页面缺少「Upload app」按钮

Atlassian 从较新版本的 UPM（Universal Plugin Manager）开始，**默认禁用了 Web 文件上传安装插件**，必须显式加 JVM 参数 `-Dupm.plugin.upload.enabled=true`，上传按钮才会出现。

## 第一个坑：参数加了却不生效

镜像的 `docker-compose.yml` 里其实早就写了这个参数：

```yaml
  jira:
    environment:
      - JVM_SUPPORT_RECOMMENDED_ARGS=-Dupm.plugin.upload.enabled=true
```

`JVM_SUPPORT_RECOMMENDED_ARGS` 是 Atlassian 官方文档推荐用来塞自定义 JVM 参数的环境变量，看起来完全正确。但页面上按钮就是不出现。

先别急着怀疑参数写错，**去看运行中的 Java 进程到底吃到了哪些参数**才是正解：

```bash
# 进容器，dump PID 1 的完整命令行
docker exec <container> sh -c 'cat /proc/1/cmdline | tr "\0" "\n"' | grep -i upm
```

结果：**空的**。也就是说 `-Dupm.plugin.upload.enabled=true` 压根没进 JVM。环境变量明明设了，怎么会没传进去？

## 根因：启动脚本把变量清空了

Jira 的 Tomcat 启动会 source 一个 `bin/setenv.sh`。翻一下这个脚本：

```bash
grep -n 'JVM_SUPPORT_RECOMMENDED_ARGS' /opt/jira/bin/setenv.sh
```

```
14:JVM_SUPPORT_RECOMMENDED_ARGS=""
94:JAVA_OPTS="${JAVA_OPTS} ... ${JVM_SUPPORT_RECOMMENDED_ARGS} ${JVM_EXTRA_ARGS} ..."
```

真相大白：

- **第 14 行**：脚本一开头就把 `JVM_SUPPORT_RECOMMENDED_ARGS` **硬编码重置为空字符串**
- **第 94 行**：才把它拼进 `JAVA_OPTS`

所以不管你在 docker-compose 里怎么设这个环境变量，被脚本第 14 行一清零，最终传给 JVM 的就是空。这就是为什么参数「设了却没生效」。

> 顺带说一句：容器里 `docker exec` 改的东西只在可写层，`docker restart` 保留、但重建（`docker compose up`）就丢。这也是为什么改容器内的 `setenv.sh` 不是长久之计。

## 挑一个不会被脚本干扰的注入口

既然 `JVM_SUPPORT_RECOMMENDED_ARGS` 会被清空，那就换一个 `setenv.sh` **不会重置**的通道。看第 94 行的拼接串，候选有 `JVM_EXTRA_ARGS`、`CATALINA_OPTS` 等。逐个验证：

```bash
grep -nE 'JVM_EXTRA_ARGS|CATALINA_OPTS' /opt/jira/bin/setenv.sh
```

```
55:JVM_EXTRA_ARGS="-XX:-OmitStackTraceInFastThrow -Djava.locale.providers=COMPAT"
94:JAVA_OPTS="... ${JVM_EXTRA_ARGS} ..."
98:CATALINA_OPTS="-Xms${JVM_MINIMUM_MEMORY} -Xmx${JVM_MAXIMUM_MEMORY} ${CATALINA_OPTS}"
100:export CATALINA_OPTS
```

- `JVM_EXTRA_ARGS`：第 55 行也被**硬编码覆盖**了 → 一样不可靠，pass
- `CATALINA_OPTS`：第 98 行是 `CATALINA_OPTS="固定内存参数 ${CATALINA_OPTS}"`，**把已有值原样保留后追加**，然后 `export` → 干净，不会丢

`CATALINA_OPTS` 是 Tomcat 标准变量，`catalina.sh` 最终 `exec java ... "$JAVA_OPTS" "$CATALINA_OPTS"` 时一定会带上。这就是我们要的注入口。

**验证一下这条路真的通**：同一套镜像家族部署的 Confluence 容器，正是用 `CATALINA_OPTS` 传这个参数的，dump 它的 Java 进程命令行，确实带上了 `-Dupm.plugin.upload.enabled=true`。现成的成功先例，稳。

## 解决方案

改 `docker-compose.yml`，把那行失效的环境变量换成 `CATALINA_OPTS`：

```yaml
  jira:
    environment:
      # 旧的（会被 setenv.sh 清空，无效）：
      # - JVM_SUPPORT_RECOMMENDED_ARGS=-Dupm.plugin.upload.enabled=true
      # 改成：
      - CATALINA_OPTS=-Dupm.plugin.upload.enabled=true
```

然后重建容器让新环境变量生效（**注意：只 restart 不够**，环境变量是创建容器时注入的，必须重建）：

```bash
docker compose up -d jira
```

重建完再验证一次：

```bash
docker exec <container> sh -c 'cat /proc/1/cmdline | tr "\0" "\n"' | grep -i upm
# 应输出：-Dupm.plugin.upload.enabled=true
```

刷新 `/plugins/servlet/upm` 页面，「Upload app」按钮就出现了。

## 重建容器安全吗？先 docker diff 看一眼

重建会重建整个容器，动手前最好确认「会丢什么」。用 `docker diff` 看容器可写层相对镜像的所有改动：

```bash
docker diff <container>
```

我这次看到的改动**全是运行时自动生成的东西**：

- `/opt/jira/logs/*`——历史日志
- `/opt/jira/work/`、`/opt/jira/temp/`——JSP 编译缓存、临时文件
- `/tmp/hsperfdata_*`——JVM 性能数据

这些重建后都会自动重新生成，无所谓。**真正的业务数据**（数据库配置、已装插件、附件、索引）都在挂载卷 `jira-home` 里，重建不碰挂载卷，所以数据安全。

判断标准很简单：**只要业务数据都在 volume 里、可写层没有手工改过的重要文件，重建就是安全的**。这也顺便说明了为什么「改容器内文件」不靠谱——那些改动就落在会被重建清掉的可写层里。

## 顺便：文件系统投放插件

除了 Web 上传，还有一种「文件系统投放」的装法——直接把插件文件丢进 Jira Home 的扫描目录：

```
<jira-home>/plugins/installed-plugins/
```

配合挂载卷的话，从宿主机对应目录拷进去即可。缺点是：

- Jira 10 通常**不会热加载**，要重启容器才扫描
- 没有兼容性 / 许可证的即时校验，加载失败只能翻日志

所以能用 Web 上传（UPM）就优先用 UPM，投放文件适合脚本化批量部署或上传失败时兜底。

## 小结

| 排查步骤 | 命令 / 动作 | 结论 |
|---------|------------|------|
| 确认按钮真缺失还是被隐藏 | 查页面有没有 `#upm-upload` 元素 | 元素不存在，参数没生效 |
| 看 JVM 实际吃到的参数 | `cat /proc/1/cmdline` | 参数确实没进去 |
| 查启动脚本 | `grep setenv.sh` | 第 14 行把变量清空了 |
| 找干净的注入口 | 对比 `JVM_EXTRA_ARGS` / `CATALINA_OPTS` | 只有 `CATALINA_OPTS` 不被重置 |
| 改配置 + 重建 | `docker compose up -d` | 按钮出现 |

一句话教训：**JVM 参数「设了」不等于「生效了」，一定要 dump 运行进程的真实命令行来验证**。启动脚本里一句不起眼的 `VAR=""` 就能让你的配置石沉大海。遇到「参数明明加了却不管用」，别在原地反复改值，去看进程实际吃到了什么，往往一眼就破案。
