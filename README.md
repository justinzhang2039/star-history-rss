# Star History 周榜 RSS 订阅

本仓库通过 GitHub Actions 自动生成 [Star History](https://www.star-history.com) 周榜 RSS 订阅源。

## 功能说明

订阅源会在以下情况推送新条目：

1. **🆕 新进榜单 Top20** — 有新项目进入滚动周榜前 20
2. **🔥 新进前 5** — 有新项目进入前 5（该条目会列出当前前 5 及各自近 7 天新增星数）

数据来源：Star History 网站左侧栏 "Weekly" 榜单（滚动 7 天窗口，每日更新）。

## 订阅地址

```
https://raw.githubusercontent.com/justinzhang2039/star-history-rss/main/star-history-weekly.xml
```

将此链接添加到你的 RSS 阅读器即可订阅。

## 更新频率

GitHub Actions 每天 01:30 和 13:30 UTC 各运行一次（约北京时间 09:30 和 21:30）。

## 手动触发

1. 进入本仓库的 **Actions** 页面
2. 左侧选择 **Update Star History RSS Feed**
3. 点击 **Run workflow** → **Run workflow**

或使用 GitHub CLI：

```bash
gh workflow run update-feed.yml
```
